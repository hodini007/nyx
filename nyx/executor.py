import shutil
import time
import uuid
from pathlib import Path
from typing import NamedTuple

from .db import open_db
from .planner import Move, unique_dst
from .safety import ensure_inside


class ApplyResult(NamedTuple):
    batch: str
    moved: int
    failed: int


def apply_plan(root: Path, moves: list[Move]) -> ApplyResult:
    db = open_db(root)
    try:
        return _apply(db, root, moves)
    finally:
        db.close()


def _apply(db, root: Path, moves: list[Move]) -> ApplyResult:
    batch = uuid.uuid4().hex[:8]
    taken: set[Path] = set()
    moved = failed = 0
    for m in moves:
        src = ensure_inside(root, m.src)
        dst = ensure_inside(root, unique_dst(m.dst, taken))
        taken.add(dst)
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError:
            failed += 1
            continue
        db.execute(
            "INSERT INTO moves (batch, src, dst, reason, ts) VALUES (?,?,?,?,?)",
            (batch, str(src), str(dst), m.reason, time.time()),
        )
        db.execute("UPDATE analysis SET path=? WHERE path=?", (str(dst), str(src)))
        db.commit()
        moved += 1
    return ApplyResult(batch, moved, failed)


def _restore(db, root: Path, mid: int, src: str, dst: str) -> bool:
    s, d = ensure_inside(root, Path(src)), ensure_inside(root, Path(dst))
    moved = False
    if d.exists() and not s.exists():
        shutil.move(str(d), str(s))
        db.execute("UPDATE analysis SET path=? WHERE path=?", (str(s), str(d)))
        moved = True
    db.execute("UPDATE moves SET undone=1 WHERE id=?", (mid,))
    parent = d.parent
    while parent != root and parent.is_relative_to(root) and parent.exists() and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent
    return moved


def undo_last(root: Path) -> int:
    db = open_db(root)
    try:
        return _undo_last(db, root)
    finally:
        db.close()


def _undo_last(db, root: Path) -> int:
    row = db.execute("SELECT batch FROM moves WHERE undone=0 ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return 0
    rows = db.execute("SELECT id, src, dst FROM moves WHERE batch=? AND undone=0 ORDER BY id DESC", (row[0],)).fetchall()
    restored = sum(_restore(db, root, mid, src, dst) for mid, src, dst in rows)
    db.commit()
    return restored


def undo_move(root: Path, move_id: int) -> bool:
    db = open_db(root)
    try:
        return _undo_move(db, root, move_id)
    finally:
        db.close()


def _undo_move(db, root: Path, move_id: int) -> bool:
    row = db.execute("SELECT id, src, dst FROM moves WHERE id=? AND undone=0", (move_id,)).fetchone()
    if not row:
        return False
    moved = _restore(db, root, *row)
    db.commit()
    return moved
