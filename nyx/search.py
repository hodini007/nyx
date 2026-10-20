import re
import sqlite3
from pathlib import Path


def ask(db: sqlite3.Connection, query: str, limit: int = 5) -> list[tuple[Path, str, str]]:
    words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
    scored = []
    for path, cat, desc in db.execute("SELECT path, category, description FROM analysis"):
        text = f"{cat} {desc} {Path(path).name}".lower()
        score = sum(1 for w in words if w in text)
        if score:
            scored.append((score, Path(path), cat, desc))
    scored.sort(key=lambda t: -t[0])
    return [(p, c, d) for _, p, c, d in scored[:limit]]
