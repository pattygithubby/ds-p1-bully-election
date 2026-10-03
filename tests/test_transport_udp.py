import json
import socket

import pytest

from bully.state import TaskDefinition
from bully.transport_udp import UdpCommunication, peers_from_template

T = 0.3  # timeout bound used in these tests, in seconds


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


@pytest.fixture
def cluster():
    """Three UdpCommunications on localhost, each serving a FakeNode. Stopped after the test."""
    peers = {}                                    # shared by all three, filled in below
    comms, nodes = {}, {}
    for i in (1, 2, 3):
        nodes[i] = FakeNode(i)
        comms[i] = UdpCommunication(T, peers, port=0, host="127.0.0.1")   # port 0 = any free port
        comms[i].start(nodes[i])
        peers[i] = ("127.0.0.1", comms[i].port)
    yield comms, nodes
    for comm in comms.values():
        comm.stop()


def ask(port, request):
    """Send one raw request to a server on localhost and return its reply (or None on timeout)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(T)
        try:
            sock.sendto(json.dumps(request).encode("utf-8"), ("127.0.0.1", port))
            data, _ = sock.recvfrom(65535)
        except OSError:
            return None
    return json.loads(data.decode("utf-8"))


# --- Part 1: peers_from_template ---
def test_peers_compose_template():
    assert peers_from_template("node{id}:9000", 3) == {
        1: ("node1", 9000), 2: ("node2", 9000), 3: ("node3", 9000),
    }

def test_peers_kubernetes_template():
    assert peers_from_template("bully-{ord}.bully:9000", 2) == {
        1: ("bully-0.bully", 9000), 2: ("bully-1.bully", 9000),
    }

def test_peers_port_is_a_number():
    host, port = peers_from_template("node{id}:9000", 1)[1]
    assert isinstance(port, int)


# --- Part 2: __init__ and _handle (no network yet) ---
def make_comm(node):
    comm = UdpCommunication(T, {}, port=0, host="127.0.0.1")
    comm.node = node
    return comm

def test_handle_setup():
    comm = UdpCommunication(T, {1: ("node1", 9000)}, port=9000)
    assert comm.peers == {1: ("node1", 9000)}
    assert comm.port == 9000
    assert comm.host == "0.0.0.0"
    assert sum(comm.sent.values()) == 0
    with pytest.raises(ValueError):
        UdpCommunication(0, {}, port=9000)

def test_handle_are_you_there():
    node = FakeNode(1)
    assert make_comm(node)._handle({"type": "AreYouThere"}) == {"result": True}
    assert node.received == [("are_you_there",)]

def test_handle_are_you_normal():
    assert make_comm(FakeNode(1, normal=True))._handle({"type": "AreYouNormal"}) == {"result": True}
    assert make_comm(FakeNode(1, normal=False))._handle({"type": "AreYouNormal"}) == {"result": False}

def test_handle_halt():
    node = FakeNode(1)
    assert make_comm(node)._handle({"type": "Halt", "sender": 3}) == {"result": True}
    assert node.received == [("halt", 3)]

def test_handle_new_coordinator():
    node = FakeNode(1)
    assert make_comm(node)._handle({"type": "NewCoordinator", "sender": 3}) == {"result": True}
    assert node.received == [("new_coordinator", 3)]

def test_handle_ready_rebuilds_the_task():
    node = FakeNode(1)
    task = TaskDefinition((1, 3), "demo")
    request = {"type": "Ready", "sender": 3, "task": task.to_dict()}
    assert make_comm(node)._handle(request) == {"result": True}
    assert node.received == [("ready", 3, task)]     # a TaskDefinition again, not a dict

def test_handle_unknown_type():
    with pytest.raises(ValueError):
        make_comm(FakeNode(1))._handle({"type": "Nonsense"})


# --- Part 3: start, _serve, stop (the receiving side) ---
def test_serve_answers_a_request(cluster):
    comms, nodes = cluster
    assert ask(comms[2].port, {"type": "Halt", "sender": 3}) == {"result": True}
    assert nodes[2].received == [("halt", 3)]

def test_serve_survives_a_bad_packet(cluster):
    comms, _ = cluster
    assert ask(comms[2].port, {"type": "Nonsense"}) is None                  # no reply...
    assert ask(comms[2].port, {"type": "AreYouThere"}) == {"result": True}   # ...but still running

def test_serve_stop_means_no_more_answers(cluster):
    comms, _ = cluster
    port = comms[2].port
    comms[2].stop()
    assert ask(port, {"type": "AreYouThere"}) is None

def test_serve_stop_twice_is_harmless(cluster):
    comms, _ = cluster
    comms[2].stop()
    comms[2].stop()


# --- Part 4: the sending side ---
def test_probe_alive_node(cluster):
    comms, nodes = cluster
    assert comms[1].probe(2) is True
    assert nodes[2].received == [("are_you_there",)]

def test_probe_stopped_node(cluster):
    comms, _ = cluster
    comms[2].stop()                               # node 2 "crashes"
    assert comms[1].probe(2) is False

def test_probe_unknown_node(cluster):
    comms, _ = cluster
    assert comms[1].probe(99) is False

def test_query_normal_yes_and_no(cluster):
    comms, nodes = cluster
    nodes[3].normal = False
    assert comms[1].query_normal(2) is True
    assert comms[1].query_normal(3) is False

def test_query_normal_stopped_node_gives_none(cluster):
    comms, _ = cluster
    comms[2].stop()
    assert comms[1].query_normal(2) is None

def test_send_halt(cluster):
    comms, nodes = cluster
    assert comms[3].send_halt(1, 3) is True
    assert nodes[1].received == [("halt", 3)]
    comms[1].stop()
    assert comms[3].send_halt(1, 3) is False

def test_send_new_coordinator(cluster):
    comms, nodes = cluster
    assert comms[3].send_new_coordinator(2, 3) is True
    assert nodes[2].received == [("new_coordinator", 3)]

def test_send_ready_delivers_task(cluster):
    comms, nodes = cluster
    task = TaskDefinition((1, 2, 3), "demo")
    assert comms[3].send_ready(2, 3, task) is True
    assert nodes[2].received == [("ready", 3, task)]

def test_send_counts_per_message_type(cluster):
    comms, _ = cluster
    comms[2].stop()
    comms[3].send_halt(1, 3)
    comms[3].send_halt(2, 3)                      # no answer, but still sent
    comms[3].send_new_coordinator(1, 3)
    comms[3].probe(1)
    assert comms[3].sent == {"Halt": 2, "NewCoordinator": 1, "AreYouThere": 1}
