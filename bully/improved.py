"""The improved variant: NewCoordinator is merged into Ready."""

from .original import OriginalNode
from .state import Status, TaskDefinition


class ImprovedNode(OriginalNode):
    """Bully with one message fewer per participant: NewCoordinator is merged into Ready.

    The original sends Halt, NewCoordinator and Ready to every lower node: 3(i - 1) messages
    for node i. The task definition is already known when the Halt round is over, so here
    Ready also announces the coordinator: 2(i - 1) messages.

        original    Halt -> NewCoordinator -> Ready      Election -> Reorganization -> Normal
        improved    Halt -> Ready                        Election -> Normal

    Halt stays a separate step. The guard that protects NewCoordinator in the original
    (s = Election and h = sender) moves to Ready, so a message from a superseded election
    is still rejected.
    """

    def ready(self, sender_id: int, task: TaskDefinition) -> None:
        with self._lock:
            # The guard NewCoordinator has in the original
            if self.state.s == Status.ELECTION and self.state.h == sender_id:
                self.state.c = sender_id
                self.state.d = task
                self.state.s = Status.NORMAL
                self.storage.atomic_update(self.state)  # saved before work is allowed
                self.processing = True

    def election(self) -> None:
        # As in OriginalNode, but without the NewCoordinator round
        with self._lock:
            halts = self._halts

        while True:
            if not self._halt_lower_nodes(halts):
                return

            # Every lower node has been halted, so the task can be made right away
            with self._lock:
                if self._stopped(halts):
                    return
                participants = sorted(self.state.up)
                task = self._task(participants)
                self.state.c = self.id
                self.state.s = Status.REORGANIZATION
                self.state.d = task
                self.storage.atomic_update(self.state)

            # Ready tells the participants both who the coordinator is and what the task is
            if self._send_to_all(participants, lambda j: self.comm.send_ready(j, self.id, task), halts):
                self._become_normal(halts)
                return
