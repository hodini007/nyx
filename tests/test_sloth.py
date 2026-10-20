import subprocess
import sys
import unittest
from pathlib import Path

from sloth.rules import normalize
from sloth.safety import SANDBOX, UnsafePath, ensure_root

PROJECT = Path(__file__).resolve().parent.parent
DOWNLOADS = SANDBOX / "Downloads"


def run(*args):
    return subprocess.run([sys.executable, "-m", "sloth.cli", *args], cwd=PROJECT, capture_output=True, text=True)


class SafetyTests(unittest.TestCase):
    def test_refuses_outside_sandbox(self):
        for bad in ["/tmp", str(Path.home()), str(PROJECT), str(SANDBOX / ".." / "sloth")]:
            with self.assertRaises(UnsafePath):
                ensure_root(Path(bad))

    def test_cli_refuses_home(self):
        r = run("apply", "--root", str(Path.home()))
        self.assertEqual(r.returncode, 2)


class NormalizeTests(unittest.TestCase):
    def test_versions_collapse(self):
        names = ["report", "report_v2", "report_v3_final", "report (1)", "report - Copy", "setup-1.4.2", "setup-1.5.0"]
        self.assertEqual({normalize(n) for n in names}, {"report", "setup"})


class EndToEnd(unittest.TestCase):
    def test_apply_then_undo_restores_everything(self):
        subprocess.run([sys.executable, "make_playground.py"], cwd=PROJECT, check=True, capture_output=True)
        before = sorted(p.name for p in DOWNLOADS.iterdir())
        self.assertEqual(run("apply").returncode, 0)
        self.assertTrue((DOWNLOADS / "_archive").exists())
        self.assertTrue((DOWNLOADS / "just-downloaded.pdf").exists())
        self.assertEqual(run("undo").returncode, 0)
        after = sorted(p.name for p in DOWNLOADS.iterdir() if not p.name.startswith("."))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
