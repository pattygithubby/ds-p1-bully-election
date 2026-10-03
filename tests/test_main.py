import threading
import time
from pathlib import Path

import pytest

from bully import __main__ as cli
from bully.state import StateVector
from bully.storage import SafeStorage
from bully.transport_udp import UdpCommunication

COMPOSE_ENV = {
    "BULLY_ID": "3",
    "BULLY_N": "5",
    "BULLY_ALGORITHM": "original",
    "BULLY_PEERS": "node{id}:9000",
    "BULLY_PORT": "9000",
    "BULLY_STATE_DIR": "/data",
}


class FakeNode:
    """Stands in for the real Node: same constructor and drivers, and it records what is called."""

    def __init__(self, node_id, n, comm, storage):
        self.id = node_id
        self.n = n
        self.comm = comm
        self.storage = storage
        self.state = StateVector()
        self.calls = []

    def recovery(self):
        self.calls.append("recovery")

    def check(self):
        self.calls.append("check")

    def timeout(self):
        self.calls.append("timeout")

    def are_you_there(self):
        return True


# --- Config.from_env ---
def test_config_from_compose_env():
    config = cli.Config.from_env(COMPOSE_ENV)
    assert config == cli.Config(
        node_id=3, n=5, algorithm="original", peers="node{id}:9000",
        port=9000, state_dir=Path("/data"), timeout=1.0,
    )

def test_config_id_from_kubernetes_hostname():
    env = {"HOSTNAME": "bully-3", "BULLY_N": "5", "BULLY_PEERS": "bully-{ord}.bully:9000"}
    config = cli.Config.from_env(env)
    assert config.node_id == 4            # pod ordinal 3 is node 4
    assert config.algorithm == "improved"
    assert config.port == 9000

def test_config_timeout_can_be_set():
    assert cli.Config.from_env({**COMPOSE_ENV, "BULLY_TIMEOUT": "0.25"}).timeout == 0.25

@pytest.mark.parametrize("change", [
    {"BULLY_N": None},                    # missing
    {"BULLY_PEERS": None},                # missing
    {"BULLY_ID": None},                   # missing, and no pod host name to fall back on
    {"BULLY_ID": "6"},                    # outside 1..n
    {"BULLY_ID": "0"},
    {"BULLY_ID": "three"},                # not a number
    {"BULLY_ALGORITHM": "fastest"},       # unknown
])
def test_config_rejects_bad_env(change):
    env = {**COMPOSE_ENV, **change}
    env = {name: value for name, value in env.items() if value is not None}
    with pytest.raises(ValueError):
        cli.Config.from_env(env)


# --- build ---
def test_build_wires_node_storage_and_communication(tmp_path, monkeypatch):
    monkeypatch.setitem(cli.ALGORITHMS, "original", FakeNode)
    state_dir = tmp_path / "state"        # does not exist yet: build must create it
    config = cli.Config.from_env({**COMPOSE_ENV, "BULLY_STATE_DIR": str(state_dir)})

    node, comm = cli.build(config)

    assert isinstance(node, FakeNode)
    assert (node.id, node.n) == (3, 5)
    assert node.comm is comm
    assert isinstance(comm, UdpCommunication)
    assert comm.timeout_bound_t == 1.0
    assert comm.port == 9000
    assert comm.peers[5] == ("node5", 9000)
    assert isinstance(node.storage, SafeStorage)
    assert node.storage.path == state_dir / "node3.json"
    assert state_dir.is_dir()


# --- serve ---
def test_serve_runs_recovery_then_checks_until_stopped():
    peers = {}
    comm = UdpCommunication(0.3, peers, port=0, host="127.0.0.1")
    node = FakeNode(1, 1, comm, None)
    stop = threading.Event()
    thread = threading.Thread(target=cli.serve, args=(node, comm, stop, 0.02))
    thread.start()

    deadline = time.monotonic() + 5
    while "timeout" not in node.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    peers[1] = ("127.0.0.1", comm.port)
    assert comm.probe(1) is True          # the node answers while serve is running

    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert node.calls[:3] == ["recovery", "check", "timeout"]
    assert comm.probe(1) is False         # and stops answering afterwards


# --- main ---
def test_main_rejects_unknown_command(capsys):
    assert cli.main(["bogus"]) == 2
    assert "usage" in capsys.readouterr().err

def test_main_reports_configuration_error(monkeypatch, capsys):
    monkeypatch.delenv("BULLY_N", raising=False)
    assert cli.main(["node"]) == 2
    assert "BULLY_N is not set" in capsys.readouterr().err
