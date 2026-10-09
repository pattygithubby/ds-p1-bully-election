from bully.original import OriginalNode
from bully.state import Status, TaskDefinition
from bully.storage import MemoryStorage
from bully.transport_memory import InMemoryCommunication


class Cluster:
    """n real nodes on one in-memory transport, each with its own storage."""

    def __init__(self, n, comm=None, node_class=OriginalNode):
        self.n = n
        self.node_class = node_class
        self.comm = comm or InMemoryCommunication(timeout_bound_t=1)
        self.stores = {i: MemoryStorage() for i in range(1, n + 1)}
        self.nodes = {}
        for i in range(1, n + 1):
            self.boot(i)

    def boot(self, node_id):
        """(Re)start a node from its safe storage, as after a crash. Does not run recovery()."""
        self.comm.restart(node_id)
        self.nodes[node_id] = self.node_class(node_id, self.n, self.comm, self.stores[node_id])
        self.comm.register(self.nodes[node_id])
        return self.nodes[node_id]

    def recover_all(self):
        """Run recovery() on every node that is up. A crashed node must not send anything."""
        for node_id in sorted(self.nodes):
            if node_id not in self.comm.crashed:
                self.nodes[node_id].recovery()

    def rounds(self, count=3):
        """What serve() does periodically, for every node that is up."""
        for _ in range(count):
            for node_id in sorted(self.nodes):
                if node_id not in self.comm.crashed:
                    self.nodes[node_id].check()
                    self.nodes[node_id].timeout()

    def view(self):
        """{id: (status, coordinator)} for every node that is up."""
        return {
            node_id: (node.state.s, node.state.c)
            for node_id, node in sorted(self.nodes.items())
            if node_id not in self.comm.crashed
        }


def all_normal(ids, coordinator):
    return {node_id: (Status.NORMAL, coordinator) for node_id in ids}


def test_new_node_starts_down_and_idle():
    node = Cluster(1).nodes[1]
    assert node.state.s == Status.DOWN
    assert node.state.h is None
    assert node.processing is False


def test_highest_node_becomes_coordinator():
    cluster = Cluster(4)
    cluster.recover_all()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)
    assert cluster.nodes[4].state.up == {1, 2, 3}
    assert all(node.processing for node in cluster.nodes.values())


def test_all_nodes_get_the_same_task():
    cluster = Cluster(3)
    cluster.recover_all()
    task = TaskDefinition(participants=(1, 2, 3), application_algorithm="behandl opgaver")
    assert [node.state.d for node in cluster.nodes.values()] == [task, task, task]


def test_single_node_elects_itself():
    cluster = Cluster(1)
    cluster.recover_all()
    assert cluster.view() == all_normal([1], coordinator=1)


def test_node_does_not_bid_when_a_higher_node_answers():
    cluster = Cluster(3)
    cluster.nodes[1].recovery()
    assert cluster.nodes[1].state.s == Status.DOWN
    assert cluster.comm.sent["Halt"] == 0


def test_coordinator_crash_is_detected_by_timeout():
    cluster = Cluster(4)
    cluster.recover_all()
    cluster.comm.crash(4)
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)


def test_recovering_highest_node_takes_over():
    cluster = Cluster(4)
    cluster.comm.crash(4)
    cluster.recover_all()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)

    cluster.boot(4).recovery()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)


def test_recovering_lower_node_is_picked_up_by_check():
    cluster = Cluster(3)
    cluster.recover_all()
    cluster.comm.crash(1)
    cluster.boot(1).recovery()    # node 3 answers the probe, so node 1 stays Down
    assert cluster.nodes[1].state.s == Status.DOWN

    cluster.rounds()              # the coordinator's check() sees a node that is not Normal
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)


def test_halt_stops_processing_and_records_sender():
    cluster = Cluster(3)
    cluster.recover_all()
    node = cluster.nodes[1]
    node.halt(2)
    assert (node.state.s, node.state.h, node.processing) == (Status.ELECTION, 2, False)


def test_new_coordinator_is_ignored_unless_sender_sent_the_last_halt():
    node = Cluster(3).nodes[1]
    node.halt(2)
    node.new_coordinator(3)
    assert (node.state.s, node.state.c) == (Status.ELECTION, None)
    node.new_coordinator(2)
    assert (node.state.s, node.state.c) == (Status.REORGANIZATION, 2)


