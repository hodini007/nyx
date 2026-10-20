# Nyx

**A local agent that tidies your messy folders while you sleep.**
Your files never leave your machine.

Built for the Hacktoberfest Open-Source AI Challenge, Week 3 ("Slow and Steady").
Nyx is named after the Greek goddess of night, because that is when it works.

## The problem
Every Downloads folder turns into the same mess: `report_v2_final_FINAL.docx`, three installers of the same app,
`photo (1).jpg`, and hundreds of screenshots you meant to deal with later. Nobody wants to sort them by hand,
and nobody wants to upload their screenshots, receipts and documents to a cloud service to have them sorted.

## What Nyx does
- **Archives exact duplicates** (`photo (1).jpg`, `photo - Copy.jpg`).
- **Archives older versions** of the same file (`report`, `report_v2`, `setup-1.4.2` vs `setup-1.5.0`), keeping the newest.
- **Sorts everything else by type** (Documents, Images, Installers, Archives, Code, Spreadsheets, ...).
- **Reads screenshots with a local vision model** (Gemma 3) and files them by what they show:
  receipt, error, chat, code, document and so on.
- **Remembers what each screenshot shows**, so you can search for it later.
- **Learns from you**: if you re-file a type of file twice, it follows your habit from then on.
- **Works when you are away**: a background service tidies when the machine is idle or inside a night window,
  and stops as soon as you come back.

## Why open models matter here
This project only makes sense with an open-weight model running locally.
- **Privacy:** screenshots and downloads contain receipts, chats and documents. They are read by Gemma on your own
  CPU through Ollama and are never uploaded anywhere.
- **Cost:** it runs in the background forever. A local model costs nothing per file, and each screenshot is analyzed
  only once because results are cached by file hash.
- **Offline:** it keeps working without an internet connection.
- **Honest trade-off:** a local model on a laptop CPU is slow (see Performance). Running overnight is what makes
  that acceptable, and it is exactly what the theme is about.

## Safety rules
- **Nothing is ever deleted.** Duplicates and old versions move to `_archive/` inside the same folder.
- **Only folders you add.** Nyx refuses your whole home folder, drive roots, system folders, folders that overlap an
  existing one, and the Nyx program folder.
- **Preview first.** A newly added folder is preview-only until you switch it to automatic.
- **Loose files only.** Subfolders, partial downloads (`.crdownload`, `.part`, ...) and files newer than 24 hours
  are left alone.
- **Always undoable.** Every move is logged as it happens. Undo a whole run or a single move.
- **Local model only.** The model client refuses any host other than localhost.

## How it works
```
 timer (daemon, every few minutes)        control panel (Tkinter)  |  CLI  |  browser detail view
              |                                         \              |             /
   idle? AC power? night window?  ------------------->  engine (same code for all three)
              |
   scan folder -> rules (duplicates, versions, types) -> planner -> executor (+ undo log, SQLite)
                                  |
                      screenshots only -> Gemma 3 via Ollama (local) -> category + description
```
The daemon wakes every few minutes and decides whether to work. It runs only when the machine is on AC power
(unless you allow battery), the CPU is quiet, and you have been idle for the configured time, or inside the night
window, and when enough files are waiting. If you come back mid-run it stops after the current screenshot.
Settings and the watched-folder list are re-read every cycle, so edits apply without a restart.

## Setup
1. Python 3.10 or newer. The control panel needs Tkinter (Ubuntu/Debian: `sudo apt install python3-tk`;
   the python.org installers for Windows and macOS include it).
2. [Ollama](https://ollama.com) with a vision model: `ollama pull gemma3:4b` (about 3 GB).
   Without a model, rule-based sorting still works and screenshots wait for the model.
3. No other dependencies. Nyx uses only the Python standard library (`make_playground.py` optionally uses Pillow
   to draw realistic fake screenshots).

## Use
```bash
python3 -m nyx.cli gui                        # control panel: folders, schedule, service, activity
python3 -m nyx.cli folders add ~/Downloads    # or add folders from the panel (starts as preview only)
python3 -m nyx.cli folders auto ~/Downloads on
python3 -m nyx.cli daemon                     # background service (or use the panel's Start service button)
python3 -m nyx.cli run                        # tidy all watched folders now
python3 -m nyx.cli schedule --os linux        # autostart and hotkey instructions (linux | macos | windows)
python3 -m nyx.cli app                        # browser-based detail view: search, thumbnails, history
```
Per-folder commands take `--root FOLDER`: `plan` (dry run), `apply`, `undo`, `analyze`, `ask "wifi password"`,
`changes` (what changed between document versions), `learn`.

The control panel lets you add or remove watched folders, switch each between preview and automatic, preview what
would move, tidy now, undo the last run, and set the schedule: idle minutes, night window, how many waiting files
trigger a run, check interval, CPU effort, and whether to run on battery.

### Try it safely
`python3 make_playground.py` builds a folder of dummy files at `playground/Downloads`.
Everything inside `playground/` can be used without registering it (`python3 -m nyx.cli plan`).

## Where Nyx keeps things
- Per watched folder: a hidden `.nyx/` folder with the undo log, file hash cache and screenshot descriptions.
- Per user: `~/.config/nyx` (Linux), `~/Library/Application Support/Nyx` (macOS) or `%APPDATA%\Nyx` (Windows),
  holding the watched-folder list and schedule settings. Set `NYX_HOME` to move it.

## Performance (measured on an i7-10850H laptop, no GPU)
- Rule-based steps (duplicates, versions, types, undo, search): instant.
- Gemma 3 4B reading a new screenshot: about **60 to 75 seconds** on the CPU. Using 12 threads instead of 6 made no
  difference, because the chip has 6 physical cores.
- On 6 synthetic screenshots (receipt, error, chat, Wi-Fi note, code, report) it classified all 6 correctly.
- Results are cached by content hash, so the cost is paid once per screenshot.
- A GPU, or Apple silicon, is much faster.

## Honest limitations
- Only Linux has been tested. The Windows and macOS idle, power and window code is written but untested.
  If idle time cannot be read (for example on Hyprland), automatic runs happen only in the night window.
- Search is keyword matching over the saved descriptions, not semantic search.
- Version grouping is based on file names. In testing, `dhaka-breath-v4-kaggle.ipynb` was not grouped with
  `dhaka-breath.ipynb`, `-v1`, `-v2` and `-v3` because of the extra `-kaggle` suffix.
- "What changed" summaries work for text files only (txt, md, csv, code), not Word or PDF.
- Screenshots on CPU are slow; a large first backlog may take several nights.

## Tests
`python3 -m unittest discover -s tests -t .` runs 53 tests covering the safety rules, undo after a mid-run failure,
the scheduler, the settings, the web API and the control panel (GUI tests skip themselves when there is no display).
Tests use a temporary config folder and never touch your real settings.

## Challenge entry
Hacktoberfest Open-Source AI Challenge, Week 3: Slow and Steady.
Open-weight model at the core: **Gemma 3 (4B) running locally through Ollama**, used for the partner category
*Best Use of Gemma*. Nyx does not use any other partner technology.
