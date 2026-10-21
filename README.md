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
- **Smart sorting (optional)**: TabPFN, a tabular foundation model running locally, learns from the folders you
  already organized yourself and suggests which of them a new loose file belongs in, with a confidence score.
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
                      loose files (optional) -> TabPFN (local) -> "looks like your files in Work/ (87% sure)"
```
The daemon wakes every few minutes and decides whether to work. It runs only when the machine is on AC power
(unless you allow battery), the CPU is quiet, and you have been idle for the configured time, or inside the night
window, and when enough files are waiting. If you come back mid-run it stops after the current screenshot.
Settings and the watched-folder list are re-read every cycle, so edits apply without a restart.

## How idle checking works, and cheaper ways to trigger it
The daemon wakes every few minutes, but a check that decides "not now" is nearly free: it looks at AC power, CPU
load and idle time first, and does no scanning, planning or model work until those pass (about 3 ms for the idle
probe on the test machine). If the desktop cannot report idle time at all, as on Hyprland, the daemon does not keep
waking up for nothing. It sleeps until the night window opens, and wakes early if you change a setting or the
folder list.

Better than polling is letting the desktop tell Nyx when you go idle. `nyx schedule --os linux` prints this snippet
for `hypridle` (Hyprland) and the same idea works with `swayidle`:
```
listener {
    timeout = 300
    on-timeout = sh -c 'cd ~/path/to/nyx && python3 -m nyx.cli run --if-idle --idle-known'
    on-resume  = sh -c 'cd ~/path/to/nyx && python3 -m nyx.cli interrupt'
}
```
`--idle-known` means "the desktop says I am idle" (AC power and CPU load are still checked), and `nyx interrupt`
asks a running tidy-up to stop after its current file when you come back. This is written and unit-tested but has
not been run through a real `hypridle` session yet. Other options:
- **Night window only:** turn off daytime runs by relying on the night window, so the daemon wakes once a day.
- **Windows:** Task Scheduler has a built-in "start only when the computer is idle" trigger.

## Setup
1. Python 3.10 or newer. The control panel needs Tkinter (Ubuntu/Debian: `sudo apt install python3-tk`;
   the python.org installers for Windows and macOS include it).
2. [Ollama](https://ollama.com) with a vision model: `ollama pull gemma3:4b` (about 3 GB).
   Without a model, rule-based sorting still works and screenshots wait for the model.
3. Optional smart sorting: install TabPFN in a virtual environment and run the one-time setup (see below).
4. No other dependencies. Nyx uses only the Python standard library (`make_playground.py` optionally uses Pillow
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
python3 -m nyx.cli smart status               # smart sorting: status | setup | on | off
```
Per-folder commands take `--root FOLDER`: `plan` (dry run), `apply`, `undo`, `analyze`, `ask "wifi password"`,
`changes` (what changed between document versions), `learn`.

The control panel lets you add or remove watched folders, switch each between preview and automatic, preview what
would move, tidy now, undo the last run, and set the schedule: idle minutes, night window, how many waiting files
trigger a run, check interval, CPU effort, and whether to run on battery.

### Optional: smart sorting with TabPFN
```bash
uv venv --python /usr/bin/python3 .venv          # or: python3 -m venv .venv
uv pip install --python .venv/bin/python torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only build
uv pip install --python .venv/bin/python tabpfn
.venv/bin/python -m nyx.cli smart setup           # run it yourself in a terminal
.venv/bin/python -m nyx.cli smart on
```
`smart setup` opens a Prior Labs login where you accept the model license (the current TabPFN weights are under a
non-commercial license) and downloads about 835 MB of weights once. After that it runs offline and locally.
The background service never starts that login by itself. Run Nyx from the `.venv` interpreter to use it.
It only learns from folders you made yourself (not Nyx's own category folders), acts only when it is at least 70%
confident, and your explicit corrections still win. Without TabPFN, Nyx works exactly as before.

### Try it safely
`python3 make_playground.py` builds a folder of dummy files at `playground/Downloads`.
Everything inside `playground/` can be used without registering it (`python3 -m nyx.cli plan`).

## Where Nyx keeps things
- Per watched folder: a hidden `.nyx/` folder with the undo log, file hash cache and screenshot descriptions.
- Per user: `~/.config/nyx` (Linux), `~/Library/Application Support/Nyx` (macOS) or `%APPDATA%\Nyx` (Windows),
  holding the watched-folder list and schedule settings. Set `NYX_HOME` to move it.

## Performance (measured on an i7-10850H laptop, no GPU)
- Rule-based steps (duplicates, versions, types, undo, search): instant.
- Gemma 3 4B reading a new screenshot on the CPU: a median of **44 seconds** (range 42 to 58) across 24 real
  screenshots, about 18 minutes in total. An earlier benchmark on synthetic images took 60 to 75 seconds. Using 12 threads instead of 6 made no
  difference, because the chip has 6 physical cores.
- On 6 synthetic screenshots (receipt, error, chat, Wi-Fi note, code, report) it classified all 6 correctly.
- Results are cached by content hash, so the cost is paid once per screenshot.
- TabPFN smart sorting: the model loads in about 4 seconds and fitting plus predicting takes under a second
  for small folders, on the same CPU.
- A GPU, or Apple silicon, is much faster.

## Possible future: a remote model (not implemented)
Nyx is local-only today and does not use any remote or cloud model. Because Nyx talks to Ollama over its HTTP API,
running Gemma on a GPU server you control (for example a DigitalOcean GPU Droplet) should work by forwarding the
server's port to localhost over SSH, which keeps Nyx's localhost-only rule intact. That would make screenshot
analysis much faster, but it uploads your screenshots to that server, so it would have to be an explicit opt-in.
This has **not been built or tested** and is not part of the challenge entry. It is noted here as a path that could
support the DigitalOcean category later.

## Honest limitations
- Smart sorting was only checked on a tiny set: 15 labeled files in 3 folders, leave-one-out. It was right 10 times
  (67%) against 40% for always guessing the biggest folder, and every prediction at 71% confidence or higher was correct
  (7 of 7). That shows the confidence score is informative. It is not an accuracy measurement. It leans heavily on
  words in file names, so it helps most with consistently named files, and its confidence varies slightly between runs.
- TabPFN's weights have a non-commercial license and need a free Prior Labs account to download.
- Only Linux has been tested. The Windows and macOS idle, power and window code is written but untested.
  If idle time cannot be read (for example on Hyprland), automatic runs happen only in the night window.
- Search is keyword matching over the saved descriptions, not semantic search.
- Version grouping is based on file names. In testing, `dhaka-breath-v4-kaggle.ipynb` was not grouped with
  `dhaka-breath.ipynb`, `-v1`, `-v2` and `-v3` because of the extra `-kaggle` suffix.
- "What changed" summaries work for text files only (txt, md, csv, code), not Word or PDF.
- Screenshots on CPU are slow; a large first backlog may take several nights.

## Tests
`python3 -m unittest discover -s tests -t .` runs 61 tests covering the safety rules, undo after a mid-run failure,
the scheduler, the settings, smart sorting (with a stand-in model), the web API and the control panel (GUI tests skip themselves when there is no display).
Tests use a temporary config folder and never touch your real settings.

## Challenge entry
Hacktoberfest Open-Source AI Challenge, Week 3: Slow and Steady.
Open-weight models at the core, both running locally:
- **Gemma 3 (4B) through Ollama** reads screenshots: *Best Use of Gemma*.
- **TabPFN** classifies which of your own folders a loose file belongs in, from the historical data of files you
  already filed: *Best Use of TabPFN*.

Nyx does not use any other partner technology.
