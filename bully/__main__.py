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
    BULLY_LOG_LEVEL  INFO shows state changes, election messages and failures;
                     DEBUG also shows the routine heartbeats (default: INFO)

What this file expects from Node (see the class diagram):
    NodeClass(node_id, n, comm, storage)   constructor
    node.recovery()                        called once at start-up
    node.check(), node.timeout()           called every CHECK_INTERVAL seconds
"""

import logging
import os
import re
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from .improved import ImprovedNode
from .original import OriginalNode
from .state import StateVector, Status
from .storage import SafeStorage
from .transport_udp import UdpCommunication, peers_from_template

ALGORITHMS = {"original": OriginalNode, "improved": ImprovedNode}
LOG_LEVELS = ("DEBUG", "INFO", "WARNING")

CHECK_INTERVAL = 2.0  # seconds between each round of check() and timeout()

log = logging.getLogger("bully")


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
    log_level: str = "INFO"

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

        log_level = env.get("BULLY_LOG_LEVEL", "INFO").upper()
        if log_level not in LOG_LEVELS:
            raise ValueError(f"BULLY_LOG_LEVEL must be one of {list(LOG_LEVELS)}, not {log_level!r}")

        return cls(
            node_id=node_id,
            n=n,
            algorithm=algorithm,
            peers=env["BULLY_PEERS"],
            port=_number(env, "BULLY_PORT", int, default="9000"),
            state_dir=Path(env.get("BULLY_STATE_DIR", "/data")),
            timeout=_number(env, "BULLY_TIMEOUT", float, default="1.0"),
            log_level=log_level,
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


def describe(node_id: int, state: StateVector) -> str:
    """Say in one line what a node's state means, e.g. "ELECTION: halted by node 5, waiting for it"."""
    if state.s == Status.DOWN:
        return "DOWN: starting"
    if state.s == Status.ELECTION:
        if state.h == node_id:
            return "ELECTION: running its own election"
        return f"ELECTION: halted by node {state.h}, waiting for it"
    if state.s == Status.REORGANIZATION:
        if state.c == node_id:
            return f"REORGANIZATION: coordinator, announcing to nodes {sorted(state.up)}"
        return f"REORGANIZATION: node {state.c} is coordinator, waiting for the task"
    if state.c == node_id:
        return f"NORMAL: coordinator of nodes {list(state.d.participants)}"
    return f"NORMAL: node {state.c} is coordinator"


class LoggingStorage(SafeStorage):
    """SafeStorage that also logs the node's state each time its meaning changes.

    Every state change is saved (Assumption 4), so the save is the one place where every
    change can be seen, whichever thread made it.
    """

    def __init__(self, path: Path, node_id: int):
        super().__init__(path)
        self.node_id = node_id
        self._last_line = None   # the description logged last, to log only real changes

    def atomic_update(self, state: StateVector) -> None:
        super().atomic_update(state)
        line = describe(self.node_id, state)
        if line != self._last_line:
            log.info(line)
            self._last_line = line


def message_summary(comm) -> str:
    """E.g. "sent 37 messages (AreYouThere 20, Halt 6, ...), 5 unanswered"."""
    by_type = ", ".join(f"{kind} {count}" for kind, count in sorted(comm.sent.items()))
    return (f"sent {comm.sent.total()} messages ({by_type or 'none'}), "
            f"{comm.unanswered.total()} unanswered")


def build(config: Config):
    """Create the node and its communication from the config. Nothing is started yet."""
    config.state_dir.mkdir(parents=True, exist_ok=True)   # SafeStorage needs the folder to exist
    storage = LoggingStorage(config.state_dir / f"node{config.node_id}.json", config.node_id)
    peers = peers_from_template(config.peers, config.n)
    comm = UdpCommunication(config.timeout, peers, config.port)
    node = ALGORITHMS[config.algorithm](config.node_id, config.n, comm, storage)
    return node, comm


def serve(node, comm, stop: threading.Event, interval: float = CHECK_INTERVAL) -> None:
    """Run the node until stop is set. State changes are logged by LoggingStorage."""
    comm.start(node)    # start answering the other nodes before taking part in an election
    try:
        log.info("listening on port %d", comm.port)
        node.recovery()    # a (re)started node always begins with an election
        while not stop.wait(interval):    # sleeps for interval, but wakes at once when stop is set
            node.check()      # coordinator: is every node Normal?
            node.timeout()    # everyone else: is the coordinator still there?
    finally:
        comm.stop()
        log.info("stopped; %s", message_summary(comm))


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

    logging.basicConfig(
        level=config.log_level, format=f"[node {config.node_id}] %(message)s", stream=sys.stdout
    )
    log.info("%s Bully, %d nodes, T = %.1f s", config.algorithm, config.n, config.timeout)
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
