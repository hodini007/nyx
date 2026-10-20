import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path


PARTIAL = {".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload", ".aria2", ".!ut", ".temp"}
JUNK = {"desktop.ini", "thumbs.db", ".ds_store"}


@dataclass
class FileInfo:
    path: Path
    size: int
    mtime: float
    sha: str | None = None
    cache: object = field(default=None, repr=False, compare=False)

    @property
    def sha256(self) -> str:
        """Content hash, computed only when needed and remembered in the cache."""
        if self.sha is None:
            key = (str(self.path), self.size, self.mtime)
            found = self.cache.get(key) if self.cache is not None else None
            if found is None:
                found = hash_file(self.path)
                if self.cache is not None:
                    self.cache[key] = found
            self.sha = found
        return self.sha

    @property
    def name(self) -> str:
        return self.path.name


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def scan(root: Path, min_age_hours: float = 24.0, hash_cache: dict | None = None) -> tuple[list[FileInfo], list[Path]]:
    """Top-level regular files only. Returns (files, skipped_recent)."""
    cutoff = time.time() - min_age_hours * 3600
    files: list[FileInfo] = []
    skipped: list[Path] = []
    for p in sorted(root.iterdir()):
        if p.name.startswith(".") or p.name.lower() in JUNK or p.suffix.lower() in PARTIAL or p.is_symlink() or not p.is_file():
            continue
        st = p.stat()
        if st.st_mtime > cutoff:
            skipped.append(p)
            continue
        files.append(FileInfo(p, st.st_size, st.st_mtime, None, hash_cache))
    return files, skipped
