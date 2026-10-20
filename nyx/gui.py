import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .analyzer import OllamaClient, load_categories
from .config import load_settings, save_settings, threads_for
from .daemon import daemon_running, start_background, stop_background
from .db import DbHashCache, open_db
from .executor import apply_plan, undo_last
from .learn import load_rules
from .planner import build_plan
from .registry import add_folder, load_folders, remove_folder, set_auto_move
from .runner import run_once
from .safety import PROJECT, UnsafePath
from .scanner import scan
from .smart import smart_plan

HOURS = [f"{h:02d}:00" for h in range(24)]
EFFORT = {"full": "Full speed (all physical cores)", "gentle": "Gentle (a quarter of the threads)"}
AUTO, PREVIEW = "Moves automatically", "Preview only"


def _smart_message() -> str:
    from .smart import smart_status

    return smart_status()["message"]


def ago(ts: float) -> str:
    return time.strftime("%a %H:%M", time.localtime(ts))


class NyxPanel:
    def __init__(self, tk_root: tk.Tk):
        self.win = tk_root
        self.win.title("Nyx control panel")
        self.win.geometry("940x660")
        self.win.minsize(780, 540)
        self.results: queue.Queue = queue.Queue()
        self.ui: queue.Queue = queue.Queue()
        self.busy = False
        self.style = ttk.Style()
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self.style.configure("Title.TLabel", font=("TkDefaultFont", 20, "bold"))
        self.style.configure("Muted.TLabel", foreground="#666666")
        self.style.configure("Good.TLabel", foreground="#127a4b")
        self.style.configure("Warn.TLabel", foreground="#9a5b00")
        self.style.configure("Accent.TButton", font=("TkDefaultFont", 10, "bold"))
        self._header()
        self.tabs = ttk.Notebook(self.win)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        self._folders_tab()
        self._schedule_tab()
        self._activity_tab()
        self.status = tk.StringVar(value="Ready.")
        bar = ttk.Frame(self.win)
        bar.pack(fill="x", padx=12, pady=8)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=140)
        ttk.Label(bar, textvariable=self.status, style="Muted.TLabel").pack(side="left")
        self.progress.pack(side="right")
        self.load_form()
        self.refresh_folders()
        self.refresh_activity()
        self.poll()
        self.tick()

    # ---- dialogs (overridable in tests)
    def confirm(self, message: str) -> bool:
        return messagebox.askyesno("Nyx", message, parent=self.win)

    def warn(self, message: str) -> None:
        messagebox.showwarning("Nyx", message, parent=self.win)

    def info(self, message: str) -> None:
        messagebox.showinfo("Nyx", message, parent=self.win)

    # ---- layout
    def _header(self) -> None:
        head = ttk.Frame(self.win)
        head.pack(fill="x", padx=12, pady=(12, 0))
        left = ttk.Frame(head)
        left.pack(side="left")
        ttk.Label(left, text="☾ Nyx", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="It works while you sleep. Your files never leave this machine.", style="Muted.TLabel").pack(anchor="w")
        right = ttk.Frame(head)
        right.pack(side="right")
        self.service_label = ttk.Label(right, text="Background service: ...")
        self.service_label.grid(row=0, column=0, padx=8)
        self.service_btn = ttk.Button(right, text="Start service", command=self.toggle_service)
        self.service_btn.grid(row=0, column=1)
        self.model_label = ttk.Label(right, text="Model: checking...", style="Muted.TLabel")
        self.model_label.grid(row=1, column=0, columnspan=2, sticky="e", pady=(4, 0))

    def _folders_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(tab, text="Watched folders")
        ttk.Label(tab, text="Nyx only touches folders you add here. It never deletes anything, and every run can be undone.",
                  style="Muted.TLabel", wraplength=820).pack(anchor="w")
        cols = ("folder", "mode", "waiting")
        self.tree = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse", height=9)
        for c, text, w in (("folder", "Folder", 460), ("mode", "Mode", 170), ("waiting", "Files to tidy", 110)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor="w" if c == "folder" else "center")
        self.tree.pack(fill="both", expand=True, pady=10)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.update_buttons())
        row1 = ttk.Frame(tab)
        row1.pack(fill="x")
        ttk.Button(row1, text="Add folder...", style="Accent.TButton", command=self.on_add).pack(side="left", padx=(0, 6))
        self.btn_remove = ttk.Button(row1, text="Remove", command=self.on_remove)
        self.btn_remove.pack(side="left", padx=6)
        self.btn_mode = ttk.Button(row1, text="Switch to automatic", command=self.on_toggle_mode)
        self.btn_mode.pack(side="left", padx=6)
        row2 = ttk.Frame(tab)
        row2.pack(fill="x", pady=(8, 0))
        self.btn_preview = ttk.Button(row2, text="Preview what would move", command=self.on_preview)
        self.btn_preview.pack(side="left", padx=(0, 6))
        self.btn_tidy = ttk.Button(row2, text="Tidy now", command=self.on_tidy)
        self.btn_tidy.pack(side="left", padx=6)
        self.btn_undo = ttk.Button(row2, text="Undo last run", command=self.on_undo)
        self.btn_undo.pack(side="left", padx=6)
        self.btn_details = ttk.Button(row2, text="Open details (search, thumbnails)", command=self.on_details)
        self.btn_details.pack(side="left", padx=6)
        self.update_buttons()

    def _schedule_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(tab, text="Schedule")
        self.v_enabled = tk.BooleanVar()
        self.v_smart = tk.BooleanVar()
        self.v_night = tk.BooleanVar()
        self.v_battery = tk.BooleanVar()
        self.v_idle, self.v_new, self.v_interval, self.v_age = (tk.StringVar() for _ in range(4))
        self.v_start, self.v_end, self.v_effort = (tk.StringVar() for _ in range(3))
        rows = [
            ("Automatic tidying", ttk.Checkbutton(tab, variable=self.v_enabled), "Master switch. Off pauses the background service."),
            ("Start when idle for (minutes)", ttk.Spinbox(tab, from_=1, to=240, textvariable=self.v_idle, width=8),
             "Needs a system that reports idle time. Otherwise only the night window applies."),
            ("Use a night window", ttk.Checkbutton(tab, variable=self.v_night), "Allowed to run in these hours even if idle time cannot be detected."),
            ("Night starts at", ttk.Combobox(tab, values=HOURS, textvariable=self.v_start, width=8, state="readonly"), ""),
            ("Night ends at", ttk.Combobox(tab, values=HOURS, textvariable=self.v_end, width=8, state="readonly"), ""),
            ("Also run when this many files wait", ttk.Spinbox(tab, from_=1, to=1000, textvariable=self.v_new, width=8), "Only while you are idle."),
            ("Check every (minutes)", ttk.Spinbox(tab, from_=1, to=120, textvariable=self.v_interval, width=8), ""),
            ("Leave files alone until older than (hours)", ttk.Spinbox(tab, from_=0, to=720, textvariable=self.v_age, width=8),
             "Protects files you are still downloading or using."),
            ("Effort", ttk.Combobox(tab, values=list(EFFORT.values()), textvariable=self.v_effort, width=34, state="readonly"), ""),
            ("Run on battery power", ttk.Checkbutton(tab, variable=self.v_battery), ""),
            ("Smart sorting (TabPFN)", ttk.Checkbutton(tab, variable=self.v_smart),
             "Learns from folders you organized yourself. " + _smart_message()),
        ]
        for i, (label, widget, hint) in enumerate(rows):
            ttk.Label(tab, text=label).grid(row=i * 2, column=0, sticky="w", pady=(8, 0), padx=(0, 20))
            widget.grid(row=i * 2, column=1, sticky="w", pady=(8, 0))
            if hint:
                ttk.Label(tab, text=hint, style="Muted.TLabel").grid(row=i * 2 + 1, column=0, columnspan=2, sticky="w")
        foot = ttk.Frame(tab)
        foot.grid(row=len(rows) * 2, column=0, columnspan=2, sticky="w", pady=16)
        ttk.Button(foot, text="Save settings", style="Accent.TButton", command=self.on_save).pack(side="left")
        self.save_msg = ttk.Label(foot, text="Changes apply on the next check. No restart needed.", style="Muted.TLabel")
        self.save_msg.pack(side="left", padx=12)

    def _activity_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(tab, text="Activity")
        cols = ("when", "folder", "trigger", "result")
        self.act = ttk.Treeview(tab, columns=cols, show="headings", height=14)
        for c, text, w in (("when", "When", 110), ("folder", "Folder", 160), ("trigger", "Why it ran", 160), ("result", "Result", 440)):
            self.act.heading(c, text=text)
            self.act.column(c, width=w, anchor="w")
        self.act.pack(fill="both", expand=True)
        ttk.Button(tab, text="Refresh", command=self.refresh_activity).pack(anchor="w", pady=8)

    # ---- settings form
    def load_form(self) -> None:
        s = load_settings()
        self.v_enabled.set(s.enabled)
        self.v_night.set(s.night_enabled)
        self.v_battery.set(s.run_on_battery)
        self.v_smart.set(s.smart_sorting)
        self.v_idle.set(f"{s.idle_minutes:g}")
        self.v_new.set(str(s.min_new))
        self.v_interval.set(f"{s.interval_minutes:g}")
        self.v_age.set(f"{s.min_age_hours:g}")
        self.v_start.set(HOURS[s.night_start])
        self.v_end.set(HOURS[s.night_end])
        self.v_effort.set(EFFORT[s.effort])

    def collect_form(self) -> dict:
        return {
            "enabled": self.v_enabled.get(), "night_enabled": self.v_night.get(), "run_on_battery": self.v_battery.get(),
            "idle_minutes": float(self.v_idle.get()), "min_new": int(float(self.v_new.get())),
            "interval_minutes": float(self.v_interval.get()), "min_age_hours": float(self.v_age.get()),
            "smart_sorting": self.v_smart.get(), "night_start": int(self.v_start.get()[:2]), "night_end": int(self.v_end.get()[:2]),
            "effort": "gentle" if self.v_effort.get().startswith("Gentle") else "full",
        }

    def on_save(self) -> None:
        try:
            save_settings(self.collect_form())
        except (ValueError, OSError) as e:
            self.warn(f"Could not save: please check the numbers.\n{e}")
            return
        self.load_form()
        self.save_msg.config(text="Saved. It takes effect on the next check.")

    # ---- background work
    def work(self, label: str, fn, done) -> None:
        if self.busy:
            self.info("Nyx is already working on something. Please wait for it to finish.")
            return
        self.busy = True
        self.status.set(label)
        self.progress.start(12)
        self.update_buttons()

        def target():
            try:
                self.results.put((done, fn(), None))
            except Exception as e:
                self.results.put((done, None, e))

        threading.Thread(target=target, daemon=True).start()

    def poll(self) -> None:
        try:
            while True:
                self.ui.get_nowait()()
        except queue.Empty:
            pass
        try:
            while True:
                done, value, err = self.results.get_nowait()
                self.busy = False
                self.progress.stop()
                self.update_buttons()
                if err:
                    self.status.set(f"Error: {err}")
                    self.warn(str(err))
                else:
                    done(value)
        except queue.Empty:
            pass
        self.win.after(150, self.poll)

    def update_service(self) -> None:
        running = daemon_running()
        self.service_label.config(text="Background service: " + ("running" if running else "not running"),
                                  style="Good.TLabel" if running else "Warn.TLabel")
        self.service_btn.config(text="Stop service" if running else "Start service")

    def tick(self) -> None:
        self.update_service()
        self.win.after(3000, self.tick)
        if time.time() - getattr(self, "_model_checked", 0) > 30:
            self._model_checked = time.time()
            threading.Thread(target=self._check_model, daemon=True).start()

    def _check_model(self) -> None:
        client = OllamaClient()
        ok = client.available()
        self.ui.put(lambda: self.model_label.config(
            text=f"Model {client.model}: " + ("ready (local)" if ok else "not running (screenshots will wait)"),
            style="Good.TLabel" if ok else "Warn.TLabel"))

    # ---- folders
    def selected(self) -> Path | None:
        sel = self.tree.selection()
        return Path(sel[0]) if sel else None

    def update_buttons(self) -> None:
        sel = self.selected()
        state = "normal" if sel and not self.busy else "disabled"
        for b in (self.btn_remove, self.btn_mode, self.btn_preview, self.btn_tidy, self.btn_undo, self.btn_details):
            b.config(state=state)
        if sel:
            auto = any(f.path == sel and f.auto_move for f in load_folders())
            self.btn_mode.config(text="Switch to preview only" if auto else "Switch to automatic")

    def refresh_folders(self) -> None:
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        folders = load_folders()
        for f in folders:
            self.tree.insert("", "end", iid=str(f.path), values=(str(f.path), AUTO if f.auto_move else PREVIEW, "..."))
        if keep and self.tree.exists(keep[0]):
            self.tree.selection_set(keep[0])
        self.update_buttons()
        if folders:
            threading.Thread(target=self._count_waiting, args=(folders,), daemon=True).start()

    def _count_waiting(self, folders) -> None:
        s = load_settings()
        for f in folders:
            try:
                db = open_db(f.path)
                try:
                    files, _ = scan(f.path, s.min_age_hours, DbHashCache(db))
                    n = len(smart_plan(f.path, files, db))
                finally:
                    db.close()
                text = str(n)
            except Exception:
                text = "?"
            self.ui.put(lambda p=f.path, t=text: self.tree.exists(str(p)) and self.tree.set(str(p), "waiting", t))

    def add_folder_path(self, path: Path) -> bool:
        try:
            f = add_folder(path)
        except UnsafePath as e:
            self.warn(str(e))
            return False
        self.refresh_folders()
        self.status.set(f"Now watching {f.path.name} in preview mode. Nothing moves until you switch it to automatic.")
        return True

    def on_add(self) -> None:
        chosen = filedialog.askdirectory(parent=self.win, title="Choose a folder for Nyx to watch", mustexist=True)
        if chosen:
            self.add_folder_path(Path(chosen))

    def on_remove(self) -> None:
        sel = self.selected()
        if sel and self.confirm(f"Stop watching {sel.name}?\nYour files stay exactly where they are."):
            remove_folder(sel)
            self.refresh_folders()

    def on_toggle_mode(self) -> None:
        sel = self.selected()
        if not sel:
            return
        auto = any(f.path == sel and f.auto_move for f in load_folders())
        if not auto and not self.confirm(
                f"Let Nyx move files in {sel.name} automatically while you are away?\n"
                "Nothing is deleted, and every run can be undone."):
            return
        set_auto_move(sel, not auto)
        self.refresh_folders()

    def _plan(self, path: Path):
        s = load_settings()
        db = open_db(path)
        try:
            files, skipped = scan(path, s.min_age_hours, DbHashCache(db))
            moves = smart_plan(path, files, db)
            return [(m.src.name, str(m.dst.relative_to(path).parent), m.reason) for m in moves], len(skipped)
        finally:
            db.close()

    def on_preview(self) -> None:
        sel = self.selected()
        if sel:
            self.work(f"Looking at {sel.name}...", lambda: self._plan(sel), lambda r: self.show_preview(sel, *r))

    def show_preview(self, folder: Path, rows, skipped: int) -> None:
        self.status.set(f"{len(rows)} file(s) would move in {folder.name}; {skipped} recent file(s) left alone.")
        top = tk.Toplevel(self.win)
        top.title(f"Preview: {folder.name}")
        top.geometry("820x460")
        tree = ttk.Treeview(top, columns=("file", "to", "why"), show="headings")
        for c, text, w in (("file", "File", 280), ("to", "Goes to", 170), ("why", "Why", 330)):
            tree.heading(c, text=text)
            tree.column(c, width=w, anchor="w")
        for r in rows:
            tree.insert("", "end", values=r)
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Label(top, text="This is only a preview. Nothing has been moved." if rows else "Nothing to tidy right now.",
                  style="Muted.TLabel").pack(pady=(0, 10))
        self.preview_window = top

    def on_tidy(self) -> None:
        sel = self.selected()
        if not sel or not self.confirm(
                f"Tidy {sel.name} now?\nNyx will look at screenshots (about a minute each on a CPU) and move files into folders.\n"
                "Nothing is deleted and you can undo the whole run."):
            return
        s = load_settings()

        def job():
            return run_once(sel, min_age_hours=s.min_age_hours, min_new=s.min_new, window=s.window(),
                            idle_minutes=s.idle_minutes, threads=threads_for(s.effort), force=True)

        self.work(f"Tidying {sel.name}...", job, lambda r: self.finished(sel, r))

    def finished(self, folder: Path, r: dict) -> None:
        self.status.set(f"{folder.name}: {r['note']}")
        self.refresh_folders()
        self.refresh_activity()

    def on_undo(self) -> None:
        sel = self.selected()
        if sel and self.confirm(f"Put back everything moved by the last run in {sel.name}?"):
            self.work("Undoing...", lambda: undo_last(sel), lambda n: (self.status.set(f"Restored {n} file(s) in {sel.name}."), self.refresh_folders(), self.refresh_activity()))

    def on_details(self) -> None:
        sel = self.selected()
        if sel:
            subprocess.Popen([sys.executable, "-m", "nyx.cli", "app", "--root", str(sel)], cwd=PROJECT,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---- service
    def toggle_service(self) -> None:
        if daemon_running():
            if not self.confirm("Stop the background service? Automatic tidying will pause until you start it again."):
                return
            stop_background()
        else:
            if not load_folders():
                self.warn("Add a folder first. The service has nothing to watch yet.")
                return
            start_background()
        self.win.after(700, self.update_service)

    # ---- activity
    def refresh_activity(self) -> None:
        self.act.delete(*self.act.get_children())
        rows = []
        for f in load_folders():
            try:
                db = open_db(f.path)
                try:
                    for ts, status, trig, note in db.execute("SELECT ts, status, trigger, note FROM runs ORDER BY id DESC LIMIT 20"):
                        rows.append((ts, f.path.name, trig or "-", f"{status}: {note}"))
                finally:
                    db.close()
            except Exception:
                continue
        for ts, name, trig, result in sorted(rows, reverse=True)[:60]:
            self.act.insert("", "end", values=(ago(ts), name, trig, result))


def run_gui() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print(f"Cannot open a window: {e}", file=sys.stderr)
        return 1
    NyxPanel(root)
    root.mainloop()
    return 0
