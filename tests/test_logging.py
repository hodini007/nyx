import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from nyx import logfile
from nyx.daemon import run_daemon
from nyx.runner import run_once


class LogFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"NYX_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_write_tail_clear(self):
        self.assertEqual(logfile.tail(), "")
        logfile.write("first")
        logfile.write("second")
        text = logfile.tail()
        self.assertIn("first", text)
        self.assertTrue(text.rstrip().endswith("second"))
        self.assertRegex(text.splitlines()[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d  first$")
        logfile.clear()
        self.assertEqual(logfile.tail(), "")

    def test_rotates_when_large(self):
        with mock.patch.object(logfile, "MAX_BYTES", 200):
            for i in range(30):
                logfile.write(f"line {i} " + "x" * 20)
        self.assertTrue(logfile.log_path().with_name("nyx.log.1").exists())
        self.assertLess(logfile.log_path().stat().st_size, 400)

    def test_tail_drops_partial_first_line(self):
        for i in range(50):
            logfile.write(f"entry {i:03d}")
        lines = logfile.tail(max_bytes=200).splitlines()
        self.assertTrue(all(l.split("  ", 1)[1].startswith("entry") for l in lines))

    def test_stamp_changes_on_write(self):
        before = logfile.stamp()
        logfile.write("x")
        self.assertNotEqual(before, logfile.stamp())

    def test_write_never_raises(self):
        with mock.patch("builtins.open", side_effect=OSError("disk full")):
            logfile.write("ignored")


class FakeModel:
    model = "fake-vision"

    def __init__(self, up=True):
        self.up = up

    def available(self):
        return self.up

    def classify_image(self, data):
        return {"category": "receipt", "description": "a receipt"}


def make_root(shots=2, docs=3):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    old = time.time() - 5 * 86400
    for i in range(docs):
        f = root / f"n{i}.txt"
        f.write_text(str(i))
        os.utime(f, (old, old))
    for i in range(shots):
        f = root / f"Screenshot {i}.png"
        f.write_bytes(b"png%d" % i)
        os.utime(f, (old, old))
    return tmp, root


class RunnerLogTests(unittest.TestCase):
    def test_progress_is_logged(self):
        tmp, root = make_root()
        with tmp:
            lines = []
            run_once(root, force=True, client=FakeModel(), log=lines.append)
        text = "\n".join(lines)
        self.assertIn("run started (manual)", text)
        self.assertIn("reading 2 screenshot(s) with fake-vision", text)
        self.assertIn("screenshot 1/2 Screenshot 0.png: receipt", text)
        self.assertIn("run finished: analyzed 2", text)

    def test_unreachable_model_is_logged(self):
        tmp, root = make_root(shots=1)
        with tmp:
            lines = []
            run_once(root, force=True, client=FakeModel(up=False), log=lines.append)
        self.assertTrue(any("model not reachable" in l for l in lines))

    def test_default_log_goes_to_the_file(self):
        tmp, root = make_root(shots=0, docs=2)
        with tmp, tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"NYX_HOME": home}):
            run_once(root, force=True)
            self.assertIn("run finished", logfile.tail())


class DaemonLogTests(unittest.TestCase):
    def test_daemon_default_log_prints_and_writes_file(self):
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"NYX_HOME": home}):
            run_daemon(lambda: [], max_ticks=1, sleep=lambda s: None, lock_dir=Path(home))
            text = logfile.tail()
        self.assertIn("Nyx daemon started", text)
        self.assertIn("no watched folders", text)


if __name__ == "__main__":
    unittest.main()
