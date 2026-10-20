import sqlite3
from pathlib import Path


def open_db(root: Path) -> sqlite3.Connection:
    d = root / ".sloth"
    d.mkdir(exist_ok=True)
    return init_db(sqlite3.connect(d / "sloth.db"))


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
    return db
