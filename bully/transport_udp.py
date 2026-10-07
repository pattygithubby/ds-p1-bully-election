# UdpCommunication is a sender-side UDP client that implements the operations in the Communication interface.
# UdpCommunication Methods send JSON messages to peers and wait for replies. UdpMessageServer receives them.
import json
import socket
from uuid import uuid4

from .communication import Communication
from .node import Node


class UdpCommunication(Communication):
    # stores the timeout and a mapping from node IDs to addresses
    def __init__(
        self,
        timeout_bound_t: float,
        peers: dict[int, tuple[str, int]],
    ) -> None:
        super().__init__(timeout_bound_t)
        self.peers = peers

    # does the common request/reply work
    def _request(self, target_id: int, message: dict) -> dict | None:
        # looks up target address and returns None if unknown
        address = self.peers.get(target_id)
        if address is None:
            return None

        # Adds a unique request ID to JSON message
        request_id = uuid4().hex
        message["request_id"] = request_id
        expected_addresses = {
            (result[4][0], result[4][1])
            for result in socket.getaddrinfo(
                address[0],
                address[1],
                socket.AF_INET,
                socket.SOCK_DGRAM,
            )
        }

        # Sends message over a UDP socket and waits up to timeout_bound_t for a reply
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(self.timeout_bound_t)
            sock.sendto(json.dumps(message).encode("utf-8"), address)

            try:
                data, response_address = sock.recvfrom(4096)
            except socket.timeout:
                return None


        # Checks that the reply came from the target and has the matching request ID
        if response_address not in expected_addresses:
            return None

        # Returns the decoded reply or None if no valid reply arrived in time
        response = json.loads(data.decode("utf-8"))
        if response.get("request_id") != request_id:
            return None
        return response

    # Sends are_you_there, returns True if peer acknowledges, otherwise False
    def probe(self, target_id: int) -> bool:
        response = self._request(target_id, {"type": "are_you_there"})
        return response is not None and response.get("ok") is True

    # Sends are_you_normal, returns True or False based on peer's status, or None if there was no reply
    def query_normal(self, target_id: int) -> bool | None:
        response = self._request(target_id, {"type": "are_you_normal"})
        if response is None:
            return None  # no acknowledgement before the timeout
        return response.get("normal") is True

    # Sends a Halt message with the sender’s ID; returns True if it receives an ok acknowledgement.
    def send_halt(self, target_id: int, sender_id: int) -> bool:
        response = self._request(
            target_id,
            {"type": "halt", "sender_id": sender_id},
        )
        return response is not None and response.get("ok") is True

    # Sends the coordinator announcement and returns whether it was acknowledged.
    def send_new_coordinator(self, target_id: int, sender_id: int) -> bool:
        response = self._request(
            target_id,
            {"type": "new_coordinator", "sender_id": sender_id},
        )
        return response is not None and response.get("ok") is True

    # Sends the task assignment and returns whether it was acknowledged.
    def send_ready(self, target_id: int, sender_id: int, task: str) -> bool:
        response = self._request(
            target_id,
            {"type": "ready", "sender_id": sender_id, "task": task},
        )
        return response is not None and response.get("ok") is True

# Listens on one node’s UDP port, passes incoming requests to that node’s methods, 
# and sends a reply to the requester.
class UdpMessageServer:
    def __init__(self, node: Node, host: str, port: int) -> None:
        self.node = node
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # Create UDP socket
        self.socket.settimeout(0.2)
        self.socket.bind((host, port)) # bind socket to address and port
        self._running = False

    def serve_forever(self) -> None:
        self._running = True
        while self._running: # repeatedly waits for datagrams
            try:
                data, sender_address = self.socket.recvfrom(4096)
            except socket.timeout: # timeout used to check if loop should stop
                continue
            except OSError:
                if not self._running:
                    break
                raise
            response = self._handle_message(data) 
            self.socket.sendto(
                json.dumps(response).encode("utf-8"), # sends resulting JSON response back to sender 
                sender_address,
            )

    # Decodes a JSON request and checks its "type"
    def _handle_message(self, data: bytes) -> dict:
        request = json.loads(data.decode("utf-8"))
        message_type = request["type"]
        request_id = request["request_id"]

        if message_type == "are_you_there":
            return {"request_id": request_id, "ok": True}

        if message_type == "are_you_normal":
            return {
                "request_id": request_id,
                "ok": True,
                "normal": self.node.are_you_normal(),
            }

        sender_id = request["sender_id"]

        if message_type == "halt":
            self.node.halt(sender_id)
        elif message_type == "new_coordinator":
            self.node.new_coordinator(sender_id)
        elif message_type == "ready":
            self.node.ready(sender_id, request["task"])
        else:
            return {"request_id": request_id, "ok": False}

        return {"request_id": request_id, "ok": True}

    # Marks server as stopping and closes its socket
    def close(self) -> None:
        self._running = False
        self.socket.close()