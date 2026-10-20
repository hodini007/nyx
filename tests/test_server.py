import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from nyx.safety import SANDBOX
from nyx.server import App, make_handler

PROJECT = Path(__file__).resolve().parent.parent


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess, sys
        subprocess.run([sys.executable, "make_playground.py"], cwd=PROJECT, check=True, capture_output=True)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App.__new__(App)))
        port = cls.httpd.server_address[1]
        cls.app = App(SANDBOX / "Downloads", port, 24.0)
        cls.httpd.RequestHandlerClass = make_handler(cls.app)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, path, body=None, token=None, host=None):
        r = urllib.request.Request(self.base + path, json.dumps(body).encode() if body is not None else None)
        if token:
            r.add_header("X-Nyx-Token", token)
        if host:
            r.add_header("Host", host)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_state_and_page(self):
        code, body = self.req("/api/state")
        self.assertEqual(code, 200)
        state = json.loads(body)
        self.assertEqual(len(state["plan"]), 19)
        code, page = self.req("/")
        self.assertIn(self.app.token.encode(), page)

    def test_post_requires_token(self):
        self.assertEqual(self.req("/api/apply", {})[0], 403)
        self.assertEqual(self.req("/api/apply", {}, token="wrong")[0], 403)

    def test_foreign_host_rejected(self):
        self.assertEqual(self.req("/api/state", host="evil.example.com")[0], 403)

    def test_apply_then_undo_via_api(self):
        t = self.app.token
        code, body = self.req("/api/apply", {}, token=t)
        self.assertEqual(json.loads(body)["moved"], 19)
        state = json.loads(self.req("/api/state")[1])
        self.assertEqual(state["report"]["tidied"], 19)
        self.assertEqual(state["plan"], [])
        self.assertEqual(json.loads(self.req("/api/undo", {}, token=t)[1])["restored"], 19)


if __name__ == "__main__":
    unittest.main()
