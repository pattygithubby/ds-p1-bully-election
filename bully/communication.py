from abc import ABC, abstractmethod
from collections import Counter

from .state import TaskDefinition

# The five messages, named as in the paper. The names are the keys of `sent`,
# and the UDP transport uses them as the "type" of each packet.
ARE_YOU_THERE = "AreYouThere"
ARE_YOU_NORMAL = "AreYouNormal"
HALT = "Halt"
NEW_COORDINATOR = "NewCoordinator"
READY = "Ready"


class Communication(ABC):
    """Interface for sending Bully protocol messages between nodes."""

    def __init__(self, timeout_bound_t: float) -> None:
        if timeout_bound_t <= 0:
            raise ValueError("timeout_bound_t must be positive")
        self.timeout_bound_t = timeout_bound_t
        self.sent: Counter[str] = Counter()  # message name -> how many were sent, answered or not
        self.unanswered: Counter[str] = Counter()  # message name -> how many got no answer within T

    @abstractmethod
    def probe(self, target_id: int) -> bool:
        """Return True if the target responds; otherwise False."""
        raise NotImplementedError

    @abstractmethod
    def query_normal(self, target_id: int) -> bool | None:
        """Return the target's status, or None if it does not respond."""
        raise NotImplementedError

    @abstractmethod
    def send_halt(self, target_id: int, sender_id: int) -> bool:
        """Send Halt and return whether the target acknowledged it."""
        raise NotImplementedError

    @abstractmethod
    def send_new_coordinator(self, target_id: int, sender_id: int) -> bool:
        """Send NewCoordinator and return whether the target acknowledged it."""
        raise NotImplementedError

    @abstractmethod
    def send_ready(
        self, target_id: int, sender_id: int, task: TaskDefinition
    ) -> bool:
        """Send Ready and return whether the target acknowledged it."""
        raise NotImplementedError