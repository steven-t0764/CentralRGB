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
* OverlayPanel - the counter: a bare number in Orbitron, no box (also used for the preview inside the app)
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

# Windows API with proper 64-bit types. Without argtypes, ctypes passes plain ints as 32-bit values, so
# HWND_TOPMOST (-1) arrived as 0xFFFFFFFF, Windows rejected the call, and the overlay stayed *behind* the
# game whenever the game was in front (it only showed after tabbing out).
HWND_TOPMOST, HWND_NOTOPMOST, HWND_TOP = -1, -2, 0
_user32 = None


def _u32():
    global _user32
    if _user32 is None and eng.IS_WIN:
        from ctypes import wintypes as w
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.SetWindowPos.argtypes = [w.HWND, w.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]
        u.SetWindowPos.restype = w.BOOL
        u.GetWindow.argtypes = [w.HWND, w.UINT]
        u.GetWindow.restype = w.HWND
        u.GetParent.argtypes = [w.HWND]
        u.GetParent.restype = w.HWND
        u.GetForegroundWindow.restype = w.HWND
        u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        u.IsWindow.argtypes = [w.HWND]
        u.IsIconic.argtypes = [w.HWND]
        u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        u.ClientToScreen.argtypes = [w.HWND, ctypes.POINTER(w.POINT)]
        u.GetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        _user32 = u
    return _user32

PM_API = "https://api.github.com/repos/GameTechDev/PresentMon/releases/latest"
PM_FALLBACK = "https://github.com/GameTechDev/PresentMon/releases/download/v2.3.1/PresentMon-2.3.1-x64.exe"
PM_ASSET = re.compile(r"^PresentMon-[\d.]+-x64\.exe$", re.I)
SESSION = "CentralRGB"
IGNORED = {"dwm.exe", "explorer.exe", "central rgb.exe", "searchhost.exe", "shellexperiencehost.exe",
           "startmenuexperiencehost.exe", "textinputhost.exe", "applicationframehost.exe"}

CORNERS = ["Top left", "Top right", "Bottom left", "Bottom right"]
SIZES = {"Small": 0.8, "Medium": 1.0, "Large": 1.3}

# The counter: a bare number in Orbitron (SIL Open Font License, bundled unmodified in fonts/), coloured by
# how smooth the game is running. No box: a thin dark outline keeps it readable on bright and dark scenes.
COUNTER_FONT = "Orbitron"
FPS_GOOD, FPS_OK = 60, 30                                    # green at 60+, amber 30-59, red below 30
FPS_COLORS = {"good": "#6ee68c", "ok": "#ffbe46", "low": "#ff5555"}
OUTLINE = "#0b0b0d"                                          # must differ from the window's see-through colour
_font_loaded = None


def load_counter_font() -> str | None:
    """Make the bundled Orbitron available to this app only (nothing is installed). Returns its family name,
    or None to fall back to the app font."""
    global _font_loaded
    if _font_loaded is not None:
        return _font_loaded or None
    _font_loaded = ""
    try:
        import sys
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        path = base / "fonts" / "Orbitron-Bold.ttf"
        if not path.exists():
            return None
        if eng.IS_WIN:
            FR_PRIVATE = 0x10
            if ctypes.windll.gdi32.AddFontResourceExW(str(path), FR_PRIVATE, 0) <= 0:
                return None
        _font_loaded = COUNTER_FONT
    except Exception:
        return None
    return _font_loaded


def fps_color(v) -> str:
    return FPS_COLORS["good"] if v >= FPS_GOOD else FPS_COLORS["ok"] if v >= FPS_OK else FPS_COLORS["low"]
ITEMS = [("fps", "Frame rate (the number)"), ("low", "1% low"), ("frametime", "Frame time"),
         ("cpu", "CPU temperature and load"), ("gpu", "GPU temperature and load")]
DEFAULTS = {"enabled": False, "corner": "Top left", "size": "Medium",
            "items": {"fps": True, "low": False, "frametime": False, "cpu": False, "gpu": False}, "style": 2}


def overlay_settings(settings) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    saved = settings.data.get("overlay") or {}
    cfg.update({k: v for k, v in saved.items() if k != "items"})
    if saved.get("style") == 2:          # older settings switch to the new number-only default once
        cfg["items"].update(saved.get("items") or {})
    cfg["style"] = 2
    return cfg


def foreground_pid() -> int:
    if not eng.IS_WIN:
        return 0
    return foreground_window()[1]


