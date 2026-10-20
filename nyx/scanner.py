import hashlib
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FileInfo:
    path: Path
    size: int
    mtime: float
    sha256: str

    @property
    def name(self) -> str:
        return self.path.name


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path, min_age_hours: float = 24.0) -> tuple[list[FileInfo], list[Path]]:
    """Top-level regular files only. Returns (files, skipped_recent)."""
    cutoff = time.time() - min_age_hours * 3600
    files: list[FileInfo] = []
    skipped: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") or p.is_symlink() or not p.is_file():
            continue
        st = p.stat()
        if st.st_mtime > cutoff:
            skipped.append(p)
            continue
        files.append(FileInfo(p, st.st_size, st.st_mtime, hash_file(p)))
    return files, skipped
