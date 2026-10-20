import sqlite3
from pathlib import Path


def open_db(root: Path) -> sqlite3.Connection:
    d = root / ".nyx"
    d.mkdir(exist_ok=True)
    return init_db(sqlite3.connect(d / "nyx.db"))


def init_db(db: sqlite3.Connection) -> sqlite3.Connection:
    db.execute(
        "CREATE TABLE IF NOT EXISTS moves (id INTEGER PRIMARY KEY, batch TEXT, src TEXT, dst TEXT,"
        " reason TEXT, ts REAL, undone INTEGER DEFAULT 0, learned INTEGER DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS analysis (sha256 TEXT PRIMARY KEY, path TEXT, category TEXT,"
        " description TEXT, model TEXT, ts REAL)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS rules (ext TEXT PRIMARY KEY, folder TEXT, hits INTEGER)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, ts REAL, status TEXT, trigger TEXT,"
        " analyzed INTEGER, moved INTEGER, note TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS hashes (path TEXT, size INTEGER, mtime REAL, sha TEXT, PRIMARY KEY (path, size, mtime))"
    )
    return db


class DbHashCache:
    """dict-like cache of file hashes keyed by (path, size, mtime), persisted so big folders are not re-read."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get(self, key):
        row = self.db.execute("SELECT sha FROM hashes WHERE path=? AND size=? AND mtime=?", key).fetchone()
        return row[0] if row else None

    def __setitem__(self, key, sha):
        self.db.execute("INSERT OR REPLACE INTO hashes VALUES (?,?,?,?)", (*key, sha))
        self.db.commit()
