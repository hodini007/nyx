import os
import tempfile
import time
import unittest
from pathlib import Path

from nyx.idle import in_window
from nyx.runner import run_once


class FakeModel:
    model = "fake"

    def __init__(self):
        self.calls = 0

    def available(self):
        return True

    def classify_image(self, data):
        self.calls += 1
        return {"category": "receipt", "description": "a receipt"}


class DownModel(FakeModel):
    def available(self):
        return False


def make_root(n_docs=12, n_shots=0):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    old = time.time() - 5 * 86400
    for i in range(n_docs):
        f = root / f"note{i}.txt"
        f.write_text(f"content {i}")
        os.utime(f, (old, old))
    for i in range(n_shots):
        f = root / f"Screenshot {i}.png"
        f.write_bytes(b"png-%d" % i)
        os.utime(f, (old, old))
    return tmp, root


BUSY = lambda: (False, "user is active")
IDLE = lambda: (True, "user idle")


class RunnerTests(unittest.TestCase):
    def test_busy_machine_does_nothing(self):
        tmp, root = make_root()
        with tmp:
            r = run_once(root, idle_check=BUSY, client=FakeModel())
            self.assertEqual(r["status"], "skipped")
            self.assertEqual(len(list(root.glob("note*.txt"))), 12)

    def test_too_few_files_daytime_waits(self):
        tmp, root = make_root(n_docs=3)
        with tmp:
            r = run_once(root, min_new=10, window=(0, 0), idle_check=IDLE, client=FakeModel())
            self.assertEqual(r["status"], "skipped")

    def test_idle_with_enough_files_sorts_and_screenshots_get_subfolders(self):
        tmp, root = make_root(n_docs=10, n_shots=2)
        with tmp:
            model = FakeModel()
            r = run_once(root, min_new=10, idle_check=IDLE, client=model, still_idle=lambda: True)
            self.assertEqual(r["status"], "done")
            self.assertEqual(model.calls, 2)
            self.assertEqual(len(list((root / "Screenshots" / "Receipt").glob("*.png"))), 2)
            self.assertEqual(len(list((root / "Documents").glob("*.txt"))), 10)

    def test_user_returning_stops_analysis_and_leaves_screenshots(self):
        tmp, root = make_root(n_docs=10, n_shots=3)
        with tmp:
            model = FakeModel()
            answers = iter([True, False, False])
            r = run_once(root, min_new=10, idle_check=IDLE, client=model, still_idle=lambda: next(answers))
            self.assertEqual(model.calls, 1)
            self.assertIn("came back", r["note"])
            self.assertEqual(len(list(root.glob("Screenshot *.png"))), 2)

    def test_model_down_still_sorts_other_files(self):
        tmp, root = make_root(n_docs=10, n_shots=1)
        with tmp:
            r = run_once(root, min_new=10, idle_check=IDLE, client=DownModel(), still_idle=lambda: True)
            self.assertEqual(len(list((root / "Documents").glob("*.txt"))), 10)
            self.assertEqual(len(list(root.glob("Screenshot *.png"))), 1)
            self.assertIn("waiting for the model", r["note"])

    def test_force_runs_anyway(self):
        tmp, root = make_root(n_docs=2)
        with tmp:
            r = run_once(root, force=True, client=FakeModel())
            self.assertEqual(r["moved"], 2)

    def test_window_wraps_midnight(self):
        self.assertTrue(in_window(23, (22, 5)))
        self.assertTrue(in_window(3, (22, 5)))
        self.assertFalse(in_window(12, (22, 5)))
        self.assertTrue(in_window(2, (1, 5)))


if __name__ == "__main__":
    unittest.main()
