"""UDP transport: one node per container (Docker Compose / Kubernetes)."""

import json
import socket
import threading
from collections import Counter

from .communication import Communication
from .state import TaskDefinition

MAX_PACKET = 65535    # largest UDP packet we are prepared to receive, in bytes
POLL_INTERVAL = 0.1   # how often the listening loop checks whether it should stop, in seconds


def peers_from_template(template: str, n: int) -> dict[int, tuple[str, int]]:
    """Turn "node{id}:9000" into {1: ("node1", 9000), 2: ("node2", 9000), ...} for ids 1..n."""
    peers = {}
    for node_id in range(1, n + 1):
        address = template.format(id=node_id, ord=node_id-1)   # e.g. "node3:9000"
        host, port = address.rsplit(":", 1)                   # "node3", "9000"
        peers[node_id] = (host, int(port))
    return peers


class UdpCommunication(Communication):
    """Sends each message as a UDP packet and waits up to T for the reply.

    There is one UdpCommunication per node. It also listens for packets from
    the other nodes and passes them to its own node's handlers.
    """

    def __init__(self, timeout_bound_t, peers, port, host="0.0.0.0"):
        super().__init__(timeout_bound_t)   # Communication checks and stores the timeout
        self.peers = peers                  # node id -> (host, port) of every node
        self.port = port                    # the UDP port this node listens on
        self.host = host                    # the address to listen on; 0.0.0.0 = all network interfaces
        self.sent = Counter()               # message name -> how many were sent
        self.node = None                    # the node in this container; set by start()
        self._sock = None                   # the listening socket; set by start()
        self._thread = None                 # the background thread that listens
        self._running = False               # True while the background thread should keep going

    def _handle(self, request: dict) -> dict:
        """Call the handler that matches an incoming request and return the reply to send back."""
        kind = request["type"]
        result = True                                   # the reply for messages that are only acknowledged
        if kind == "AreYouThere":
            result = self.node.are_you_there()
        elif kind == "AreYouNormal":
            result = self.node.are_you_normal()
        elif kind == "Halt":
            self.node.halt(request["sender"])
        elif kind == "NewCoordinator":
            self.node.new_coordinator(request["sender"])
        elif kind == "Ready":
            task = TaskDefinition.from_dict(request["task"])   # dict -> TaskDefinition
            self.node.ready(request["sender"], task)
        else:
            raise ValueError(f"unknown message type: {kind}")
        return {"result": result}

    # --- Receiving side: listen for requests from the other nodes ---

    def start(self, node) -> None:
        """Open the listening socket and start answering requests on behalf of node."""
        self.node = node
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # SOCK_DGRAM = UDP
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(POLL_INTERVAL)       # so _serve wakes up regularly to check _running
        self.port = self._sock.getsockname()[1]    # the real port, in case port 0 ("any free port") was asked for
        self._running = True
        # daemon=True: the thread must not keep the program alive when the main program ends.
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop answering requests. To the other nodes this looks like a crash."""
        self._running = False
        if self._thread is not None:
            self._thread.join()                    # wait for _serve to finish its current round
            self._thread = None
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _serve(self) -> None:
        """The listening loop. Runs in the background thread until stop() is called."""
        while self._running:
            try:
                data, sender_address = self._sock.recvfrom(MAX_PACKET)
            except OSError:
                continue    # nothing arrived within POLL_INTERVAL: go round and check _running again
            try:
                request = json.loads(data.decode("utf-8"))    # bytes -> string -> dict
                reply = self._handle(request)
                # Reply to the address the request came from, which is the sender's waiting socket.
                self._sock.sendto(json.dumps(reply).encode("utf-8"), sender_address)
            except Exception:
                # A broken packet or a failing handler must not stop the loop.
                # No reply is sent, so the sender sees a timeout.
                continue

    # --- Sending side: the five messages ---

    def _request(self, target_id: int, message: dict) -> dict | None:
        """Send message to target_id and wait up to T for the reply. None means no answer."""
        self.sent[message["type"]] += 1            # counted even if nobody answers
        if target_id not in self.peers:
            return None
        data = json.dumps(message).encode("utf-8")    # dict -> string -> bytes
        # A new socket for every request: the only thing that can arrive on it is the reply
        # to this request, so a late reply to an earlier one can never be mistaken for it.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout_bound_t)     # the bound T from Assumption 8
            try:
                sock.sendto(data, self.peers[target_id])
                reply, _ = sock.recvfrom(MAX_PACKET)
            except OSError:
                return None    # timeout, unknown host name, or port closed: the target is down
        return json.loads(reply.decode("utf-8"))

    def probe(self, target_id: int) -> bool:
        """AreYouThere: True if the target is alive."""
        reply = self._request(target_id, {"type": "AreYouThere"})
        return reply is not None    # any reply at all proves the node is there

    def query_normal(self, target_id: int) -> bool | None:
        """AreYouNormal: True or False from the target, None if it does not answer."""
        reply = self._request(target_id, {"type": "AreYouNormal"})
        if reply is None:
            return None    # "no answer" is not the same as "No"
        return reply["result"]

    def send_halt(self, target_id: int, sender_id: int) -> bool:
        """Halt: True if the target acknowledged, False on timeout."""
        reply = self._request(target_id, {"type": "Halt", "sender": sender_id})
        return reply is not None

    def send_new_coordinator(self, target_id: int, sender_id: int) -> bool:
        """NewCoordinator: True if the target acknowledged, False on timeout."""
        reply = self._request(target_id, {"type": "NewCoordinator", "sender": sender_id})
        return reply is not None

    def send_ready(self, target_id: int, sender_id: int, task: TaskDefinition) -> bool:
        """Ready: True if the target acknowledged, False on timeout."""
        message = {"type": "Ready", "sender": sender_id, "task": task.to_dict()}   # JSON cannot carry a TaskDefinition
        reply = self._request(target_id, message)
        return reply is not None
