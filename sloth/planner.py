from dataclasses import dataclass
from pathlib import Path

from .rules import category_for, find_duplicates, find_versions
from .scanner import FileInfo

ARCHIVE = "_archive"


@dataclass
class Move:
    src: Path
    dst: Path
    reason: str


def build_plan(root: Path, files: list[FileInfo], analysis: dict[str, str] | None = None,
               rules: dict[str, str] | None = None) -> list[Move]:
    moves: list[Move] = []
    handled: set[Path] = set()

    for keeper, extras in find_duplicates(files):
        for f in extras:
            moves.append(Move(f.path, root / ARCHIVE / "duplicates" / f.name, f"exact duplicate of {keeper.name}"))
            handled.add(f.path)

    remaining = [f for f in files if f.path not in handled]
    for newest, older in find_versions(remaining):
        for f in older:
            moves.append(Move(f.path, root / ARCHIVE / "old_versions" / f.name, f"older version of {newest.name}"))
            handled.add(f.path)

    for f in files:
        if f.path in handled:
            continue
        learned = (rules or {}).get(f.path.suffix.lower())
        if learned:
            moves.append(Move(f.path, root / learned / f.name, f"learned rule: {f.path.suffix.lower()} files go to {learned}"))
            continue
        cat = category_for(f)
        sub = (analysis or {}).get(f.sha256) if cat == "Screenshots" else None
        dst = root / cat / sub.capitalize() / f.name if sub else root / cat / f.name
        moves.append(Move(f.path, dst, f"sorted as {cat}" + (f" ({sub}, by model)" if sub else "")))

    return moves


def unique_dst(dst: Path, taken: set[Path]) -> Path:
    if dst not in taken and not dst.exists():
        return dst
    i = 1
    while True:
        cand = dst.with_name(f"{dst.stem}__{i}{dst.suffix}")
        if cand not in taken and not cand.exists():
            return cand
        i += 1
