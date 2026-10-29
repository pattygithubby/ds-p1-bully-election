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
            return StateVector()  # first start
        return StateVector.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def atomic_update(self, state: StateVector) -> None:
        """Save the state so that a crash leaves either the old file or the new one, never half of one."""
        text = json.dumps(state.to_dict())

        # Write a temp file first, so the real file is untouched until the new one is complete
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,  # os.replace is only atomic within one filesystem
            delete=False,
            suffix=".tmp",
        )
        try:
            with tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())  # make sure it is on disk, not just in the OS cache
            # Closed before the rename, because Windows can't rename an open file
            os.replace(tmp.name, self.path)
        except Exception:
            os.unlink(tmp.name)
            raise


class MemoryStorage(SafeStorage):
    """Keeps the state in memory. For tests and experiments with many nodes in one process.

    Copies on the way in and on the way out, so it behaves like a disk: changes to the
    node's live state are lost in a simulated crash unless atomic_update was called.
    """

    def __init__(self):
        self._stored: StateVector | None = None

    def load(self) -> StateVector:
        if self._stored is None:
            return StateVector()
        return copy.deepcopy(self._stored)

    def atomic_update(self, state: StateVector) -> None:
        self._stored = copy.deepcopy(state)
