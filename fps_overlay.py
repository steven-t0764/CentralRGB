# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Central RGB - in-game FPS overlay.

FPS comes from Intel's open-source PresentMon (MIT). It listens to Windows' own graphics events
(ETW), so nothing is injected into the game - that keeps it clear of anti-cheat systems.
PresentMon is downloaded the first time the overlay is switched on.

* FpsCounter  - runs PresentMon, reads its CSV stream and works out the FPS of the foreground app
* OverlayPanel - the small stats panel (also used for the preview inside the app)
* OverlayWindow - always-on-top, click-through window that holds the panel
"""
from __future__ import annotations

import collections
import ctypes
import json
import os
import re
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path

import rgb_engine as eng

PM_API = "https://api.github.com/repos/GameTechDev/PresentMon/releases/latest"
PM_FALLBACK = "https://github.com/GameTechDev/PresentMon/releases/download/v2.3.1/PresentMon-2.3.1-x64.exe"
PM_ASSET = re.compile(r"^PresentMon-[\d.]+-x64\.exe$", re.I)
SESSION = "CentralRGB"
IGNORED = {"dwm.exe", "explorer.exe", "central rgb.exe", "searchhost.exe", "shellexperiencehost.exe",
           "startmenuexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe"}

CORNERS = ["Top left", "Top right", "Bottom left", "Bottom right"]
SIZES = {"Small": 0.8, "Medium": 1.0, "Large": 1.3}
ITEMS = [("fps", "FPS"), ("low", "1% low"), ("frametime", "Frame time"),
         ("cpu", "CPU temperature and load"), ("gpu", "GPU temperature and load")]
DEFAULTS = {"enabled": False, "corner": "Top left", "size": "Medium",
            "items": {"fps": True, "low": True, "frametime": False, "cpu": True, "gpu": True}}


def overlay_settings(settings) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    saved = settings.data.get("overlay") or {}
    cfg.update({k: v for k, v in saved.items() if k != "items"})
    cfg["items"].update(saved.get("items") or {})
    return cfg


def foreground_pid() -> int:
    if not eng.IS_WIN:
        return 0
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def frame_stats(frames, now, window=1.0, low_window=10.0):
    """frames: iterable of (timestamp, ms_between_presents). Returns (fps, one_percent_low_fps, frame_ms)."""
    recent = [ms for t, ms in frames if now - t <= window and ms > 0]
    if len(recent) < 3:
        return None
    avg_ms = sum(recent) / len(recent)
    longer = sorted(ms for t, ms in frames if now - t <= low_window and ms > 0)
    worst = longer[min(len(longer) - 1, int(len(longer) * 0.99))]
    return 1000.0 / avg_ms, 1000.0 / worst, avg_ms


class FpsCounter:
    """Runs PresentMon and keeps recent frame times per process."""

    def __init__(self, log):
        self.log = log
        self.proc: subprocess.Popen | None = None
        self.lock = threading.Lock()
        self.frames: dict[int, collections.deque] = {}
        self.names: dict[int, str] = {}
        self.status, self.message = "off", ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------- PresentMon binary
    @staticmethod
    def pm_dir() -> Path:
        d = eng.install_dir() / "PresentMon"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def find_exe(self) -> Path | None:
        for base in (eng.app_dir(), eng.app_dir() / "PresentMon", self.pm_dir()):
            if base.is_dir():
                for f in sorted(base.glob("PresentMon*.exe"), reverse=True):
                    return f
        return None

    def download(self) -> Path:
        url, name = PM_FALLBACK, PM_FALLBACK.rsplit("/", 1)[1]
        try:
            req = urllib.request.Request(PM_API, headers={"User-Agent": eng.APP_NAME, "Accept": "application/vnd.github+json"})
            rel = json.loads(urllib.request.urlopen(req, timeout=15).read())
            for a in rel.get("assets", []):
                if PM_ASSET.match(a["name"]):
                    url, name = a["browser_download_url"], a["name"]
                    break
        except Exception as e:
            self.log(f"Couldn't check the latest PresentMon ({e}); using 2.3.1.")
        self.log(f"Downloading PresentMon (FPS counter): {url}")
        dest = self.pm_dir() / name
        tmp = dest.with_suffix(".part")
        req = urllib.request.Request(url, headers={"User-Agent": eng.APP_NAME})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        tmp.replace(dest)
        return dest

    # ---------------- lifecycle
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.status, self.message = "starting", "Starting the FPS counter…"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass
        exe = self.find_exe() if eng.IS_WIN else None
        if exe:   # make sure the Windows trace session is closed too
            eng.run_quiet([str(exe), "--terminate_existing_session", "--session_name", SESSION], timeout=10)
        with self.lock:
            self.frames.clear()
        self.status, self.message = "off", ""

    def _run(self):
        try:
            if not eng.IS_WIN:
                raise RuntimeError("The FPS overlay is Windows-only.")
            exe = self.find_exe() or self.download()
            cmd = [str(exe), "--output_stdout", "--no_console_stats", "--stop_existing_session",
                   "--session_name", SESSION, "--no_track_gpu", "--no_track_input"]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                         errors="replace", bufsize=1, creationflags=eng.NO_WINDOW)
            self.status, self.message = "running", "FPS counter running"
            self.log("FPS counter started (PresentMon).")
            self.read_stream(self.proc.stdout)
            if not self._stop.is_set():
                self.status, self.message = "error", "PresentMon stopped unexpectedly (is another copy running?)"
                self.log(self.message)
        except Exception as e:
            if not self._stop.is_set():
                self.status, self.message = "error", f"FPS counter unavailable: {e}"
                self.log(self.message)

    def read_stream(self, stream):
        """Parse PresentMon's CSV stream. Columns are found by name, so column order doesn't matter."""
        cols = None
        for line in stream:
            if self._stop.is_set():
                break
            parts = line.rstrip("\r\n").split(",")
            if cols is None:
                if "Application" in parts and "ProcessID" in parts:
                    ms_col = next((c for c in ("MsBetweenPresents", "FrameTime", "msBetweenPresents") if c in parts), None)
                    if ms_col:
                        cols = (parts.index("Application"), parts.index("ProcessID"), parts.index(ms_col))
                continue
            try:
                name, pid, ms = parts[cols[0]], int(parts[cols[1]]), float(parts[cols[2]])
            except (ValueError, IndexError):
                continue
            now = time.monotonic()
            with self.lock:
                dq = self.frames.get(pid)
                if dq is None:
                    dq = self.frames[pid] = collections.deque(maxlen=6000)
                    self.names[pid] = name
                dq.append((now, ms))

    # ---------------- reading
    def current(self, pid=None):
        """Stats for the foreground app: {'name', 'fps', 'low', 'ms'} or None when it isn't rendering."""
        pid = foreground_pid() if pid is None else pid
        now = time.monotonic()
        with self.lock:
            for k in [k for k, dq in self.frames.items() if not dq or now - dq[-1][0] > 15]:
                self.frames.pop(k, None)
                self.names.pop(k, None)
            dq = self.frames.get(pid)
            name = self.names.get(pid, "")
            frames = list(dq) if dq else []
        if not frames or pid == os.getpid() or name.lower() in IGNORED:
            return None
        st = frame_stats(frames, now)
        if st is None:
            return None
        return {"name": name, "fps": st[0], "low": st[1], "ms": st[2]}


