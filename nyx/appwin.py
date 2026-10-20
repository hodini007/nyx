import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .server import make_server

BROWSERS = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
GRACE = 90
SILENCE = 180


def find_browser() -> str | None:
    for b in BROWSERS:
        found = shutil.which(b) or (b if os.path.isabs(b) and Path(b).exists() else None)
        if found:
            return found
    return None


def open_window(url: str) -> bool:
    """Open url as a standalone app window (Chrome or Edge app mode). False when only a normal tab was possible."""
    exe = find_browser()
    if exe:
        subprocess.Popen([exe, f"--app={url}", "--window-size=1150,860"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    webbrowser.open(url)
    return False


def run_app(root: Path, min_age_hours: float | None = None) -> int:
    httpd, app = make_server(root, 0, min_age_hours)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://localhost:{app.port}"
    standalone = open_window(url)
    print(f"Nyx is open at {url}" + ("" if standalone else " (no Chrome/Edge found, opened in your browser)"))
    print("Close the window to quit. The background service keeps running if you started it.")
    started = time.time()
    try:
        while True:
            time.sleep(2)
            quiet_for = time.time() - (app.last_ping or started)
            if quiet_for > (SILENCE if app.last_ping else GRACE):
                break
    except KeyboardInterrupt:
        pass
    httpd.shutdown()
    httpd.server_close()
    return 0
