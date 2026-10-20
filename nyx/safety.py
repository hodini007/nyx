import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SANDBOX = (PROJECT / "playground").resolve()

SYSTEM_PREFIXES = {
    "linux": ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc", "/root", "/run", "/sbin", "/sys", "/usr", "/var", "/snap"],
    "darwin": ["/System", "/Library", "/Applications", "/private", "/usr", "/bin", "/sbin", "/etc", "/var", "/dev", "/cores"],
}


class UnsafePath(Exception):
    pass


def _system_prefixes() -> list[Path]:
    if sys.platform == "win32":
        keys = ["SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"]
        return [Path(os.environ[k]).resolve() for k in keys if os.environ.get(k)]
    return [Path(p) for p in SYSTEM_PREFIXES.get("darwin" if sys.platform == "darwin" else "linux", [])]


def forbidden_reason(path: Path) -> str | None:
    """Why Nyx must never tidy this folder, or None if it is acceptable."""
    p = Path(path).resolve()
    home = Path.home().resolve()
    if p.parent == p:
        return "that is a drive or filesystem root"
    if p == home:
        return "that is your whole home folder; choose a folder inside it, such as Downloads"
    if home.is_relative_to(p):
        return "that folder contains your home folder"
    if p == PROJECT or PROJECT.is_relative_to(p):
        return "that folder contains the Nyx program itself"
    if p.is_relative_to(PROJECT) and not p.is_relative_to(SANDBOX):
        return "that folder is part of the Nyx program"
    for system in _system_prefixes():
        if p == system or p.is_relative_to(system):
            return f"that is a system folder ({system})"
    return None


def check_folder(path: Path) -> Path:
    """Validate a folder the user wants Nyx to watch. Returns the resolved path or raises UnsafePath."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise UnsafePath(f"Not a folder: {p}")
    if not os.access(p, os.R_OK | os.W_OK | os.X_OK):
        raise UnsafePath(f"Nyx needs read and write access to {p}")
    if not p.is_relative_to(SANDBOX):
        reason = forbidden_reason(p)
        if reason:
            raise UnsafePath(f"Refusing {p}: {reason}.")
    return p


def ensure_root(root: Path) -> Path:
    """A root is allowed if the user registered it, or it lives inside the demo sandbox."""
    from .registry import is_registered

    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise UnsafePath(f"Root does not exist: {resolved}")
    if resolved != SANDBOX and resolved.is_relative_to(SANDBOX):
        return resolved
    if is_registered(resolved):
        check_folder(resolved)
        return resolved
    raise UnsafePath(f"{resolved} is not a watched folder. Add it first: nyx folders add \"{resolved}\"")


def ensure_inside(root: Path, path: Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root):
        raise UnsafePath(f"Path escapes root: {resolved}")
    return resolved
