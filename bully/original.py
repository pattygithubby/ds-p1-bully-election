"""The original Bully algorithm."""

from collections.abc import Callable

from .node import Node
from .state import Status, TaskDefinition

APPLICATION = "process tasks"   # the application algorithm in the task definition


class OriginalNode(Node):
    """The original Bully algorithm (Garcia-Molina 1982, Section III), see docs/bully-ref.md.

    Node holds the state vector and the five message handlers. This class adds the four
    procedures a node starts itself, written from the paper's pseudocode:

        paper           method
        Election(i)     election()
        Recovery(i)     recovery()
        Check(i)        check()
        Timeout(i)      timeout()

    An election run by node i with every higher node down sends n - i AreYouThere, then
    i - 1 Halt, and one NewCoordinator and one Ready to each node that answered the Halt.
    """

    def recovery(self) -> None:
        with self._lock:
            self.state.h = None
            self.storage.atomic_update(self.state)
        self.election()

    def election(self) -> None:
        # The lock is only held around the state, never while waiting for another node
        with self._lock:
            halts = self._halts

        while True:
            if not self._halt_lower_nodes(halts):
                return

            with self._lock:
                if self._stopped(halts):
                    return
                self.state.c = self.id
                self.state.s = Status.REORGANIZATION
                self.storage.atomic_update(self.state)
                participants = sorted(self.state.up)

            if not self._send_to_all(
                participants, lambda j: self.comm.send_new_coordinator(j, self.id), halts
            ):
                continue

            task = self._task(participants)
            with self._lock:
                if self._stopped(halts):
                    return
                self.state.d = task
                self.storage.atomic_update(self.state)

            if self._send_to_all(participants, lambda j: self.comm.send_ready(j, self.id, task), halts):
                self._become_normal(halts)
                return

    def check(self) -> None:
        # Only the coordinator checks, and only once it is Normal
        with self._lock:
            if self.state.s != Status.NORMAL or self.state.c != self.id:
                return
        for node_id in range(1, self.n + 1):
            if node_id == self.id:
                continue
            # A node that doesn't answer is ignored; one that answers "no" is stranded
            if self.comm.query_normal(node_id) is False:
                self.election()
                return

    def timeout(self) -> None:
        with self._lock:
            status = self.state.s
            coordinator_id = self.state.c

        if status not in (Status.NORMAL, Status.REORGANIZATION):
            self.election()
        elif coordinator_id is None:
            self.election()
        elif coordinator_id != self.id and not self.comm.probe(coordinator_id):
            self.election()

    # --- Steps of Election(i) shared with ImprovedNode ---

    def _halt_lower_nodes(self, halts: int) -> bool:
        """Part 1 and the Halt round of Election(i).

        Returns False if the election is given up: a higher node answered, or this
        node was halted itself. Otherwise the nodes that acknowledged are in state.up.
        """
        # Part 1: if any higher node is up, leave the election to it
        for node_id in range(self.id + 1, self.n + 1):
            if self._stopped(halts) or self.comm.probe(node_id):
                return False

        with self._lock:
            if self._stopped(halts):
                return False
            self.stop_processing()
            self.state.s = Status.ELECTION
            self.state.h = self.id
            self.state.up = set()
            self.storage.atomic_update(self.state)

        # Part 2: halt every lower node, from i - 1 down to 1
        for node_id in range(self.id - 1, 0, -1):
            if self._stopped(halts):
                return False
            if self.comm.send_halt(node_id, self.id):
                with self._lock:
                    if self._stopped(halts):
                        return False
                    self.state.up.add(node_id)
                    self.storage.atomic_update(self.state)
        return True

    def _send_to_all(self, participants: list[int], send: Callable[[int], bool], halts: int) -> bool:
        """Send one message to every participant.

        Returns False if one of them didn't answer, so the election starts over. It also
        returns False if this node was halted; the restart then gives up straight away.
        """
        for node_id in participants:
            if self._stopped(halts) or not send(node_id):
                return False
        return True

    def _task(self, participants: list[int]) -> TaskDefinition:
        return TaskDefinition(
            participants=tuple(sorted(participants + [self.id])),
            application_algorithm=APPLICATION,
        )

    def _become_normal(self, halts: int) -> None:
        with self._lock:
            if self._stopped(halts):
                return
            self.state.s = Status.NORMAL
            self.storage.atomic_update(self.state)
            self.processing = True
