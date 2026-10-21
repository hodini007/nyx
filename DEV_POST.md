---
title: Nyx: a night-goddess agent that tidies your Downloads while you sleep (local Gemma + TabPFN)
published: false
tags: devchallenge, hf26challenge, hacktoberfest, productivity
---

*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19)*

## What I Built

Every Downloads folder rots the same way. `report_v2_final_FINAL.docx`. Three installers of the same app. `photo (1).jpg`. And a Screenshots folder with 176 images I swore I would deal with later.

I will never sort those by hand, and I refuse to upload screenshots, receipts and documents to a cloud service so something else can. So I built **Nyx**, named after the Greek goddess of night, because that is when it works.

Nyx is a local agent that tidies folders you choose, while you are away:

- **Archives exact duplicates** and **older versions** of the same file (`setup-1.4.2` vs `setup-1.5.0`), keeping the newest.
- **Sorts everything else by type** into Documents, Code, Installers, Archives and so on.
- **Reads your screenshots with a local vision model** (Gemma 3) and files each one by what it shows: error, code, document, chat, receipt.
- **Learns your own filing habits** with TabPFN: it studies the folders you already organized and suggests which one a new loose file belongs in, with a confidence score.
- **Works only when you are not**: a small background service runs when the machine is idle or in a night window, and stops the moment you come back.

You add a folder, preview what would happen, flip it to automatic, and go to bed. In the morning it is sorted, and one button undoes everything.

It is for anyone whose Downloads folder is a landfill and who would rather not hand their files to someone else's server to fix it.

## Demo

[TODO: embed your video demo here, 3 to 4 minutes]

[TODO: add 2 or 3 screenshots: the control panel's folder list, the preview with reasons, the folder before and after]

What the demo shows, on 42 real files I copied from my own Downloads and Screenshots folders into a sandbox:

1. A flat folder of 42 loose files.
2. In the control panel I add the folder. It starts in **preview only** mode and lists exactly what would move, with a reason for each file ("older version of ...", screenshot category).
3. I switch it to automatic and press **Tidy now**. Old versions go to `_archive/`, files go to type folders, and the 24 screenshots land in subfolders by category.
4. **Undo last run** puts all 42 files back.
5. I add a small test folder I had organized by hand into three project folders, tick **Smart sorting**, and TabPFN places a new notebook into the right project folder: "looks like your files in DhakaBreath/ (73% sure, TabPFN)".

The slow part is the screenshots. Gemma 3 4B reading all 24 on a laptop CPU with no GPU took about **18 minutes** (median 44 seconds each). That is exactly why Nyx runs while you sleep, and each screenshot is only ever analyzed once because results are cached by file hash. On my screenshots, Gemma labeled 15 as documents, 5 as code, 2 as errors and 2 as other.

## Code

[TODO: replace with your repository, for example {% github your-username/nyx %}]

```bash
python3 -m nyx.cli gui                        # control panel
python3 -m nyx.cli folders add ~/Downloads    # starts in preview-only mode
python3 -m nyx.cli daemon                     # background service
python3 -m nyx.cli smart status               # optional TabPFN smart sorting
```

It is about 2,500 lines of Python with **no dependencies beyond the standard library** (TabPFN is optional), 61 tests, and a Tkinter control panel.

## How I Built It

**Models are expensive, so use them last.** Most of tidying needs no AI. Duplicates are found by comparing file hashes, versions by filename patterns, types by extension. Only screenshots, which have no useful name, go to the vision model. Hashing is lazy and cached in SQLite, so a real Downloads folder with multi-gigabyte ISOs is not re-read every few minutes.

**Safety before cleverness.** This tool moves real files, so the rules came first:
- Nothing is ever deleted. Old versions go to `_archive/` inside the same folder.
- Nyx only works in folders you add. It refuses your whole home folder, drive roots, system folders, overlapping folders and its own program folder.
- New folders start **preview only**. Partial downloads and files newer than 24 hours are left alone.
- Every move is logged as it happens, so even a crash halfway through leaves a run that can be undone. There is a test that makes a move fail midway and checks undo still restores the rest.

**An agent that knows when to work.** A daemon wakes every few minutes and runs only when the machine is on AC power, the CPU is quiet, and you have been idle, or inside a night window you set. If you come back mid-run, it stops after the current screenshot. Idle detection is written for Windows, macOS, X11 and GNOME. On my own machine (Hyprland on Wayland) the desktop cannot report idle time, so Nyx honestly falls back to the night window instead of guessing.

**Gemma 3 through Ollama** reads each screenshot and returns a category and a one-line description, which also powers a simple search over what the screenshots show. The client refuses any address that is not localhost.

**TabPFN for "where does this belong?"** TabPFN is a tabular foundation model that learns from very few examples, which is exactly the situation here: you have a handful of files in a few folders. I turn each file into numbers (extension, size, age, words in its name), train on the folders you made yourself (never Nyx's own category folders), and act only above a confidence threshold. Your explicit corrections still win. It runs locally after a one-time license acceptance.

**Built with an AI pair programmer.** I built Nyx with Claude Code as my coding agent, working in small steps with tests after each one. [TODO: add your DevRelay agent session here if you want to.]

**What went wrong, honestly**
- My first speed measurement was wrong. I measured 3.6 seconds per screenshot, then noticed in Ollama's own log that it was re-reading images it had already seen. The real number is around 45 seconds. I corrected it everywhere.
- 12 threads were no faster than 6, because the chip has 6 physical cores.
- TabPFN was only checked on a tiny set: 15 labeled files in 3 folders. Leave-one-out it was right 10 times (67%) against 40% for always guessing the biggest folder, and every prediction at 71% confidence or higher was correct (7 of 7). That says the confidence score is meaningful. It does not say TabPFN is a great file sorter, and it leans heavily on file names.
- Only Linux is tested. The Windows and macOS code is written but untested.

## Why Does Open Innovation Matter?

Look at the kind of files Nyx reads: receipts, chats, assignments, error dialogs. This is one of the most private piles of files on a computer. With an open-weight model running on my own CPU, **none of it leaves the machine**: the model client refuses any host except localhost, and inference happens entirely on my own hardware.

It also changes the economics. A tool that runs forever in the background and looks at every new screenshot would be a recurring bill with a cloud API. A local model costs nothing per file, and a cache means each screenshot is read once.

And it makes the trade-off honest instead of hidden. Open and local means slow on a laptop CPU, about 45 seconds per screenshot. A closed API would have been faster and easier. For a job that happens while I sleep, I will take slow and private over fast and uploaded every time.

## My Agent Session

[TODO: optional. Embed your DevRelay session, or delete this section.]

## The Lazy Payoff

What I stopped doing: opening Downloads, squinting at `report_v3_final`, wondering which installer is newest, and scrolling a wall of screenshots looking for "that one error".

What Nyx did on my demo folder: 42 loose files sorted, 3 old versions archived instead of cluttering the folder, 24 screenshots read and filed by what they show, all undoable in one click. [TODO: add your own honest estimate of how long that would have taken by hand.]

## Prize Categories

- **Best Use of Gemma**: Gemma 3 (4B) runs locally through Ollama and reads every screenshot. It is the reason Nyx can sort images by content, and the reason the files never leave the machine.
- **Best Use of TabPFN**: TabPFN classifies which of your own folders a loose file belongs in, learning from the historical data of files you already filed, running locally. I only used TabPFN where its few-example learning fits, and I report its limits above.
