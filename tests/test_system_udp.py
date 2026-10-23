"""System test over real UDP: five nodes, each driven by __main__.serve as in a container.

The same scenario as `docker compose up` / `stop node5` / `start node5`, but on localhost
and in one process, so it runs without Docker.
"""

import pytest

from bully.__main__ import ALGORITHMS
from bully.simulation import UdpCluster

from .test_node import all_normal

N = 5


@pytest.fixture
def cluster(request):
    cluster = UdpCluster(N, ALGORITHMS[request.param])
    yield cluster
    cluster.shutdown()


@pytest.mark.parametrize("cluster", ["original", "improved"], indirect=True)
def test_system_coordinator_crash_and_recovery_over_udp(cluster):
    for node_id in range(1, N + 1):
        cluster.boot(node_id)
    assert cluster.wait_until_settled(), cluster.view()
    assert cluster.view() == all_normal(range(1, N + 1), coordinator=N)

    cluster.crash(N)                       # the coordinator goes down: the next one takes over
    assert cluster.wait_until_settled(), cluster.view()
    assert cluster.view() == all_normal(range(1, N), coordinator=N - 1)

    cluster.boot(N)                        # it comes back and bullies its way back in
    assert cluster.wait_until_settled(), cluster.view()
    assert cluster.view() == all_normal(range(1, N + 1), coordinator=N)
