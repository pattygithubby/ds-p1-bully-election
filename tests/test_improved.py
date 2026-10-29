"""The improved Bully algorithm: NewCoordinator is merged into Ready.

The first part pins down what is different from the original (the messages and the Ready
handler). The second part runs the same scenarios against both variants, since they must
elect the same coordinator.
"""

import pytest

from bully.__main__ import ALGORITHMS
from bully.improved import ImprovedNode
from bully.original import OriginalNode
from bully.simulation import Cluster
from bully.state import Status, TaskDefinition

from .test_node import all_normal, assert_one_coordinator, race

BOTH = pytest.mark.parametrize("node_class", [OriginalNode, ImprovedNode])

TASK = TaskDefinition(participants=(1, 2), application_algorithm="x")


def cluster_of(n, node_class=ImprovedNode, down=()):
    """n nodes of the given variant, the ones in `down` crashed. Nobody has run an election yet."""
    cluster = Cluster(n, node_class=node_class)
    for node_id in down:
        cluster.comm.crash(node_id)
    return cluster


# --- What is different from the original ---


def test_improved_is_the_algorithm_selected_by_name():
    assert ALGORITHMS["improved"] is ImprovedNode


@pytest.mark.parametrize("n", [1, 2, 5, 10])
def test_election_by_highest_node_message_count(n):
    cluster = cluster_of(n)
    cluster.nodes[n].election()
    sent = cluster.comm.sent
    assert sent["NewCoordinator"] == 0
    assert sent["Halt"] == sent["Ready"] == n - 1
    assert sum(sent.values()) == 2 * (n - 1)
    assert cluster.view() == all_normal(range(1, n + 1), coordinator=n)


@pytest.mark.parametrize("i", [1, 2, 3, 4])
def test_election_with_all_higher_nodes_down_message_count(i):
    n = 5
    cluster = cluster_of(n, down=range(i + 1, n + 1))
    cluster.nodes[i].election()
    sent = cluster.comm.sent
    assert sent["AreYouThere"] == n - i    # Part 1 is unchanged
    assert sent["NewCoordinator"] == 0
    assert sent["Halt"] == sent["Ready"] == i - 1
    assert cluster.view() == all_normal(range(1, i + 1), coordinator=i)


@pytest.mark.parametrize("n", [2, 5, 10])
def test_election_saves_one_message_per_participant(n):
    totals = {}
    for node_class in (OriginalNode, ImprovedNode):
        cluster = cluster_of(n, node_class)
        cluster.nodes[n].election()
        totals[node_class] = sum(cluster.comm.sent.values())
    assert totals[OriginalNode] - totals[ImprovedNode] == n - 1


def test_every_halt_is_sent_before_any_ready():
    """Halt and announce are still two steps."""
    cluster = cluster_of(4)
    order = []
    for name in ("send_halt", "send_new_coordinator", "send_ready"):
        original = getattr(cluster.comm, name)
        setattr(cluster.comm, name, lambda *args, _n=name, _o=original: order.append(_n) or _o(*args))
    cluster.nodes[4].election()
    assert order == ["send_halt"] * 3 + ["send_ready"] * 3


def test_ready_takes_a_halted_node_straight_to_normal():
    node = cluster_of(3).nodes[1]
    node.halt(2)
    node.ready(2, TASK)
    assert (node.state.s, node.state.c, node.state.d) == (Status.NORMAL, 2, TASK)
    assert node.processing is True


def test_ready_is_ignored_unless_sender_sent_the_last_halt():
    node = cluster_of(3).nodes[1]
    node.halt(2)
    node.ready(3, TASK)
    assert (node.state.s, node.state.c, node.state.d) == (Status.ELECTION, None, None)
    assert node.processing is False


def test_ready_is_ignored_unless_node_is_in_election():
    node = cluster_of(3).nodes[1]
    node.ready(2, TASK)    # Down: never halted
    assert (node.state.s, node.state.d) == (Status.DOWN, None)

    node.halt(2)
    node.ready(2, TASK)    # now Normal with coordinator 2
    other = TaskDefinition(participants=(1,), application_algorithm="y")
    node.ready(2, other)   # a second Ready must not replace the task
    assert (node.state.s, node.state.d) == (Status.NORMAL, TASK)


def test_participant_failure_restarts_the_election():
    """Node 1 answers the Halt and then dies: the election is run again without it."""
    cluster = cluster_of(3)
    send_ready = cluster.comm.send_ready

    def dies_first(target_id, sender_id, task):
        if target_id == 1:
            cluster.comm.crash(1)
        return send_ready(target_id, sender_id, task)

    cluster.comm.send_ready = dies_first
    cluster.nodes[3].election()
    assert cluster.nodes[3].state.up == {2}
    assert cluster.view() == all_normal([2, 3], coordinator=3)
    assert cluster.comm.sent["NewCoordinator"] == 0


# --- Same outcome as the original ---


@BOTH
def test_highest_node_becomes_coordinator(node_class):
    cluster = cluster_of(4, node_class)
    cluster.recover_all()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)
    assert all(node.processing for node in cluster.nodes.values())


@BOTH
def test_all_nodes_get_the_same_task(node_class):
    cluster = cluster_of(3, node_class)
    cluster.recover_all()
    task = TaskDefinition(participants=(1, 2, 3), application_algorithm="process tasks")
    assert [node.state.d for node in cluster.nodes.values()] == [task, task, task]


@BOTH
def test_coordinator_crash_is_detected_by_timeout(node_class):
    cluster = cluster_of(4, node_class)
    cluster.recover_all()
    cluster.comm.crash(4)
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)


@BOTH
def test_recovering_highest_node_takes_over(node_class):
    cluster = cluster_of(4, node_class, down=[4])
    cluster.recover_all()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)

    cluster.boot(4).recovery()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)


@BOTH
def test_recovering_lower_node_is_picked_up_by_check(node_class):
    cluster = cluster_of(3, node_class)
    cluster.recover_all()
    cluster.comm.crash(1)
    cluster.boot(1).recovery()
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)


@BOTH
@pytest.mark.parametrize("message, target", [("Halt", 1), ("Ready", 2), ("Ready", 1)])
def test_higher_node_recovering_mid_election_wins(node_class, message, target):
    """Node 4 recovers while node 3 is sending `message` to `target`."""
    cluster = race(message, target, node_class)
    assert_one_coordinator(cluster)
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)


@BOTH
def test_system_crash_and_recovery_of_every_coordinator_in_turn(node_class):
    """System test: Assertion 2 after each change, down to one node and back up again."""
    n = 5
    cluster = cluster_of(n, node_class)
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
