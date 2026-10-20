# Sloth: a local agent that tidies your Downloads and screenshots

Hacktoberfest 2026 Open-Source AI Challenge, Week 3 ("Slow and Steady").
Deadline: **October 25, 11:59 PM PDT**.

## One-line pitch
An agent that lives on your computer, understands your files (not just their names), and sorts the mess while you sleep. Your files never leave your machine.

## Hard rules for any agent working on this repo
1. **Local only.** All file contents are processed by a local open-weight model (Gemma via Ollama). Never send file contents to a hosted API.
2. **Never delete.** Old versions and duplicates move to `_archive/`. Every move is logged so it can be undone.
3. **Dry-run by default.** The agent only reports what it would do until the user passes `--apply`.
4. **Skip recent files.** Do not touch files modified in the last 24 hours (configurable).
5. **Rules before models.** Use hashes, filename patterns and extensions first. Call the model only when rules cannot decide.
6. **Cache by hash.** Never analyze the same file content twice.
7. **Only tiny, non-private data may go online** (for example, a "latest version of VS Code" lookup). No filenames or contents in requests.
8. Default to no comments in code, keep modules small, keep dependencies few.

## Stack
- Python 3.11+
- Ollama running `gemma3:4b` (text and vision). Fallback: `moondream` for weak machines.
- SQLite for the file index, decisions log and undo history
- `watchdog` for folder watching, `rapidfuzz` for name similarity
- Optional: TabPFN (learn from user corrections), Temporal (durable overnight runs), SerpApi (latest-version lookup)

## Features
### MVP (must ship)
- **Scan and index:** hash, size, type, timestamps for every file in watched folders.
- **Exact duplicates:** same hash, keep one, archive the rest.
- **Version grouping:** detect `v1/v2/final/(1)/-copy` names and software versions like `setup-1.4.2.exe`; keep the newest, archive the rest.
- **Type sorting:** installers, archives, images, docs, etc., into folders.
- **Screenshot understanding:** Gemma classifies each screenshot (receipt, error, chat, document, meme, other) and writes a one-line description.
- **Dry-run report, apply, and undo** commands.
- **Morning report:** a short summary of what was done and space freed.

### Wow features (in this order, cut from the bottom)
1. **Ask your files:** natural-language search over stored descriptions ("the screenshot with the wifi password").
2. **What changed?:** a 3-line summary of differences between two versions before archiving the older one.
3. **Learn from corrections:** if the user moves a file the agent sorted, store it as a rule; after a few corrections stop asking. TabPFN is a candidate predictor here (verify its fit on the challenge hub first).
4. **Outdated installer check:** compare installer versions with the latest release (SerpApi).
5. **Sensitive file alert:** flag passports, statements, IDs and offer to move them to a private folder.
6. **Screenshot actions:** receipts into an expense CSV, error text extracted for search.
7. **Calm voice morning report** (ElevenLabs), optional.

## Architecture
```
watcher / nightly schedule
   -> scanner (hash, metadata)  -> SQLite index
   -> rule engine (duplicates, versions, types)
   -> analyzer (Gemma: only for unknowns, cached by hash)
   -> planner (builds a list of moves)
   -> dry-run report  |  executor (--apply) -> move log (undo)
   -> reporter (morning summary)
```
Suggested layout:
```
sloth/
  cli.py          # scan, plan, apply, undo, ask, report
  scanner.py      # walk folders, hash, index
  rules.py        # duplicates, version grouping, type sorting
  analyzer.py     # Ollama/Gemma calls, hash cache
  planner.py      # turns decisions into moves
  executor.py     # performs moves, writes undo log
  learn.py        # corrections to rules (TabPFN optional)
  search.py       # ask-your-files
  report.py       # morning summary
  db.py           # SQLite schema
tests/
```

## Partner categories (be honest in the post)
| Category | Role in the project | Confidence |
|---|---|---|
| Gemma (featured) | Reads screenshots and documents, writes summaries | Core |
| TabPFN (featured) | Predicts destination folders from few examples | Verify fit before claiming |
| Temporal | Durable overnight runs and retries | Optional |
| SerpApi | Latest-version lookup for installers | Optional |
| Sentry Agent Tracing | "Why did you move this?" decision traces | Optional |

Only enter categories that are genuinely used. One win per challenge, so depth beats breadth.

## 5-day plan
| Day | Goal | Done when |
|---|---|---|
| Oct 20-21 | Project setup, scanner, SQLite, duplicates, version grouping, dry-run, apply, undo | Messy test folder is sorted and fully undoable |
| Oct 22 | Ollama + Gemma, screenshot classification, hash cache, Ask your files | Searching "receipt from March" returns the right file |
| Oct 23 | What changed? summaries, learn-from-corrections (TabPFN), optional SerpApi/Temporal | Agent stops asking after 3 corrections |
| Oct 24 | Morning report, polish, record demo (before/after of a chaotic folder) | Demo video under 2 minutes |
| Oct 25 | Write DEV post using the submission template, publish before 11:59 PM PDT | Post live |

## Judging checklist (writing counts most)
- Explain what it does, who it is for, and what effort it saves (give numbers: files sorted, GB freed, minutes saved).
- Explain why open matters: private files, no per-file cost, works offline.
- Show a demo and a before/after.
- Optionally save the agent session with DevRelay and embed it.
- Use the official submission template and tags (`devchallenge`, `hf26challenge`, `hacktoberfest`).

## Test data
Create a fake Downloads folder with: versioned documents, three installer versions, exact duplicates, 30+ varied screenshots. Never test on real personal files.
