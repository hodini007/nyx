import time
from pathlib import Path

from .analyzer import ModelUnavailable, OllamaClient, analyze_screenshots, load_categories
from .db import DbHashCache, open_db
from .executor import apply_plan
from .lock import FileLock
from . import logfile
from .idle import in_window, machine_idle, user_idle_seconds
from .learn import learn_from_corrections, load_rules
from .planner import build_plan
from .registry import config_dir
from .rules import category_for
from .scanner import scan
from .smart import smart_plan


def parse_window(text: str) -> tuple[int, int]:
    a, b = text.split("-")
    return int(a), int(b)


def interrupt_file() -> Path:
    return config_dir() / "interrupt"


def request_interrupt() -> None:
    """Ask any run that started before now to stop after its current file (used when the user returns)."""
    interrupt_file().parent.mkdir(parents=True, exist_ok=True)
    interrupt_file().touch()
    import os

    os.utime(interrupt_file(), None)


def interrupt_requested(since: float) -> bool:
    try:
        return interrupt_file().stat().st_mtime >= since
    except OSError:
        return False


def run_once(root: Path, min_age_hours: float = 24.0, min_new: int = 10, window: tuple[int, int] = (1, 5),
             idle_minutes: float = 5.0, force: bool = False, idle_known: bool = False,
             threads: int | None = None, auto_move: bool = True, allow_battery: bool = False,
             client=None, idle_check=None, still_idle=None, log=None) -> dict:
    log = log or logfile.write
    started = time.time()
    if not force:
        # Cheapest checks first: a skipped check must cost almost nothing (no scan, no planning, no model).
        ok, why = (idle_check or (lambda: machine_idle(idle_minutes, window, allow_battery=allow_battery,
                                                       assume_idle=idle_known)))()
        if not ok:
            return {"status": "skipped", "note": why}
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
        files, _ = scan(root, min_age_hours, DbHashCache(db))
        known = {r[0] for r in db.execute("SELECT sha256 FROM analysis")}
        pending_shots = [f for f in files if category_for(f) == "Screenshots" and f.sha256 not in known]
        planned = build_plan(root, files, load_categories(db), load_rules(db))
        night = in_window(time.localtime().tm_hour, window)

        if force:
            trigger = "manual"
        else:
            if len(planned) >= min_new:
                trigger = f"{len(planned)} files waiting"
            elif night and planned:
                trigger = "nightly window"
            else:
                return {"status": "skipped", "note": f"only {len(planned)} file(s) waiting, need {min_new} or the night window"}

        def user_still_away() -> bool:
            if interrupt_requested(started):
                return False
            if still_idle is not None:
                return still_idle()
            if force or idle_known:
                return True
            secs = user_idle_seconds()
            return in_window(time.localtime().tm_hour, window) if secs is None else secs >= 30

        log(f"[{root.name}] run started ({trigger}): {len(files)} file(s), {len(pending_shots)} new screenshot(s)")
        analyzed, interrupted, model_down = 0, False, False
        if pending_shots:
            client = client or OllamaClient(threads=threads)
            if client.available():
                log(f"[{root.name}] reading {len(pending_shots)} screenshot(s) with {getattr(client, 'model', 'the model')}")
                for i, f in enumerate(pending_shots, 1):
                    if not user_still_away():
                        interrupted = True
                        log(f"[{root.name}] you came back, stopping after screenshot {i - 1} of {len(pending_shots)}")
                        break
                    t0 = time.time()
                    try:
                        analyzed += analyze_screenshots(db, [f], client)
                        log(f"[{root.name}] screenshot {i}/{len(pending_shots)} {f.name}: "
                            f"{load_categories(db).get(f.sha256, '?')} ({time.time() - t0:.0f} s)")
                    except ModelUnavailable:
                        model_down = True
                        log(f"[{root.name}] the model stopped responding; remaining screenshots will wait")
                        break
            else:
                model_down = True
                log(f"[{root.name}] model not reachable; {len(pending_shots)} screenshot(s) will wait for it")

        analysis, note_extra = load_categories(db), ""
        ready = [f for f in files if not (category_for(f) == "Screenshots" and f.sha256 not in analysis)]
        moves = smart_plan(root, ready, db)
        moved = 0
        if moves and (auto_move or force):
            res = apply_plan(root, moves)
            moved = res.moved
            if res.failed:
                note_extra = f"{res.failed} file(s) could not be moved"
        elif moves:
            note_extra = f"{len(moves)} file(s) waiting for your approval"
        waiting = len(files) - len(ready)
        note = f"analyzed {analyzed}, moved {moved}"
        if note_extra:
            note += f"; {note_extra}"
        if waiting:
            note += f"; {waiting} screenshot(s) waiting for the model" if model_down or interrupted else ""
        if interrupted:
            note += "; stopped early because you came back"
        log(f"[{root.name}] run finished: {note}")
        return finish("done", note, trigger, analyzed, moved)
    finally:
        lock.release()
        db.close()
