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

* FpsCounter  - runs PresentMon (restarting it if it stops), reads its CSV stream and keeps frame times per app
* GameTracker - picks the game to follow and turns problems into plain-English status messages
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
DEFAULTS = {"enabled": False, "corner": "Top left", "size": "Medium", "games_only": True,
            "items": {"fps": True, "low": False, "frametime": False, "cpu": False, "gpu": False}, "style": 2}


def overlay_settings(settings) -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    saved = settings.data.get("overlay") or {}
    cfg.update({k: v for k, v in saved.items() if k != "items"})
    if saved.get("style") == 2:          # older settings switch to the new number-only default once
        cfg["items"].update(saved.get("items") or {})
    cfg["style"] = 2
    return cfg


# Programs that draw frames but are never "the game": launchers, anti-cheat helpers, chat/recording overlays
# and RGB suites. If one of them is in front (Discord, SteelSeries GG, Steam...) the overlay stays on the game
# instead of jumping to it.
HELPERS = {"steam.exe", "steamwebhelper.exe", "gameoverlayui.exe", "epicgameslauncher.exe", "epicwebhelper.exe",
           "easyanticheat.exe", "easyanticheat_eos.exe", "easyanticheat_eos_setup.exe", "start_protected_game.exe",
           "eadesktop.exe", "eabackgroundservice.exe", "battle.net.exe", "ubisoftconnect.exe", "upc.exe",
           "riotclientservices.exe", "riotclientux.exe", "galaxyclient.exe", "discord.exe", "overwolf.exe",
           "medal.exe", "obs64.exe", "nvidia overlay.exe", "nvidia app.exe", "gamebar.exe",
           "gamebarftserver.exe", "xboxgamebarwidgets.exe", "xboxpcappft.exe", "rtss.exe", "msiafterburner.exe",
           "msi center.exe", "msi.centralserver.exe", "mysticlight.exe", "steelseriesgg.exe",
           "steelseriesggclient.exe", "steelseriesengine.exe", "steelseriesprism.exe", "razer synapse 3.exe",
           "razerappengine.exe", "icue.exe", "lghub.exe", "armourycrate.exe", "openrgb.exe"}
