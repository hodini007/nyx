import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nyx import registry
from nyx.executor import apply_plan, undo_last
from nyx.planner import Move
from nyx.safety import PROJECT, SANDBOX, UnsafePath, check_folder, ensure_root, forbidden_reason
from nyx.scanner import scan


class SafetyRuleTests(unittest.TestCase):
    def test_refuses_dangerous_folders(self):
        for bad in ["/", Path.home(), Path.home().parent, "/etc", "/usr/bin", PROJECT, PROJECT / "nyx"]:
            self.assertIsNotNone(forbidden_reason(Path(bad)), bad)

    def test_accepts_normal_folders(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIsNone(forbidden_reason(Path(t)))
            self.assertEqual(check_folder(Path(t)), Path(t).resolve())

    def test_rejects_missing_and_files(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises(UnsafePath):
                check_folder(Path(f.name))
        with self.assertRaises(UnsafePath):
            check_folder(Path("/definitely/not/here"))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.patch = mock.patch.dict(os.environ, {"NYX_HOME": str(self.base / "cfg")})
        self.patch.start()
        self.a = self.base / "a"
        self.a.mkdir()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_add_list_toggle_remove(self):
        f = registry.add_folder(self.a)
        self.assertFalse(f.auto_move)
        self.assertTrue(registry.is_registered(self.a))
        self.assertTrue(registry.set_auto_move(self.a, True))
        self.assertTrue(registry.load_folders()[0].auto_move)
        self.assertTrue(registry.remove_folder(self.a))
        self.assertEqual(registry.load_folders(), [])

    def test_duplicates_and_overlaps_refused(self):
        registry.add_folder(self.a)
        (self.a / "inner").mkdir()
        with self.assertRaises(UnsafePath):
            registry.add_folder(self.a)
        with self.assertRaises(UnsafePath):
            registry.add_folder(self.a / "inner")
        with self.assertRaises(UnsafePath):
            registry.add_folder(self.base)

    def test_ensure_root_requires_registration(self):
        with self.assertRaises(UnsafePath):
            ensure_root(self.a)
        registry.add_folder(self.a)
        self.assertEqual(ensure_root(self.a), self.a.resolve())

    def test_sandbox_still_allowed_without_registration(self):
        (SANDBOX / "Downloads").mkdir(parents=True, exist_ok=True)
        self.assertEqual(ensure_root(SANDBOX / "Downloads"), (SANDBOX / "Downloads").resolve())

    def test_corrupt_registry_means_no_folders(self):
        (self.base / "cfg").mkdir()
        (self.base / "cfg" / "folders.json").write_text("{broken")
        self.assertEqual(registry.load_folders(), [])


class MoverHardeningTests(unittest.TestCase):
    def test_failure_midway_keeps_earlier_moves_undoable(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            for n in ("a.txt", "b.txt", "c.txt"):
                (root / n).write_text(n)
            moves = [Move(root / n, root / "Documents" / n, "test") for n in ("a.txt", "b.txt", "c.txt")]
            import shutil
            real = shutil.move
            calls = {"n": 0}

            def flaky(src, dst):
                calls["n"] += 1
                if calls["n"] == 2:
                    raise PermissionError("locked")
                return real(src, dst)

            with mock.patch("nyx.executor.shutil.move", side_effect=flaky):
                res = apply_plan(root, moves)
            self.assertEqual((res.moved, res.failed), (2, 1))
            self.assertTrue((root / "b.txt").exists())
            self.assertEqual(undo_last(root), 2)
            self.assertEqual(sorted(p.name for p in root.glob("*.txt")), ["a.txt", "b.txt", "c.txt"])

    def test_partial_downloads_and_junk_are_ignored(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            old = 1_000_000_000
            for n in ("movie.mp4.crdownload", "file.part", "desktop.ini", "Thumbs.db", "real.pdf"):
                f = root / n
                f.write_text("x")
                os.utime(f, (old, old))
            files, _ = scan(root, 24)
            self.assertEqual([f.name for f in files], ["real.pdf"])


if __name__ == "__main__":
    unittest.main()
