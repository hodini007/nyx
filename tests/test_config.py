import json
import tempfile
import unittest
from pathlib import Path

from nyx.config import Settings, from_dict, load_settings, save_settings, threads_for


class ConfigTests(unittest.TestCase):
    def test_defaults_when_missing_or_broken(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(load_settings(Path(t)), Settings())
            (Path(t) / ".nyx").mkdir()
            (Path(t) / ".nyx" / "settings.json").write_text("{not json")
            self.assertEqual(load_settings(Path(t)), Settings())

    def test_values_are_clamped_and_coerced(self):
        s = from_dict({"idle_minutes": "9999", "night_start": 99, "min_new": "abc", "effort": "turbo",
                       "enabled": "false", "auto_move": True, "min_age_hours": -5})
        self.assertEqual(s.idle_minutes, 240)
        self.assertEqual(s.night_start, 23)
        self.assertEqual(s.min_new, 10)
        self.assertEqual(s.effort, "full")
        self.assertFalse(s.enabled)
        self.assertEqual(s.min_age_hours, 0)

    def test_save_and_load_roundtrip_and_window(self):
        with tempfile.TemporaryDirectory() as t:
            save_settings(Path(t), {"night_start": 22, "night_end": 6, "idle_minutes": 10})
            s = load_settings(Path(t))
            self.assertEqual((s.night_start, s.night_end, s.idle_minutes), (22, 6, 10))
            self.assertEqual(s.window(), (22, 6))
            save_settings(Path(t), {"night_enabled": False})
            self.assertEqual(load_settings(Path(t)).window(), (0, 0))
            json.loads((Path(t) / ".nyx" / "settings.json").read_text())

    def test_threads(self):
        self.assertIsNone(threads_for("full"))
        self.assertGreaterEqual(threads_for("gentle"), 1)


if __name__ == "__main__":
    unittest.main()
