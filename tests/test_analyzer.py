import sqlite3
import tempfile
import unittest
from pathlib import Path

from sloth.analyzer import ModelUnavailable, OllamaClient, analyze_screenshots, load_categories, parse_answer
from sloth.db import init_db
from sloth.planner import build_plan
from sloth.scanner import FileInfo, hash_file
from sloth.search import ask


class FakeModel:
    model = "fake"

    def __init__(self):
        self.calls = 0

    def classify_image(self, data):
        self.calls += 1
        return {"category": "receipt", "description": "Coffee shop receipt for 4.50 dollars"}


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        p = self.root / "Screenshot 2026-10-01.png"
        p.write_bytes(b"fakepng")
        self.info = FileInfo(p, 7, 0.0, hash_file(p))
        self.db = init_db(sqlite3.connect(":memory:"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_cached_by_hash(self):
        model = FakeModel()
        self.assertEqual(analyze_screenshots(self.db, [self.info], model), 1)
        self.assertEqual(analyze_screenshots(self.db, [self.info], model), 0)
        self.assertEqual(model.calls, 1)

    def test_ask_finds_description(self):
        analyze_screenshots(self.db, [self.info], FakeModel())
        hits = ask(self.db, "coffee receipt")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][1], "receipt")

    def test_plan_uses_model_category(self):
        analyze_screenshots(self.db, [self.info], FakeModel())
        moves = build_plan(self.root, [self.info], load_categories(self.db))
        self.assertEqual(moves[0].dst, self.root / "Screenshots" / "Receipt" / self.info.name)

    def test_parse_answer(self):
        self.assertEqual(parse_answer('{"category":"CHAT","description":"hi"}')["category"], "chat")
        self.assertEqual(parse_answer('{"category":"weird"}')["category"], "other")
        self.assertEqual(parse_answer("not json")["category"], "other")

    def test_refuses_remote_host(self):
        with self.assertRaises(ModelUnavailable):
            OllamaClient(host="http://example.com:11434")
        OllamaClient(host="localhost:11434")


if __name__ == "__main__":
    unittest.main()
