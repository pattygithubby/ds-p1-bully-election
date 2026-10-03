import pytest

from bully.state import TaskDefinition
from bully.transport_memory import InMemoryCommunication


class FakeNode:
    """Stands in for the real Node: same five handlers, and it records what it receives."""

    def __init__(self, node_id, normal=True):
        self.id = node_id
        self.normal = normal
        self.received = []

    def are_you_there(self):
        self.received.append(("are_you_there",))
        return True

    def are_you_normal(self):
        self.received.append(("are_you_normal",))
        return self.normal

    def halt(self, sender_id):
        self.received.append(("halt", sender_id))

    def new_coordinator(self, sender_id):
        self.received.append(("new_coordinator", sender_id))

    def ready(self, sender_id, task):
        self.received.append(("ready", sender_id, task))


def make_cluster(n=3):
    """A transport with n fake nodes registered, ids 1..n."""
    comm = InMemoryCommunication(timeout_bound_t=1)
    nodes = {i: FakeNode(i) for i in range(1, n + 1)}
    for node in nodes.values():
        comm.register(node)
    return comm, nodes


# --- Part 1: setup (register, crash, restart) ---
def test_setup_starts_empty():
    comm = InMemoryCommunication(timeout_bound_t=1)
    assert comm.nodes == {}
    assert comm.crashed == set()
    assert sum(comm.sent.values()) == 0

def test_setup_keeps_timeout_check_from_base_class():
    with pytest.raises(ValueError):
        InMemoryCommunication(timeout_bound_t=0)

def test_setup_register():
    comm, nodes = make_cluster(3)
    assert comm.nodes == {1: nodes[1], 2: nodes[2], 3: nodes[3]}

def test_setup_crash_and_restart():
    comm, _ = make_cluster(3)
    comm.crash(2)
    assert comm.crashed == {2}
    comm.restart(2)
    assert comm.crashed == set()

def test_setup_restart_of_running_node_is_harmless():
    comm, _ = make_cluster(3)
    comm.restart(2)                      # node 2 never crashed: must not raise an error
    assert comm.crashed == set()


# --- Part 2: probe and query_normal ---
def test_probe_alive_node():
    comm, nodes = make_cluster(3)
    assert comm.probe(2) is True
    assert nodes[2].received == [("are_you_there",)]

def test_probe_crashed_node():
    comm, nodes = make_cluster(3)
    comm.crash(2)
    assert comm.probe(2) is False
    assert nodes[2].received == []       # a crashed node receives nothing

def test_probe_unknown_node():
    comm, _ = make_cluster(3)
    assert comm.probe(99) is False

def test_probe_counts_every_message_sent():
    comm, _ = make_cluster(3)
    comm.crash(3)
    comm.probe(2)
    comm.probe(3)                        # no answer, but the message was still sent
    assert comm.sent["AreYouThere"] == 2

def test_query_normal_yes_and_no():
    comm, nodes = make_cluster(3)
    nodes[2].normal = False
    assert comm.query_normal(1) is True
    assert comm.query_normal(2) is False

def test_query_normal_crashed_node_gives_none():
    comm, _ = make_cluster(3)
    comm.crash(2)
    assert comm.query_normal(2) is None  # None = no answer, not the same as "No"
    assert comm.sent["AreYouNormal"] == 1


# --- Part 3: send_halt, send_new_coordinator, send_ready ---
def test_send_halt_delivers_sender_id():
    comm, nodes = make_cluster(3)
    assert comm.send_halt(1, 3) is True
    assert nodes[1].received == [("halt", 3)]

def test_send_halt_to_crashed_node():
    comm, nodes = make_cluster(3)
    comm.crash(1)
    assert comm.send_halt(1, 3) is False
    assert nodes[1].received == []

def test_send_new_coordinator():
    comm, nodes = make_cluster(3)
    assert comm.send_new_coordinator(2, 3) is True
    assert nodes[2].received == [("new_coordinator", 3)]
    comm.crash(2)
    assert comm.send_new_coordinator(2, 3) is False

def test_send_ready_delivers_task():
    comm, nodes = make_cluster(3)
    task = TaskDefinition((1, 2, 3), "demo")
    assert comm.send_ready(2, 3, task) is True
    assert nodes[2].received == [("ready", 3, task)]
    comm.crash(2)
    assert comm.send_ready(2, 3, task) is False

def test_send_counts_per_message_type():
    comm, _ = make_cluster(3)
    task = TaskDefinition((1, 2, 3), "demo")
    comm.send_halt(1, 3)
    comm.send_halt(2, 3)
    comm.send_new_coordinator(1, 3)
    comm.send_ready(1, 3, task)
    assert comm.sent == {"Halt": 2, "NewCoordinator": 1, "Ready": 1}
