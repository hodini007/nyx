import argparse
import sys
from pathlib import Path

from .executor import apply_plan, undo_last
from .planner import build_plan
from .safety import SANDBOX, UnsafePath, ensure_root
from .scanner import scan

DEFAULT_ROOT = SANDBOX / "Downloads"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sloth", description="Tidy a sandbox folder. Never deletes, always undoable.")
    p.add_argument("command", choices=["plan", "apply", "undo"])
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="folder inside the playground sandbox")
    p.add_argument("--min-age-hours", type=float, default=24.0, help="skip files modified more recently than this")
    args = p.parse_args(argv)

    try:
        root = ensure_root(Path(args.root))
    except UnsafePath as e:
        print(e, file=sys.stderr)
        return 2

    if args.command == "undo":
        print(f"Restored {undo_last(root)} file(s).")
        return 0

    files, skipped = scan(root, args.min_age_hours)
    moves = build_plan(root, files)
    for m in moves:
        print(f"{m.src.relative_to(root)}  ->  {m.dst.relative_to(root)}   ({m.reason})")
    for s in skipped:
        print(f"{s.name}  skipped (modified recently)")
    print(f"\n{len(moves)} move(s) planned, {len(skipped)} skipped.")

    if args.command == "apply":
        batch = apply_plan(root, moves)
        print(f"Applied batch {batch}. Run 'undo' to reverse it.")
    else:
        print("Dry run only. Use 'apply' to perform these moves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