# ============================================================================ visuals
class OverlayPanel(tk.Canvas):
    """Compact stats panel. `colors` = dict(bg, line, text, muted, grad=(c1, c2, c3), ok, warn, bad)."""

    def __init__(self, master, colors, font, scale=1.0):
        super().__init__(master, bg=colors["bg"], highlightthickness=1, highlightbackground=colors["line"])
        self.c, self.font, self.scale = colors, font, scale
        self.rows = []

    def render(self, cfg, fps=None, metrics=None):
        """fps: dict from FpsCounter.current() (or None); metrics: hardware monitor metrics dict."""
        c, s, m = self.c, self.scale * SIZES.get(cfg.get("size"), 1.0), metrics or {}
        items = cfg.get("items", {})
        rows = []   # (label, value, value_color, big)

        def tcol(t):
            return c["text"] if t is None else c["ok"] if t < 65 else c["warn"] if t < 82 else c["bad"]

        def num(v, unit="", nd=0):
            return "—" if v is None else f"{v:.{nd}f}{unit}"

        if items.get("fps"):
            rows.append(("FPS", num(fps["fps"]) if fps else "—", c["text"], True))
        if items.get("low"):
            rows.append(("1% LOW", num(fps["low"]) if fps else "—", c["muted"] if not fps else c["text"], False))
        if items.get("frametime"):
            rows.append(("FRAME", num(fps["ms"], " ms", 1) if fps else "—", c["text"], False))
        if items.get("cpu"):
            rows.append(("CPU", f"{num(m.get('cpu_temp'), '°')}  {num(m.get('cpu_load'), '%')}", tcol(m.get("cpu_temp")), False))
        if items.get("gpu"):
            rows.append(("GPU", f"{num(m.get('gpu_temp'), '°')}  {num(m.get('gpu_load'), '%')}", tcol(m.get("gpu_temp")), False))
        if not rows:
            rows.append(("FPS", "—", c["text"], True))

        self.delete("all")
        pad, w = int(12 * s), int(168 * s)
        y = int(4 * s) + pad
        n = 24
        for i in range(n):   # gradient strip along the top
            t = i / (n - 1) * (len(c["grad"]) - 1)
            a, b = c["grad"][min(int(t), len(c["grad"]) - 2)], c["grad"][min(int(t), len(c["grad"]) - 2) + 1]
            k = t - min(int(t), len(c["grad"]) - 2)
            col = "#%02x%02x%02x" % tuple(int(int(a[j:j + 2], 16) + (int(b[j:j + 2], 16) - int(a[j:j + 2], 16)) * k) for j in (1, 3, 5))
            self.create_rectangle(i * w / n, 0, (i + 1) * w / n + 1, int(3 * s), width=0, fill=col)
        for label, value, col, big in rows:
            size = int((26 if big else 13) * s)
            h = int(size * 1.45)
            self.create_text(pad, y + h / 2, text=label, anchor="w", fill=c["muted"], font=(self.font, max(7, int(9 * s)), "bold"))
            self.create_text(w - pad, y + h / 2, text=value, anchor="e", fill=col, font=(self.font, size, "bold"))
            y += h + int(2 * s)
        height = y + pad - int(2 * s)
        self.configure(width=w, height=height)
        return w + 2, height + 2


