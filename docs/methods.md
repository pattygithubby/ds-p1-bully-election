# Method reference for the `bully` package

A high-level description of every class, method and function in `bully/`, file by file.

## How the pieces fit together

- **`Node`** holds the state and the five message handlers shared by both variants. **`OriginalNode`** adds the paper's election procedures on top. Neither touches sockets or files directly.
- **`Communication`** is the interface a node uses to send the five protocol messages. There are two implementations: `InMemoryCommunication` (tests and experiments) and `UdpCommunication` (Docker / Kubernetes).
- **`SafeStorage`** persists the node's `StateVector` so it survives a crash. `MemoryStorage` is the in-memory version for tests.
- **`__main__`** wires these together and runs one node until it is stopped.

The five protocol messages and the node method each one triggers on the receiver:

| Message | Sent with (`Communication`) | Handled by (`Node`) |
|---|---|---|
| AreYouThere | `probe` | `are_you_there` |
| AreYouNormal | `query_normal` | `are_you_normal` |
| Halt | `send_halt` | `halt` |
| NewCoordinator | `send_new_coordinator` | `new_coordinator` |
| Ready | `send_ready` | `ready` |

## `node.py` — `Node`

The shared base of both variants: the state vector in safe storage and the five message handlers. Node ids run from 1 to `n`; the highest live id becomes coordinator.

### Message handlers

Called by the communication layer when another node sends a message.

