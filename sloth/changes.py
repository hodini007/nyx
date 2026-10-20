import difflib
from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".csv", ".py", ".json", ".html", ".log"}


def is_text(path: Path) -> bool:
    return path.suffix.lower() in TEXT_EXTS


def diff_lines(old: Path, new: Path) -> list[str]:
    a = old.read_text(errors="replace").splitlines()
    b = new.read_text(errors="replace").splitlines()
    return [l for l in difflib.unified_diff(a, b, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]


def summarize_change(old: Path, new: Path, client=None) -> str:
    lines = diff_lines(old, new)
    added = sum(1 for l in lines if l[0] == "+")
    removed = sum(1 for l in lines if l[0] == "-")
    stats = f"{added} line(s) added, {removed} removed"
    if not lines or client is None:
        return stats
    prompt = "Summarize in at most 3 short bullet points what changed between two versions of a file. Diff:\n" + "\n".join(lines[:80])
    return f"{stats}\n{client.generate_text(prompt)}"
