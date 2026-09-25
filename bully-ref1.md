# Elections in a Distributed Computing System — Condensed Notes

**Hector Garcia-Molina**, *IEEE Transactions on Computers*, Vol. C-31, No. 1, January 1982, pp. 48–59.

---

## The core claim

What "electing a coordinator" even *means* depends entirely on which failures you allow. Garcia-Molina defines two failure environments, states correctness conditions (assertions) for each, and gives one algorithm per environment: **Bully** for the strict environment, **Invitation** for the relaxed one.

Background framing you can skim: a distributed system that hits a failure can either keep running through it or halt and reorganize. This paper only cares about the second. Reorganization has to be run by exactly one node, so step one is electing that node.

---

## The assumptions

**Assumptions 1–7 hold throughout the whole paper:**

1. All nodes run the same election algorithm and cooperate.
2. The local OS and message handler are bug-free.
3. No spontaneous messages — if you received `M` from `j`, `j` actually sent it.
4. Every node has **safe storage** that survives crashes, with atomic updates (an update either fully happens or doesn't). The state vector lives here.
5. **Fail-stop** behavior. A crash halts the node immediately; it later restarts from a fixed state with no processes resumed. Non-safe memory may be lost. Nodes never behave arbitrarily — any partial hardware failure must be converted into a full crash before it can affect anything else. *This rules out Byzantine faults.*
6. No undetected transmission corruption. Says nothing about whether a message arrives at all.
7. Messages from `i` to `j` that *do* arrive are processed in send order. Doesn't mean none are dropped.

**Assumptions 8 and 9 are the strong ones, used only in Section III (Bully):**

8. The communication subsystem never fails and delivers within a known bound **T**. So if you don't get an ack within `T`, you *know* the destination is down.
9. Nodes never pause. Being slow to respond counts as a failure — a node that suspects it may have been slow enough for someone to time out on it is required to crash itself deliberately.

Together 8 and 9 give you **perfect failure detection**, which is exactly what makes Bully work. The paper's justification is that on a reliable LAN (it cites Ethernet) plus hardware timers, this is a defensible engineering assumption.

---

## The state vector

Each node `i` keeps `S(i)` in safe storage:

| Field | Meaning |
|---|---|
| `S(i).s` | Status: **Down**, **Election**, **Reorganization**, **Normal** |
| `S(i).c` | Who `i` thinks the coordinator is. `S(i).c = i` means "I am coordinator." |
| `S(i).d` | Task definition: application algorithms, participant list, etc. |

`Down` is assumed whenever the node is crashed, regardless of what's physically in the cell; on recovery it's reset to `Down`.

**Bully adds two more:**

| Field | Meaning |
|---|---|
| `S(i).h` | Identity of the last node that halted `i`. Lets a node reject stale messages from an earlier, abandoned election. |
| `S(i).Up` | Set of nodes `i` believes are alive. |

`Reorganization` means "we agree on the coordinator but don't yet know our jobs." `Normal` means "working on the task."

---

## Correctness conditions for the strict environment

### Assertion 1 (safety) — must hold at *every* instant, not just at election end

a) If two nodes are both in {Reorganization, Normal}, they have the same `.c`.
b) If two nodes are both Normal, they have the same `.d`.

Nodes that are Down or in Election are exempt, since they aren't doing anything. The "at all times" strengthening is the paper's improvement over prior work: it prevents a node from believing it's coordinator while the protocol is still running elsewhere.

### Assertion 2 (liveness)

If no failures occur *during* the election, the protocol eventually reaches a state where one node `i` has `s = Normal, c = i` and every non-failed node `j` has `s = Normal, c = i`.

It has to be conditioned on no failures, because an unlucky infinite string of failures can stall any protocol forever.

### What a coordinator actually knows

