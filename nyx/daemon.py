import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import load_settings, threads_for
from .lock import FileLock
from .registry import Folder, config_dir, load_folders
from .runner import run_once


def _dir(lock_dir: Path | None) -> Path:
    d = lock_dir or config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def daemon_running(lock_dir: Path | None = None) -> bool:
    lock = FileLock(_dir(lock_dir) / "daemon.lock")
    if lock.acquire():
        lock.release()
        return False
    return True


def start_background() -> bool:
    """Start the daemon (all watched folders) as a detached process. False if it is already running."""
    if daemon_running():
        return False
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
              "cwd": Path(__file__).resolve().parent.parent}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "nyx.cli", "daemon"], **kwargs)
    return True


def stop_background() -> bool:
    """Stop the daemon, but only if its lock is held (so a stale pid file never kills a stranger)."""
    if not daemon_running():
        return False
    try:
        os.kill(int((config_dir() / "daemon.pid").read_text().strip()), signal.SIGTERM)
        return True
    except (OSError, ValueError):
        return False


def run_daemon(targets=None, overrides: dict | None = None, max_ticks: int | None = None, sleep=time.sleep,
               log=print, lock_dir: Path | None = None, **extra) -> int:
    """Wake every few minutes and give each watched folder a chance to run; run_once decides whether the machine
    is idle enough to do any work. Settings and the folder list are re-read each cycle."""
    overrides = dict(overrides or {})
    targets = targets or load_folders
    base = _dir(lock_dir)
    lock = FileLock(base / "daemon.lock")
    if not lock.acquire():
        log("Nyx daemon is already running.")
        return 1
    pid_file = base / "daemon.pid"
    pid_file.write_text(str(os.getpid()))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    log("Nyx daemon started. Settings and watched folders are re-read every cycle. Ctrl+C to stop.")
    last: dict[str, str] = {}
    ticks = 0
    try:
        while max_ticks is None or ticks < max_ticks:
            s = load_settings()
            interval = overrides.get("interval_minutes", s.interval_minutes)
            folders: list[Folder] = targets()
            lines: list[tuple[str, str, str]] = []
            if not folders:
                lines.append(("-", "skipped", "[idle] no watched folders yet. Add one in the control panel or with: nyx folders add PATH"))
            elif not s.enabled:
                lines.append(("-", "skipped", "[paused] automatic tidying is switched off in settings"))
            else:
                for f in folders:
                    try:
                        if not f.path.is_dir():
                            lines.append((str(f.path), "skipped", f"[missing] {f.path} is not available"))
                            continue
                        kwargs = dict(min_age_hours=s.min_age_hours, min_new=s.min_new, window=s.window(),
                                      idle_minutes=s.idle_minutes, threads=threads_for(s.effort),
                                      auto_move=f.auto_move, allow_battery=s.run_on_battery)
                        kwargs.update({k: v for k, v in overrides.items() if k != "interval_minutes"})
                        kwargs.update(extra)
                        r = run_once(f.path, **kwargs)
                        lines.append((str(f.path), r["status"], f"[{r['status']}] {f.path.name}: {r.get('trigger', '')} {r['note']}".replace("  ", " ")))
                    except Exception as e:
                        lines.append((str(f.path), "error", f"[error] {f.path.name}: {e}"))
            for key, status, line in lines:
                if status != "skipped" or last.get(key) != line:
                    log(time.strftime("%H:%M:%S ") + line)
                last[key] = line
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
