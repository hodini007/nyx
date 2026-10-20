import os
from pathlib import Path


class FileLock:
    """Non-blocking exclusive lock that works on Linux, macOS and Windows."""

    def __init__(self, path: Path):
        self.path = path
        self.fh = None

    def acquire(self) -> bool:
        self.fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.fh.close()
            self.fh = None
            return False

    def release(self) -> None:
        if not self.fh:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.fh.close()
            self.fh = None
