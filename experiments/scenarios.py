"""The failure scenarios the two algorithms are compared on, run on an in-memory cluster.

A scenario has two parts. `prepare` brings a fresh cluster to where the measurement starts,
and `trigger` is the event whose cost is measured. After the trigger, the cluster runs
check() and timeout() rounds, as serve() does, until Assertion 2 holds again.

Nodes act one after another here, which makes every count exact and repeatable. The UDP
measurements in measure.py show what changes when they act at the same time.
"""

from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass

from bully.simulation import Cluster
from bully.transport_memory import InMemoryCommunication


class MeteredCommunication(InMemoryCommunication):
    """InMemoryCommunication that also counts the calls each node makes.

    A node makes its calls one after another, and each call takes at most T (Assumption 8).
    So the number of calls a node makes bounds the time it spends, in units of T.
    """

    def __init__(self):
        super().__init__(timeout_bound_t=1)
        self.calls = Counter()   # node id -> how many calls it made
        self._caller = None      # the node whose procedure is running

    @contextmanager
    def on_behalf_of(self, node_id):
        """Count the calls made inside the block as calls by node_id."""
        self._caller = node_id
        try:
            yield
        finally:
            self._caller = None

    def _deliver(self, target_id, message):
        self.calls[self._caller] += 1
        return super()._deliver(target_id, message)


# --- What serve() does, one step at a time ---


def start(cluster: Cluster, node_id: int) -> None:
    """Node node_id (re)starts from its safe storage and runs Recovery."""
    node = cluster.boot(node_id)
    with cluster.comm.on_behalf_of(node_id):
        node.recovery()


def run_round(cluster: Cluster) -> None:
    """One check() and one timeout() on every live node, as serve() does every interval."""
    for node_id in cluster.live():
        node = cluster.nodes[node_id]
        with cluster.comm.on_behalf_of(node_id):
            node.check()
            node.timeout()


def settle(cluster: Cluster, limit: int = 10) -> int:
    """Run rounds until Assertion 2 holds, and return how many rounds that took."""
    rounds = 0
    while not cluster.settled():
        if rounds == limit:
            raise RuntimeError(f"no stable coordinator after {limit} rounds: {cluster.view()}")
        run_round(cluster)
        rounds += 1
    return rounds


# --- Building blocks for the scenarios ---


def nothing(cluster: Cluster) -> None:
    pass


def elect(cluster: Cluster) -> None:
    """All nodes start, and the highest becomes coordinator."""
    for node_id in cluster.live():
        start(cluster, node_id)
    settle(cluster)


def crash_highest(cluster: Cluster, count: int) -> None:
    for node_id in range(cluster.n, cluster.n - count, -1):
        cluster.crash(node_id)


def all_down(cluster: Cluster) -> None:
    for node_id in range(1, cluster.n + 1):
        cluster.crash(node_id)


# --- The scenarios ---


def first_election(cluster: Cluster) -> None:
    for node_id in range(1, cluster.n + 1):
        start(cluster, node_id)


def coordinator_crash(cluster: Cluster) -> None:
    crash_highest(cluster, 1)


def coordinator_crash_one_detector(cluster: Cluster) -> None:
    crash_highest(cluster, 1)
    detector = cluster.n - 1                 # the node that will win anyway
    with cluster.comm.on_behalf_of(detector):
        cluster.nodes[detector].timeout()


def half_crash(cluster: Cluster) -> None:
    crash_highest(cluster, max(1, cluster.n // 2))


def elect_then_crash_coordinator(cluster: Cluster) -> None:
    elect(cluster)
    crash_highest(cluster, 1)
    settle(cluster)


def coordinator_returns(cluster: Cluster) -> None:
    start(cluster, cluster.n)


def join_lowest_first(cluster: Cluster) -> None:
    for node_id in range(1, cluster.n + 1):
        start(cluster, node_id)
        settle(cluster)


def join_highest_first(cluster: Cluster) -> None:
    for node_id in range(cluster.n, 0, -1):
        start(cluster, node_id)
        settle(cluster)


@dataclass(frozen=True)
class Scenario:
    name: str                              # short; used in tables, plots and file names
    description: str
    prepare: Callable[[Cluster], None]     # not measured
    trigger: Callable[[Cluster], None]     # measured, together with the rounds after it


SCENARIOS = [
    Scenario("first election", "All nodes start at the same time.",
             nothing, first_election),
    Scenario("coordinator crash", "The coordinator crashes; every node notices on its next timeout.",
             elect, coordinator_crash),
    Scenario("crash, one detector", "The coordinator crashes; only the next-highest node notices (best case).",
             elect, coordinator_crash_one_detector),
    Scenario("half crash", "The highest half of the nodes crash at once.",
             elect, half_crash),
    Scenario("coordinator returns", "The crashed coordinator recovers and takes over again.",
             elect_then_crash_coordinator, coordinator_returns),
    Scenario("join lowest first", "The nodes join one at a time, lowest id first (worst case).",
             all_down, join_lowest_first),
    Scenario("join highest first", "The nodes join one at a time, highest id first.",
             all_down, join_highest_first),
    Scenario("steady state", "One check/timeout round with no failure: the cost of failure detection.",
             elect, run_round),
]
