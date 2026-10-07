from abc import ABC, abstractmethod

from .state import TaskDefinition


class Communication(ABC):
    """Interface for sending Bully protocol messages between nodes."""

    def __init__(self, timeout_bound_t: float) -> None:
        if timeout_bound_t <= 0:
            raise ValueError("timeout_bound_t must be positive")
        self.timeout_bound_t = timeout_bound_t

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