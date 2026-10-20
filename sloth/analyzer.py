import base64
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .rules import category_for
from .scanner import FileInfo

MODEL = os.environ.get("SLOTH_MODEL", "gemma3:4b")
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LABELS = ["receipt", "error", "chat", "document", "code", "meme", "other"]
PROMPT = (
    "You are sorting a screenshot. Reply with JSON only, in the form "
    '{"category": "<one of ' + ", ".join(LABELS) + '>", "description": "<one short sentence>"}.'
)


class ModelUnavailable(Exception):
    pass


def _local_url(host: str) -> str:
    if "://" not in host:
        host = "http://" + host
    parsed = urlparse(host)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ModelUnavailable(f"Sloth only talks to a local model, refusing host {parsed.hostname}")
    return host.rstrip("/")


class OllamaClient:
    def __init__(self, host: str = HOST, model: str = MODEL):
        self.host = _local_url(host)
        self.model = model

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.host + "/api/tags", timeout=2) as r:
                names = [m["name"] for m in json.load(r).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError):
            return False
        return any(n == self.model or n.split(":")[0] == self.model.split(":")[0] for n in names)

    def classify_image(self, data: bytes) -> dict:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": PROMPT,
                "images": [base64.b64encode(data).decode()],
                "stream": False,
                "format": "json",
            }
        ).encode()
        req = urllib.request.Request(self.host + "/api/generate", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                raw = json.load(r)["response"]
        except (urllib.error.URLError, OSError) as e:
            raise ModelUnavailable(str(e)) from e
        return parse_answer(raw)

    def generate_text(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(self.host + "/api/generate", body, {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)["response"].strip()
        except (urllib.error.URLError, OSError) as e:
            raise ModelUnavailable(str(e)) from e


def parse_answer(raw: str) -> dict:
    try:
        obj = json.loads(raw)
    except ValueError:
        return {"category": "other", "description": raw.strip()[:200]}
    cat = str(obj.get("category", "other")).lower().strip()
    return {
        "category": cat if cat in LABELS else "other",
        "description": str(obj.get("description", "")).strip()[:200],
    }


def analyze_screenshots(db: sqlite3.Connection, files: list[FileInfo], client) -> int:
    """Classify screenshots not seen before (cached by content hash). Returns how many were newly analyzed."""
    done = 0
    for f in files:
        if category_for(f) != "Screenshots":
            continue
        row = db.execute("SELECT 1 FROM analysis WHERE sha256=?", (f.sha256,)).fetchone()
        if row:
            db.execute("UPDATE analysis SET path=? WHERE sha256=?", (str(f.path), f.sha256))
            continue
        result = client.classify_image(f.path.read_bytes())
        db.execute(
            "INSERT INTO analysis VALUES (?,?,?,?,?,?)",
            (f.sha256, str(f.path), result["category"], result["description"], getattr(client, "model", "?"), time.time()),
        )
        done += 1
    db.commit()
    return done


def load_categories(db: sqlite3.Connection) -> dict[str, str]:
    return {sha: cat for sha, cat in db.execute("SELECT sha256, category FROM analysis")}
