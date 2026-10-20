import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from nyx.cli import main
from nyx.daemon import run_daemon
from nyx.idle import parse_gnome_idle, parse_hid_idle
from nyx.lock import FileLock
from nyx.safety import SANDBOX

BUSY = lambda: (False, "user is active")


class ParseTests(unittest.TestCase):
    def test_macos_hid_idle(self):
        self.assertEqual(parse_hid_idle('    | "HIDIdleTime" = 4000000000\n'), 4.0)
        self.assertIsNone(parse_hid_idle("nothing here"))

    def test_gnome_idle(self):
        self.assertEqual(parse_gnome_idle("(uint64 5234,)"), 5.234)
        self.assertIsNone(parse_gnome_idle("error"))


class LockTests(unittest.TestCase):
    def test_second_lock_fails_until_released(self):
        with tempfile.TemporaryDirectory() as t:
            a, b = FileLock(Path(t) / "x.lock"), FileLock(Path(t) / "x.lock")
            self.assertTrue(a.acquire())
            self.assertFalse(b.acquire())
            a.release()
            self.assertTrue(b.acquire())
            b.release()


class DaemonTests(unittest.TestCase):
    def test_ticks_and_collapses_repeated_skips(self):
        with tempfile.TemporaryDirectory() as t:
            logs = []
            code = run_daemon(Path(t), max_ticks=3, sleep=lambda s: None, log=logs.append, idle_check=BUSY)
            self.assertEqual(code, 0)
            self.assertEqual(len(logs), 2)
            self.assertIn("user is active", logs[1])

    def test_second_daemon_refuses(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".nyx").mkdir()
            held = FileLock(Path(t) / ".nyx" / "daemon.lock")
            held.acquire()
            logs = []
            self.assertEqual(run_daemon(Path(t), max_ticks=1, sleep=lambda s: None, log=logs.append), 1)
            held.release()


class ScheduleTests(unittest.TestCase):
    def test_instructions_for_each_os(self):
        (SANDBOX / "Downloads").mkdir(parents=True, exist_ok=True)
        expect = {"linux": "systemctl --user", "macos": "launchctl load", "windows": "schtasks /Create"}
        for os_name, needle in expect.items():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["schedule", "--os", os_name]), 0)
            self.assertIn(needle, out.getvalue())
            self.assertIn("nyx.cli run", out.getvalue())


if __name__ == "__main__":
    unittest.main()