# ---------------------------------------------------------------------------- is it a game?
# Browsers, chat, video players and everyday apps draw frames too (smooth scrolling, video, animations), so
# "it's presenting frames" isn't enough. An app counts as a game when Windows itself lists it as one (Game Bar's
# list), it's installed in a game library (Steam, Epic, GOG, Xbox, Riot, EA, Ubisoft...), or it fills the
# screen while drawing, and it's never one of these.
NOT_GAMES = {
    # browsers and web views
    "chrome.exe", "msedge.exe", "msedgewebview2.exe", "firefox.exe", "opera.exe", "opera_gx.exe", "brave.exe",
    "vivaldi.exe", "arc.exe", "iexplore.exe", "librewolf.exe", "waterfox.exe", "zen.exe", "thorium.exe",
    "floorp.exe", "yandex.exe", "chromium.exe",
    # chat, calls, mail
    "slack.exe", "teams.exe", "ms-teams.exe", "zoom.exe", "telegram.exe", "whatsapp.exe", "signal.exe",
    "skype.exe", "outlook.exe", "olk.exe", "thunderbird.exe", "element.exe", "guilded.exe", "vesktop.exe",
    # video and music
    "spotify.exe", "vlc.exe", "mpc-hc64.exe", "mpc-hc.exe", "mpc-be64.exe", "potplayermini64.exe",
    "potplayermini.exe", "wmplayer.exe", "mpv.exe", "itunes.exe", "applemusic.exe", "music.ui.exe",
    "video.ui.exe", "plex.exe", "kodi.exe", "stremio.exe", "netflix.exe", "twitch.exe", "aimp.exe",
    "foobar2000.exe", "tidal.exe", "deezer.exe", "amazon music.exe",
    # office, notes, PDFs
    "winword.exe", "excel.exe", "powerpnt.exe", "onenote.exe", "msaccess.exe", "acrobat.exe", "acrord32.exe",
    "notion.exe", "obsidian.exe", "evernote.exe", "sumatrapdf.exe", "notepad.exe", "notepad++.exe",
    # code and terminals
    "code.exe", "cursor.exe", "devenv.exe", "windowsterminal.exe", "wt.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "conhost.exe", "openconsole.exe", "pycharm64.exe", "idea64.exe", "rider64.exe", "clion64.exe",
    "webstorm64.exe", "sublime_text.exe", "githubdesktop.exe", "zed.exe",
    # creative and streaming tools
    "photoshop.exe", "illustrator.exe", "afterfx.exe", "adobe premiere pro.exe", "resolve.exe", "figma.exe",
    "obs64.exe", "obs32.exe", "streamlabs obs.exe", "streamlabs desktop.exe", "xsplit.core.exe", "gimp-2.10.exe",
    "krita.exe", "paint.net.exe", "mspaint.exe", "clipchamp.exe",
    # system and utilities
    "taskmgr.exe", "systemsettings.exe", "mmc.exe", "regedit.exe", "control.exe", "photos.exe",
    "microsoft.photos.exe", "snippingtool.exe", "screenclippinghost.exe", "lockapp.exe", "hwinfo64.exe",
    "cpuz.exe", "gpu-z.exe", "aida64.exe", "wiztree64.exe", "everything.exe", "7zfm.exe", "winrar.exe",
}
# Where game launchers install games (matched anywhere in the exe's full path, lower case)
GAME_FOLDERS = ("\\steamapps\\common\\", "\\epic games\\", "\\gog galaxy\\games\\", "\\gog games\\",
                "\\xboxgames\\", "\\riot games\\", "\\ea games\\", "\\origin games\\", "\\electronic arts\\",
                "\\ubisoft game launcher\\games\\", "\\rockstar games\\", "\\amazon games\\library\\",
                "\\battle.net\\games\\", "\\blizzard entertainment\\", "\\itch\\apps\\", "\\games\\",
                "\\.minecraft\\", "\\wargaming.net\\")
NOT_GAME_WORDS = ("launcher", "crashhandler", "crashreport", "crashpad", "setup", "unins", "updater",
                  "installer", "bootstrapper")   # launchers, crash reporters and installers live in game folders too
GAME_EXES = {"javaw.exe"}          # Minecraft Java runs as javaw.exe from wherever Java is installed


def process_exe(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).exe()
    except Exception:
        return ""


def windows_known_games() -> set[str]:
    """Full paths (lower case) of the exes Windows has recognised as games: Game Bar's own list, in
    HKCU\\System\\GameConfigStore\\Children. Empty anywhere it can't be read."""
    if not eng.IS_WIN:
        return set()
    out = set()
    try:
        import winreg
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"System\GameConfigStore\Children")
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(root, sub) as k:
                    path, _ = winreg.QueryValueEx(k, "MatchedExeFullPath")
                    if path:
                        out.add(str(path).lower())
            except OSError:
                pass
    except Exception:
        pass
    return out


