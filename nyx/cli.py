import argparse
import sys
from pathlib import Path

from .analyzer import ModelUnavailable, OllamaClient, analyze_screenshots, load_categories
from .changes import is_text, summarize_change
from .db import open_db
from .learn import learn_from_corrections, load_rules
from .executor import apply_plan, undo_last
from .planner import build_plan
from .safety import SANDBOX, UnsafePath, ensure_root
from .scanner import scan
from .search import ask

DEFAULT_ROOT = SANDBOX / "Downloads"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="nyx", description="Tidy a sandbox folder. Never deletes, always undoable.")
    p.add_argument("command", choices=["plan", "apply", "undo", "analyze", "ask", "changes", "learn"])
    p.add_argument("query", nargs="*", help="search words for the ask command")
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

    if args.command == "ask":
        results = ask(open_db(root), " ".join(args.query))
        for path, cat, desc in results:
            print(f"{path.relative_to(root)}  [{cat}]  {desc}")
        if not results:
            print("No matches. Run 'analyze' first so screenshots have descriptions.")
        return 0

    if args.command == "learn":
        print(f"Learned from {learn_from_corrections(root, open_db(root))} correction(s).")
        return 0

    files, skipped = scan(root, args.min_age_hours)
    db = open_db(root)

    if args.command == "changes":
        client = OllamaClient()
        client = client if client.available() else None
        if client is None:
            print("(local model not reachable, showing line counts only)")
        for m in build_plan(root, files):
            if "older version of" not in m.reason:
                continue
            newer = root / m.reason.removeprefix("older version of ")
            if is_text(m.src) and newer.exists():
                print(f"{m.src.name} -> {newer.name}\n  " + summarize_change(m.src, newer, client).replace("\n", "\n  "))
        return 0

    if args.command == "analyze":
        client = OllamaClient()
        if not client.available():
            print(f"Local model '{client.model}' not reachable. Install Ollama and run: ollama pull {client.model}", file=sys.stderr)
            return 3
        try:
            n = analyze_screenshots(db, files, client)
        except ModelUnavailable as e:
            print(e, file=sys.stderr)
            return 3
        print(f"Analyzed {n} new screenshot(s); the rest were cached.")
        return 0

    moves = build_plan(root, files, load_categories(db), load_rules(db))
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
