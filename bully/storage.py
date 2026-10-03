"""Safe storage for the state vector: survives crashes, updates atomically (Assumption 4)."""

import copy
import json
import os
import tempfile
from pathlib import Path

from .state import StateVector


class SafeStorage:
    """Stores the state vector as a JSON file on disk."""

    def __init__(self, path: Path):
        self.path = path  # the file that holds this node's state

    def load(self) -> StateVector:
        """Return the stored state, or a fresh StateVector if nothing has been stored yet.

        Returns exactly what was stored. Resetting s to Down on recovery is the node's job.
        """
        if not self.path.exists():
            return StateVector()  # first start: this node has never saved anything
        text = self.path.read_text(encoding="utf-8")
        data = json.loads(text)
        return StateVector.from_dict(data)

    def atomic_update(self, state: StateVector) -> None:
        """Save the state so that a crash leaves either the old file or the new one, never half of one."""
        text = json.dumps(state.to_dict())

        # Write to a temp file first, so the real file is untouched until the new one is complete.
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,  # same folder: os.replace is only atomic within one filesystem
            delete=False,          # we rename it ourselves
            suffix=".tmp",
        )
        try:
            with tmp:
                tmp.write(text)
                tmp.flush()             # Python's buffer -> operating system
                os.fsync(tmp.fileno())  # operating system -> physical disk
            # The file must be closed before the rename (Windows cannot rename an open file).
            os.replace(tmp.name, self.path)  # atomic swap: readers see the old or the new file
        except Exception:
            os.unlink(tmp.name)  # do not leave a half-written temp file behind
            raise


class MemoryStorage(SafeStorage):
    """Keeps the state in memory. For tests and experiments with many nodes in one process.

    Copies on the way in and on the way out, so it behaves like a disk: changes to the
    node's live state are lost in a simulated crash unless atomic_update was called.
    """

    def __init__(self):
        self._stored: StateVector | None = None  # None = nothing saved yet

    def load(self) -> StateVector:
        if self._stored is None:
            return StateVector()
        return copy.deepcopy(self._stored)  # the caller must not be able to change what is stored

    def atomic_update(self, state: StateVector) -> None:
        self._stored = copy.deepcopy(state)  # a snapshot of the state as it is right now
