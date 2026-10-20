# Nyx

A local agent that tidies messy folders (Downloads, Desktop, screenshots) while you sleep.
It archives exact duplicates and old versions, sorts files by type, and uses a local vision model
(Gemma 3 through Ollama) to read screenshots and file them by what they show.
Your files never leave your machine.

## Safety rules
- Nothing is ever deleted. Duplicates and old versions go to `_archive/` inside the same folder.
- Nyx only works in folders you add yourself. It refuses your whole home folder, drive roots,
  system folders, folders that overlap an existing one, and the Nyx program folder.
- A newly added folder is **preview only** until you switch it to automatic.
- Only loose files are handled. Subfolders, partial downloads and files newer than 24 hours are left alone.
- Every run is logged and can be undone, whole run or single move.

## Setup
1. Python 3.10+ (the control panel needs Tkinter; on Ubuntu: `sudo apt install python3-tk`).
2. Ollama with a vision model: `ollama pull gemma3:4b` (about 3 GB). Without it, only rule-based sorting runs.

## Use
```bash
python3 -m nyx.cli gui                        # control panel: folders, schedule, service, activity
python3 -m nyx.cli folders add ~/Downloads    # or add folders from the panel
python3 -m nyx.cli daemon                     # background service (or start it from the panel)
python3 -m nyx.cli run                        # tidy all watched folders now
python3 -m nyx.cli schedule --os linux        # autostart + hotkey instructions (linux | macos | windows)
python3 -m nyx.cli app                        # browser-based detail view (search, thumbnails)
```
Per-folder commands (`plan`, `apply`, `undo`, `ask`, `analyze`) take `--root FOLDER`.
Try everything safely on dummy files: `python3 make_playground.py`, then run commands without `--root`.

## How automatic mode decides to run
The daemon wakes every few minutes. It works only when the machine is on AC power, the CPU is quiet and
you have been idle for the configured time, or inside the night window, and when enough files are waiting
(or it is night). If you come back mid-run it stops. Settings are edited in the control panel and take effect
on the next check.

## Honest limitations
- CPU-only speed: about 60 to 75 seconds per new screenshot with Gemma 3 4B. Results are cached by file hash,
  so each screenshot is analyzed once. A GPU or Apple silicon is much faster.
- Idle detection works on Windows, macOS, X11 and GNOME, and falls back to the night window elsewhere
  (for example Hyprland). Only Linux has been tested; the Windows and macOS code paths are untested.
- `nyx gui` and `nyx app` were tested on Linux only.

## Tests
`python3 -m unittest discover -s tests -t .` (GUI tests skip themselves when there is no display).
