import re
from collections import defaultdict

from .scanner import FileInfo

_COPY = re.compile(r"[\s_-]*\(\d+\)|[\s_-]*-?\s*copy(\s*\d+)?", re.I)
_MARKERS = re.compile(r"[\s_-]*(final|latest|new|old|draft)", re.I)
_VERSION = re.compile(r"[\s_-]*v?(\d+(?:\.\d+){1,3})$|[\s_-]*v(\d+)", re.I)

CATEGORIES = {
    "Installers": {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"},
    "Archives": {".zip", ".tar", ".gz", ".7z", ".rar", ".tgz"},
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".odt", ".rtf"},
    "Spreadsheets": {".xls", ".xlsx", ".csv", ".ods"},
    "Presentations": {".ppt", ".pptx", ".key", ".odp"},
}


def category_for(info: FileInfo) -> str:
    if info.name.lower().startswith("screenshot") and info.path.suffix.lower() in CATEGORIES["Images"]:
        return "Screenshots"
    ext = info.path.suffix.lower()
    for name, exts in CATEGORIES.items():
        if ext in exts:
            return name
    return "Other"


def normalize(stem: str) -> str:
    s = stem.lower()
    changed = True
    while changed:
        before = s
        s = _COPY.sub("", s)
        s = _VERSION.sub("", s)
        s = _MARKERS.sub("", s)
        s = s.strip(" _-.")
        changed = s != before
    return s


def version_key(info: FileInfo) -> tuple:
    stem = info.path.stem.lower()
    nums: tuple = ()
    m = re.search(r"v?(\d+(?:\.\d+){1,3})(?!.*\d)", stem) or re.search(r"v(\d+)", stem)
    if m:
        nums = tuple(int(x) for x in m.group(1).split("."))
    final = 1 if re.search(r"final|latest", stem) else 0
    return (nums, final, info.mtime)


def find_duplicates(files: list[FileInfo]) -> list[tuple[FileInfo, list[FileInfo]]]:
    """(keeper, extras) for each set of identical content. Keeper = cleanest name, then oldest."""
    by_hash: dict[str, list[FileInfo]] = defaultdict(list)
    for f in files:
        by_hash[f.sha256].append(f)
    out = []
    for group in by_hash.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda f: (bool(_COPY.search(f.path.stem)), f.mtime, f.name))
        out.append((group[0], group[1:]))
    return out


def find_versions(files: list[FileInfo]) -> list[tuple[FileInfo, list[FileInfo]]]:
    """(newest, older) for each group of files that look like versions of one thing."""
    groups: dict[tuple[str, str], list[FileInfo]] = defaultdict(list)
    for f in files:
        key = normalize(f.path.stem)
        if key:
            groups[(key, f.path.suffix.lower())].append(f)
    out = []
    for group in groups.values():
        if len(group) < 2:
            continue
        group = sorted(group, key=version_key, reverse=True)
        out.append((group[0], group[1:]))
    return out
