"""Entry point: `python -m bully node` runs one node until it is stopped.

Configured through environment variables:
    BULLY_ID         this node's id, 1..n. If unset, it is taken from the host name:
                     Kubernetes pod "bully-3" is node 4 (ordinal + 1).
    BULLY_N          number of nodes
    BULLY_ALGORITHM  "original" or "improved" (default: improved)
    BULLY_PEERS      address template, e.g. "node{id}:9000" or "bully-{ord}.bully:9000"
    BULLY_PORT       UDP port to listen on (default: 9000)
    BULLY_STATE_DIR  directory for safe storage (default: /data)
    BULLY_TIMEOUT    the bound T in seconds (default: 1.0)

What this file expects from Node (see the class diagram):
    NodeClass(node_id, n, comm, storage)   constructor
    node.recovery()                        called once at start-up
    node.check(), node.timeout()           called every CHECK_INTERVAL seconds
    node.state                             the StateVector, read for logging
"""

import os
import re
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .improved import ImprovedNode
from .original import OriginalNode
from .storage import SafeStorage
from .transport_udp import UdpCommunication, peers_from_template

ALGORITHMS = {"original": OriginalNode, "improved": ImprovedNode}

CHECK_INTERVAL = 2.0  # seconds between each round of check() and timeout()


@dataclass(frozen=True)
class Config:
    """The settings for one node, read from the environment."""

    node_id: int
    n: int
    algorithm: str
    peers: str       # address template for the other nodes
    port: int
    state_dir: Path
    timeout: float   # the bound T, in seconds

    @classmethod
    def from_env(cls, env) -> "Config":
        """Build a Config from a dict of environment variables. Raises ValueError if one is wrong."""
        n = _number(env, "BULLY_N", int)
        if "BULLY_ID" in env:
            node_id = _number(env, "BULLY_ID", int)
        else:
            node_id = _id_from_hostname(env.get("HOSTNAME", ""))
        if not 1 <= node_id <= n:
            raise ValueError(f"node id {node_id} is not in 1..{n}")

        algorithm = env.get("BULLY_ALGORITHM", "improved")
        if algorithm not in ALGORITHMS:
            raise ValueError(f"BULLY_ALGORITHM must be one of {sorted(ALGORITHMS)}, not {algorithm!r}")

        if "BULLY_PEERS" not in env:
            raise ValueError("BULLY_PEERS is not set")

        return cls(
            node_id=node_id,
            n=n,
            algorithm=algorithm,
            peers=env["BULLY_PEERS"],
            port=_number(env, "BULLY_PORT", int, default="9000"),
            state_dir=Path(env.get("BULLY_STATE_DIR", "/data")),
            timeout=_number(env, "BULLY_TIMEOUT", float, default="1.0"),
        )


def _number(env, name: str, kind, default: str | None = None):
    """Read env[name] as an int or a float, with a clear error if it is missing or not a number."""
    text = env.get(name, default)
    if text is None:
        raise ValueError(f"{name} is not set")
    try:
        return kind(text)
    except ValueError:
        raise ValueError(f"{name} must be a number, not {text!r}") from None


def _id_from_hostname(hostname: str) -> int:
    """Kubernetes names the pods bully-0, bully-1, ...; node ids start at 1."""
    match = re.search(r"-(\d+)$", hostname)
    if match is None:
        raise ValueError("BULLY_ID is not set, and the host name does not end in a pod number")
    return int(match.group(1)) + 1


def build(config: Config):
    """Create the node and its communication from the config. Nothing is started yet."""
    config.state_dir.mkdir(parents=True, exist_ok=True)   # SafeStorage needs the folder to exist
    storage = SafeStorage(config.state_dir / f"node{config.node_id}.json")
    peers = peers_from_template(config.peers, config.n)
    comm = UdpCommunication(config.timeout, peers, config.port)
    node = ALGORITHMS[config.algorithm](config.node_id, config.n, comm, storage)
    return node, comm


def describe(node) -> str:
    return f"status={node.state.s.name} coordinator={node.state.c}"


def log(node, text: str) -> None:
    print(f"[node {node.id}] {text}", flush=True)


def serve(node, comm, stop: threading.Event, interval: float = CHECK_INTERVAL) -> None:
    """Run the node until stop is set."""
    comm.start(node)    # start answering the other nodes before taking part in an election
    try:
        log(node, f"started, {describe(node)}")
        node.recovery()    # a (re)started node always begins with an election
        last = None
        while not stop.wait(interval):    # sleeps for interval, but wakes at once when stop is set
            node.check()      # coordinator: is every node Normal?
            node.timeout()    # everyone else: is the coordinator still there?
            now = describe(node)
            if now != last:   # only log when something changed
                log(node, now)
                last = now
    finally:
        comm.stop()
        log(node, "stopped")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["node"]:
        print("usage: python -m bully node", file=sys.stderr)
        return 2
    try:
        config = Config.from_env(os.environ)
    except ValueError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    node, comm = build(config)

    # Stop cleanly on Ctrl+C and on `docker stop` (SIGTERM). The handler is needed in a
    # container: a process running as PID 1 ignores SIGTERM unless it handles it itself.
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())

    serve(node, comm, stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
