from .node import Node

class Communication:
    # Configurable timeout bound value
    def __init__(self, timeout_bound_t):
        if timeout_bound_t <= 0:
            raise ValueError("timeout_bound_t must be positive")
        self.timeout_bound_t = timeout_bound_t

    def probe(target_id) -> bool:
        target = self.nodes.get(target_id)

    def query_normal(target_id) -> bool:
        pass

    def send_halt(target_id, sender_id):
        pass

    def send_new_coordinator(target_id, sender_id):
        pass

    def send_ready(target_id, sender_id, task):
        pass