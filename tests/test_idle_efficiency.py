import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from nyx import idle
from nyx.config import settings_path
from nyx.daemon import next_sleep, watch_sleep
from nyx.idle import WAIT_NIGHT, machine_idle, seconds_until_window
from nyx.runner import interrupt_file, request_interrupt, run_once

BUSY = lambda: (False, "user is active")
IDLE = lambda: (True, "user idle")


def at(hour, minute=0):
    return time.struct_time((2026, 10, 21, hour, minute, 0, 2, 294, -1))


class CheapGateTests(unittest.TestCase):
    def test_skipped_check_does_no_heavy_work(self):
        with tempfile.TemporaryDirectory() as t, \
             mock.patch("nyx.runner.scan") as scan, mock.patch("nyx.runner.open_db") as opendb, \
             mock.patch("nyx.runner.smart_plan") as plan:
            r = run_once(Path(t), idle_check=BUSY)
        self.assertEqual(r["status"], "skipped")
        scan.assert_not_called()
        opendb.assert_not_called()
        plan.assert_not_called()

    def test_assume_idle_still_respects_battery(self):
        with mock.patch.object(idle, "on_ac_power", return_value=False):
            self.assertEqual(machine_idle(5, (1, 5), assume_idle=True), (False, "on battery"))
        with mock.patch.object(idle, "on_ac_power", return_value=True), mock.patch.object(idle, "load_ok", return_value=True):
            ok, why = machine_idle(5, (1, 5), assume_idle=True)
        self.assertTrue(ok)
        self.assertIn("desktop", why)


class WindowMathTests(unittest.TestCase):
    def test_seconds_until_window(self):
        self.assertEqual(seconds_until_window((1, 5), at(12, 30)), 12 * 3600 + 30 * 60)
        self.assertEqual(seconds_until_window((1, 5), at(3)), 0)
        self.assertEqual(seconds_until_window((22, 6), at(12)), 10 * 3600)
        self.assertIsNone(seconds_until_window((0, 0), at(12)))

    def test_daemon_sleeps_until_night_when_idle_unknown(self):
        waiting = [f"[skipped] x: idle time unknown, {WAIT_NIGHT}"]
        self.assertEqual(next_sleep(waiting, 5, (1, 5), at(20)), 5 * 3600)
        self.assertEqual(next_sleep(waiting, 5, (1, 5), at(12)), 12 * 3600)
        self.assertEqual(next_sleep(waiting, 5, (1, 5), at(3)), 300)
        self.assertEqual(next_sleep(waiting, 5, (0, 0), at(12)), 6 * 3600)

    def test_normal_interval_when_anything_else_happened(self):
        self.assertEqual(next_sleep(["[skipped] x: user is active"], 5, (1, 5), at(12)), 300)
        self.assertEqual(next_sleep([f"a {WAIT_NIGHT}", "[done] b"], 5, (1, 5), at(12)), 300)
        self.assertEqual(next_sleep([], 5, (1, 5), at(12)), 300)


class WatchSleepTests(unittest.TestCase):
    def test_wakes_early_when_settings_change(self):
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        settings_path().write_text("{}")
        threading.Timer(0.3, lambda: settings_path().write_text('{"idle_minutes": 9}')).start()
        start = time.time()
        os.utime(settings_path(), (start - 100, start - 100))
        watch_sleep(10, step=0.1)
        self.assertLess(time.time() - start, 3)


class FakeModel:
    model = "fake"

    def __init__(self, interrupt_after_first=False):
        self.calls = 0
        self.interrupt_after_first = interrupt_after_first

    def available(self):
        return True

    def classify_image(self, data):
        self.calls += 1
        if self.interrupt_after_first and self.calls == 1:
            request_interrupt()
        return {"category": "receipt", "description": "a receipt"}


def make_root(shots=3, docs=10):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    old = time.time() - 5 * 86400
    for i in range(docs):
        f = root / f"note{i}.txt"
        f.write_text(str(i))
        os.utime(f, (old, old))
    for i in range(shots):
        f = root / f"Screenshot {i}.png"
        f.write_bytes(b"png%d" % i)
        os.utime(f, (old, old))
    return tmp, root


class InterruptTests(unittest.TestCase):
    def setUp(self):
        interrupt_file().unlink(missing_ok=True)

    def test_interrupt_stops_run_after_current_file(self):
        tmp, root = make_root()
        with tmp:
            model = FakeModel(interrupt_after_first=True)
            r = run_once(root, idle_known=True, idle_check=IDLE, client=model)
            self.assertEqual(model.calls, 1)
            self.assertIn("came back", r["note"])
            self.assertEqual(len(list(root.glob("Screenshot *.png"))), 2)

    def test_stale_interrupt_is_ignored(self):
        tmp, root = make_root()
        with tmp:
            request_interrupt()
            old = time.time() - 3600
            os.utime(interrupt_file(), (old, old))
            model = FakeModel()
            run_once(root, idle_known=True, idle_check=IDLE, client=model)
            self.assertEqual(model.calls, 3)


if __name__ == "__main__":
    unittest.main()


class LogindTests(unittest.TestCase):
    def test_idlehint_no_is_treated_as_unknown(self):
        out = "IdleHint=no\nIdleSinceHint=0\n"
        with mock.patch.object(idle, "_run", return_value=out), \
             mock.patch.dict(os.environ, {"XDG_SESSION_ID": "1", "XDG_CURRENT_DESKTOP": "Hyprland", "XDG_SESSION_TYPE": "wayland"}), \
             mock.patch.object(idle.shutil, "which", side_effect=lambda n: "/usr/bin/loginctl" if n == "loginctl" else None):
            self.assertIsNone(idle._idle_linux())

    def test_idlehint_yes_is_trusted(self):
        since = int((time.time() - 600) * 1e6)
        out = f"IdleHint=yes\nIdleSinceHint={since}\n"
        with mock.patch.object(idle, "_run", return_value=out), \
             mock.patch.dict(os.environ, {"XDG_SESSION_ID": "1", "XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}), \
             mock.patch.object(idle.shutil, "which", side_effect=lambda n: "/usr/bin/loginctl" if n == "loginctl" else None):
            self.assertGreaterEqual(idle._idle_linux(), 599)