class OverlayWindow(tk.Toplevel):
    """Always-on-top, click-through window. Works over windowed and borderless-fullscreen games."""
    MARGIN = 18

    def __init__(self, root, colors, font):
        super().__init__(root)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=colors["bg"])
        self.panel = OverlayPanel(self, colors, font)
        self.panel.pack()
        try:
            self.attributes("-topmost", True)
            self.attributes("-alpha", 0.88)
        except tk.TclError:
            pass
        self._styled = False
        self.shown = False

    def _click_through(self):
        if self._styled or not eng.IS_WIN:
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
            GWL_EXSTYLE = -20
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            # layered + transparent (clicks pass through) + tool window (no taskbar button) + never takes focus
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
            self._styled = True
        except Exception:
            pass

    def update_overlay(self, cfg, fps, metrics, always_show=False):
        if fps is None and not always_show:
            if self.shown:
                self.withdraw()
                self.shown = False
            return
        w, h = self.panel.render(cfg, fps, metrics)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        corner = cfg.get("corner", "Top left")
        x = self.MARGIN if "left" in corner else sw - w - self.MARGIN
        y = self.MARGIN if "Top" in corner else sh - h - self.MARGIN - 48
        self.geometry(f"{w}x{h}+{x}+{y}")
        if not self.shown:
            self.deiconify()
            self.shown = True
            self.update_idletasks()
            self._click_through()
        try:
            self.attributes("-topmost", True)     # games can push other windows down; keep re-asserting
        except tk.TclError:
            pass
