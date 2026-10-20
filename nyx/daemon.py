import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import load_settings, threads_for
from .lock import FileLock
from .runner import run_once


def _lock(root: Path) -> FileLock:
    (root / ".nyx").mkdir(exist_ok=True)
    return FileLock(root / ".nyx" / "daemon.lock")


def daemon_running(root: Path) -> bool:
    lock = _lock(root)
    if lock.acquire():
        lock.release()
        return False
    return True


def start_background(root: Path) -> bool:
    """Start the daemon as a detached process. False if one is already running."""
    if daemon_running(root):
        return False
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "cwd": Path(__file__).resolve().parent.parent}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "nyx.cli", "daemon", "--root", str(root)], **kwargs)
    return True


def stop_background(root: Path) -> bool:
    """Stop the daemon, but only if its lock is held (so a stale pid file never kills a stranger)."""
    pid_file = root / ".nyx" / "daemon.pid"
    if not daemon_running(root):
        return False
    try:
        os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
        return True
    except (OSError, ValueError):
        return False


def run_daemon(root: Path, overrides: dict | None = None, max_ticks: int | None = None, sleep=time.sleep,
               log=print, **extra) -> int:
    """Wake every few minutes; run_once decides whether the machine is idle enough to do any work.
    Settings are re-read each cycle, so edits take effect without a restart."""
    overrides = dict(overrides or {})
    lock = _lock(root)
    if not lock.acquire():
        log("Nyx daemon is already running for this folder.")
        return 1
    pid_file = root / ".nyx" / "daemon.pid"
    pid_file.write_text(str(os.getpid()))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    log("Nyx daemon started. Settings are re-read every cycle. Ctrl+C to stop.")
    last, ticks = None, 0
    try:
        while max_ticks is None or ticks < max_ticks:
            s = load_settings(root)
            interval = overrides.get("interval_minutes", s.interval_minutes)
            try:
                if not s.enabled:
                    r, line = {"status": "skipped"}, "[paused] automatic tidying is switched off in settings"
                else:
                    kwargs = dict(min_age_hours=s.min_age_hours, min_new=s.min_new, window=s.window(),
                                  idle_minutes=s.idle_minutes, threads=threads_for(s.effort),
                                  auto_move=s.auto_move, allow_battery=s.run_on_battery)
                    kwargs.update({k: v for k, v in overrides.items() if k != "interval_minutes"})
                    kwargs.update(extra)
                    r = run_once(root, **kwargs)
                    line = f"[{r['status']}] {r.get('trigger', '')} {r['note']}".replace("  ", " ")
            except Exception as e:
                r, line = {"status": "error"}, f"[error] {e}"
            if r["status"] != "skipped" or line != last:
                log(time.strftime("%H:%M:%S ") + line)
            last = line
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            sleep(interval * 60)
    except KeyboardInterrupt:
        pass
    finally:
        pid_file.unlink(missing_ok=True)
        lock.release()
    return 0
