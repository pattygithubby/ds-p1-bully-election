import json
import os

import pytest

from bully.state import StateVector, Status, TaskDefinition
from bully.storage import MemoryStorage, SafeStorage


def example_state() -> StateVector:
    return StateVector(s=Status.NORMAL, c=5, d=TaskDefinition((1, 5), "x"), h=5, up={1, 2})


# --- Part 1: MemoryStorage ---
def test_memory_fresh_state():
    assert MemoryStorage().load() == StateVector()

def test_memory_round_trip():
    st = MemoryStorage()
    st.atomic_update(example_state())
    assert st.load() == example_state()

def test_memory_snapshot_on_save():
    st = MemoryStorage()
    v = StateVector(c=3)
    st.atomic_update(v)
    v.c = 99                         # changed AFTER saving...
    assert st.load().c == 3          # ...must not affect what was stored

def test_memory_returns_copy():
    st = MemoryStorage()
    st.atomic_update(StateVector(c=3))
    st.load().c = 99                 # changing what we loaded...
    assert st.load().c == 3          # ...must not affect what is stored


# --- Part 2: SafeStorage.load ---
def test_load_missing_file(tmp_path):
    assert SafeStorage(tmp_path / "node.json").load() == StateVector()

def test_load_existing_file(tmp_path):
    path = tmp_path / "node.json"
    path.write_text(json.dumps(example_state().to_dict()), encoding="utf-8")
    assert SafeStorage(path).load() == example_state()


# --- Part 3: SafeStorage.atomic_update ---
def test_update_round_trip(tmp_path):
    st = SafeStorage(tmp_path / "node.json")
    st.atomic_update(example_state())
    assert st.load() == example_state()

def test_update_overwrites(tmp_path):
    st = SafeStorage(tmp_path / "node.json")
    st.atomic_update(StateVector(c=1))
    st.atomic_update(StateVector(c=2))
    assert st.load().c == 2

def test_update_leaves_no_temp_files(tmp_path):
    st = SafeStorage(tmp_path / "node.json")
    st.atomic_update(example_state())
    assert list(tmp_path.iterdir()) == [tmp_path / "node.json"]

def test_update_crash_keeps_old_file(tmp_path, monkeypatch):
    st = SafeStorage(tmp_path / "node.json")
    st.atomic_update(StateVector(c=1))

    def crash(*args):
        raise OSError("simulated crash before the rename")
    monkeypatch.setattr(os, "replace", crash)   # make the final step fail

    with pytest.raises(OSError):
        st.atomic_update(StateVector(c=2))
    monkeypatch.undo()

    assert st.load().c == 1                                   # old state is intact
    assert list(tmp_path.iterdir()) == [tmp_path / "node.json"]  # temp file cleaned up
