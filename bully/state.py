"""The state vector S(i) that each node keeps in safe storage (Garcia-Molina 1982).

Every class here can be converted to and from a plain dict (to_dict / from_dict),
so it can be written to disk as JSON and sent between nodes.
"""

from enum import Enum, auto
from dataclasses import dataclass, field


class Status(Enum):
    """S(i).s: which phase of the protocol the node is in."""

    DOWN = auto()            # crashed, or just restarted and not yet in an election
    ELECTION = auto()        # halted by a higher node, or running its own election
    REORGANIZATION = auto()  # coordinator is agreed on, but the task is not yet known
    NORMAL = auto()          # working on the task given by the coordinator


@dataclass(frozen=True)
class TaskDefinition:
    """S(i).d: the task the coordinator hands out in Ready.

    Frozen, because the same object is handed to every node.
    """

    participants: tuple[int, ...] = ()
    application_algorithm: str = ""

    def to_dict(self) -> dict:
        return {
            "participants": list(self.participants),  # JSON has no tuples
            "application_algorithm": self.application_algorithm,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskDefinition":
        return cls(
            participants=tuple(data["participants"]),
            application_algorithm=data["application_algorithm"],
        )


@dataclass
class StateVector:
    """S(i): everything a node must remember across a crash."""

    s: Status = Status.DOWN
    c: int | None = None             # coordinator; c == own id means "I am coordinator"
    d: TaskDefinition | None = None  # task definition, None until Ready is received
    h: int | None = None             # last node that halted this node; rejects stale messages
    up: set[int] = field(default_factory=set)  # nodes that acknowledged our Halt

    def to_dict(self) -> dict:
        return {
            "s": self.s.name,
            "c": self.c,
            "d": self.d.to_dict() if self.d is not None else None,
            "h": self.h,
            "up": sorted(self.up),  # JSON has no sets
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StateVector":
        return cls(
            s=Status[data["s"]],
            c=data["c"],
            d=TaskDefinition.from_dict(data["d"]) if data["d"] is not None else None,
            h=data["h"],
            up=set(data["up"]),
        )
