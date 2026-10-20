import sqlite3
import tempfile
import unittest
from pathlib import Path

from nyx.changes import summarize_change
from nyx.db import init_db
from nyx.learn import learn_from_corrections, load_rules
from nyx.planner import build_plan
from nyx.scanner import FileInfo


class LearnTests(unittest.TestCase):
    def test_rule_needs_two_corrections_then_applies(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            db = init_db(sqlite3.connect(":memory:"))
            (root / "Documents").mkdir()
            (root / "Taxes").mkdir()
            for i, name in enumerate(["a.pdf", "b.pdf"]):
                dst = root / "Documents" / name
                db.execute("INSERT INTO moves (batch, src, dst, reason, ts) VALUES ('x', ?, ?, 'r', 0)", (str(root / name), str(dst)))
                (root / "Taxes" / name).write_text("x")
                self.assertEqual(learn_from_corrections(root, db), 1)
                self.assertEqual(load_rules(db), {} if i == 0 else {".pdf": "Taxes"})
            self.assertEqual(learn_from_corrections(root, db), 0)
            info = FileInfo(root / "c.pdf", 1, 0.0, "h")
            self.assertEqual(build_plan(root, [info], rules=load_rules(db))[0].dst, root / "Taxes" / "c.pdf")


class ChangesTests(unittest.TestCase):
    def test_counts_and_model_summary(self):
        with tempfile.TemporaryDirectory() as t:
            old, new = Path(t, "a.txt"), Path(t, "b.txt")
            old.write_text("one\ntwo\n")
            new.write_text("one\nthree\nfour\n")
            self.assertEqual(summarize_change(old, new), "2 line(s) added, 1 removed")

            class Fake:
                def generate_text(self, prompt):
                    return "- replaced two with three"

            self.assertIn("replaced two", summarize_change(old, new, Fake()))


if __name__ == "__main__":
    unittest.main()
