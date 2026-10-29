"""The original Bully algorithm checked against the paper (docs/bully-ref.md).

The message counts follow from the pseudocode of Election(i): one AreYouThere per higher
node until one answers, one Halt per lower node, and one NewCoordinator and one Ready
per node that answered the Halt.
"""

import pytest

from bully.__main__ import ALGORITHMS
from bully.original import OriginalNode
from bully.simulation import Cluster
from bully.state import Status

from .test_node import all_normal


def cluster_of(n, down=()):
    """n OriginalNodes, the ones in `down` crashed. Nobody has run an election yet."""
    cluster = Cluster(n, node_class=OriginalNode)
    for node_id in down:
        cluster.comm.crash(node_id)
    return cluster


def test_original_is_the_algorithm_selected_by_name():
    assert ALGORITHMS["original"] is OriginalNode


@pytest.mark.parametrize("n", [1, 2, 5, 10])
def test_election_by_highest_node_message_count(n):
    cluster = cluster_of(n)
    cluster.nodes[n].election()
    sent = cluster.comm.sent
    assert sent["AreYouThere"] == 0    # there is nobody above to probe
    assert sent["Halt"] == sent["NewCoordinator"] == sent["Ready"] == n - 1
    assert sum(sent.values()) == 3 * (n - 1)
    assert cluster.view() == all_normal(range(1, n + 1), coordinator=n)


@pytest.mark.parametrize("i", [1, 2, 3, 4])
def test_election_with_all_higher_nodes_down_message_count(i):
    n = 5
    cluster = cluster_of(n, down=range(i + 1, n + 1))
    cluster.nodes[i].election()
    sent = cluster.comm.sent
    assert sent["AreYouThere"] == n - i    # every higher node is probed and times out
    assert sent["Halt"] == sent["NewCoordinator"] == sent["Ready"] == i - 1
    assert cluster.view() == all_normal(range(1, i + 1), coordinator=i)


def test_election_is_abandoned_at_the_first_higher_node_that_answers():
    cluster = cluster_of(5, down=[2])
    cluster.nodes[1].election()
    assert cluster.comm.sent == {"AreYouThere": 2}    # node 2 times out, node 3 answers
    assert cluster.nodes[1].state.s == Status.DOWN


def test_lower_nodes_that_are_down_are_left_out_of_up():
    cluster = cluster_of(5, down=[2, 4])
    cluster.nodes[5].election()
    sent = cluster.comm.sent
    assert sent["Halt"] == 4                               # sent to every lower node
    assert sent["NewCoordinator"] == sent["Ready"] == 2    # only to those that answered
    assert cluster.nodes[5].state.up == {1, 3}
    assert cluster.nodes[5].state.d.participants == (1, 3, 5)


def test_halt_comes_before_new_coordinator_and_ready():
    """Part 2 is two steps: every lower node is halted before anyone is told the result."""
    cluster = cluster_of(4)
    order = []
    for name in ("send_halt", "send_new_coordinator", "send_ready"):
        original = getattr(cluster.comm, name)
        setattr(cluster.comm, name, lambda *args, _n=name, _o=original: order.append(_n) or _o(*args))
    cluster.nodes[4].election()
    assert order == ["send_halt"] * 3 + ["send_new_coordinator"] * 3 + ["send_ready"] * 3


def test_participant_failure_in_part_two_restarts_the_election():
    """Node 1 answers the Halt and then dies: the election is run again without it."""
    cluster = cluster_of(3)
    send_new_coordinator = cluster.comm.send_new_coordinator

    def dies_first(target_id, sender_id):
        if target_id == 1:
            cluster.comm.crash(1)
        return send_new_coordinator(target_id, sender_id)

    cluster.comm.send_new_coordinator = dies_first
    cluster.nodes[3].election()
    assert cluster.nodes[3].state.up == {2}
    assert cluster.view() == all_normal([2, 3], coordinator=3)
    assert cluster.comm.sent["Halt"] == 4    # two rounds of two


def test_check_only_polls_from_a_normal_coordinator():
    cluster = cluster_of(4)
    cluster.recover_all()
    cluster.comm.sent.clear()
    for node_id in (1, 2, 3):
        cluster.nodes[node_id].check()
    assert cluster.comm.sent == {}
    cluster.nodes[4].check()
    assert cluster.comm.sent == {"AreYouNormal": 3}


def test_check_starts_an_election_when_a_node_answers_no():
    cluster = cluster_of(3)
    cluster.recover_all()
    cluster.nodes[1].halt(3)    # node 1 is stranded in Election
    cluster.nodes[3].check()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)


def test_timeout_probes_the_coordinator_and_does_nothing_while_it_answers():
    cluster = cluster_of(3)
    cluster.recover_all()
    cluster.comm.sent.clear()
    cluster.nodes[1].timeout()
    assert cluster.comm.sent == {"AreYouThere": 1}
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)


def test_timeout_starts_an_election_when_not_normal_or_reorganizing():
    cluster = cluster_of(2, down=[2])
    assert cluster.nodes[1].state.s == Status.DOWN
    cluster.nodes[1].timeout()
    assert cluster.view() == all_normal([1], coordinator=1)


def test_recovery_clears_h_and_runs_an_ordinary_election():
    cluster = cluster_of(3, down=[3])
    cluster.nodes[2].halt(3)
    cluster.nodes[2].recovery()
    assert cluster.nodes[2].state.h == 2    # reset, then set by its own election
    assert cluster.view() == all_normal([1, 2], coordinator=2)


def test_system_crash_and_recovery_of_every_coordinator_in_turn():
    """System test: Assertion 2 after each change, down to one node and back up again."""
    n = 5
    cluster = cluster_of(n)
    cluster.recover_all()
    assert cluster.view() == all_normal(range(1, n + 1), coordinator=n)

    for coordinator in range(n, 1, -1):
        cluster.comm.crash(coordinator)
        cluster.rounds()
        assert cluster.view() == all_normal(range(1, coordinator), coordinator=coordinator - 1)

    for node_id in range(2, n + 1):
        cluster.boot(node_id).recovery()
        cluster.rounds()
        assert cluster.view() == all_normal(range(1, node_id + 1), coordinator=node_id)
