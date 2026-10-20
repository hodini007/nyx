from pathlib import Path

SANDBOX = (Path(__file__).resolve().parent.parent / "playground").resolve()


class UnsafePath(Exception):
    pass


def ensure_root(root: Path) -> Path:
    resolved = Path(root).expanduser().resolve()
    if resolved == SANDBOX or not resolved.is_relative_to(SANDBOX):
        raise UnsafePath(f"Refusing to work outside the sandbox. Root must be inside {SANDBOX}, got {resolved}")
    if not resolved.is_dir():
        raise UnsafePath(f"Root does not exist: {resolved}")
    return resolved


def ensure_inside(root: Path, path: Path) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(root):
        raise UnsafePath(f"Path escapes root: {resolved}")
    return resolved
