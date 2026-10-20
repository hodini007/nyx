import json
import mimetypes
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import load_settings, save_settings
from .registry import load_folders
from .daemon import daemon_running, start_background, stop_background
from dataclasses import asdict
from .analyzer import ModelUnavailable, OllamaClient, analyze_screenshots, load_categories
from .db import open_db
from .executor import apply_plan, undo_last, undo_move
from .learn import MIN_HITS, learn_from_corrections, load_rules
from .planner import ARCHIVE, build_plan
from .rules import category_for
from .safety import UnsafePath, ensure_inside
from .runner import run_once
from .scanner import scan
from .search import ask

PAGE = Path(__file__).parent / "web" / "index.html"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class App:
    def __init__(self, root: Path, port: int, min_age_hours: float | None = None):
        self.root = root
        self.port = port
        self.min_age_override = min_age_hours
        self.last_ping: float | None = None
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.hash_cache: dict = {}
        self.job = {"state": "idle", "done": 0, "total": 0, "message": ""}
        self._model = (0.0, {"name": "", "ready": False})

    @property
    def min_age(self) -> float:
        if self.min_age_override is not None:
            return self.min_age_override
        return load_settings().min_age_hours

    def settings_payload(self) -> dict:
        return {**asdict(load_settings()), "service_running": daemon_running(),
                "folders": [{"path": str(f.path), "auto_move": f.auto_move} for f in load_folders()]}

    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def model_status(self) -> dict:
        ts, cached = self._model
        if time.time() - ts > 10:
            client = OllamaClient()
            cached = {"name": client.model, "ready": client.available()}
            self._model = (time.time(), cached)
        return cached

    def rel(self, p) -> str:
        return str(Path(p).relative_to(self.root))

    def state(self) -> dict:
        db = open_db(self.root)
        try:
            files, skipped = scan(self.root, self.min_age, self.hash_cache)
            sizes = {f.path: f.size for f in files}
            moves = build_plan(self.root, files, load_categories(db), load_rules(db))
            plan = [
                {"src": self.rel(m.src), "dst": self.rel(m.dst), "reason": m.reason, "size": sizes.get(m.src, 0)}
                for m in moves
            ]
            history = [
                {"id": i, "src": self.rel(s), "dst": self.rel(d), "reason": r, "ts": ts, "undone": bool(u)}
                for i, s, d, r, ts, u in db.execute(
                    "SELECT id, src, dst, reason, ts, undone FROM moves ORDER BY id DESC LIMIT 60"
                )
            ]
            rules = [
                {"ext": e, "folder": f, "hits": h, "active": h >= MIN_HITS}
                for e, f, h in db.execute("SELECT ext, folder, hits FROM rules ORDER BY hits DESC")
            ]
            return {
                "root": self.root.name,
                "model": self.model_status(),
                "job": self.job,
                "before": [{"name": f.name, "size": f.size} for f in files],
                "skipped": [p.name for p in skipped],
                "plan": plan,
                "report": self.report(db),
                "history": history,
                "rules": rules,
                "last_run": self.last_run(db),
                "service_running": daemon_running(),
                "analyzed": db.execute("SELECT COUNT(*) FROM analysis").fetchone()[0],
                "screenshots": sum(1 for f in files if category_for(f) == "Screenshots"),
            }
        finally:
            db.close()

    def last_run(self, db) -> dict | None:
        row = db.execute("SELECT ts, trigger, analyzed, moved, note FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(zip(("ts", "trigger", "analyzed", "moved", "note"), row)) if row else None

    def report(self, db) -> dict | None:
        row = db.execute("SELECT batch, MAX(ts) FROM moves WHERE batch=(SELECT batch FROM moves ORDER BY id DESC LIMIT 1)").fetchone()
        if not row or not row[0]:
            return None
        rows = db.execute("SELECT dst, reason, undone FROM moves WHERE batch=?", (row[0],)).fetchall()
        live = [(d, r) for d, r, u in rows if not u]
        archive_dir = self.root / ARCHIVE
        freed = 0
        for d, _ in live:
            p = Path(d)
            if p.is_relative_to(archive_dir) and p.exists():
                freed += p.stat().st_size
        return {
            "when": row[1],
            "tidied": len(live),
            "archived": sum(1 for d, _ in live if Path(d).is_relative_to(archive_dir)),
            "freed": freed,
            "by_model": sum(1 for _, r in live if "by model" in r),
            "undone": sum(1 for *_, u in rows if u),
        }

    def ask(self, q: str) -> list[dict]:
        db = open_db(self.root)
        try:
            out = []
            for path, cat, desc in ask(db, q, limit=8):
                row = db.execute("SELECT sha256 FROM analysis WHERE path=?", (str(path),)).fetchone()
                out.append({"path": self.rel(path), "category": cat, "description": desc, "sha": row[0] if row else None})
            return out
        finally:
            db.close()

    def apply(self) -> dict:
        with self.lock:
            db = open_db(self.root)
            try:
                files, _ = scan(self.root, self.min_age, self.hash_cache)
                moves = build_plan(self.root, files, load_categories(db), load_rules(db))
            finally:
                db.close()
            res = apply_plan(self.root, moves) if moves else None
            return {"batch": res.batch if res else None, "moved": res.moved if res else 0, "failed": res.failed if res else 0}

    def start_analyze(self) -> dict:
        with self.lock:
            if self.job["state"] == "running":
                return self.job
            client = OllamaClient()
            if not client.available():
                self.job = {"state": "error", "done": 0, "total": 0, "message": f"Model '{client.model}' is not reachable. Start Ollama first."}
                return self.job
            self.job = {"state": "running", "done": 0, "total": 0, "message": "Looking at screenshots..."}
        threading.Thread(target=self._analyze, args=(client,), daemon=True).start()
        return self.job

    def start_run(self) -> dict:
        with self.lock:
            if self.job["state"] == "running":
                return self.job
            self.job = {"state": "running", "done": 0, "total": 0, "message": "Understanding screenshots and tidying..."}
        threading.Thread(target=self._run_now, daemon=True).start()
        return self.job

    def _run_now(self) -> None:
        try:
            r = run_once(self.root, self.min_age, force=True)
            self.job = {"state": "done", "done": 0, "total": 0, "message": r["note"].capitalize() + "."}
        except Exception as e:
            self.job = {"state": "error", "done": 0, "total": 0, "message": str(e)}

    def _analyze(self, client) -> None:
        db = open_db(self.root)
        try:
            files, _ = scan(self.root, self.min_age, self.hash_cache)
            known = {r[0] for r in db.execute("SELECT sha256 FROM analysis")}
            todo = [f for f in files if category_for(f) == "Screenshots" and f.sha256 not in known]
            self.job["total"] = len(todo)

            def progress(n):
                self.job["done"] = n

            analyze_screenshots(db, files, client, progress)
            self.job = {"state": "done", "done": len(todo), "total": len(todo), "message": f"Analyzed {len(todo)} new screenshot(s)."}
        except ModelUnavailable as e:
            self.job = {"state": "error", "done": self.job["done"], "total": self.job["total"], "message": str(e)}
        finally:
            db.close()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Nyx"

        def log_message(self, *args):
            pass

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in app.allowed_hosts()

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "bad host"}, 403)
            url = urlparse(self.path)
            if url.path == "/":
                html = PAGE.read_text().replace("__TOKEN__", app.token)
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if url.path == "/api/ping":
                app.last_ping = time.time()
                return self._json({"ok": True})
            if url.path == "/api/settings":
                return self._json(app.settings_payload())
            if url.path == "/api/state":
                return self._json(app.state())
            if url.path == "/api/ask":
                q = parse_qs(url.query).get("q", [""])[0][:200]
                return self._json(app.ask(q))
            if url.path.startswith("/thumb/"):
                return self._thumb(url.path.removeprefix("/thumb/"))
            self._json({"error": "not found"}, 404)

        def _thumb(self, sha: str) -> None:
            db = open_db(app.root)
            try:
                row = db.execute("SELECT path FROM analysis WHERE sha256=?", (sha,)).fetchone()
            finally:
                db.close()
            try:
                path = ensure_inside(app.root, Path(row[0])) if row else None
            except UnsafePath:
                path = None
            if not path or not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
                return self._json({"error": "not found"}, 404)
            self._send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-Nyx-Token") != app.token:
                return self._json({"error": "forbidden"}, 403)
            length = min(int(self.headers.get("Content-Length") or 0), 10_000)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            path = urlparse(self.path).path
            if path == "/api/apply":
                return self._json(app.apply())
            if path == "/api/undo":
                with app.lock:
                    return self._json({"restored": undo_last(app.root)})
            if path == "/api/undo_move":
                with app.lock:
                    return self._json({"restored": undo_move(app.root, int(body.get("id", -1)))})
            if path == "/api/settings":
                save_settings(body)
                return self._json(app.settings_payload())
            if path == "/api/service":
                action = body.get("action")
                if action == "start":
                    start_background()
                elif action == "stop":
                    stop_background()
                else:
                    return self._json({"error": "bad action"}, 400)
                for _ in range(20):
                    if daemon_running() == (action == "start"):
                        break
                    time.sleep(0.1)
                return self._json({"service_running": daemon_running()})
            if path == "/api/run":
                return self._json(app.start_run())
            if path == "/api/analyze":
                return self._json(app.start_analyze())
            if path == "/api/learn":
                with app.lock:
                    db = open_db(app.root)
                    try:
                        return self._json({"learned": learn_from_corrections(app.root, db)})
                    finally:
                        db.close()
            self._json({"error": "not found"}, 404)

    return Handler


def make_server(root: Path, port: int = 8765, min_age_hours: float | None = None):
    app = App(root, port, min_age_hours)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    app.port = httpd.server_address[1]
    return httpd, app


def serve(root: Path, port: int = 8765, min_age_hours: float | None = None) -> None:
    httpd, app = make_server(root, port, min_age_hours)
    print(f"Nyx dashboard: http://localhost:{app.port}  (watching {root})  Ctrl+C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
