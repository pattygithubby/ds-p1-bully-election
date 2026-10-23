"""In-process transport: all nodes live in one Python process (tests and experiments)."""

from .communication import (
    ARE_YOU_NORMAL,
    ARE_YOU_THERE,
    HALT,
    NEW_COORDINATOR,
    READY,
    Communication,
)


class InMemoryCommunication(Communication):
    """Delivers a message by calling the target node's handler directly.

    One InMemoryCommunication is shared by all nodes in the simulated cluster.
    """

    def __init__(self, timeout_bound_t):
        super().__init__(timeout_bound_t)   # Communication checks and stores the timeout
        self.nodes = {}                     # node id -> node object
        self.crashed = set()                # ids of nodes that are down right now

    def register(self, node) -> None:
        """Add a node to the cluster so messages can reach it."""
        self.nodes[node.id] = node            # key: the node's id, value: the node itself

    def crash(self, node_id: int) -> None:
        """Simulate a crash: the node stops answering.

        Only incoming messages are blocked. The caller must also stop calling the
        crashed node's own procedures, since a crashed node sends nothing (Assumption 5).
        """
        self.crashed.add(node_id)

    def restart(self, node_id: int) -> None:
        """The node answers again.

        A recovering node starts from safe storage, not from its old memory: build a new
        Node on the same storage, register() it, and call its recovery().
        """
        self.crashed.discard(node_id)           # must not fail if the node was never crashed
        
    def _deliver(self, target_id: int, message: str):
        """Count one sent message. Return the target node, or None if it cannot answer."""
        self.sent[message] += 1
        if target_id in self.crashed or target_id not in self.nodes:
            self.unanswered[message] += 1
            return None
        return self.nodes[target_id]

    def probe(self, target_id: int) -> bool:
        """AreYouThere: True if the target is alive."""
        target = self._deliver(target_id, ARE_YOU_THERE)
        if target is None:
            return False
        return target.are_you_there()

    def query_normal(self, target_id: int) -> bool | None:
        """AreYouNormal: True or False from the target, None if it does not answer."""
        target = self._deliver(target_id, ARE_YOU_NORMAL)
        if target is None:
            return None
        return target.are_you_normal()
    
    def send_halt(self, target_id: int, sender_id: int) -> bool:
        """Halt: True if the target acknowledged, False on timeout."""
        target = self._deliver(target_id, HALT)
        if target is None:
            return False
        target.halt(sender_id)
        return True

    def send_new_coordinator(self, target_id: int, sender_id: int) -> bool:
        """NewCoordinator: True if the target acknowledged, False on timeout."""
        target = self._deliver(target_id, NEW_COORDINATOR)
        if target is None:
            return False
        target.new_coordinator(sender_id)
        return True

    def send_ready(self, target_id: int, sender_id: int, task) -> bool:
        """Ready: True if the target acknowledged, False on timeout."""
        target = self._deliver(target_id, READY)
        if target is None:
            return False
        target.ready(sender_id, task)
        return True