def foreground_window() -> tuple[int, int]:
    """(window handle, process id) of the window in front."""
    if not eng.IS_WIN:
        return 0, 0
    try:
        from ctypes import wintypes as w
        u = _u32()
        hwnd = u.GetForegroundWindow()
        pid = w.DWORD(0)
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(hwnd or 0), int(pid.value)
    except Exception:
        return 0, 0


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def game_window_state(hwnd: int):
    """Screen rectangle (x, y, w, h) of the game's drawing area, 'minimized', or None if the window is gone."""
    if not eng.IS_WIN or not hwnd:
        return None
    try:
        from ctypes import wintypes as wt
        u = _u32()
        if not u.IsWindow(hwnd):
            return None
        if u.IsIconic(hwnd):
            return "minimized"
        r = wt.RECT()
        u.GetClientRect(hwnd, ctypes.byref(r))
        pt = wt.POINT(0, 0)
        u.ClientToScreen(hwnd, ctypes.byref(pt))
        w, h = r.right - r.left, r.bottom - r.top
        if w < 200 or h < 150:
            return None
        return pt.x, pt.y, w, h
    except Exception:
        return None


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
        self.modes: dict[int, str] = {}
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
                        cols = (parts.index("Application"), parts.index("ProcessID"), parts.index(ms_col),
                                parts.index("PresentMode") if "PresentMode" in parts else None)
                continue
            try:
                name, pid, ms = parts[cols[0]], int(parts[cols[1]]), float(parts[cols[2]])
                if cols[3] is not None:
                    self.modes[pid] = parts[cols[3]]
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
    def mode(self, pid) -> str:
        """How the game shows its frames, as PresentMon reports it (e.g. 'Hardware: Legacy Flip')."""
        return self.modes.get(pid, "")

    @staticmethod
    def exclusive(mode: str) -> bool:
        """Exclusive fullscreen: the game owns the screen and no normal window (like this overlay) can show
        on top of it. 'Hardware: Legacy Flip' / 'Legacy Copy' are exclusive; flip/composed modes are not."""
        return "Legacy" in (mode or "")

    def alive(self, pid) -> bool:
        """True while this process has drawn a frame in the last 15 seconds."""
        now = time.monotonic()
        with self.lock:
            dq = self.frames.get(pid)
            return bool(dq) and now - dq[-1][0] <= 15

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
    """The counter: the frame rate as a bare number (no box), optional extras in small text beside it.
    `colors` = dict(bg, line, text, muted, ok, warn, bad); `outer` is the colour behind the text (see-through on
    Windows)."""

    def __init__(self, master, colors, font, scale=1.0, outer=None):
        self.outer = outer or colors["bg"]
        super().__init__(master, bg=self.outer, highlightthickness=0)
        self.c, self.scale = colors, scale
        self.font = load_counter_font() or font
        self._fonts = {}

    def _font(self, size, weight):
        import tkinter.font as tkfont
        key = (size, weight)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(root=self, family=self.font, size=size, weight=weight)
        return self._fonts[key]

    def _outlined(self, x, y, text, font, fill, stroke):
        """Text with a dark outline and a small drop shadow, so it reads on any game without a box."""
        sh = stroke + 1
        self.create_text(x + sh, y + sh, text=text, anchor="w", fill=OUTLINE, font=font)
        for dx in range(-stroke, stroke + 1):
            for dy in range(-stroke, stroke + 1):
                if (dx or dy) and dx * dx + dy * dy <= stroke * stroke + 1:
                    self.create_text(x + dx, y + dy, text=text, anchor="w", fill=OUTLINE, font=font)
        self.create_text(x, y, text=text, anchor="w", fill=fill, font=font)

    def render(self, cfg, fps=None, metrics=None, stale=False):
        """fps: dict from FpsCounter.current() (or None); metrics: hardware monitor metrics."""
        c, s, m = self.c, self.scale * SIZES.get(cfg.get("size"), 1.0), metrics or {}
        items = cfg.get("items", {})

        def tcol(t):
            return "#f2f2f4" if t is None or t < 70 else FPS_COLORS["ok"] if t < 85 else FPS_COLORS["low"]

        def num(v, unit="", nd=0):
            return "—" if v is None else f"{v:.{nd}f}{unit}"

        light, dim = "#f2f2f4", "#c9cace"
        extras = []   # list of [(text, colour), ...] segments
        if items.get("low"):
            extras.append([(num(fps["low"]) if fps else "—", fps_color(fps["low"]) if fps else light), (" low", dim)])
        if items.get("frametime"):
            extras.append([(num(fps["ms"], "", 1) if fps else "—", light), (" ms", dim)])
        if items.get("cpu"):
            extras.append([("CPU ", dim), (num(m.get("cpu_temp"), "°"), tcol(m.get("cpu_temp")))])
        if items.get("gpu"):
            extras.append([("GPU ", dim), (num(m.get("gpu_temp"), "°"), tcol(m.get("gpu_temp")))])
        show_fps = items.get("fps") or not extras

        big = self._font(max(12, int(24 * s)), "bold")
        small = self._font(max(7, int(9 * s)), "bold")
        stroke = max(1, round(2 * s))
        pad, gap = stroke + 3, int(10 * s)
        h = big.metrics("linespace") + 2 * pad
        x = pad
        self.delete("all")
        parts = []
        if show_fps:
            value = num(fps["fps"]) if fps else "—"
            col = "#8a8c92" if stale or not fps else fps_color(fps["fps"])
            parts.append((x, value, big, col, stroke))
            x += big.measure(value) + gap
        for segs in extras:
            for text, col in segs:
                parts.append((x, text, small, col, max(1, stroke - 1)))
                x += small.measure(text)
            x += gap
        w = max(x - gap + pad + stroke + 1, h)
        mid = h / 2
        for px, text, f, col, st in parts:
            self._outlined(px, mid, text, f, col, st)
        self.configure(width=w, height=h)
        return w, h