*(This is the paper's best conceptual point.)* Being coordinator only guarantees that every *currently active* node recognizes you, and that no one else can become coordinator while you stay up. It does **not** tell you who is active. Constituents can die at any moment. So a coordinator cannot just issue commands and assume they happened — it must use **two-phase commit** for anything that needs all-or-nothing execution across a set of nodes.

### Why elections ≠ mutual exclusion

Three differences, which is why you shouldn't just reuse a mutex protocol:

1. Fairness is irrelevant — a working coordinator never needs to yield. This makes elections *simpler* than mutex.
2. The protocol must handle the holder of the "critical region" crashing; most mutex algorithms assume it won't.
3. The winner must actively inform everyone else; in mutex, nodes outside the region don't care who's inside.

---

## The Bully Algorithm

Node IDs are `1..n`, unique, assigned at creation, and act as priority. Highest live ID wins by forcing everyone below it to submit.

### Part 1 — clear the field above you

Ping every node `j` where `i < j ≤ n`.

- If **any** responds, `i` gives up and waits for that node to become coordinator (and restarts the election from scratch if no coordinator materializes in time).
- If **all** time out, Assumption 8 means they're definitely down, so Assertion 1 is satisfied with respect to everyone above `i`.

At this point `i` has effectively won: the higher nodes are dead, and every lower node will fail its own Part 1 because `i` is alive.

### Part 2 — take the nodes below you, in two steps

One step would break Assertion 1, so:

- **Step A (halt):** send `Halt` to each lower node, which sets its status to `Election`, records `h = i`, and stops all its processing — a simulated failure. Now every lower node is in a known, inert state, so state vectors can be rewritten safely. Nodes that respond go into `S(i).Up`.
- **Step B (announce):** send "I am elected" to everyone in `Up`. Each recipient sets `c = i`, then `s = Reorganization` — **but only after checking that the last `Halt` it received came from `i`.** That check is what `h` is for.

Then `i` sets its own `c = i, s = Reorganization`, computes the new task description, distributes it (`Ready`), and everyone moves to `Normal`.

### Recovery is not special

A recovering node just resets `h` to undefined and runs the ordinary election protocol. This works out cleanly: in running Part 2 it halts any lower-priority node that was mid-election, so it can't corrupt an election in progress. **That means the algorithm described for the never-recover case *is* the complete algorithm.**

---

## Implementation detail

The five message handlers are **immediate procedures**: executed directly by the receiving OS rather than by spawning a process, and guaranteed to respond within `T`. Keep them short and don't nest calls inside them.

| Procedure | Behavior |
|---|---|
| `AreYouThere(i)` | No-op, existence probe. |
| `AreYouNormal(i, ans)` | Answer `Yes` iff `s = Normal`. |
| `Halt(i, j)` | `s := Election; h := j; STOP` |
| `NewCoordinator(i, j)` | **if `h = j` and `s = Election`** → `c := j; s := Reorganization` |
| `Ready(i, j, x)` | **if `c = j` and `s = Reorganization`** → `d := x; s := Normal` |

Those guard conditions are **not optional**; they're what rejects messages from superseded elections.

### `Election(i)`

```
for j := i+1 .. n:
    call AreYouThere(j), ontimeout(T): continue
    return                      // someone above is alive, abandon bid

STOP                            // halt own processing
s := "Election"; h := i; Up := {}
for j := i-1 downto 1:
    call Halt(j, i), ontimeout(T): continue
    Up := Up ∪ {j}
// "election point" reached here
c := i; s := "Reorganization"
for j in Up:
    call NewCoordinator(j, i), ontimeout(T): { Election(i); return }
// compute new task description d (typically includes a copy of Up)
for j in Up:
    call Ready(j, i, d), ontimeout(T): { Election(i); return }
s := "Normal"
```

Any timeout in Part 2 means a participant died, and the simplest correct response is to restart the whole election.

### Three driver procedures

- **`Recovery(i)`** — `h := undefined; Election(i)`. Called by the OS on restart, or by the application when it notices the coordinator is gone.
- **`Check(i)`** — called periodically. If `s = Normal and c = i`, poll all other nodes with `AreYouNormal`; if any answers "No," call `Election(i)`. This catches nodes stranded in `Election` or `Reorganization`.
- **`Timeout(i)`** — fired when nothing has been heard from the coordinator for a while. If `s ∈ {Normal, Reorganization}`, probe the coordinator with `AreYouThere`; on timeout, call `Election(i)`. Otherwise call `Election(i)` directly.

### Concurrency

Processes at one node run concurrently, so all state-vector access sits in a critical section (the `[[ ]]` brackets in the paper). If `STOP` fires while a process is inside its critical region, the OS lets it exit first. After a crash the mutual-exclusion mechanism resets.

### Theorem 1

Under Assumptions 1–9, Bully satisfies Assertions 1 and 2. The proofs in Appendix I are informal contradiction arguments; you don't need them to implement, but the part-(a) proof is where the `h` field earns its keep, and the part-(b) proof relies on FIFO delivery (Assumption 7).

---

## The relaxed environment

Drop Assumptions 8 and 9 and you get partitions, one-way links, non-transitive reachability (`i` and `j` can both reach `k` but not each other), and arbitrary pauses.

### Theorem 2 — impossibility

In such a system, **no protocol satisfies Assertions 1 and 2.**

*Sketch:* a node `i` can be `Normal` with `c = i` while unreachable or paused. The others see it as Down, so Assertion 2 obliges them to elect someone new, which immediately violates Assertion 1.

So "coordinator" has to be redefined as **local to a group** rather than global.

### Group numbers

Every group formed gets a unique number, carried in every message, so foreign messages can be ignored. Generated as `node_id` concatenated with a per-node counter, both in safe storage. **Uniqueness is the only property required.** `S(i).g` holds the current group number, `S(i).counter` the counter.

### Assertion 3

Assertion 1 with `S(i).g = S(j).g` added as a precondition to both clauses. Assertion 1 is just the special case where everything is one fixed group.

### Assertion 4

Liveness, scoped to a maximal set `R` of nodes with two-way communication among all members: absent failures, all of `R` converges on one coordinator and one group number. Nodes with one-way or partial connectivity are explicitly given **no guarantees**.

### The Invitation Algorithm (informally)

You can't bully anyone when several nodes may each believe they're the highest-priority survivor, so instead of forcing, coordinators **invite**.

- A recovering or stranded node forms a **singleton group** with itself as coordinator.
- Coordinators periodically look around (`AreYouCoordinator`) for other coordinators and try to merge.
- Lower-priority nodes **defer proportionally to the priority gap**, so the highest-ID candidate usually organizes the merge first. This only reduces conflict probability rather than eliminating it — which is fine: conflicting merges just produce two groups that merge again later.
- Merging creates a **fresh group number**, so invited nodes rejoin cleanly rather than silently migrating.
- A node accepting an invitation **forwards it to its own old members** if it was itself a coordinator.

Note also that `T` no longer means certainty here, only "probably down," and immediate procedures are dropped.

### Two practical points worth keeping

- **Restricted operations under partition:** if isolated groups must not concurrently do something (e.g. update replicated data), require that a group hold a **majority** of the system's nodes before it may do it. At most one group can. Consequence: sometimes *no* group is allowed to proceed. The check happens during reorganization, and the operation itself still needs two-phase commit, since membership can shrink between the count and the act.
- **Group histories:** recording group number, coordinator, members, and predecessor groups produces a DAG back to the original group, useful at reorganization time for cleaning up conflicting work from prior groups.

The author's own closing recommendation is that **Invitation may be the better choice even when Assumptions 8 and 9 hold**, since it's more general and not much more complicated.

---

## What you can safely skip

- The introductory sensor-network example
- The continuous-operation-vs-reorganization digression
- The `CALL`/`ONTIMEOUT`/`IMMEDIATE` OS-facility description in Appendix I — that's just 1982 pseudocode plumbing; in a modern implementation it's an RPC with a timeout
- Both informal proofs, unless your project asks for correctness argumentation

---

## Implementation gotchas

If you're implementing Bully specifically, the four things people get wrong:

1. **The guard conditions** on `NewCoordinator` and `Ready`
2. **The separation of halt from announce** (two steps, not one)
3. **The `h` field** — rejecting stale messages from superseded elections
4. **Treating recovery as a plain election**, not a special case
