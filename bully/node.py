"""The state and message handlers shared by both variants of the Bully algorithm."""

import threading
from abc import ABC, abstractmethod

from .communication import Communication
from .state import Status, TaskDefinition
from .storage import SafeStorage


class Node(ABC):
    """Common base for both variants of the Bully algorithm, see docs/bully-ref.md.

    Holds the state vector S(i) in safe storage (Assumption 4) and the five immediate
    procedures that run when a message arrives:
        are_you_there, are_you_normal, halt, new_coordinator, ready
    The procedures a node starts itself (election, recovery, check and timeout) are
    implemented by the subclasses (OriginalNode, ImprovedNode).
    """

    def __init__(
        self,
        node_id: int,
        n: int,
        comm: Communication,
        storage: SafeStorage,
    ):
        self.id = node_id
        self.n = n              # ids run from 1 to n
        self.comm = comm
        self.storage = storage

        # A restarted node keeps what is in safe storage, but always starts out Down
        self.state = self.storage.load()
        self.state.s = Status.DOWN
        self.state.h = None
        self.storage.atomic_update(self.state)

        self.processing = False

        # The paper's critical section: handlers and procedures may run in different threads
        self._lock = threading.RLock()
        self._halts = 0  # Halts received so far; a change aborts a running election

    def are_you_there(self) -> bool:
        # Any answer at all means the node is up. A crashed node simply doesn't answer,
        # which the communication layer reports as a timeout.
        return True

    def are_you_normal(self) -> bool:
        with self._lock:
            return self.state.s == Status.NORMAL

    def stop_processing(self) -> None:
        # A running election is aborted separately, by halt() through self._halts
        self.processing = False

    def _stopped(self, halts: int) -> bool:
        # The paper's STOP: has a Halt arrived since the election noted the count?
        with self._lock:
            return self._halts != halts

    def halt(self, sender_id: int) -> None:
        with self._lock:
            self._halts += 1
            self.state.s = Status.ELECTION
            self.state.h = sender_id
            self.stop_processing()
            self.storage.atomic_update(self.state)

    def new_coordinator(self, sender_id: int) -> None:
        with self._lock:
            # Only accept it from the node that halted us, so a stale election is ignored
            if self.state.s == Status.ELECTION and self.state.h == sender_id:
                self.state.c = sender_id
                self.state.s = Status.REORGANIZATION
                self.storage.atomic_update(self.state)

    def ready(self, sender_id: int, task: TaskDefinition) -> None:
        with self._lock:
            if self.state.s == Status.REORGANIZATION and self.state.c == sender_id:
                self.state.d = task
                self.state.s = Status.NORMAL
                self.storage.atomic_update(self.state)  # saved before work is allowed
                self.processing = True

    @abstractmethod
    def recovery(self) -> None: ...

    @abstractmethod
    def election(self) -> None: ...

    @abstractmethod
    def check(self) -> None: ...

    @abstractmethod
    def timeout(self) -> None: ...