class GameDetector:
    """Decides whether a process is a game the FPS counter should follow. Results are cached per process."""

    KNOWN_EVERY = 120.0        # re-read Windows' list of games this often (new installs show up)

    def __init__(self, exe_of=process_exe, known_games=windows_known_games, clock=time.monotonic):
        self.exe_of, self.known_games, self.clock = exe_of, known_games, clock
        self._known, self._known_at = set(), -1e9
        self._cache = {}

    def known(self) -> set[str]:
        now = self.clock()
        if now - self._known_at > self.KNOWN_EVERY:
            self._known, self._known_at = self.known_games(), now
        return self._known

    def verdict(self, pid: int, name: str = "", fills_screen: bool = False) -> tuple[bool, str]:
        """(is_game, why). fills_screen: its window covers the monitor (fullscreen or borderless)."""
        if not pid:
            return False, "no app"
        hit = self._cache.get(pid)
        if hit and hit[0] == (name or "").lower():
            fixed, why = hit[1], hit[2]
            if fixed is not None:
                return fixed, why
            return (True, "fills the screen") if fills_screen else (False, "not recognised as a game")
        n = (name or "").lower()
        exe = (self.exe_of(pid) or "").lower()
        n = n or exe.rsplit("\\", 1)[-1]
        fixed, why = None, ""
        if n in NOT_GAMES or n in IGNORED or is_helper(n) or any(w in n for w in NOT_GAME_WORDS):
            fixed, why = False, f"{n} is not a game"
        elif exe.startswith(("c:\\windows\\", "c:\\program files\\windowsapps\\microsoft.windows")):
            fixed, why = False, "part of Windows"
        elif exe and exe in self.known():
            fixed, why = True, "Windows lists it as a game"
        elif n in GAME_EXES or any(f in exe for f in GAME_FOLDERS):
            fixed, why = True, "installed in a game library"
        self._cache[pid] = ((name or "").lower(), fixed, why)
        if len(self._cache) > 500:
            self._cache.clear()
        if fixed is not None:
            return fixed, why
        if fills_screen:                    # unknown app drawing full screen: very likely a game
            return True, "fills the screen"
        return False, "not recognised as a game"


MIN_FRAMES = 3          # frames in the last second before a process counts as "drawing"
WAIT_SECS = 4.0         # a game-like window in front with no frames this long -> tell the user
RESTART_DELAYS = (2, 5, 10)   # seconds before restarting PresentMon after it stops on its own


def is_helper(name: str) -> bool:
    n = (name or "").lower()
    return n in IGNORED or n in HELPERS or n.startswith("easyanticheat")


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


def process_name(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name()
    except Exception:
        return ""


def process_family(pid: int) -> set[int]:
    """The parent and all children of a process. A game is sometimes drawn by a different exe than the one that
    owns the window (a bootstrapper or anti-cheat launcher that starts the real game as a child)."""
    out: set[int] = set()
    try:
        import psutil
        p = psutil.Process(pid)
        out.update(c.pid for c in p.children(recursive=True))
        parent = p.ppid()
        if parent:
            out.add(parent)
    except Exception:
        pass
    out.discard(pid)
    return out


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


def monitor_rect(hwnd: int):
    """(x, y, w, h) of the monitor that holds most of this window, or None."""
    if not eng.IS_WIN or not hwnd:
        return None
    try:
        from ctypes import wintypes as wt

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        u = _u32()
        u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
        u.MonitorFromWindow.restype = wt.HMONITOR
        u.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.POINTER(MONITORINFO)]
        mon = u.MonitorFromWindow(hwnd, 2)                      # MONITOR_DEFAULTTONEAREST
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not mon or not u.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return None
        r = mi.rcMonitor
        return r.left, r.top, r.right - r.left, r.bottom - r.top
    except Exception:
        return None


def covers_monitor(rect, monitor, share=0.9) -> bool:
    """True when a window fills (almost) its whole monitor - how fullscreen and borderless games look."""
    if not isinstance(rect, tuple) or not monitor:
        return False
    return rect[2] >= monitor[2] * share and rect[3] >= monitor[3] * share


def frame_stats(frames, now, window=1.0, low_window=10.0):
    """frames: iterable of (timestamp, ms_between_presents). Returns (fps, one_percent_low_fps, frame_ms)."""
    recent = [ms for t, ms in frames if now - t <= window and ms > 0]
    if len(recent) < 3:
        return None
    avg_ms = sum(recent) / len(recent)
    longer = sorted(ms for t, ms in frames if now - t <= low_window and ms > 0)
    worst = longer[min(len(longer) - 1, int(len(longer) * 0.99))]
    return 1000.0 / avg_ms, 1000.0 / worst, avg_ms


