"""Theorem 1: both algorithms keep Assertion 1 (safety) at every instant and reach Assertion 2.

Every Cluster in the tests has a SafetyMonitor that checks Assertion 1 after every state
change, so all system tests already check safety continuously. This file adds:
    - tests that the monitor really catches a violation;
    - random crashes and recoveries, also in the middle of elections, for both algorithms.
"""

import random
from contextlib import contextmanager

import pytest

from bully.improved import ImprovedNode
from bully.original import OriginalNode
from bully.simulation import Cluster, SafetyViolation
from bully.state import Status, TaskDefinition
from bully.transport_memory import InMemoryCommunication

BOTH = pytest.mark.parametrize("node_class", [OriginalNode, ImprovedNode])


def settled_cluster(n=3):
    cluster = Cluster(n)
    cluster.recover_all()
    assert cluster.settled()
    return cluster


def save(node, **changes):
    """Change a node's state behind the algorithm's back and save it, as a buggy node would."""
    for field, value in changes.items():
        setattr(node.state, field, value)
    node.storage.atomic_update(node.state)


# --- The monitor itself ---


def test_monitor_catches_two_coordinators():
    cluster = settled_cluster()
    with pytest.raises(SafetyViolation, match="1a"):
        save(cluster.nodes[2], c=2)


def test_monitor_catches_two_tasks():
    cluster = settled_cluster()
    with pytest.raises(SafetyViolation, match="1b"):
        save(cluster.nodes[2], d=TaskDefinition((2,), "another task"))


def test_monitor_ignores_nodes_in_election_and_crashed_nodes():
    cluster = settled_cluster()
    save(cluster.nodes[2], s=Status.ELECTION, c=2)     # Election is exempt
    cluster.crash(1)
    save(cluster.nodes[1], c=1)                         # so is a crashed node's old state
    assert cluster.monitor.checks > 0


# --- Random faults ---


class FaultInjector(InMemoryCommunication):
    """Injects crashes and recoveries at random moments, also in the middle of elections.

    Before some deliveries it either crashes the receiver, or lets a crashed node recover.
    The recovering node then runs its whole recovery inside the other node's election, as if
    the two ran at the same time.

    Fail-stop (Assumption 5) is respected: a node is only crashed while none of its own
    procedures is running, because a crashed node must not send anything more.
    """

    CRASH = 0.05        # chance, per delivery, that the receiver crashes just before it
    RECOVER = 0.05      # chance, per delivery, that a crashed node recovers just before it
    MAX_NESTING = 3     # at most this many procedures running inside each other

    def __init__(self, rng):
        super().__init__(timeout_bound_t=1)
        self.rng = rng
        self.cluster = None     # set once the cluster exists
        self.enabled = False
        self.running = set()    # nodes with one of their own procedures on the call stack
        self.crashes = 0
        self.recoveries = 0

    @contextmanager
    def runs(self, node_id):
        """Mark node_id as running one of its procedures while the block runs."""
        self.running.add(node_id)
        try:
            yield
        finally:
            self.running.discard(node_id)

    def _deliver(self, target_id, message):
        if self.enabled:
            self._maybe_inject_fault(target_id)
        return super()._deliver(target_id, message)

    def _maybe_inject_fault(self, target_id):
        roll = self.rng.random()
        can_crash = (
            target_id not in self.crashed
            and target_id not in self.running
            and len(self.cluster.live()) > 1
        )
        if roll < self.CRASH and can_crash:
            self.cluster.crash(target_id)
            self.crashes += 1
        elif roll < self.CRASH + self.RECOVER and self.crashed and len(self.running) < self.MAX_NESTING:
            riser = self.rng.choice(sorted(self.crashed))
            self.recoveries += 1
            with self.runs(riser):
                self.cluster.boot(riser).recovery()


def run_with_faults(node_class, seed, rounds=30):
    """A random cluster of 2..7 nodes: start it, run `rounds` rounds with faults, then 4 without."""
    rng = random.Random(seed)
    comm = FaultInjector(rng)
    cluster = Cluster(rng.randint(2, 7), comm, node_class)
    comm.cluster = cluster
    comm.enabled = True

    def let_every_live_node(procedure_name):
        for node_id in cluster.live():
            if node_id in comm.crashed:     # crashed earlier in this same round
                continue
            with comm.runs(node_id):
                getattr(cluster.nodes[node_id], procedure_name)()

    let_every_live_node("recovery")
    for _ in range(rounds):
        let_every_live_node("check")
        let_every_live_node("timeout")

    comm.enabled = False
    cluster.rounds(4)       # the failures have stopped: Assertion 2 says the cluster settles
    return cluster, comm


@BOTH
def test_random_crashes_and_recoveries_keep_both_assertions(node_class):
    crashes = recoveries = checks = 0
    for seed in range(200):
        try:
            cluster, comm = run_with_faults(node_class, seed)
        except SafetyViolation as error:
            pytest.fail(f"seed {seed}: {error}")
        assert cluster.settled(), f"seed {seed} did not settle: {cluster.view()}"
        crashes += comm.crashes
        recoveries += comm.recoveries
        checks += cluster.monitor.checks

    # The test only means something if faults really happened.
    assert crashes > 100 and recoveries > 100
    assert checks > 10_000