| Method | Description |
|---|---|
| `__init__(node_id, n, comm, storage)` | Loads the saved state from storage, resets the status to `DOWN`, clears `h`, and saves. The node does no work yet. Also creates the lock that guards the state and the Halt counter `_halts`. |
| `are_you_there()` | Always returns `True`. Any reply at all proves the node is alive; a crashed node is detected by the communication layer as a missing reply. |
| `are_you_normal()` | Returns whether the node's status is `NORMAL`. |
| `stop_processing()` | Clears the `processing` flag, marking the node as not working. |
| `_stopped(halts)` | Returns whether a Halt has been received since the running election noted the counter value `halts`. |
| `halt(sender_id)` | Moves the node to `ELECTION`, records the sender in `h`, stops work, and saves. It also increments `_halts`, which makes an election this node is running itself give up (the paper's `STOP`). |
| `new_coordinator(sender_id)` | Accepts the sender as coordinator and moves to `REORGANIZATION`. Ignored unless the node is in `ELECTION` and the sender is the node that halted it, which rejects stale messages from an older election. |
| `ready(sender_id, task)` | Stores the task definition, moves to `NORMAL` and allows work. Ignored unless the node is in `REORGANIZATION` and the sender is its coordinator. |

### Procedures

`recovery()`, `election()`, `check()` and `timeout()` are declared here but raise `NotImplementedError`. They are implemented by the subclasses; see `OriginalNode` below.

## `original.py` — `OriginalNode`

The original Bully algorithm (Garcia-Molina 1982, Section III). It adds the four procedures a node starts itself, written from the paper's pseudocode.

| Method | Description |
|---|---|
| `recovery()` | Run once at start-up. Clears `h`, saves, and starts an election. |
| `election()` | The election procedure, described in steps below. |
| `check()` | Run periodically. Only acts if this node is the coordinator and in `NORMAL`: it asks every other node whether it is normal, and starts an election if a live node answers no. Nodes that do not answer are ignored. |
| `timeout()` | Run periodically. In `NORMAL` or `REORGANIZATION` it starts an election if there is no coordinator or the coordinator does not answer a probe; it does nothing if this node is the coordinator. In any other status it starts an election. |

Steps of `election()`:

1. Probe every node with a higher id. If one answers, return; that node will run the election.
2. Stop work, move to `ELECTION`, set `h` to the node's own id and empty the `up` set.
3. Send Halt to every lower id. Each node that acknowledges is added to `up`.
4. Set itself as coordinator and move to `REORGANIZATION`.
5. Send NewCoordinator to every node in `up`. If one does not acknowledge, start again from step 1.
6. Build a `TaskDefinition` with the participants (`up` plus itself) and store it.
7. Send Ready with the task to every node in `up`. If one does not acknowledge, start again from step 1.
8. Move to `NORMAL` and allow work.

The state is saved to storage after every change.

### Concurrency

With the UDP transport the handlers run in the listening thread while `election()`, `check()` and `timeout()` run in the main thread. Two mechanisms keep this safe:

- **Lock.** Every read and write of the state vector happens inside `self._lock`, the paper's critical section. The lock is never held while waiting for another node's reply, so the handlers can always answer within T.
- **Halt aborts a running election.** `election()` notes the value of `_halts` when it starts and compares it (via `_stopped`) before every message it sends and every state change. If a Halt has arrived in the meantime, the election returns at once and leaves the state as the Halt set it, so the halting node's `NewCoordinator` is accepted. Without this, a node halted in the middle of its own election would carry on and make itself coordinator alongside the node that halted it.

## `improved.py` — `ImprovedNode`

The improved variant, a subclass of `OriginalNode`. NewCoordinator is merged into Ready, so an election by node `i` sends `2(i − 1)` messages to the lower nodes instead of `3(i − 1)`. `BULLY_ALGORITHM` selects between the two variants.

| Method | Description |
|---|---|
| `ready(sender_id, task)` | Sets the coordinator, stores the task and moves to `NORMAL` in one step. Ignored unless the node is in `ELECTION` and the sender is the node that halted it, which is the guard NewCoordinator has in the original. |
| `election()` | As in `OriginalNode`, without the NewCoordinator round: after the Halt round the node sets itself as coordinator, builds and stores the task, and sends Ready to every node in `up`. |

Everything else is inherited. `new_coordinator()` still exists but is never called, because the message is not sent. A lower node goes straight from `ELECTION` to `NORMAL`; only the coordinator passes through `REORGANIZATION`.

## `communication.py` — `Communication`

Abstract base class. A node calls these methods to talk to another node; each returns only after the target answered or the timeout bound T passed.

| Method | Description |
|---|---|
| `__init__(timeout_bound_t)` | Stores T. Raises `ValueError` if it is not positive. |
| `probe(target_id)` | AreYouThere. `True` if the target answers, otherwise `False`. |
| `query_normal(target_id)` | AreYouNormal. `True` or `False` from the target, or `None` if it does not answer. |
| `send_halt(target_id, sender_id)` | Sends Halt. `True` if acknowledged, `False` on timeout. |
| `send_new_coordinator(target_id, sender_id)` | Sends NewCoordinator. `True` if acknowledged, `False` on timeout. |
| `send_ready(target_id, sender_id, task)` | Sends Ready with the task definition. `True` if acknowledged, `False` on timeout. |

## `transport_memory.py` — `InMemoryCommunication`

All nodes live in one Python process and share one instance. A message is delivered by calling the target node's handler directly.

| Method | Description |
|---|---|
| `__init__(timeout_bound_t)` | Creates the empty node registry, the set of crashed ids, and the message counter `sent`. |
| `register(node)` | Adds a node to the cluster so messages can reach it. |
| `crash(node_id)` | Simulates a crash: the node stops answering. Only incoming messages are blocked, so the caller must also stop calling the crashed node's own procedures. |
| `restart(node_id)` | The node answers again. Safe to call for a node that was never crashed. To model a real recovery, build a new `Node` on the same storage, register it, and call its `recovery()`. |
| `_deliver(target_id, message)` | Counts one sent message and returns the target node, or `None` if it is crashed or not registered. |
| `probe`, `query_normal`, `send_halt`, `send_new_coordinator`, `send_ready` | Implement the `Communication` interface on top of `_deliver`. |

## `transport_udp.py` — `UdpCommunication`

One instance per node, one node per container. Messages are JSON in UDP packets.

| Function / method | Description |
|---|---|
| `peers_from_template(template, n)` | Module-level function. Expands an address template such as `"node{id}:9000"` or `"bully-{ord}.bully:9000"` into a map from node id to `(host, port)` for ids 1..n. |
| `__init__(timeout_bound_t, peers, port, host)` | Stores the peer map, the listening port and address, and the message counter `sent`. Nothing is opened yet. |
| `start(node)` | Opens the listening socket and starts a background thread that answers requests on behalf of `node`. |
| `stop()` | Stops the thread and closes the socket. To the other nodes this looks like a crash. |
| `_serve()` | The listening loop in the background thread: receive a packet, decode it, call `_handle`, send the reply back. A broken packet or failing handler sends no reply, so the sender sees a timeout. |
| `_handle(request)` | Calls the `Node` handler that matches the request's `type` and returns the reply dict. Raises `ValueError` for an unknown type. |
| `_request(target_id, message)` | Sends one message on a fresh socket and waits up to T for the reply. Returns the reply dict, or `None` on timeout, unknown host or unknown id. A new socket per request means a late reply to an earlier request cannot be mistaken for this one. |
| `probe`, `query_normal`, `send_halt`, `send_new_coordinator`, `send_ready` | Implement the `Communication` interface on top of `_request`. |

## `state.py`

The data a node keeps, convertible to and from plain dicts so it can be stored as JSON and sent between nodes.

| Class / method | Description |
|---|---|
| `Status` | Enum of the four protocol phases: `DOWN`, `ELECTION`, `REORGANIZATION`, `NORMAL`. |
| `TaskDefinition` | Immutable task handed out by the coordinator in Ready: the participant ids and the name of the application algorithm. |
| `TaskDefinition.to_dict()` / `from_dict(data)` | Convert to and from a dict (tuple ↔ list for the participants). |
| `StateVector` | Everything a node must remember across a crash: status `s`, coordinator `c`, task `d`, last halting node `h`, and the set `up` of nodes that answered Halt. |
| `StateVector.to_dict()` / `from_dict(data)` | Convert to and from a dict (status stored by name, `up` stored as a sorted list). |

## `storage.py`

| Class / method | Description |
|---|---|
| `SafeStorage.__init__(path)` | Stores the path of the JSON file that holds this node's state. |
| `SafeStorage.load()` | Returns the stored `StateVector`, or a fresh one if the file does not exist. Returns exactly what was stored; resetting the status on recovery is the node's job. |
| `SafeStorage.atomic_update(state)` | Writes the state to a temp file in the same folder, flushes it to disk, then renames it over the real file. A crash leaves either the old file or the new one, never half of one. |
| `MemoryStorage.__init__()` | Starts with nothing stored. |
| `MemoryStorage.load()` | Returns a deep copy of the stored state, or a fresh `StateVector`. |
| `MemoryStorage.atomic_update(state)` | Stores a deep copy of the state. The copying makes it behave like a disk: changes made after the last update are lost in a simulated crash. |

## `__main__.py`

Entry point for `python -m bully node`, configured through `BULLY_*` environment variables.

| Function / method | Description |
|---|---|
| `Config` | Frozen dataclass with the settings for one node: id, n, algorithm, peer template, port, state directory and timeout. |
| `Config.from_env(env)` | Builds a `Config` from a dict of environment variables and validates it. Raises `ValueError` if a value is missing or wrong. |
| `_number(env, name, kind, default)` | Reads one variable as an int or float, with a clear error if it is missing or not a number. |
| `_id_from_hostname(hostname)` | Derives the node id from a Kubernetes pod name: `bully-3` is node 4. |
| `build(config)` | Creates the storage, the UDP communication and the node. Nothing is started. |
| `describe(node)` | Returns a one-line summary of the node's status and coordinator. |
| `log(node, text)` | Prints a line prefixed with the node id. |
| `serve(node, comm, stop, interval)` | Starts the transport, runs `recovery()`, then calls `check()` and `timeout()` every `interval` seconds until `stop` is set. Logs only when the status changes, and always stops the transport on the way out. |
| `main(argv)` | Checks the arguments, loads the config, installs SIGINT/SIGTERM handlers, and calls `serve`. Returns the exit code. |
