"""One writer process per research store (WEL-41).

An advisory `flock` on a file beside the resolved SQLite path, held for the lifetime of the
worker process. The OS releases it when the holder exits or is killed, so there is no lease to
expire and no stale-lock cleanup. A second entrance while it is held gets `False` and must do
no request and no model call. Every worker entrance (manual `run`, `cycle`) goes through this.
"""
import fcntl
import os
from pathlib import Path
from typing import Optional, Union


def lock_path(db_path: Union[str, Path]) -> Path:
    p = Path(db_path).resolve()
    return p.with_name(p.name + ".lock")


class StoreLock:
    def __init__(self, db_path: Union[str, Path]):
        self.path = lock_path(db_path)
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        """Non-blocking. True if this process now holds the lock, False if another holds it.
        Raises OSError if the lock file cannot be opened (treated as store unavailable)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        try:  # for humans inspecting a held lock; not used for any decision
            os.ftruncate(fd, 0)
            os.write(fd, ("pid %d\n" % os.getpid()).encode())
        except OSError:
            pass
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None

    @property
    def held(self) -> bool:
        return self._fd is not None
