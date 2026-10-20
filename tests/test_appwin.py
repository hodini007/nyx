import time
import unittest
from pathlib import Path
from unittest import mock

from nyx import appwin
from nyx.safety import SANDBOX


class AppWindowTests(unittest.TestCase):
    def test_opens_chrome_style_app_window(self):
        with mock.patch.object(appwin, "find_browser", return_value="/usr/bin/chromium"), \
             mock.patch("nyx.appwin.subprocess.Popen") as popen:
            self.assertTrue(appwin.open_window("http://localhost:1234"))
        cmd = popen.call_args[0][0]
        self.assertEqual(cmd[0], "/usr/bin/chromium")
        self.assertIn("--app=http://localhost:1234", cmd)

    def test_falls_back_to_default_browser(self):
        with mock.patch.object(appwin, "find_browser", return_value=None), \
             mock.patch("nyx.appwin.webbrowser.open") as opened:
            self.assertFalse(appwin.open_window("http://localhost:1234"))
        opened.assert_called_once()

    def test_app_exits_when_window_never_pings(self):
        (SANDBOX / "Downloads").mkdir(parents=True, exist_ok=True)
        with mock.patch.object(appwin, "open_window", return_value=True), mock.patch.object(appwin, "GRACE", 1):
            start = time.time()
            self.assertEqual(appwin.run_app(SANDBOX / "Downloads"), 0)
        self.assertLess(time.time() - start, 10)


if __name__ == "__main__":
    unittest.main()