def test_ready_is_ignored_unless_sender_is_the_coordinator():
    node = Cluster(3).nodes[1]
    task = TaskDefinition(participants=(1, 2), application_algorithm="x")
    node.halt(2)
    node.new_coordinator(2)
    node.ready(3, task)
    assert (node.state.s, node.state.d) == (Status.REORGANIZATION, None)
    node.ready(2, task)
    assert (node.state.s, node.state.d, node.processing) == (Status.NORMAL, task, True)


def test_state_is_saved_and_reset_to_down_on_restart():
    cluster = Cluster(3)
    cluster.recover_all()
    cluster.comm.crash(2)
    node = cluster.boot(2)
    assert (node.state.s, node.state.c, node.state.h) == (Status.DOWN, 3, None)


class RecoverDuring(InMemoryCommunication):
    """Lets node `riser` recover in the middle of another node's election.

    The recovery runs just before the first `message` from `sender` to `target` is delivered.
    """

    def __init__(self, message, sender, target, riser):
        super().__init__(timeout_bound_t=1)
        self.trigger = (message, sender, target)
        self.riser = riser
        self.cluster = None
        self.armed = False

    def _fire(self, message, sender_id, target_id):
        if self.armed and (message, sender_id, target_id) == self.trigger:
            self.armed = False
            self.cluster.boot(self.riser).recovery()

    def send_halt(self, target_id, sender_id):
        self._fire("Halt", sender_id, target_id)
        return super().send_halt(target_id, sender_id)

    def send_new_coordinator(self, target_id, sender_id):
        self._fire("NewCoordinator", sender_id, target_id)
        return super().send_new_coordinator(target_id, sender_id)

    def send_ready(self, target_id, sender_id, task):
        self._fire("Ready", sender_id, target_id)
        return super().send_ready(target_id, sender_id, task)


def race(message, target, node_class=OriginalNode):
    """Node 3 runs an election with node 4 down; node 4 recovers at the given point in it."""
    comm = RecoverDuring(message, sender=3, target=target, riser=4)
    cluster = Cluster(4, comm, node_class)
    comm.cluster = cluster
    comm.crash(4)
    cluster.recover_all()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)

    comm.armed = True
    cluster.nodes[3].election()
    return cluster


def assert_one_coordinator(cluster):
    """Assertion 1a: nodes in Reorganization or Normal agree on the coordinator."""
    coordinators = {
        c for s, c in cluster.view().values() if s in (Status.REORGANIZATION, Status.NORMAL)
    }
    assert len(coordinators) <= 1


def test_halt_during_halt_loop_aborts_the_election():
    cluster = race("Halt", target=1)
    assert cluster.nodes[3].state.c == 4    # node 3 gave up its own bid
    assert_one_coordinator(cluster)
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)


def test_halt_during_new_coordinator_aborts_the_election():
    cluster = race("NewCoordinator", target=1)
    assert_one_coordinator(cluster)
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)


def test_halt_during_ready_aborts_the_election():
    cluster = race("Ready", target=2)
    assert_one_coordinator(cluster)
    cluster.rounds()
    assert cluster.view() == all_normal([1, 2, 3, 4], coordinator=4)


def test_halt_during_probing_aborts_the_election():
    """Node 2 has probed node 3 (down) and is probing node 4 (down) when node 3 recovers."""

    class RecoverDuringProbe(InMemoryCommunication):
        cluster = None
        armed = False

        def probe(self, target_id):
            if self.armed and target_id == 4:
                self.armed = False
                self.cluster.boot(3).recovery()
            return super().probe(target_id)

    comm = RecoverDuringProbe(timeout_bound_t=1)
    cluster = Cluster(4, comm)
    comm.cluster = cluster
    comm.crash(3)
    comm.crash(4)
    cluster.recover_all()
    assert cluster.view() == all_normal([1, 2], coordinator=2)

    comm.armed = True
    cluster.nodes[2].election()
    assert cluster.view() == all_normal([1, 2, 3], coordinator=3)
