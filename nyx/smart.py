"""Smart sorting: predict which of the user's own folders a loose file belongs in, learning from the files
already sitting in folders the user organized themselves. Uses TabPFN (a tabular foundation model) locally."""
import math
import re
from collections import Counter
from pathlib import Path

from .planner import ARCHIVE, Move, build_plan
from .rules import CATEGORIES, category_for
from .scanner import FileInfo

NYX_FOLDERS = set(CATEGORIES) | {"Screenshots", "Other", ARCHIVE}
MIN_ROWS = 8
MAX_ROWS = 1500
PER_FOLDER = 300
VOCAB_SIZE = 25
_cache: dict = {}


def user_folders(root: Path) -> list[Path]:
    """Subfolders the user made (not Nyx's own category folders)."""
    out = []
    for p in sorted(root.iterdir()):
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and p.name not in NYX_FOLDERS:
            out.append(p)
    return out


def collect_training(root: Path) -> list[tuple[Path, str]]:
    rows: list[tuple[Path, str]] = []
    for folder in user_folders(root):
        n = 0
        for f in sorted(folder.rglob("*")):
            if n >= PER_FOLDER or len(rows) >= MAX_ROWS:
                break
            if f.is_file() and not f.is_symlink() and not f.name.startswith("."):
                rows.append((f, folder.name))
                n += 1
    return rows


def tokens(name: str) -> list[str]:
    stem = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name)
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)
    return [t for t in re.findall(r"[a-z]{3,}", spaced.lower())]


def _log_size(size: int) -> float:
    return math.log10(size + 1)


def features(name: str, size: int, mtime: float, vocab: list[str], exts: dict[str, int], now: float) -> list[float]:
    ext = Path(name).suffix.lower()
    toks = set(tokens(name))
    stem = Path(name).stem
    return [
        float(exts.get(ext, len(exts))),
        _log_size(size),
        math.log10(max(now - mtime, 0) / 86400 + 1),
        float(len(stem)),
        float(sum(c.isdigit() for c in stem)) / max(len(stem), 1),
        1.0 if re.match(r"^\d{4,}", stem) else 0.0,
        1.0 if re.search(r"\(\d+\)|copy", stem, re.I) else 0.0,
        *[1.0 if t in toks else 0.0 for t in vocab],
    ]


def build_dataset(train: list[tuple[Path, str]], now: float):
    names = [(p.name, p.stat().st_size, p.stat().st_mtime, label) for p, label in train if p.exists()]
    counts = Counter(t for n, *_ in names for t in set(tokens(n)))
    vocab = [t for t, c in counts.most_common(VOCAB_SIZE * 2) if c >= 2][:VOCAB_SIZE]
    exts = {e: i for i, e in enumerate(sorted({Path(n).suffix.lower() for n, *_ in names}))}
    X = [features(n, s, m, vocab, exts, now) for n, s, m, _ in names]
    y = [label for *_, label in names]
    return X, y, vocab, exts


class TabPFNModel:
    """Thin adapter so tests can swap in a fake classifier with the same two methods."""

    def __init__(self):
        from tabpfn import TabPFNClassifier

        self.clf = TabPFNClassifier()

    def fit(self, X, y):
        import numpy as np

        self.clf.fit(np.asarray(X, dtype=float), np.asarray(y))
        return self

    def predict_proba(self, X):
        import numpy as np

        return self.clf.predict_proba(np.asarray(X, dtype=float)).tolist(), list(self.clf.classes_)


def predict_folders(root: Path, loose: list[FileInfo], now: float, factory=None, threshold: float = 0.75
                    ) -> dict[Path, tuple[str, float]]:
    """{file path: (folder name, confidence)} for loose files the model is confident about."""
    if not loose:
        return {}
    train = collect_training(root)
    labels = Counter(label for _, label in train)
    usable = {l for l, c in labels.items() if c >= 2}
    train = [(p, l) for p, l in train if l in usable]
    if len(train) < MIN_ROWS or len(usable) < 2:
        return {}
    key = (tuple((str(p), l) for p, l in train), tuple(str(f.path) for f in loose), threshold)
    if key in _cache:
        return _cache[key]
    X, y, vocab, exts = build_dataset(train, now)
    model = (factory or TabPFNModel)()
    model.fit(X, y)
    probs, classes = model.predict_proba([features(f.name, f.size, f.mtime, vocab, exts, now) for f in loose])
    out = {}
    for f, row in zip(loose, probs):
        best = max(range(len(classes)), key=lambda i: row[i])
        if row[best] >= threshold:
            out[f.path] = (classes[best], float(row[best]))
    _cache.clear()
    _cache[key] = out
    return out


def smart_plan(root: Path, files: list[FileInfo], db, settings=None, factory=None, now: float | None = None) -> list[Move]:
    """build_plan plus, when enabled and ready, folder predictions learned from the user's own folders."""
    import time

    from .analyzer import load_categories
    from .config import load_settings
    from .learn import load_rules

    settings = settings or load_settings()
    analysis, rules = load_categories(db), load_rules(db)
    predictions = None
    if settings.smart_sorting and (factory is not None or smart_status()["ready"]):
        base = build_plan(root, files, analysis, rules)
        loose = [f for f in files if any(m.src == f.path and m.reason.startswith("sorted as") for m in base)
                 and f.path.suffix.lower() not in rules and category_for(f) != "Screenshots"]
        try:
            predictions = predict_folders(root, loose, now or time.time(), factory, settings.smart_threshold)
        except Exception:
            predictions = None
    return build_plan(root, files, analysis, rules, predictions)


def weights_cached() -> bool:
    import os

    candidates = []
    if os.environ.get("TABPFN_MODEL_CACHE_DIR"):
        candidates.append(Path(os.environ["TABPFN_MODEL_CACHE_DIR"]))
    try:
        import platformdirs

        candidates.append(Path(platformdirs.user_cache_dir("tabpfn")))
    except ImportError:
        pass
    candidates.append(Path.home() / ".cache" / "tabpfn")
    return any(d.is_dir() and any(d.glob("*.ckpt")) or d.is_dir() and any(d.glob("*.safetensors")) for d in candidates)


def smart_status() -> dict:
    try:
        import tabpfn  # noqa: F401

        installed = True
    except ImportError:
        installed = False
    cached = weights_cached() if installed else False
    if not installed:
        message = "TabPFN is not installed in this Python environment."
    elif not cached:
        message = "TabPFN is installed but its model weights are not downloaded yet. Run: nyx smart setup"
    else:
        message = "TabPFN is ready."
    return {"installed": installed, "weights": cached, "ready": installed and cached, "message": message}
