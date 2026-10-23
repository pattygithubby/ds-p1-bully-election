"""Many nodes in one process: the harness for the system tests and the experiments.

Cluster      n real nodes on one InMemoryCommunication: deterministic and fast.
UdpCluster   n real nodes on real UDP sockets on localhost, each driven by __main__.serve
             in its own thread, as in a container: concurrent and timed.

Every node saves its state after each change (Assumption 4). The in-memory Cluster uses that
to check the paper's Assertion 1 at every instant: SafetyMonitor looks at all nodes after
every save, and raises SafetyViolation the moment the assertion does not hold.
"""

import socket
import threading
import time
from collections import Counter

from .__main__ import serve
from .original import OriginalNode
from .state import StateVector, Status
from .storage import MemoryStorage
from .transport_memory import InMemoryCommunication
from .transport_udp import UdpCommunication


def all_follow_highest(states: dict[int, StateVector]) -> bool:
    """Assertion 2: every live node is Normal and has the highest live node as coordinator."""
    if not states:
        return False
    highest = max(states)
    return all(s.s == Status.NORMAL and s.c == highest for s in states.values())


# --- Assertion 1 ---


class SafetyViolation(AssertionError):
    """The paper's Assertion 1 does not hold."""


class SafetyMonitor:
    """Checks Assertion 1 after every state change of every node in a cluster.

    Assertion 1, which must hold at every instant:
        a) nodes in Reorganization or Normal all have the same coordinator c;
        b) Normal nodes all have the same task definition d.
    Crashed nodes (Down) and nodes in Election are exempt.

    Since it sees every state change, it also counts the elections that were completed
    (a node becoming Normal as coordinator), for the experiments.
    """

    def __init__(self, comm: InMemoryCommunication):
        self.comm = comm      # tells which nodes are crashed
        self.states = {}      # node id -> the state it saved last
        self.checks = 0       # how many times Assertion 1 was checked
        self.elections = 0    # how many times a node became Normal as coordinator

    def storage(self, node_id: int) -> MemoryStorage:
        """A storage for node_id that reports every save to this monitor."""
        return _MonitoredStorage(self, node_id)

    def saved(self, node_id: int, state: StateVector) -> None:
        if _leads(node_id, state) and not _leads(node_id, self.states.get(node_id)):
            self.elections += 1
        self.states[node_id] = state
        self.check()

    def check(self) -> None:
        self.checks += 1
        live = {i: s for i, s in self.states.items() if i not in self.comm.crashed}
        coordinators = {s.c for s in live.values() if s.s in (Status.REORGANIZATION, Status.NORMAL)}
        tasks = {s.d for s in live.values() if s.s == Status.NORMAL}
        if len(coordinators) > 1:
            raise SafetyViolation(f"Assertion 1a: nodes disagree on the coordinator: {_describe(live)}")
        if len(tasks) > 1:
            raise SafetyViolation(f"Assertion 1b: Normal nodes have different tasks: {_describe(live)}")


class _MonitoredStorage(MemoryStorage):
    def __init__(self, monitor: SafetyMonitor, node_id: int):
        super().__init__()
        self.monitor = monitor
        self.node_id = node_id

    def atomic_update(self, state: StateVector) -> None:
        super().atomic_update(state)
        self.monitor.saved(self.node_id, self.load())   # load() is a copy, as a disk would give


def _leads(node_id: int, state: StateVector | None) -> bool:
    return state is not None and state.s == Status.NORMAL and state.c == node_id


def _describe(states: dict[int, StateVector]) -> str:
    return ", ".join(f"node {i}: {s.s.name} c={s.c}" for i, s in sorted(states.items()))


# --- In memory ---