def pick_game(fg_pid, fg_name, presenting, related=(), own_pid=None, is_game=None):
    """Which process to show FPS for, given the window in front.
    presenting: {pid: (name, frames_in_last_second)} from FpsCounter.presenting(); related: process_family(fg_pid).
    is_game(pid, name) -> bool: when given, only games are picked (no counter over a browser or Discord).
    Returns a pid, or None to keep whatever was picked before (desktop, helper apps, this app, nothing drawing)."""
    own_pid = os.getpid() if own_pid is None else own_pid
    if not fg_pid or fg_pid == own_pid or (fg_name or "").lower() in IGNORED:
        return None

    def drawing(pid):
        name, n = presenting.get(pid, ("", 0))
        return (n >= MIN_FRAMES and pid != own_pid and not is_helper(name)
                and (is_game is None or is_game(pid, name or (fg_name if pid == fg_pid else ""))))

    if drawing(fg_pid) and not is_helper(fg_name):
        return fg_pid
    family = [p for p in related if p != fg_pid and drawing(p)]
    if family:                     # window belongs to a launcher/bootstrapper; its child draws the frames
        return max(family, key=lambda p: presenting[p][1])
    return None


ERROR_SHORT = {"admin": "PresentMon needs admin", "download": "Couldn't download PresentMon",
               "blocked": "PresentMon was blocked", "crashed": "PresentMon keeps stopping",
               "sessions": "Too many trace sessions", "windows": "FPS overlay is Windows-only",
               "other": "FPS counter unavailable"}


def classify_pm_exit(text: str, returncode) -> tuple[str, str]:
    """Turn PresentMon's own error output into (kind, plain-English message)."""
    t = (text or "").lower()
    if "access denied" in t or "performance log users" in t or "administrat" in t or "elevat" in t:
        return "admin", ("PresentMon needs administrator rights to read Windows' graphics events. Run Central RGB "
                         "as administrator (or add your Windows account to the 'Performance Log Users' group and "
                         "sign out and back in), then switch the overlay off and on.")
    if "too many" in t or "no system resources" in t or "1450" in t:
        return "sessions", ("Windows has run out of graphics trace sessions (other monitoring or RGB apps use them "
                            "too). Close other overlay/monitoring tools or restart the PC.")
    if "already running" in t or "already exists" in t:
        return "crashed", "Another FPS counter session with the same name was in the way."
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    detail = f": {first[:160]}" if first else f" (exit code {returncode})" if returncode not in (None, 0) else ""
    return "crashed", f"PresentMon stopped unexpectedly{detail}."


def classify_launch_error(e: BaseException) -> tuple[str, str]:
    """Why PresentMon couldn't even be started."""
    code = getattr(e, "winerror", None)
    if code == 193:                                      # not a valid program: half-downloaded or damaged file
        return "corrupt", "The downloaded PresentMon is damaged."
    if code == 225 or "virus" in str(e).lower():
        return "blocked", ("Your antivirus blocked PresentMon (Intel's FPS tool). Allow it in Windows Security, "
                           "then switch the overlay off and on.")
    if code == 5 or isinstance(e, PermissionError):
        return "admin", "Windows refused to start PresentMon (access denied). Run Central RGB as administrator."
    if code == 2 or isinstance(e, FileNotFoundError):
        return "blocked", ("PresentMon disappeared from disk (often removed by antivirus). Allow it in Windows "
                           "Security, then switch the overlay off and on.")
    return "other", f"FPS counter unavailable: {e}"


