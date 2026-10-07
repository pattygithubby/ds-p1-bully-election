import socket
from threading import Thread

import pytest

from bully.node import Node, Status
from bully.transport_udp import UdpCommunication, UdpMessageServer


@pytest.fixture
def running_udp_node():
    node = Node(2)
    server = UdpMessageServer(node, "127.0.0.1", 0)
    port = server.socket.getsockname()[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    communication = UdpCommunication(0.5, {2: ("localhost", port)})

    try:
        yield node, communication
    finally:
        server.close()
        thread.join(timeout=1)
        assert not thread.is_alive()


def test_probe_gets_acknowledgement(running_udp_node):
    _, communication = running_udp_node

    assert communication.probe(2) is True


def test_query_normal_returns_peer_status(running_udp_node):
    node, communication = running_udp_node
    node.s = Status.ELECTION

    assert communication.query_normal(2) is False

    node.s = Status.NORMAL
    assert communication.query_normal(2) is True


def test_election_messages_are_acknowledged_and_dispatched(running_udp_node):
    node, communication = running_udp_node
    node.processing = True

    assert communication.send_halt(2, sender_id=1) is True
    assert node.s is Status.ELECTION
    assert node.h == 1
    assert node.processing is False

    assert communication.send_new_coordinator(2, sender_id=1) is True
    assert node.s is Status.REORGANIZATION
    assert node.c == 1

    assert communication.send_ready(2, sender_id=1, task="compute") is True
    assert node.s is Status.NORMAL
    assert node.d == "compute"
    assert node.processing is True


def test_probe_and_query_normal_time_out():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as silent_peer:
        silent_peer.bind(("127.0.0.1", 0))
        communication = UdpCommunication(
            0.05,
            {2: silent_peer.getsockname()},
        )

        assert communication.probe(2) is False
        assert communication.query_normal(2) is None


def test_unknown_peer_is_unreachable():
    communication = UdpCommunication(0.05, {})

    assert communication.probe(2) is False
    assert communication.query_normal(2) is None
