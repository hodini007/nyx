import sqlite3
from pathlib import Path

from .safety import ensure_inside

MIN_HITS = 2


def learn_from_corrections(root: Path, db: sqlite3.Connection) -> int:
    """If the user moved a file Nyx placed, remember where that extension should go."""
    learned = 0
    rows = db.execute("SELECT id, dst FROM moves WHERE undone=0 AND learned=0").fetchall()
    for mid, dst in rows:
        dst = Path(dst)
        if dst.exists():
            continue
        matches = [p for p in root.rglob(dst.name) if p.is_file() and ".nyx" not in p.parts]
        db.execute("UPDATE moves SET learned=1 WHERE id=?", (mid,))
        if len(matches) != 1:
            continue
        folder = ensure_inside(root, matches[0]).parent.relative_to(root)
        if str(folder) in ("", "."):
            continue
        ext = dst.suffix.lower()
        row = db.execute("SELECT folder, hits FROM rules WHERE ext=?", (ext,)).fetchone()
        if row and row[0] == str(folder):
            db.execute("UPDATE rules SET hits=hits+1 WHERE ext=?", (ext,))
        else:
            db.execute("INSERT OR REPLACE INTO rules VALUES (?,?,1)", (ext, str(folder)))
        learned += 1
    db.commit()
    return learned


def load_rules(db: sqlite3.Connection) -> dict[str, str]:
    return {ext: folder for ext, folder, hits in db.execute("SELECT ext, folder, hits FROM rules") if hits >= MIN_HITS}