def status_text(status, kind="", message="", *, fps=None, game_name="", exclusive=False, waiting_name=""):
    """What to tell the user. Returns (level, overlay_note, page_text); level is off/info/ok/warn/bad.
    overlay_note is the short line drawn in the overlay itself ('' = just the number)."""
    if status == "off":
        return "off", "", "Off"
    if status == "starting":
        return "info", "Starting FPS counter…", message or "Starting the FPS counter (the first time it downloads PresentMon)…"
    if status == "restarting":
        return "warn", "FPS counter restarting…", message or "PresentMon stopped; restarting it…"
    if status == "error":
        return "bad", ERROR_SHORT.get(kind, ERROR_SHORT["other"]), message or ERROR_SHORT.get(kind, "")
    name = game_name or (fps or {}).get("name") or "Your game"
    if exclusive:
        return "warn", "Exclusive fullscreen hides overlays", (
            f"{name} is in exclusive fullscreen, so no overlay can show on top of it. "
            "Switch the game to Borderless (or Windowed) fullscreen in its display settings.")
    if fps:
        return "ok", "", f"Tracking {fps['name']}: {fps['fps']:.0f} FPS"
    if waiting_name:
        return "warn", "No frames from this game yet", (
            f"{waiting_name} is in front, but Windows hasn't reported any frames from it yet. This is normal on "
            "menus and loading screens for a few seconds. If it lasts, the game may be using exclusive fullscreen, "
            "or another program may be holding Windows' graphics trace.")
    return "ok", "", "Running. Open a game and it will appear on it."