class OverlayWindow(tk.Toplevel):
    """Click-through window pinned to a corner of the game's window.
    In front of the game while you play; when you tab out it stays on the game (just above it,
    not on top of every other app) and hides when the game is minimised or closed."""
    MARGIN = 12
    KEY = "#010102"          # see-through colour behind the number (Windows)

    def __init__(self, root, colors, font):
        super().__init__(root)
        self.withdraw()
        self.overrideredirect(True)
        outer = self.KEY if eng.IS_WIN else colors["bg"]
        self.configure(bg=outer)
        self.panel = OverlayPanel(self, colors, font, outer=outer)
        self.panel.pack()
        try:
            if eng.IS_WIN:
                self.attributes("-transparentcolor", self.KEY)
            self.attributes("-alpha", 0.96)
        except tk.TclError:
            pass
        self._styled = False
        self.shown = False
        self.hwnd = 0

    def _click_through(self):
        if self._styled or not eng.IS_WIN:
            return
        try:
            u = _u32()
            self.hwnd = int(u.GetParent(self.winfo_id()) or self.winfo_id())
            GWL_EXSTYLE = -20
            style = u.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
            # layered + transparent (clicks pass through) + tool window (no taskbar button) + never takes focus
            u.SetWindowLongPtrW(self.hwnd, GWL_EXSTYLE, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
            self._styled = True
        except Exception:
            pass

    def hide(self):
        if self.shown:
            self.withdraw()
            self.shown = False

    def _stack(self, game_hwnd, game_in_front):
        """Keep the overlay directly above the game window."""
        if not eng.IS_WIN or not self.hwnd:
            try:
                self.attributes("-topmost", True)
            except tk.TclError:
                pass
            return
        u = _u32()
        flags = 0x0001 | 0x0002 | 0x0010 | 0x0040   # SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        try:
            if game_in_front:
                ok = u.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)     # above everything, the game included
                if not ok and not getattr(self, "_warned", False):
                    self._warned = True
                    eng_log = getattr(self.master, "log", None)
                    if eng_log:
                        eng_log(f"Overlay couldn't move on top (Windows error {ctypes.get_last_error()}).", "warn")
            else:
                u.SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
                above = u.GetWindow(game_hwnd, 3)                                 # GW_HWNDPREV: window just above the game
                if above and int(above) != self.hwnd:
                    u.SetWindowPos(self.hwnd, above, 0, 0, 0, 0, flags)           # just below that = just above the game
                elif not above:
                    u.SetWindowPos(self.hwnd, HWND_TOP, 0, 0, 0, 0, flags)        # game is on top: go above it
        except Exception:
            pass

    def is_topmost(self) -> bool:
        """For the self-test: is the overlay really in the always-on-top layer?"""
        if not eng.IS_WIN or not self.hwnd:
            return False
        return bool(_u32().GetWindowLongPtrW(self.hwnd, -20) & 0x8)        # WS_EX_TOPMOST

    def update_overlay(self, cfg, fps, metrics, game_hwnd=0, game_in_front=True, stale=False):
        rect = game_window_state(game_hwnd) if eng.IS_WIN else (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        if rect is None or rect == "minimized":
            self.hide()
            return
        gx, gy, gw, gh = rect
        w, h = self.panel.render(cfg, fps, metrics, stale=stale)
        corner = cfg.get("corner", "Top left")
        x = gx + self.MARGIN if "left" in corner else gx + gw - w - self.MARGIN
        y = gy + self.MARGIN if "Top" in corner else gy + gh - h - self.MARGIN
        self.geometry(f"{w}x{h}+{x}+{y}")
        if not self.shown:
            self.deiconify()
            self.shown = True
            self.update_idletasks()
            self._click_through()
        self._stack(game_hwnd, game_in_front)
