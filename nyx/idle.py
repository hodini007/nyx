import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

POWER = Path("/sys/class/power_supply")


def _run(cmd: list[str], timeout: int = 5) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def _read(p: Path) -> str:
    try:
        return p.read_text().strip()
    except OSError:
        return ""


def on_ac_power() -> bool:
    """True on AC power. Unknown counts as AC (desktops, or a platform we cannot read)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte),
                            ("sys", ctypes.c_ubyte), ("life", ctypes.c_uint), ("full", ctypes.c_uint)]

            s = Status()
            ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
            return s.ac != 0
        if sys.platform == "darwin":
            return "Battery Power" not in _run(["pmset", "-g", "batt"])
        if POWER.exists():
            kinds = {p: _read(p / "type") for p in POWER.iterdir()}
            if "Battery" not in kinds.values():
                return True
            return any(_read(p / "online") == "1" for p, k in kinds.items() if k == "Mains")
    except Exception:
        pass
    return True


def load_ok(max_per_core: float = 0.5) -> bool:
    if not hasattr(os, "getloadavg"):
        return True
    return os.getloadavg()[0] / (os.cpu_count() or 1) <= max_per_core


def parse_hid_idle(text: str) -> float | None:
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', text)
    return int(m.group(1)) / 1e9 if m else None


def parse_gnome_idle(text: str) -> float | None:
    m = re.search(r"uint64\s+(\d+)", text)
    return int(m.group(1)) / 1000 if m else None


def _idle_windows() -> float | None:
    import ctypes

    class LastInput(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint), ("time", ctypes.c_uint)]

    info = LastInput()
    info.size = ctypes.sizeof(info)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    ctypes.windll.kernel32.GetTickCount.restype = ctypes.c_uint
    return ((ctypes.windll.kernel32.GetTickCount() - info.time) & 0xFFFFFFFF) / 1000


def _idle_linux() -> float | None:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if shutil.which("xprintidle") and os.environ.get("XDG_SESSION_TYPE") == "x11":
        return int(_run(["xprintidle"])) / 1000
    if "GNOME" in desktop and shutil.which("gdbus"):
        got = parse_gnome_idle(_run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
                                     "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                                     "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"]))
        if got is not None:
            return got
    sid = os.environ.get("XDG_SESSION_ID")
    if sid and shutil.which("loginctl"):
        out = _run(["loginctl", "show-session", sid, "-p", "IdleHint", "-p", "IdleSinceHint"])
        info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if info.get("IdleHint") == "yes" and int(info.get("IdleSinceHint", 0)) > 0:
            return max(0.0, time.time() - int(info["IdleSinceHint"]) / 1e6)
        if info.get("IdleHint") == "no":
            return 0.0
    return None


def user_idle_seconds() -> float | None:
    """Seconds since the last keyboard or mouse input, or None when this system cannot tell."""
    try:
        custom = os.environ.get("NYX_IDLE_COMMAND")
        if custom:
            return float(subprocess.run(custom, shell=True, capture_output=True, text=True, timeout=5).stdout.strip())
        if sys.platform == "win32":
            return _idle_windows()
        if sys.platform == "darwin":
            return parse_hid_idle(_run(["ioreg", "-c", "IOHIDSystem"]))
        return _idle_linux()
    except Exception:
        return None


def in_window(hour: int, window: tuple[int, int]) -> bool:
    start, end = window
    return start <= hour < end if start <= end else hour >= start or hour < end


def machine_idle(idle_minutes: float, window: tuple[int, int], hour: int | None = None) -> tuple[bool, str]:
    """Conservative: runs when idle is known, or at night when the system cannot tell."""
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
