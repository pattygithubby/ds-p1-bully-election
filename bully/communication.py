from abc import ABC, abstractmethod


class Communication(ABC):
    # Passes time bound t
    def __init__(self, timeout_bound_t: float) -> None:
        if timeout_bound_t <= 0:
            raise ValueError("timeout_bound_t must be positive")
        self.timeout_bound_t = timeout_bound_t 

    @abstractmethod
    def probe(self, target_id: int) -> bool:
        """Return True if the target acknowledges before the timeout."""

    @abstractmethod
    def query_normal(self, target_id: int) -> bool | None:
        """Return the target's normal status, or None if it times out."""

    @abstractmethod
    def send_halt(self, target_id: int, sender_id: int) -> bool:
        """Send Halt; return True if acknowledged before the timeout."""

    @abstractmethod
    def send_new_coordinator(self, target_id: int, sender_id: int) -> bool:
        """Send NewCoordinator; return True if acknowledged before the timeout."""

    @abstractmethod
    def send_ready(self, target_id: int, sender_id: int, task: str,) -> bool:
        """Send Ready; return True if acknowledged before the timeout."""