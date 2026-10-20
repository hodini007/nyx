import argparse
import os
import sys
from pathlib import Path

from .analyzer import ModelUnavailable, OllamaClient, analyze_screenshots, load_categories
from .changes import is_text, summarize_change
from .config import load_settings, threads_for
from .db import open_db
from .registry import Folder
from .learn import learn_from_corrections, load_rules
from .executor import apply_plan, undo_last
from .planner import build_plan
from .safety import SANDBOX, UnsafePath, ensure_root
from .scanner import scan
from .search import ask

DEFAULT_ROOT = SANDBOX / "Downloads"


def overrides(args) -> dict:
    from .runner import parse_window

    o = {}
    if args.min_age_hours is not None:
        o["min_age_hours"] = args.min_age_hours
    if args.min_new is not None:
        o["min_new"] = args.min_new
    if args.window is not None:
        o["window"] = parse_window(args.window)
    if args.idle_minutes is not None:
        o["idle_minutes"] = args.idle_minutes
    if args.interval is not None:
        o["interval_minutes"] = args.interval
    if args.gentle:
        o["threads"] = max(1, (os.cpu_count() or 4) // 4)
    return o


def print_schedule(args) -> None:
    project = Path(__file__).resolve().parent.parent
    py = sys.executable
    target = args.os or {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    flags = ""
    win_flags = ""
    if target == "linux":
        print(f"""# 1. Autostart: save as ~/.config/systemd/user/nyx.service
[Unit]
Description=Nyx background tidy-up agent

[Service]
WorkingDirectory={project}
ExecStart={py} -m nyx.cli daemon
Restart=on-failure
Nice=19

[Install]
WantedBy=default.target

#    then: systemctl --user daemon-reload && systemctl --user enable --now nyx.service

# 2. Manual "run now" key. Hyprland (~/.config/hypr/hyprland.conf):
#    bind = SUPER, N, exec, sh -c 'cd {project} && {py} -m nyx.cli run'
#    GNOME/KDE: Settings > Keyboard > Custom shortcut with that same command.""")
    elif target == "macos":
        print(f"""# 1. Autostart: save as ~/Library/LaunchAgents/com.nyx.agent.plist
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
  <key>Label</key><string>com.nyx.agent</string>
  <key>WorkingDirectory</key><string>{project}</string>
  <key>ProgramArguments</key><array>
    <string>{py}</string><string>-m</string><string>nyx.cli</string><string>daemon</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>

#    then: launchctl load ~/Library/LaunchAgents/com.nyx.agent.plist

# 2. Manual "run now" key: open Shortcuts (or Automator Quick Action), add "Run Shell Script":
#    cd "{project}" && "{py}" -m nyx.cli run
#    then assign a keyboard shortcut to it in System Settings > Keyboard > Keyboard Shortcuts.""")
    else:
        print(f"""REM 1. Autostart at login (run once in Command Prompt):
schtasks /Create /TN "Nyx" /SC ONLOGON /TR "cmd /c cd /d \\"{project}\\" && \\"{py}\\" -m nyx.cli daemon"

REM 2. Manual "run now" key: create a shortcut (right-click > New > Shortcut) whose target is
REM    cmd /c cd /d "{project}" && "{py}" -m nyx.cli run
REM    then open its Properties and set a "Shortcut key" (for example Ctrl+Alt+N).""")


def folders_command(args) -> int:
    from . import registry

    action, rest = (args.query or ["list"])[0], (args.query or [])[1:]
    try:
        if action == "list":
            folders = registry.load_folders()
            for f in folders:
                print(f"{f.path}  [{'moves automatically' if f.auto_move else 'preview only'}]")
            if not folders:
                print("No watched folders yet. Add one: nyx folders add PATH")
        elif action == "add" and rest:
            f = registry.add_folder(Path(rest[0]), auto_move=args.auto)
            print(f"Now watching {f.path} ({'moves automatically' if f.auto_move else 'preview only; use: nyx folders auto PATH on'})")
        elif action == "remove" and rest:
            print("Removed." if registry.remove_folder(Path(rest[0])) else "That folder was not being watched.")
        elif action == "auto" and len(rest) == 2 and rest[1] in ("on", "off"):
            print("Updated." if registry.set_auto_move(Path(rest[0]), rest[1] == "on") else "That folder is not being watched.")
        else:
            print("Usage: nyx folders [list | add PATH [--auto] | remove PATH | auto PATH on|off]", file=sys.stderr)
            return 2
    except UnsafePath as e:
        print(e, file=sys.stderr)
        return 2
    return 0


def all_folders_command(args, ov: dict, saved) -> int:
    from .daemon import run_daemon
    from .registry import load_folders
    from .runner import run_once

    if args.command == "daemon":
        return run_daemon(None, ov, idle_known=args.idle_known)
    folders = load_folders()
    if not folders:
        print("No watched folders yet. Add one: nyx folders add PATH")
        return 0
    if args.if_idle and not saved.enabled:
        print("[skipped] automatic tidying is switched off in settings")
        return 0
    for f in folders:
        kwargs = dict(min_age_hours=saved.min_age_hours, min_new=saved.min_new, window=saved.window(),
                      idle_minutes=saved.idle_minutes, threads=threads_for(saved.effort),
                      auto_move=f.auto_move, allow_battery=saved.run_on_battery)
        kwargs.update({k: v for k, v in ov.items() if k != "interval_minutes"})
        r = run_once(f.path, force=not args.if_idle, idle_known=args.idle_known, **kwargs)
        print(f"{f.path.name}: [{r['status']}] {r.get('trigger', '')} {r['note']}".replace("  ", " "))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="nyx", description="Tidy a sandbox folder. Never deletes, always undoable.")
    p.add_argument("command", choices=["plan", "apply", "undo", "analyze", "ask", "changes", "learn", "serve", "run", "daemon", "schedule", "app", "folders", "gui"])
    p.add_argument("query", nargs="*", help="search words for the ask command")
    p.add_argument("--root", default=None, help="a watched folder (default: the demo sandbox; run and daemon default to all watched folders)")
    p.add_argument("--auto", action="store_true", help="folders add: move files automatically from the start")
    p.add_argument("--port", type=int, default=8765, help="dashboard port (serve command)")
    p.add_argument("--if-idle", action="store_true", help="run: only act when the machine is idle and enough files are waiting")
    p.add_argument("--idle-known", action="store_true", help="run: the caller (e.g. hypridle) guarantees the machine is idle")
    p.add_argument("--min-new", type=int, default=None, help="override the saved setting: files waiting before a daytime run")
    p.add_argument("--window", default=None, help="override the saved setting: nightly hours, e.g. 1-5")
    p.add_argument("--idle-minutes", type=float, default=None, help="override the saved setting: minutes of inactivity required")
    p.add_argument("--gentle", action="store_true", help="use only a quarter of the CPU threads so other apps stay responsive")
    p.add_argument("--interval", type=float, default=None, help="override the saved setting: minutes between idle checks")
    p.add_argument("--os", choices=["linux", "macos", "windows"], help="schedule: print instructions for this system")
    p.add_argument("--min-age-hours", type=float, default=None, help="override the saved setting: skip files modified more recently than this")
    args = p.parse_args(argv)

    if args.command == "schedule":
        print_schedule(args)
        return 0
    if args.command == "folders":
        return folders_command(args)
    if args.command == "gui":
        from .gui import run_gui

        return run_gui()

    ov = overrides(args)
    saved = load_settings()

    if args.command in ("daemon", "run") and not args.root:
        return all_folders_command(args, ov, saved)

    try:
        root = ensure_root(Path(args.root or DEFAULT_ROOT))
    except UnsafePath as e:
        print(e, file=sys.stderr)
        return 2

    min_age = ov.get("min_age_hours", saved.min_age_hours)

    if args.command == "daemon":
        from .daemon import run_daemon

        return run_daemon(lambda: [Folder(root, True)], ov, lock_dir=root / ".nyx", idle_known=args.idle_known)

    if args.command == "run":
        from .runner import run_once

        kwargs = dict(min_age_hours=saved.min_age_hours, min_new=saved.min_new, window=saved.window(),
                      idle_minutes=saved.idle_minutes, threads=threads_for(saved.effort),
                      auto_move=saved.auto_move, allow_battery=saved.run_on_battery)
        kwargs.update({k: v for k, v in ov.items() if k != "interval_minutes"})
        if args.if_idle and not saved.enabled:
            print("[skipped] automatic tidying is switched off in settings")
            return 0
        r = run_once(root, force=not args.if_idle, idle_known=args.idle_known, **kwargs)
        print(f"[{r['status']}] {r.get('trigger', '')} {r['note']}".replace("  ", " "))
        return 0

    if args.command == "serve":
        from .server import serve

        serve(root, args.port, ov.get("min_age_hours"))
        return 0

    if args.command == "app":
        from .appwin import run_app

        return run_app(root, ov.get("min_age_hours"))

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

    files, skipped = scan(root, min_age)
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
        res = apply_plan(root, moves)
        print(f"Applied batch {res.batch}: moved {res.moved}" + (f", {res.failed} could not be moved" if res.failed else "") + ". Run 'undo' to reverse it.")
    else:
        print("Dry run only. Use 'apply' to perform these moves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
