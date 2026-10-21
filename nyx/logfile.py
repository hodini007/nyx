import os
import time
from pathlib import Path

from .registry import config_dir

MAX_BYTES = 1_000_000


def log_path() -> Path:
    return config_dir() / "nyx.log"


def write(message: str) -> None:
    """Append one timestamped line. Never raises: logging must not break a tidy-up."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            os.replace(path, path.with_name(path.name + ".1"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}\n")
    except OSError:
        pass


def tail(max_bytes: int = 60_000) -> str:
    try:
        with open(log_path(), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(size - max_bytes, 0))
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return data.split("\n", 1)[1] if size > max_bytes and "\n" in data else data


def clear() -> None:
    try:
        log_path().write_text("")
    except OSError:
        pass


def stamp() -> tuple:
    try:
        st = log_path().stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def default_log(message: str) -> None:
    """Daemon output: print for a terminal and keep a copy in the log file the control panel shows."""
    print(time.strftime("%H:%M:%S ") + message, flush=True)
    write(message)