class FpsCounter:
    """Runs PresentMon (restarting it if it stops on its own) and keeps recent frame times per process."""

    def __init__(self, log):
        self.log = log
        self.proc: subprocess.Popen | None = None
        self._proc_ev: threading.Event | None = None
        self.lock = threading.Lock()
        self._life = threading.Lock()        # start and stop never overlap (a late stop used to kill a new start)
        self.modes: dict[int, str] = {}
        self.frames: dict[tuple, collections.deque] = {}       # (pid, swap chain) -> (time, ms)
        self.names: dict[int, str] = {}
        self.status, self.kind, self.message = "off", "", ""
        self.last_row = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pm_text: collections.deque = collections.deque(maxlen=40)   # PresentMon's non-CSV output

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
                    if "service" not in f.name.lower() and f.stat().st_size > 100_000:
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
        if self._thread and self._thread.is_alive() and not self._stop.is_set():
            return
        self._stop = stop = threading.Event()          # each run has its own stop flag
        self.status, self.kind, self.message = "starting", "", "Starting the FPS counter…"
        self._thread = threading.Thread(target=self._run, args=(stop,), daemon=True)
        self._thread.start()

    def stop(self):
        self._shutdown(self._stop)

    def stop_async(self):
        """Stop without blocking the window. The run being stopped is fixed right now, so a start() straight
        after can't be cancelled by this stop finishing late."""
        ev = self._stop
        ev.set()
        threading.Thread(target=self._shutdown, args=(ev,), daemon=True).start()

    def _shutdown(self, ev):
        ev.set()
        with self._life:
            if self._proc_ev is ev:            # only ever stop the PresentMon that belongs to this run
                p, self.proc, self._proc_ev = self.proc, None, None
                if p and p.poll() is None:
                    try:
                        p.terminate()
                    except Exception:
                        pass
            newer = self._stop is not ev and not self._stop.is_set()
            exe = self.find_exe() if eng.IS_WIN and not newer else None
            if exe:   # make sure the Windows trace session is closed too (not if a new run already owns it)
                eng.run_quiet([str(exe), "--terminate_existing_session", "--session_name", SESSION], timeout=10)
        if not newer:
            with self.lock:
                self.frames.clear()
            self.status, self.kind, self.message = "off", "", ""

    def _fail(self, stop, kind, message):
        if not stop.is_set():
            self.status, self.kind, self.message = "error", kind, message
            self.log(message, "warn")

    def _run(self, stop):
        if not eng.IS_WIN:
            return self._fail(stop, "windows", "The FPS overlay is Windows-only.")
        try:
            exe = self.find_exe() or self.download()
        except Exception as e:
            return self._fail(stop, "download", f"Couldn't download PresentMon, the free Intel tool that measures FPS "
                                                f"({e}). Check your internet connection, then switch the overlay off and on.")
        if not eng.is_admin():
            self.log("Central RGB isn't running as administrator; PresentMon may be refused access.", "warn")
        attempts, redownloaded = 0, False
        while not stop.is_set():
            started = time.monotonic()
            try:
                rc, text = self._run_once(exe, stop)
            except OSError as e:
                kind, msg = classify_launch_error(e)
                if kind == "corrupt" and not redownloaded:
                    redownloaded = True
                    try:
                        exe.unlink()
                        exe = self.download()
                        continue
                    except Exception as e2:
                        return self._fail(stop, "download", f"{msg} Downloading it again failed ({e2}).")
                return self._fail(stop, kind, msg)
            if stop.is_set():
                return
            kind, msg = classify_pm_exit(text, rc)
            if kind in ("admin", "sessions"):
                return self._fail(stop, kind, msg)
            if time.monotonic() - started > 60:
                attempts = 0                       # it had been running fine for a while
            if attempts >= len(RESTART_DELAYS):
                return self._fail(stop, "crashed", f"{msg} It stopped {attempts + 1} times in a row, so Central RGB "
                                                   "gave up. Switch the overlay off and on to try again.")
            delay = RESTART_DELAYS[attempts]
            attempts += 1
            self.status, self.kind, self.message = "restarting", kind, f"{msg} Restarting it in {delay} s…"
            self.log(self.message, "warn")
            if stop.wait(delay):
                return

    def _run_once(self, exe, stop):
        """Run PresentMon until it exits. Returns (exit code, its error output)."""
        cmd = [str(exe), "--output_stdout", "--no_console_stats", "--stop_existing_session",
               "--session_name", SESSION, "--no_track_gpu", "--no_track_input"]
        with self._life:                       # wait for a stop() that's still closing the old session
            if stop.is_set():
                return 0, ""
            self._pm_text.clear()
            self._proc_ev = stop
            p = self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                             errors="replace", bufsize=1, creationflags=eng.NO_WINDOW)
        threading.Thread(target=self._drain, args=(p.stderr,), daemon=True).start()
        if not stop.is_set():
            self.status, self.kind, self.message = "running", "", "FPS counter running"
            self.log("FPS counter started (PresentMon).")
        self.read_stream(p.stdout, stop)
        try:
            rc = p.wait(timeout=5)
        except Exception:
            rc = None
        time.sleep(0.2)                        # let the stderr reader catch the last lines
        return rc, "\n".join(self._pm_text)

    def _drain(self, stream):
        try:
            for line in stream:
                if line.strip():
                    self._pm_text.append(line.strip())
        except Exception:
            pass

    def read_stream(self, stream, stop=None):
        """Parse PresentMon's CSV stream. Columns are found by name, so column order doesn't matter, and a new
        header (PresentMon restarted, or a different version) is picked up again."""
        stop = stop or self._stop
        cols = None
        for line in stream:
            if stop.is_set():
                break
            parts = line.rstrip("\r\n").split(",")
            if "Application" in parts and "ProcessID" in parts:
                ms_col = next((c for c in ("MsBetweenPresents", "msBetweenPresents", "FrameTime", "MsBetweenAppStart")
                               if c in parts), None)
                cols = None if ms_col is None else (
                    parts.index("Application"), parts.index("ProcessID"), parts.index(ms_col),
                    parts.index("PresentMode") if "PresentMode" in parts else None,
                    parts.index("SwapChainAddress") if "SwapChainAddress" in parts else None)
                continue
            if cols is None:
                if line.strip():
                    self._pm_text.append(line.strip())
                continue
            try:
                name, pid, ms = parts[cols[0]], int(parts[cols[1]]), float(parts[cols[2]])
                chain = parts[cols[4]] if cols[4] is not None else ""
            except (ValueError, IndexError):
                continue
            if not (0 < ms < 5000):
                continue
            now = time.monotonic()
            with self.lock:
                if cols[3] is not None:
                    self.modes[pid] = parts[cols[3]]
                dq = self.frames.get((pid, chain))
                if dq is None:
                    dq = self.frames[(pid, chain)] = collections.deque(maxlen=16000)
                self.names[pid] = name
                dq.append((now, ms))
                self.last_row = now

    # ---------------- reading
    def mode(self, pid) -> str:
        """How the game shows its frames, as PresentMon reports it (e.g. 'Hardware: Legacy Flip')."""
        return self.modes.get(pid, "")

    @staticmethod
    def exclusive(mode: str) -> bool:
        """Exclusive fullscreen: the game owns the screen and no normal window (like this overlay) can show
        on top of it. 'Hardware: Legacy Flip' / 'Legacy Copy' are exclusive; flip/composed modes are not."""
        return "Legacy" in (mode or "")

    def _main_chain(self, pid, now):
        """Frames of the swap chain that draws the most (a game can have extra ones for overlays or a launcher
        view; mixing them made the number jump around)."""
        best, best_n = None, -1
        for (p, _chain), dq in self.frames.items():
            if p != pid or not dq:
                continue
            n = sum(1 for t, _ in reversed(dq) if now - t <= 1.0) if now - dq[-1][0] <= 1.0 else 0
            if n > best_n or (n == best_n and best is not None and dq[-1][0] > best[-1][0]):
                best, best_n = dq, n
        return best, max(best_n, 0)

    def presenting(self) -> dict[int, tuple[str, int]]:
        """{pid: (name, frames in the last second)} for every process drawing right now."""
        now = time.monotonic()
        out = {}
        with self.lock:
            for pid in {p for p, _ in self.frames}:
                _dq, n = self._main_chain(pid, now)
                if n:
                    out[pid] = (self.names.get(pid, ""), n)
        return out

    def alive(self, pid) -> bool:
        """True while this process has drawn a frame in the last 15 seconds."""
        now = time.monotonic()
        with self.lock:
            return any(p == pid and dq and now - dq[-1][0] <= 15 for (p, _c), dq in self.frames.items())

    def current(self, pid=None):
        """Stats for the foreground app: {'name', 'fps', 'low', 'ms'} or None when it isn't rendering."""
        pid = foreground_pid() if pid is None else pid
        now = time.monotonic()
        with self.lock:
            for k in [k for k, dq in self.frames.items() if not dq or now - dq[-1][0] > 15]:
                self.frames.pop(k, None)
            live = {p for p, _ in self.frames}
            for p in [p for p in self.names if p not in live]:
                self.names.pop(p, None)
                self.modes.pop(p, None)
            dq, _n = self._main_chain(pid, now)
            name = self.names.get(pid, "")
            frames = list(dq) if dq else []
        if not frames or pid == os.getpid() or name.lower() in IGNORED:
            return None
        st = frame_stats(frames, now)
        if st is None:
            return None
        return {"name": name, "fps": st[0], "low": st[1], "ms": st[2]}


