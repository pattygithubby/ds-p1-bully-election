"""One measurement of one algorithm in one scenario, in memory or over UDP.

In memory (`measure_in_memory`): nodes act one after another, so the counts are exact and
repeatable. Besides the messages it records how many calls the final leader made (each takes
at most T, so this bounds the election time in units of T) and how many elections completed.

Over UDP (`measure_over_udp`): every node runs serve() in its own thread on real sockets,
so elections really overlap, and the time until a new coordinator is agreed on is measured
on the clock.
"""

import time
from collections import Counter
from dataclasses import dataclass

from bully.__main__ import ALGORITHMS
from bully.communication import ARE_YOU_NORMAL, ARE_YOU_THERE, HALT, NEW_COORDINATOR, READY
from bully.simulation import Cluster, UdpCluster

from .scenarios import MeteredCommunication, Scenario, settle

ELECTION_MESSAGES = (HALT, NEW_COORDINATOR, READY)
DETECTION_MESSAGES = (ARE_YOU_THERE, ARE_YOU_NORMAL)   # Part 1 probes, Check and Timeout

UDP_TIMEOUT = 0.2    # T for the UDP runs, in seconds
UDP_INTERVAL = 0.2   # seconds between check() and timeout() in the UDP runs


@dataclass
class Measurement:
    algorithm: str
    scenario: str
    n: int
    messages: Counter          # message name -> how many were sent
    unanswered: int            # messages that got no answer: each one cost a full T
    correct_leader: bool       # all live nodes agree on the highest live node
    # In memory only:
    rounds: int | None = None          # check/timeout rounds until settled again
    leader_calls: int | None = None    # calls made by the final leader: election time <= this x T
    elections: int | None = None       # elections completed (a node became Normal as coordinator)
    safety_checks: int | None = None   # how many times Assertion 1 was checked
    # Over UDP only:
    repetition: int | None = None
    seconds: float | None = None       # from the event until all live nodes agree

    @property
    def total(self) -> int:
        return sum(self.messages.values())

    @property
    def election_messages(self) -> int:
        return sum(self.messages[kind] for kind in ELECTION_MESSAGES)

    @property
    def detection_messages(self) -> int:
        return sum(self.messages[kind] for kind in DETECTION_MESSAGES)


def measure_in_memory(algorithm: str, scenario: Scenario, n: int) -> Measurement:
    comm = MeteredCommunication()
    cluster = Cluster(n, comm, ALGORITHMS[algorithm])
    scenario.prepare(cluster)

    # Only what happens from here on is measured.
    comm.sent.clear()
    comm.unanswered.clear()
    comm.calls.clear()
    elections_before = cluster.monitor.elections

    scenario.trigger(cluster)
    rounds = settle(cluster)

    leader = max(cluster.live())
    return Measurement(
        algorithm=algorithm,
        scenario=scenario.name,
        n=n,
        messages=Counter(comm.sent),
        unanswered=comm.unanswered.total(),
        correct_leader=cluster.settled(),
        rounds=rounds,
        leader_calls=comm.calls[leader],
        elections=cluster.monitor.elections - elections_before,
        safety_checks=cluster.monitor.checks,
    )


UDP_SCENARIOS = {
    "startup": "All nodes start at the same time.",
    "coordinator crash": "The coordinator crashes; the others notice on their own timers.",
}


def measure_over_udp(algorithm: str, scenario: str, n: int, repetition: int) -> Measurement:
    cluster = UdpCluster(n, ALGORITHMS[algorithm], UDP_TIMEOUT, UDP_INTERVAL)
    try:
        if scenario == "coordinator crash":
            for node_id in range(1, n + 1):
                cluster.boot(node_id)
            if not cluster.wait_until_settled():
                raise RuntimeError(f"{algorithm}, n={n}: no coordinator before the crash")

        sent_before, unanswered_before = cluster.sent(), cluster.unanswered()
        started = time.monotonic()
        if scenario == "startup":
            for node_id in range(1, n + 1):
                cluster.boot(node_id)
        else:
            cluster.crash(n)
        settled = cluster.wait_until_settled(limit=30)
        seconds = time.monotonic() - started

        return Measurement(
            algorithm=algorithm,
            scenario=scenario,
            n=n,
            messages=cluster.sent() - sent_before,
            unanswered=(cluster.unanswered() - unanswered_before).total(),
            correct_leader=settled,
            repetition=repetition,
            seconds=seconds,
        )
    finally:
        cluster.shutdown()
