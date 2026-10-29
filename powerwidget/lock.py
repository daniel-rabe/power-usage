"""Make sure only one process writes samples, so energy is never counted twice."""

from __future__ import annotations

import os
from pathlib import Path


class InstanceLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()  # closing the handle drops the lock on both platforms
            self._fh = None


def logger_lock(db_path: str) -> InstanceLock:
    return InstanceLock(db_path + ".lock")
