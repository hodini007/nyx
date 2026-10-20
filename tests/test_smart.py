import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from nyx.config import Settings
from nyx.db import init_db
from nyx.scanner import scan
from nyx.smart import collect_training, predict_folders, smart_plan, smart_status, tokens, user_folders


class NearestNeighbour:
    """Stand-in for TabPFN: 1-nearest-neighbour with a confident probability."""

    calls = 0

    def fit(self, X, y):
        NearestNeighbour.calls += 1
        self.X, self.y = X, y
        return self

    def predict_proba(self, X):
        classes = sorted(set(self.y))
        out = []
        for row in X:
            best = min(range(len(self.X)), key=lambda i: sum((a - b) ** 2 for a, b in zip(row, self.X[i])))
            out.append([0.9 if c == self.y[best] else 0.1 / max(len(classes) - 1, 1) for c in classes])
        return out, classes


def make_tree(root: Path):
    old = time.time() - 9 * 86400
    layout = {
        "Work": ["weekly_report_1.pdf", "weekly_report_2.pdf", "meeting_notes_a.pdf", "meeting_notes_b.pdf", "project_report_final.pdf"],
        "Taxes": ["tax_invoice_2024.pdf", "tax_invoice_2025.pdf", "tax_receipt_a.pdf", "tax_receipt_b.pdf", "tax_form_2023.pdf"],
        "Documents": ["ignored_by_training.pdf"],
        "_archive/old_versions": ["ignored_too.pdf"],
        ".nyx": ["hidden.db"],
    }
    for folder, names in layout.items():
        (root / folder).mkdir(parents=True, exist_ok=True)
        for n in names:
            f = root / folder / n
            f.write_text(n)
            os.utime(f, (old, old))
    for n in ("weekly_report_3.pdf", "tax_invoice_2026.pdf", "mystery.bin"):
        f = root / n
        f.write_text(n * 3)
        os.utime(f, (old, old))


class SmartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_tree(self.root)
        NearestNeighbour.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def test_training_uses_only_user_folders(self):
        self.assertEqual([p.name for p in user_folders(self.root)], ["Taxes", "Work"])
        labels = {l for _, l in collect_training(self.root)}
        self.assertEqual(labels, {"Work", "Taxes"})
        self.assertNotIn("ignored_by_training.pdf", [p.name for p, _ in collect_training(self.root)])

    def test_tokens(self):
        self.assertEqual(tokens("weeklyReport_Final-2026.pdf"), ["weekly", "report", "final"])

    def test_predicts_confident_folders_and_skips_the_rest(self):
        files, _ = scan(self.root, 0)
        preds = predict_folders(self.root, files, time.time(), NearestNeighbour, threshold=0.75)
        by_name = {p.name: v[0] for p, v in preds.items()}
        self.assertEqual(by_name["weekly_report_3.pdf"], "Work")
        self.assertEqual(by_name["tax_invoice_2026.pdf"], "Taxes")

    def test_too_little_history_means_no_predictions(self):
        with tempfile.TemporaryDirectory() as t:
            r = Path(t)
            (r / "OnlyOne").mkdir()
            (r / "OnlyOne" / "a.txt").write_text("a")
            (r / "b.txt").write_text("b")
            files, _ = scan(r, 0)
            self.assertEqual(predict_folders(r, files, time.time(), NearestNeighbour), {})
        self.assertEqual(NearestNeighbour.calls, 0)

    def test_model_runs_once_for_identical_input(self):
        files, _ = scan(self.root, 0)
        predict_folders(self.root, files, time.time(), NearestNeighbour)
        predict_folders(self.root, files, time.time(), NearestNeighbour)
        self.assertEqual(NearestNeighbour.calls, 1)

    def test_smart_plan_is_off_by_default_and_on_when_enabled(self):
        db = init_db(sqlite3.connect(":memory:"))
        files, _ = scan(self.root, 0)
        off = smart_plan(self.root, files, db, Settings(smart_sorting=False), factory=NearestNeighbour)
        self.assertFalse([m for m in off if "TabPFN" in m.reason])
        on = smart_plan(self.root, files, db, Settings(smart_sorting=True), factory=NearestNeighbour)
        moved = {m.src.name: m for m in on if "TabPFN" in m.reason}
        self.assertEqual(moved["weekly_report_3.pdf"].dst, self.root / "Work" / "weekly_report_3.pdf")
        self.assertIn("looks like your files in Work/", moved["weekly_report_3.pdf"].reason)
        self.assertEqual(moved["tax_invoice_2026.pdf"].dst, self.root / "Taxes" / "tax_invoice_2026.pdf")

    def test_status_reports_without_crashing(self):
        status = smart_status()
        self.assertEqual(set(status), {"installed", "weights", "ready", "message"})

    def test_failing_model_falls_back_to_normal_plan(self):
        class Broken:
            def fit(self, X, y):
                raise RuntimeError("no weights")

        db = init_db(sqlite3.connect(":memory:"))
        files, _ = scan(self.root, 0)
        plan = smart_plan(self.root, files, db, Settings(smart_sorting=True), factory=Broken)
        self.assertEqual(len(plan), 3)
        self.assertFalse([m for m in plan if "TabPFN" in m.reason])


if __name__ == "__main__":
    unittest.main()
