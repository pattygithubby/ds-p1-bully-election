"""Safe storage for the state vector: survives crashes, updates atomically (Assumption 4)."""

import os
import tempfile
import copy
import json
from pathlib import Path

from .state import StateVector


class SafeStorage:
    """Stores the state vector as a JSON file on disk."""

    def __init__(self, path: Path):
        self.path = path                                  # remember where the file is

    def load(self) -> StateVector:
        """Return the stored state, or a fresh StateVector if nothing has been stored yet."""
        if not self.path.exists():
            return StateVector()
        text = self.path.read_text(encoding="utf-8")      # file -> string
        data = json.loads(text)                                        # string -> dict (json)
        return StateVector.from_dict(data)                      # dict -> StateVector
    
    def atomic_update(self, state: StateVector) -> None:
        """Save the state so that a crash leaves either the old file or the new one, never half of one."""
        text = json.dumps(state.to_dict())                    

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.path.parent,                 # same folder as the real file
            delete=False,                         # we rename it ourselves
            suffix=".tmp",
        )
        try:
            with tmp:                             # the file is closed when the block ends
                tmp.write(text)                   
                tmp.flush()                       # Python -> operating system
                os.fsync(tmp.fileno())            # operating system -> disk
            os.replace(tmp.name, self.path)                  # C
        except Exception:
            os.unlink(tmp.name)                   # something failed: remove the temp file
            raise                                 # and report the error

class MemoryStorage(SafeStorage):
    """Keeps the state in memory. For tests and experiments with many nodes in one process."""

    def __init__(self):
        self._stored: StateVector | None = None   # None = nothing saved yet

    def load(self) -> StateVector:
        if self._stored is None:
            return StateVector()                            # nothing saved yet: a fresh, default StateVector
        return copy.deepcopy(self._stored)                 # a copy of what is stored

    def atomic_update(self, state: StateVector) -> None:
        self._stored = copy.deepcopy(state)                        # store a copy of state, not state itself