class GameTracker:
    """Picks the game to follow and works out what the overlay and the Overlay page should say.
    Kept apart from the window code so it can be tested with a fake PresentMon."""

    def __init__(self, counter, *, family=process_family, window_state=None, name_of=process_name,
                 own_pid=None, clock=time.monotonic, detector=None, games_only=True):
        self.counter, self.family, self.name_of, self.clock = counter, family, name_of, clock
        self.detector = detector or GameDetector(clock=clock)
        self.games_only = games_only        # Overlay page: "Only in games"
        self.window_state = window_state or game_window_state
        self.own_pid = os.getpid() if own_pid is None else own_pid
        self.pid = self.hwnd = self.fg_pid = None
        self.last = None
        self._wait = (None, 0.0)
        self._family_cache = (None, 0.0, set())

    def _family(self, pid, now):
        cpid, at, fam = self._family_cache
        if cpid != pid or now - at > 2.0:
            fam = self.family(pid)
            self._family_cache = (pid, now, fam)
        return fam

    def reset(self):
        self.pid = self.hwnd = self.fg_pid = self.last = None
        self._wait = (None, 0.0)

    def update(self, fg_hwnd, fg_pid, fg_gamelike=False) -> dict:
        """fg_gamelike: the window in front fills its monitor (fullscreen/borderless). Returns a dict with
        pid, hwnd, fps, stale, in_front, exclusive, level, note (short, for the overlay) and text (for the page)."""
        c, now = self.counter, self.clock()
        fps, stale, waiting_name = None, False, ""
        if c.status != "running":
            self.reset()
        else:
            presenting = c.presenting()
            fg_name = c.names.get(fg_pid) or (self.name_of(fg_pid) if fg_pid else "")
            related = () if fg_pid in presenting else self._family(fg_pid, now) if fg_pid else ()
            is_game = None
            if self.games_only:
                def is_game(pid, name, _fg=fg_pid, _full=fg_gamelike):
                    return self.detector.verdict(pid, name, fills_screen=_full and pid in (_fg,) + tuple(related))[0]
            pick = pick_game(fg_pid, fg_name, presenting, related, self.own_pid, is_game)
            if pick and pick != self.pid:
                self.pid, self.hwnd, self.fg_pid, self.last = pick, fg_hwnd, fg_pid, None      # a new game is in front
            elif pick and fg_hwnd and fg_hwnd != self.hwnd and self.window_state(self.hwnd) is None:
                self.hwnd = fg_hwnd       # same game, new window (resolution or display-mode change recreates it)
            if self.pid and (not c.alive(self.pid) or self.window_state(self.hwnd) is None):
                self.pid = self.hwnd = self.fg_pid = self.last = None                            # game closed
            if self.pid:
                fps = c.current(self.pid)
                if fps:
                    self.last = fps
                else:                         # backgrounded games often pause drawing: keep the last number, dimmed
                    fps, stale = self.last, True
            # A fullscreen window is in front but nothing is being measured for it
            if (fg_gamelike and fg_pid and fg_pid != self.own_pid and not pick and fg_pid != self.fg_pid
                    and not is_helper(fg_name)
                    and (not self.games_only or self.detector.verdict(fg_pid, fg_name, True)[0])):
                if self._wait[0] != fg_pid:
                    self._wait = (fg_pid, now)
                if now - self._wait[1] >= WAIT_SECS:
                    waiting_name = fg_name or "This game"
            else:
                self._wait = (None, 0.0)
        exclusive = bool(self.pid) and c.exclusive(c.mode(self.pid))
        level, note, text = status_text(c.status, c.kind, c.message, fps=fps,
                                        game_name=(fps or {}).get("name", ""), exclusive=exclusive,
                                        waiting_name=waiting_name)
        in_front = bool(self.pid) and fg_pid in (self.pid, self.fg_pid)
        return {"pid": self.pid, "hwnd": self.hwnd, "fps": fps, "stale": stale, "in_front": in_front,
                "exclusive": exclusive, "level": level, "note": note, "text": text}


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

    def render(self, cfg, fps=None, metrics=None, stale=False, note=""):
        """fps: dict from FpsCounter.current() (or None); metrics: hardware monitor metrics;
        note: a short status line ('PresentMon needs admin'...) drawn after the number instead of failing silently."""
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
        if note:
            parts.append((x, note, small, FPS_COLORS["ok"], max(1, stroke - 1)))
            x += small.measure(note) + gap
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

    def update_overlay(self, cfg, fps, metrics, game_hwnd=0, game_in_front=True, stale=False, note=""):
        rect = game_window_state(game_hwnd) if eng.IS_WIN else (0, 0, self.winfo_screenwidth(), self.winfo_screenheight())
        if rect is None or rect == "minimized":
            self.hide()
            return
        gx, gy, gw, gh = rect
        w, h = self.panel.render(cfg, fps, metrics, stale=stale, note=note)
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
