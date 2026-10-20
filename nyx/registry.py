import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Folder:
    path: Path
    auto_move: bool = False


def config_dir() -> Path:
    env = os.environ.get("NYX_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Nyx"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Nyx"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nyx"


def _file() -> Path:
    return config_dir() / "folders.json"


def load_folders() -> list[Folder]:
    try:
        data = json.loads(_file().read_text())
        return [Folder(Path(f["path"]), bool(f.get("auto_move", False))) for f in data.get("folders", [])]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def _save(folders: list[Folder]) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps({"folders": [{"path": str(f.path), "auto_move": f.auto_move} for f in folders]}, indent=2))
    os.replace(tmp, _file())


def is_registered(path: Path) -> bool:
    resolved = Path(path).resolve()
    return any(f.path.resolve() == resolved for f in load_folders())


def add_folder(path: Path, auto_move: bool = False) -> Folder:
    from .safety import UnsafePath, check_folder

    p = check_folder(path)
    folders = load_folders()
    for f in folders:
        existing = f.path.resolve()
        if existing == p:
            raise UnsafePath(f"{p} is already being watched.")
        if p.is_relative_to(existing) or existing.is_relative_to(p):
            raise UnsafePath(f"{p} overlaps with the watched folder {existing}.")
    folder = Folder(p, auto_move)
    _save(folders + [folder])
    return folder


def remove_folder(path: Path) -> bool:
    resolved = Path(path).expanduser().resolve()
    folders = load_folders()
    kept = [f for f in folders if f.path.resolve() != resolved]
    if len(kept) == len(folders):
        return False
    _save(kept)
    return True


def set_auto_move(path: Path, value: bool) -> bool:
    resolved = Path(path).expanduser().resolve()
    folders = load_folders()
    hit = False
    for f in folders:
        if f.path.resolve() == resolved:
            f.auto_move, hit = value, True
    if hit:
        _save(folders)
    return hit
