import shutil
import sqlite3
import time
import uuid
from pathlib import Path

from .planner import Move, unique_dst
from .safety import ensure_inside


def open_db(root: Path) -> sqlite3.Connection:
    d = root / ".sloth"
    d.mkdir(exist_ok=True)
    db = sqlite3.connect(d / "sloth.db")
    db.execute(
        "CREATE TABLE IF NOT EXISTS moves (id INTEGER PRIMARY KEY, batch TEXT, src TEXT, dst TEXT,"
        " reason TEXT, ts REAL, undone INTEGER DEFAULT 0)"
    )
    return db


def apply_plan(root: Path, moves: list[Move]) -> str:
    db = open_db(root)
    batch = uuid.uuid4().hex[:8]
    taken: set[Path] = set()
    for m in moves:
        src = ensure_inside(root, m.src)
        dst = ensure_inside(root, unique_dst(m.dst, taken))
        taken.add(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        db.execute(
            "INSERT INTO moves (batch, src, dst, reason, ts) VALUES (?,?,?,?,?)",
            (batch, str(src), str(dst), m.reason, time.time()),
        )
    db.commit()
    return batch


def undo_last(root: Path) -> int:
    db = open_db(root)
    row = db.execute("SELECT batch FROM moves WHERE undone=0 ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return 0
    rows = db.execute("SELECT id, src, dst FROM moves WHERE batch=? AND undone=0 ORDER BY id DESC", (row[0],)).fetchall()
    restored = 0
    for mid, src, dst in rows:
        s, d = ensure_inside(root, Path(src)), ensure_inside(root, Path(dst))
        if d.exists() and not s.exists():
            shutil.move(str(d), str(s))
            restored += 1
        db.execute("UPDATE moves SET undone=1 WHERE id=?", (mid,))
        parent = d.parent
        while parent != root and parent.is_relative_to(root) and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    db.commit()
    return restored
