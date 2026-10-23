"""The experiments measure what they claim to: counts match closed forms, and runs are correct."""

import pytest

from experiments.measure import measure_in_memory, measure_over_udp
from experiments.run import run
from experiments.scenarios import SCENARIOS

SCENARIO = {s.name: s for s in SCENARIOS}
SIZES = range(2, 9)


def total(algorithm, scenario, n):
    return measure_in_memory(algorithm, SCENARIO[scenario], n).total


# Messages for one election by node n, the highest: the original sends Halt, NewCoordinator and
# Ready to each of the n - 1 lower nodes, the improved only Halt and Ready.
@pytest.mark.parametrize("n", SIZES)
def test_first_election(n):
    # n - 1 nodes each probe the node above them, which answers; node n then runs the election.
    assert total("original", "first election", n) == (n - 1) + 3 * (n - 1)
    assert total("improved", "first election", n) == (n - 1) + 2 * (n - 1)


@pytest.mark.parametrize("n", SIZES)
def test_coordinator_returns(n):
    assert total("original", "coordinator returns", n) == 3 * (n - 1)
    assert total("improved", "coordinator returns", n) == 2 * (n - 1)


@pytest.mark.parametrize("n", SIZES)
def test_coordinator_crash(n):
    # Each of the n - 1 survivors probes the dead coordinator, then the node above it;
    # node n - 1 wins and sends its election messages to the n - 2 nodes below it.
    assert total("original", "coordinator crash", n) == 2 * (n - 1) + 3 * (n - 2)
    assert total("improved", "coordinator crash", n) == 2 * (n - 1) + 2 * (n - 2)


@pytest.mark.parametrize("n", SIZES)
def test_crash_with_one_detector(n):
    assert total("original", "crash, one detector", n) == 2 + 3 * (n - 2)
    assert total("improved", "crash, one detector", n) == 2 + 2 * (n - 2)


@pytest.mark.parametrize("n", SIZES)
def test_steady_state_costs_the_same_for_both(n):
    # The coordinator asks the n - 1 others AreYouNormal; each of them probes the coordinator.
    assert total("original", "steady state", n) == total("improved", "steady state", n) == 2 * (n - 1)


def test_joining_one_by_one_grows_quadratically():
    for algorithm in ("original", "improved"):
        assert total(algorithm, "join lowest first", 16) > 3.5 * total(algorithm, "join lowest first", 8)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_every_scenario_elects_the_highest_live_node(scenario):
    for algorithm in ("original", "improved"):
        for n in SIZES:
            measurement = measure_in_memory(algorithm, scenario, n)
            assert measurement.correct_leader
            assert measurement.safety_checks > 0


def test_election_time_is_one_call_per_message_of_the_leader():
    m = measure_in_memory("improved", SCENARIO["coordinator returns"], 6)
    assert m.leader_calls == m.total == 2 * 5     # only the returning node sends anything


def test_udp_measurement_agrees_and_is_timed():
    m = measure_over_udp("improved", "coordinator crash", 3, repetition=0)
    assert m.correct_leader
    assert m.unanswered >= 2                       # the dead coordinator was probed twice
    assert 0 < m.seconds < 5


def test_run_writes_all_results(tmp_path):
    text = run(tmp_path, sizes=[2, 3, 10, 12], udp_sizes=[3], repetitions=1)
    for name in ("in_memory.csv", "udp.csv", "messages.png", "election_time.png", "udp.png", "summary.md"):
        assert (tmp_path / name).stat().st_size > 0
    assert "It never failed" in text
