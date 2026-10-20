import time

from .lock import FileLock
from .runner import run_once


def run_daemon(root, interval_minutes: float = 5.0, max_ticks: int | None = None, sleep=time.sleep, log=print, **run_kwargs) -> int:
    """Wake every few minutes; run_once decides whether the machine is idle enough to do any work."""
    (root / ".nyx").mkdir(exist_ok=True)
    lock = FileLock(root / ".nyx" / "daemon.lock")
    if not lock.acquire():
        log("Nyx daemon is already running for this folder.")
        return 1
    log(f"Nyx daemon started (checking every {interval_minutes:g} min). Ctrl+C to stop.")
    last, ticks = None, 0
    try:
        while max_ticks is None or ticks < max_ticks:
            try:
                r = run_once(root, **run_kwargs)
                line = f"[{r['status']}] {r.get('trigger', '')} {r['note']}".replace("  ", " ")
            except Exception as e:
                r, line = {"status": "error"}, f"[error] {e}"
            if r["status"] != "skipped" or line != last:
                log(time.strftime("%H:%M:%S ") + line)
            last = line
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            sleep(interval_minutes * 60)
    except KeyboardInterrupt:
        pass
    finally:
        lock.release()
    return 0
