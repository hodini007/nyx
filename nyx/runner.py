import time
from pathlib import Path

from .analyzer import ModelUnavailable, OllamaClient, analyze_screenshots, load_categories
from .db import open_db
from .executor import apply_plan
from .lock import FileLock
from .idle import in_window, machine_idle, user_idle_seconds
from .learn import learn_from_corrections, load_rules
from .planner import build_plan
from .rules import category_for
from .scanner import scan


def parse_window(text: str) -> tuple[int, int]:
    a, b = text.split("-")
    return int(a), int(b)


def run_once(root: Path, min_age_hours: float = 24.0, min_new: int = 10, window: tuple[int, int] = (1, 5),
             idle_minutes: float = 5.0, force: bool = False, idle_known: bool = False,
             threads: int | None = None, auto_move: bool = True, allow_battery: bool = False,
             client=None, idle_check=None, still_idle=None) -> dict:
    db = open_db(root)
    lock = FileLock(root / ".nyx" / "run.lock")
    if not lock.acquire():
        db.close()
        return {"status": "skipped", "note": "another run is already in progress"}

    def finish(status: str, note: str, trigger: str = "", analyzed: int = 0, moved: int = 0) -> dict:
        db.execute("INSERT INTO runs (ts, status, trigger, analyzed, moved, note) VALUES (?,?,?,?,?,?)",
                   (time.time(), status, trigger, analyzed, moved, note))
        db.commit()
        return {"status": status, "note": note, "trigger": trigger, "analyzed": analyzed, "moved": moved}

    try:
        learn_from_corrections(root, db)
        files, _ = scan(root, min_age_hours)
        known = {r[0] for r in db.execute("SELECT sha256 FROM analysis")}
        pending_shots = [f for f in files if category_for(f) == "Screenshots" and f.sha256 not in known]
        planned = build_plan(root, files, load_categories(db), load_rules(db))
        night = in_window(time.localtime().tm_hour, window)

        if force:
            trigger = "manual"
        else:
            if idle_known:
                ok, why = True, "idle reported by the desktop"
            else:
                ok, why = (idle_check or (lambda: machine_idle(idle_minutes, window, allow_battery=allow_battery)))()
            if not ok:
                return {"status": "skipped", "note": why}
            if len(planned) >= min_new:
                trigger = f"{len(planned)} files waiting"
            elif night and planned:
                trigger = "nightly window"
            else:
                return {"status": "skipped", "note": f"only {len(planned)} file(s) waiting, need {min_new} or the night window"}

        def user_still_away() -> bool:
            if still_idle is not None:
                return still_idle()
            if force or idle_known:
                return True
            secs = user_idle_seconds()
            return in_window(time.localtime().tm_hour, window) if secs is None else secs >= 30

        analyzed, interrupted, model_down = 0, False, False
        if pending_shots:
            client = client or OllamaClient(threads=threads)
            if client.available():
                for f in pending_shots:
                    if not user_still_away():
                        interrupted = True
                        break
                    try:
                        analyzed += analyze_screenshots(db, [f], client)
                    except ModelUnavailable:
                        model_down = True
                        break
            else:
                model_down = True

        analysis, note_extra = load_categories(db), ""
        ready = [f for f in files if not (category_for(f) == "Screenshots" and f.sha256 not in analysis)]
        moves = build_plan(root, ready, analysis, load_rules(db))
        if moves and (auto_move or force):
            apply_plan(root, moves)
        elif moves:
            note_extra, moves = f"{len(moves)} file(s) waiting for your approval", []
        waiting = len(files) - len(ready)
        note = f"analyzed {analyzed}, moved {len(moves)}"
        if note_extra:
            note += f"; {note_extra}"
        if waiting:
            note += f"; {waiting} screenshot(s) waiting for the model" if model_down or interrupted else ""
        if interrupted:
            note += "; stopped early because you came back"
        return finish("done", note, trigger, analyzed, len(moves))
    finally:
        lock.release()
        db.close()
