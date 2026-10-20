import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    enabled: bool = True
    idle_minutes: float = 5.0
    night_enabled: bool = True
    night_start: int = 1
    night_end: int = 5
    min_new: int = 10
    interval_minutes: float = 5.0
    min_age_hours: float = 24.0
    effort: str = "full"
    run_on_battery: bool = False

    def window(self) -> tuple[int, int]:
        return (self.night_start, self.night_end) if self.night_enabled else (0, 0)


BOUNDS = {
    "idle_minutes": (1, 240), "night_start": (0, 23), "night_end": (0, 23), "min_new": (1, 1000),
    "interval_minutes": (1, 120), "min_age_hours": (0, 720),
}


def from_dict(data: dict) -> Settings:
    s = Settings()
    for f in fields(Settings):
        if f.name not in data:
            continue
        raw, default = data[f.name], getattr(s, f.name)
        try:
            if isinstance(default, bool):
                value = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
            elif f.name == "effort":
                value = raw if raw in ("full", "gentle") else default
            else:
                value = type(default)(float(raw)) if isinstance(default, int) else float(raw)
                lo, hi = BOUNDS[f.name]
                value = type(default)(min(max(value, lo), hi))
        except (TypeError, ValueError):
            continue
        setattr(s, f.name, value)
    return s


def settings_path(base: Path | None = None) -> Path:
    from .registry import config_dir

    return (base or config_dir()) / "settings.json"


def load_settings(base: Path | None = None) -> Settings:
    try:
        return from_dict(json.loads(settings_path(base).read_text()))
    except (OSError, ValueError, AttributeError):
        return Settings()


def save_settings(data: dict, base: Path | None = None) -> Settings:
    s = from_dict(data)
    path = settings_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2))
    os.replace(tmp, path)
    return s


def threads_for(effort: str) -> int | None:
    return max(1, (os.cpu_count() or 4) // 4) if effort == "gentle" else None
