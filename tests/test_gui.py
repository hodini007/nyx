import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import tkinter as tk
except ImportError:
    tk = None

from nyx import registry
from nyx.scanner import FileInfo, scan
from nyx.rules import find_duplicates


def display_ok() -> bool:
    if tk is None:
        return False
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(display_ok(), "needs Tkinter and a display")
class PanelTests(unittest.TestCase):
    def setUp(self):
        from nyx.gui import NyxPanel

        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"NYX_HOME": str(base / "cfg")})
        self.env.start()
        self.dl = base / "Downloads"
        self.dl.mkdir()
        old = time.time() - 5 * 86400
        for n in ("a.txt", "b.docx", "c.pdf"):
            f = self.dl / n
            f.write_text(n)
            os.utime(f, (old, old))
        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = NyxPanel(self.root)
        self.warnings = []
        self.panel.warn = self.warnings.append
        self.panel.confirm = lambda m: True

    def tearDown(self):
        self.root.destroy()
        self.env.stop()
        self.tmp.cleanup()

    def pump(self, seconds=1.5):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.02)

    def test_add_refuse_toggle_tidy_undo(self):
        self.assertTrue(self.panel.add_folder_path(self.dl))
        self.assertFalse(self.panel.add_folder_path(Path.home()))
        self.assertIn("home folder", self.warnings[-1])
        self.assertFalse(self.panel.add_folder_path(Path("/etc")))
        self.assertIn("system folder", self.warnings[-1])
        self.assertFalse(registry.load_folders()[0].auto_move)
        self.panel.tree.selection_set(str(self.dl.resolve()))
        self.panel.on_toggle_mode()
        self.assertTrue(registry.load_folders()[0].auto_move)
        self.panel.on_tidy()
        for _ in range(40):
            self.pump(0.25)
            if not self.panel.busy:
                break
        self.assertFalse(list(self.dl.glob("*.txt")))
        self.assertIn("moved 3", self.panel.status.get())
        self.panel.on_undo()
        self.pump(1.5)
        self.assertEqual(sorted(p.name for p in self.dl.iterdir() if p.is_file()), ["a.txt", "b.docx", "c.pdf"])

    def test_save_settings_roundtrip(self):
        self.panel.v_idle.set("12")
        self.panel.v_start.set("22:00")
        self.panel.on_save()
        from nyx.config import load_settings

        s = load_settings()
        self.assertEqual((s.idle_minutes, s.night_start), (12.0, 22))

    def test_bad_number_is_reported_not_crashing(self):
        self.panel.v_idle.set("abc")
        self.panel.on_save()
        self.assertTrue(self.warnings)


class LazyHashTests(unittest.TestCase):
    def test_only_same_size_files_are_hashed_and_cache_is_reused(self):
        from nyx.db import DbHashCache, init_db
        import sqlite3

        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            old = time.time() - 5 * 86400
            for n, body in [("one.bin", "1"), ("two.bin", "22"), ("three.bin", "22"), ("four.bin", "4444")]:
                (root / n).write_text(body)
                os.utime(root / n, (old, old))
            cache = DbHashCache(init_db(sqlite3.connect(":memory:")))
            with mock.patch("nyx.scanner.hash_file", side_effect=lambda p: f"h-{p.read_text()}") as h:
                files, _ = scan(root, 24, cache)
                self.assertEqual(len(find_duplicates(files)), 1)
                self.assertEqual(h.call_count, 2)
                files, _ = scan(root, 24, cache)
                find_duplicates(files)
                self.assertEqual(h.call_count, 2)


if __name__ == "__main__":
    unittest.main()