class Cluster:
    """n real nodes on one in-memory transport, each with its own monitored storage."""

    def __init__(self, n, comm=None, node_class=OriginalNode):
        self.n = n
        self.node_class = node_class
        self.comm = comm or InMemoryCommunication(timeout_bound_t=1)
        self.monitor = SafetyMonitor(self.comm)
        self.stores = {i: self.monitor.storage(i) for i in range(1, n + 1)}
        self.nodes = {}
        for i in range(1, n + 1):
            self.boot(i)

    def boot(self, node_id):
        """(Re)start a node from its safe storage, as after a crash. Does not run recovery()."""
        self.comm.restart(node_id)
        self.nodes[node_id] = self.node_class(node_id, self.n, self.comm, self.stores[node_id])
        self.comm.register(self.nodes[node_id])
        return self.nodes[node_id]

    def crash(self, node_id):
        """Fail-stop: the node stops answering, and the cluster stops running its procedures."""
        self.comm.crash(node_id)

    def live(self):
        """The ids of the nodes that are up, lowest first."""
        return [i for i in sorted(self.nodes) if i not in self.comm.crashed]

    def recover_all(self):
        """Run recovery() on every node that is up. A crashed node must not send anything."""
        for node_id in self.live():
            self.nodes[node_id].recovery()

    def rounds(self, count=3):
        """What serve() does periodically, for every node that is up."""
        for _ in range(count):
            for node_id in self.live():
                self.nodes[node_id].check()
                self.nodes[node_id].timeout()

    def view(self):
        """{id: (status, coordinator)} for every node that is up."""
        return {i: (self.nodes[i].state.s, self.nodes[i].state.c) for i in self.live()}

    def settled(self):
        """Assertion 2 holds: every live node is Normal and follows the highest live node."""
        return all_follow_highest({i: self.nodes[i].state for i in self.live()})


# --- Over UDP ---


def _silent_socket(port: int = 0) -> socket.socket:
    """A socket bound to a localhost port that never answers, standing in for a node that is down."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", port))
    return sock


class UdpCluster:
    """n real nodes over UDP on localhost, each running __main__.serve in its own thread.

    While a node is down, its port stays bound to a socket that never answers, so a message
    to it costs the sender the full T, as with a machine that is gone. (A closed port on
    localhost would instead be reported at once, which is faster than any real network.)
    """

    def __init__(self, n, node_class, timeout_bound_t=0.2, interval=0.2):
        self.n = n
        self.node_class = node_class
        self.timeout_bound_t = timeout_bound_t   # T
        self.interval = interval                 # seconds between check() and timeout()
        self.stores = {i: MemoryStorage() for i in range(1, n + 1)}
        self.silent = {i: _silent_socket() for i in range(1, n + 1)}   # every node starts down
        self.peers = {i: sock.getsockname() for i, sock in self.silent.items()}
        self.nodes, self.stops, self.threads = {}, {}, {}
        self.comms = []   # every UdpCommunication ever started, for the message counts

    def boot(self, node_id):
        """(Re)start a node from its safe storage, as when its container starts."""
        self.silent.pop(node_id).close()     # free the port for the node itself
        comm = UdpCommunication(self.timeout_bound_t, self.peers, self.peers[node_id][1], host="127.0.0.1")
        self.comms.append(comm)
        self.nodes[node_id] = self.node_class(node_id, self.n, comm, self.stores[node_id])
        self.stops[node_id] = threading.Event()
        self.threads[node_id] = threading.Thread(
            target=serve, args=(self.nodes[node_id], comm, self.stops[node_id], self.interval)
        )
        self.threads[node_id].start()

    def crash(self, node_id):
        """Stop the node's serve() loop, as `docker compose stop`; its port goes silent."""
        self.stops[node_id].set()
        self.threads[node_id].join()
        self.silent[node_id] = _silent_socket(self.peers[node_id][1])

    def shutdown(self):
        for node_id in self.live():
            self.crash(node_id)
        for sock in self.silent.values():
            sock.close()

    def live(self):
        return [i for i in sorted(self.threads) if self.threads[i].is_alive()]

    def view(self):
        """{id: (status, coordinator)} for every node that is up."""
        return {i: (s.s, s.c) for i, s in self._states().items()}

    def settled(self):
        return all_follow_highest(self._states())

    def wait_until_settled(self, limit=10.0) -> bool:
        """Poll until Assertion 2 holds, or give up after limit seconds."""
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            if self.settled():
                return True
            time.sleep(0.01)
        return False

    def sent(self) -> Counter:
        """Messages sent by all nodes together, by type."""
        return sum((comm.sent for comm in self.comms), Counter())

    def unanswered(self) -> Counter:
        return sum((comm.unanswered for comm in self.comms), Counter())

    def _states(self) -> dict[int, StateVector]:
        """A consistent snapshot of every live node's state, read under the node's own lock."""
        snapshot = {}
        for i in self.live():
            node = self.nodes[i]
            with node._lock:   # another thread may be changing the state right now
                snapshot[i] = StateVector(s=node.state.s, c=node.state.c, d=node.state.d, h=node.state.h)
        return snapshot
