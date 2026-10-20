import os
import shutil
import subprocess
import time
from pathlib import Path

POWER = Path("/sys/class/power_supply")


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def on_ac_power() -> bool:
    if not POWER.exists():
        return True
    kinds = {p: _read(p / "type") for p in POWER.iterdir()}
    if "Battery" not in kinds.values():
        return True
    return any(_read(p / "online") == "1" for p, k in kinds.items() if k == "Mains")


def load_ok(max_per_core: float = 0.5) -> bool:
    return os.getloadavg()[0] / (os.cpu_count() or 1) <= max_per_core


def user_idle_seconds() -> float | None:
    """Seconds since the last user input, or None when this desktop does not report it."""
    custom = os.environ.get("NYX_IDLE_COMMAND")
    if custom:
        try:
            return float(subprocess.run(custom, shell=True, capture_output=True, text=True, timeout=5).stdout.strip())
        except (ValueError, subprocess.SubprocessError):
            return None
    if shutil.which("xprintidle") and os.environ.get("XDG_SESSION_TYPE") == "x11":
        try:
            return int(subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=5).stdout) / 1000
        except (ValueError, subprocess.SubprocessError):
            return None
    sid = os.environ.get("XDG_SESSION_ID")
    if sid and shutil.which("loginctl"):
        try:
            out = subprocess.run(
                ["loginctl", "show-session", sid, "-p", "IdleHint", "-p", "IdleSinceHint"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
            if info.get("IdleHint") == "yes" and int(info.get("IdleSinceHint", 0)) > 0:
                return max(0.0, time.time() - int(info["IdleSinceHint"]) / 1e6)
            if info.get("IdleHint") == "no":
                return 0.0
        except (ValueError, subprocess.SubprocessError):
            return None
    return None


def in_window(hour: int, window: tuple[int, int]) -> bool:
    start, end = window
    return start <= hour < end if start <= end else hour >= start or hour < end


def machine_idle(idle_minutes: float, window: tuple[int, int], hour: int | None = None) -> tuple[bool, str]:
    """Conservative: only runs when idle is known, or at night when the desktop cannot tell."""
    if not on_ac_power():
        return False, "on battery"
    if not load_ok():
        return False, "machine is busy"
    secs = user_idle_seconds()
    if secs is not None:
        ok = secs >= idle_minutes * 60
        return ok, "user idle" if ok else "user is active"
    night = in_window(time.localtime().tm_hour if hour is None else hour, window)
    return night, "night window (idle time unknown)" if night else "idle time unknown, waiting for the night window"
