from bully.state import Status, TaskDefinition, StateVector


# --- Part 1 ---
def test_status_has_four_members():
    assert [m.name for m in Status] == ["DOWN", "ELECTION", "REORGANIZATION", "NORMAL"]

def test_status_name_round_trip():
    assert Status[Status.ELECTION.name] is Status.ELECTION


# --- Part 2 ---
def test_task_round_trip():
    t = TaskDefinition(participants=(1, 2, 3), application_algorithm="demo")
    assert TaskDefinition.from_dict(t.to_dict()) == t

def test_task_participants_is_tuple_after_round_trip():
    t = TaskDefinition.from_dict({"participants": [1, 2], "application_algorithm": "x"})
    assert t.participants == (1, 2)

def test_task_is_frozen():
    import dataclasses, pytest
    t = TaskDefinition((1,), "x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.application_algorithm = "changed"


# --- Part 3 ---
def test_state_defaults():
    v = StateVector()
    assert (v.s, v.c, v.d, v.h, v.up) == (Status.DOWN, None, None, None, set())

def test_state_up_not_shared():
    a, b = StateVector(), StateVector()
    a.up.add(3)
    assert b.up == set()

def test_state_round_trip_full():
    v = StateVector(s=Status.NORMAL, c=5, d=TaskDefinition((1, 5), "x"), h=5, up={1, 2})
    assert StateVector.from_dict(v.to_dict()) == v

def test_state_round_trip_empty():
    assert StateVector.from_dict(StateVector().to_dict()) == StateVector()
