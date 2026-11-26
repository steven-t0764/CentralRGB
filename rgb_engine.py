# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Central RGB - engine (no GUI code in here).

* Settings           - saved to %APPDATA%\\CentralRGB\\settings.json
* OpenRGBManager     - finds, downloads and launches OpenRGB (the hardware layer)
* system_check()     - Windows checks: admin, PawnIO driver, conflicting RGB apps, hardware inventory
* LightingEngine     - background thread that pushes colors/effects to every device
"""
from __future__ import annotations

import atexit
import colorsys
import ctypes
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from openrgb import OpenRGBClient
from openrgb.utils import DeviceType, ModeColors, ModeFlags, RGBColor

# Newer OpenRGB versions may report device types this library doesn't know yet.
# Map anything unknown to UNKNOWN instead of crashing.
DeviceType._missing_ = classmethod(lambda cls, value: cls.UNKNOWN)

APP_NAME = "Central RGB"
APP_VERSION = "2.4.0"   # release builds overwrite this with the release tag
SDK_HOST = "127.0.0.1"
SDK_PORT = 6742
RELEASES_PAGE = "https://openrgb.org/releases.html"
FALLBACK_ZIP = ("https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_1.1/"
                "OpenRGB_1.1_Windows_64_8e16de2.zip")
PAWNIO_PAGE = "https://pawnio.eu"
PAWNIO_SETUP = "https://github.com/namazso/PawnIO.Setup/releases/latest/download/PawnIO_setup.exe"


def pawnio_installed() -> bool:
    if not IS_WIN:
        return False
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Services\PawnIO").Close()
        return True
    except Exception:
        return False


def install_pawnio(log=print) -> str:
    """Download the official, signed PawnIO installer (the same one the setup uses; never bundled) and run
    it silently. PawnIO is the driver LibreHardwareMonitor and OpenRGB use for CPU temperatures, fan control
    and RGB RAM. Returns 'ok', 'reboot' or an error message."""
    if not IS_WIN:
        return "PawnIO is Windows-only."
    import tempfile
    import urllib.request
    try:
        dest = Path(tempfile.gettempdir()) / "PawnIO_setup.exe"
        log(f"Downloading PawnIO: {PAWNIO_SETUP}")
        with urllib.request.urlopen(PAWNIO_SETUP, timeout=60) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        code = subprocess.run([str(dest), "-install", "-silent"], creationflags=NO_WINDOW, timeout=180).returncode
        if code == 3010:
            return "reboot"
        return "ok" if code == 0 else f"PawnIO installer exited with code {code}"
    except Exception as e:
        return f"Couldn't install PawnIO: {e}"
IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW for helper commands


def is_onefile() -> bool:
    """True for the portable single-file exe (it unpacks itself to a _MEI temp folder each launch)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return bool(getattr(sys, "frozen", False) and meipass and Path(meipass).name.startswith("_MEI"))


def child_env() -> dict | None:
    """Environment for starting another copy of this app (helpers, restart).
    The portable exe passes its unpack folder to child processes, and PyInstaller then insists the
    original parent is still running ("Security validation failure ... PID not found") - which breaks
    helpers and restarts. Asking for a reset gives each copy its own clean start."""
    if not getattr(sys, "frozen", False):
        return None
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env):
        if k.startswith("_PYI_") or k.startswith("_MEIPASS"):
            env.pop(k, None)
    return env

BASIC_EFFECTS = ["Static", "Breathing", "Color Cycle", "Rainbow Wave", "Off"]
PRESET_EFFECTS = ["Tide", "Drizzle", "Sweep", "Ember", "Pulse", "Drift", "Volt", "Frost",
                  "Aurora", "Supernova", "Cascade", "Cyberpunk", "Magma", "Stardust", "Nebula", "Eclipse"]
RENAMED = {'Calm Water': 'Tide', 'Rain': 'Drizzle', 'Side to Side': 'Sweep', 'Crimson': 'Ember', 'RGBarz': 'Pulse', 'Gradient Wave': 'Drift', 'Neon Storm': 'Volt', 'Black Ice': 'Frost'}   # older preset names, kept so saved settings still work
EFFECTS = BASIC_EFFECTS[:4] + PRESET_EFFECTS + ["Off"]
ANIMATED = set(EFFECTS) - {"Static", "Off"}
USES_COLOR = {"Static", "Breathing"}        # effects that use the colour you pick

# Presets the user made (Lighting -> Create preset): name -> {"motion": ..., "colors": [[r, g, b], ...]}.
# The app fills this from settings; compute_colors() draws them like any built-in effect.
CUSTOM_PRESETS: dict[str, dict] = {}
CUSTOM_MOTIONS = ["Gradient", "Wave", "Breathe", "Cycle", "Pulse", "Sparkle"]


def is_animated(effect: str) -> bool:
    if effect in CUSTOM_PRESETS:
        return CUSTOM_PRESETS[effect].get("motion") != "Gradient"
    return effect in ANIMATED

TYPE_NAMES = {
    DeviceType.MOTHERBOARD: "Motherboard", DeviceType.DRAM: "RAM", DeviceType.GPU: "GPU",
    DeviceType.COOLER: "Cooler", DeviceType.LEDSTRIP: "LED strip", DeviceType.KEYBOARD: "Keyboard",
    DeviceType.MOUSE: "Mouse", DeviceType.MOUSEMAT: "Mousepad", DeviceType.HEADSET: "Headset",
    DeviceType.HEADSET_STAND: "Headset stand", DeviceType.GAMEPAD: "Gamepad",
    DeviceType.LIGHT: "Light", DeviceType.SPEAKER: "Speaker", DeviceType.VIRTUAL: "Virtual",
    DeviceType.STORAGE: "Storage", DeviceType.CASE: "Case", DeviceType.MICROPHONE: "Microphone",
    DeviceType.ACCESSORY: "Accessory", DeviceType.KEYPAD: "Keypad", DeviceType.UNKNOWN: "Other",
}

# Vendor RGB apps that fight over the same hardware. Process name (lowercase) -> friendly name.
CONFLICTING_APPS = {
    "icue.exe": "Corsair iCUE",
    "armourycrate.service.exe": "ASUS Armoury Crate",
    "armourycrate.usersessionhelper.exe": "ASUS Armoury Crate",
    "lightingservice.exe": "ASUS Aura / Armoury Crate lighting service",
    "msi.centralserver.exe": "MSI Center / Mystic Light",
    "ledkeeper2.exe": "MSI Mystic Light",
    "mysticlight.exe": "MSI Mystic Light",
    "rgbfusion.exe": "Gigabyte RGB Fusion",
    "gcc.exe": "Gigabyte Control Center",
    "nzxt cam.exe": "NZXT CAM",
    "signalrgb.exe": "SignalRGB",
    "razer synapse 3.exe": "Razer Synapse",
    "razer synapse.exe": "Razer Synapse",
    "razercentralservice.exe": "Razer Synapse",
    "lghub.exe": "Logitech G HUB",
    "lghub_agent.exe": "Logitech G HUB",
    "steelseriesgg.exe": "SteelSeries GG",
    "steelseriesengine.exe": "SteelSeries Engine",
    "l-connect 3.exe": "Lian Li L-Connect",
    "lianli.l-connect3.exe": "Lian Li L-Connect",
    "thermaltake rgb plus.exe": "Thermaltake RGB Plus",
    "tt rgb plus.exe": "Thermaltake RGB Plus",
    "hyperx ngenuity.exe": "HyperX NGENUITY",
    "polychromergb.exe": "ASRock Polychrome",
    "openrgbwrapper.exe": "ASRock Polychrome",
}


# Of those, the ones that also write to RGB RAM over the motherboard's SMBus. Two programs writing the
# same sticks at once makes them flicker, whatever Central RGB does.
RAM_WRITERS = {"Corsair iCUE", "MSI Center / Mystic Light", "MSI Mystic Light", "ASUS Armoury Crate",
               "ASUS Aura / Armoury Crate lighting service", "Gigabyte RGB Fusion", "Gigabyte Control Center",
               "SignalRGB", "HyperX NGENUITY", "ASRock Polychrome", "Thermaltake RGB Plus"}

# RGB RAM: every stick shares one slow SMBus (often behind a driver like PawnIO), so it gets its own,
# lower and steady frame rate, small changes are held back, and the sticks take turns on the bus.
DRAM_FPS = 10
DRAM_MIN_CHANGE = 4          # a RAM frame is only sent if some LED moved at least this much (0-255)
# Built-in effects the RAM can run by itself (its own hardware mode), so nothing is streamed at all.
HW_EFFECT_MODES = {"Breathing": ("breathing",),
                   "Color Cycle": ("spectrum cycle", "color cycle", "colour cycle", "rainbow")}


def find_conflicts() -> dict[str, list[int]]:
    """Running vendor RGB apps: friendly name -> process ids."""
    out: dict[str, list[int]] = {}
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            app = _conflict_name(p.info["name"], p.info.get("exe") or "")
            if app:
                out.setdefault(app, []).append(p.pid)
    except Exception:
        pass
    return out


# Install folders of vendor apps that run several helpers and services (MSI Center starts Mystic Light's
# LEDKeeper2 and its own services from these). Anything running from them is closed with the app.
CONFLICT_FOLDERS = {
    "\\msi center\\mystic light\\": "MSI Mystic Light",
    "\\msi\\mystic light": "MSI Mystic Light",
    "\\msi\\msi center\\": "MSI Center / Mystic Light",
}


def _conflict_name(name: str, path: str = "") -> str | None:
    """Friendly app name for a process (by exe name, or by the vendor folder it runs from), else None."""
    name, path = (name or "").lower(), (path or "").lower().replace("/", "\\")
    if name in CONFLICTING_APPS:
        return CONFLICTING_APPS[name]
    for folder, app in CONFLICT_FOLDERS.items():
        if folder in path:
            return app
    return None


def close_conflicts(log=print) -> list[str]:
    """Close the vendor RGB apps that hold the hardware, including their background services
    (e.g. MSI's Mystic Light service keeps running after MSI Center is closed). Services are set to
    start manually so they don't grab the hardware again at the next sign-in; the vendor app still
    works if the user opens it. Returns what was done; anything that couldn't be stopped (usually because
    Central RGB isn't running as administrator) is reported through log."""
    done: list[str] = []
    if not IS_WIN:
        return done
    try:
        import psutil
    except Exception:
        return done
    exes = set(CONFLICTING_APPS)
    try:                                         # services first, so they can't restart the processes
        for svc in psutil.win_service_iter():
            try:
                info = svc.as_dict()
                binpath = (info.get("binpath") or "").lower()
                if not any(e in binpath for e in exes) and not _conflict_name("", binpath):
                    continue
                name = info["name"]
                label = info.get("display_name") or name
                if info.get("start_type") == "automatic":
                    r = run_quiet(["sc", "config", name, "start=", "demand"])
                    if r is not None and r.returncode == 0:
                        done.append(f"Service '{label}' set to start manually")
                    else:
                        log(f"Couldn't set service '{label}' to start manually (run Central RGB as administrator).")
                if info.get("status") == "running":
                    r = run_quiet(["sc", "stop", name])
                    if r is not None and r.returncode == 0:
                        done.append(f"Stopped service '{label}'")
                    else:
                        log(f"Couldn't stop service '{label}' (run Central RGB as administrator).")
            except Exception:
                continue
    except Exception as e:
        log(f"Couldn't check services: {e}")
    time.sleep(1.0)
    for p in psutil.process_iter(["name", "exe"]):
        try:
            app = _conflict_name(p.info["name"], p.info.get("exe") or "")
            if not app:
                continue
            p.terminate()
            try:
                p.wait(timeout=4)
            except psutil.TimeoutExpired:
                p.kill()
            done.append(f"Closed {app} ({p.info['name']})")
        except psutil.NoSuchProcess:
            continue
        except Exception as e:
            log(f"Couldn't close {p.info.get('name')}: {e} (run Central RGB as administrator).")
    return done


def wait_for_conflicts_gone(timeout=10.0, poll=0.5) -> dict[str, list[int]]:
    """After close_conflicts: wait (up to timeout) until no vendor RGB app is left, so the SMBus and the
    mouse's HID interface are really free before OpenRGB looks again. Returns what is still running."""
    end = time.time() + timeout
    left = find_conflicts()
    while left and time.time() < end:
        time.sleep(poll)
        left = find_conflicts()
    return left


# --------------------------------------------------------------------------- helpers
def app_dir() -> Path:
    """Folder the program lives in (next to the .exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    p = Path(base) / "CentralRGB"
    p.mkdir(parents=True, exist_ok=True)
    return p


def install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    p = Path(base) / "CentralRGB"
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_admin() -> bool:
    if not IS_WIN:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --------------------------------------------------------------------------- DDR5 RAM guard
# On many boards (seen on Intel Z790 with T-Force Delta DDR5, and others) OpenRGB finds DDR5 RGB RAM only
# the first time it searches for hardware after the PC starts. Every later search (restarting OpenRGB,
# Rescan) misses the RAM until the PC is fully shut down, and can leave the RAM unreadable to other tools.
# So when DDR5 is installed, the hidden OpenRGB is started once and then kept: it isn't restarted by
# Rescan, by closing conflicting apps, or by quitting and reopening Central RGB.
SMBIOS_DDR5 = 34                       # Win32_PhysicalMemory.SMBIOSMemoryType for DDR5
_ddr5_cache: bool | None = None

RAM_SHUTDOWN_TIP = ("Shut the PC down fully (hold Shift while you click Shut down, so Windows' Fast Startup "
                    "doesn't skip the full power-off), turn it back on, then open Central RGB before any other "
                    "RGB app.")


def ddr5_installed() -> bool:
    """True if the PC's memory is DDR5. Set CENTRALRGB_FAKE_DDR5=1 (or 0) to override, for tests."""
    global _ddr5_cache
    fake = os.environ.get("CENTRALRGB_FAKE_DDR5")
    if fake is not None:
        return fake.strip() == "1"
    if _ddr5_cache is None:
        _ddr5_cache = False
        if IS_WIN:
            r = run_quiet(["powershell", "-NoProfile", "-Command",
                           "(Get-CimInstance Win32_PhysicalMemory | Select-Object -ExpandProperty SMBIOSMemoryType)"
                           " -join ','"], timeout=15)
            if r and r.stdout:
                _ddr5_cache = str(SMBIOS_DDR5) in [t.strip() for t in r.stdout.split(",")]
    return _ddr5_cache


def boot_id() -> int:
    """Identifies this boot of Windows (the boot time, to the minute). 0 if unknown."""
    try:
        import psutil
        return int(psutil.boot_time() // 60)
    except Exception:
        return 0


def keep_openrgb_running(ddr5: bool) -> bool:
    """Leave the hidden OpenRGB running when Central RGB closes, and reuse one that is already running
    instead of restarting it, so the RAM isn't searched for a second time this boot."""
    return ddr5


def rescan_needs_ok(ddr5: bool, ours: bool, ram_found: bool) -> bool:
    """A full Rescan restarts the hidden OpenRGB. With DDR5 RAM already found, that would lose the RAM
    until the next full shutdown, so ask first."""
    return ddr5 and ours and ram_found


def ram_missing_note(ddr5: bool, ram_found: bool, searched_before_this_boot: bool, seen_before: bool) -> str | None:
    """What to tell the user when DDR5 RGB RAM wasn't found (None if there's nothing to say)."""
    if not ddr5 or ram_found:
        return None
    if searched_before_this_boot or seen_before:
        return ("RAM lighting wasn't found. DDR5 RGB RAM is often only found the first time OpenRGB looks for "
                "hardware after the PC starts, and OpenRGB already looked earlier this boot. " + RAM_SHUTDOWN_TIP)
    return ("No RAM lighting found. If your DDR5 RAM has RGB: close other RGB apps (T-Force Blitz, Polychrome "
            "Sync, iCUE, Armoury Crate...), then " + RAM_SHUTDOWN_TIP[0].lower() + RAM_SHUTDOWN_TIP[1:])


def run_quiet(cmd, timeout=20) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=NO_WINDOW, errors="replace")
    except Exception:
        return None


def device_key(dev) -> str:
    md = getattr(dev, "metadata", None)
    loc = getattr(md, "location", "") if md else ""
    serial = getattr(md, "serial", "") if md else ""
    return f"{dev.name}|{loc}|{serial}"


# --------------------------------------------------------------------------- per-key colours
# Keyboards that OpenRGB drives LED by LED report each key as an LED named like "Key: W" and lay the keys out in
# a matrix (rows x columns of LED numbers). Per-key colours are kept by LED name, so they survive OpenRGB
# renumbering, and sit on top of whatever effect runs on the rest of the keyboard.
KEY_GROUPS = {
    "WASD": ["W", "A", "S", "D"],
    "Arrows": ["Up Arrow", "Left Arrow", "Down Arrow", "Right Arrow"],
    "Numbers": [str(i) for i in range(1, 10)] + ["0"],
    "F keys": [f"F{i}" for i in range(1, 13)],
}
_KEY_ALIASES = {"up": "up arrow", "down": "down arrow", "left": "left arrow", "right": "right arrow",
                "arrow up": "up arrow", "arrow down": "down arrow", "arrow left": "left arrow",
                "arrow right": "right arrow", "esc": "escape"}


def key_label(led_name: str) -> str:
    """'Key: Left Shift' -> 'Left Shift'; other names come back as they are."""
    n = str(led_name or "").strip()
    return n[4:].strip() if n.lower().startswith("key:") else n


def _key_norm(label: str) -> str:
    n = key_label(label).lower().replace("_", " ").strip()
    if n.startswith("number "):                         # some keyboards say "Number 1"
        n = n[7:]
    return _KEY_ALIASES.get(n, n)


def per_key_capable(dev) -> bool:
    """True if the device has a mode that takes a colour for every LED (OpenRGB's Direct / custom mode)."""
    try:
        return any(m.color_mode == ModeColors.PER_LED for m in dev.modes) and len(dev.leds) > 1
    except Exception:
        return False


def keyboard_layout(dev) -> list[list[tuple]]:
    """Rows of (LED index or None, label) to draw the keys in their places. Uses OpenRGB's key matrix when the
    keyboard reports one; otherwise the LEDs in order, 16 to a row."""
    rows = []
    for zone in getattr(dev, "zones", []) or []:
        mat = getattr(zone, "matrix_map", None)
        leds = getattr(zone, "leds", []) or []
        if not mat:
            continue
        for mrow in mat:
            row = []
            for v in mrow:
                if v is None or not (0 <= v < len(leds)):
                    row.append((None, ""))
                else:
                    led = leds[v]
                    row.append((getattr(led, "id", v), key_label(getattr(led, "name", ""))))
            if any(i is not None for i, _ in row):
                rows.append(row)
    if rows:
        return rows
    leds = list(getattr(dev, "leds", []) or [])
    flat = [(getattr(led, "id", i), key_label(getattr(led, "name", f"LED {i + 1}"))) for i, led in enumerate(leds)]
    return [flat[i:i + 16] for i in range(0, len(flat), 16)]


def led_names(dev) -> list[str]:
    return [str(getattr(led, "name", f"LED {i + 1}")) for i, led in enumerate(getattr(dev, "leds", []) or [])]


def find_keys(dev, labels) -> list[str]:
    """The LED names on this keyboard for the given key labels (e.g. KEY_GROUPS['WASD']), in that order."""
    by_norm = {}
    for name in led_names(dev):
        by_norm.setdefault(_key_norm(name), name)
    return [by_norm[_key_norm(lb)] for lb in labels if _key_norm(lb) in by_norm]


def apply_key_colors(cols, dev, key_colors, brightness=100):
    """Put the per-key colours (LED name -> (r, g, b)) on top of a frame of colours for dev. Brightness scales
    them like the rest of the lighting, so dimming the keyboard dims the painted keys too."""
    if not key_colors:
        return cols
    out = list(cols)
    for i, name in enumerate(led_names(dev)[:len(out)]):
        c = key_colors.get(name)
        if c is not None:
            out[i] = compute_colors("Static", tuple(c), brightness, 0, 1, 0)[0]
    return out


def type_name(dev) -> str:
    return TYPE_NAMES.get(dev.type, "Other")


# --------------------------------------------------------------------------- settings
class Settings:
    DEFAULTS = {
        "openrgb_path": "",
        "state": {"color": [0, 120, 255], "effect": "Static", "brightness": 100, "speed": 50},
        "excluded": [],
        "device_overrides": {},
        "key_colors": {},          # device key -> {LED name: [r, g, b]}: keys painted in the key editor
        "battery_alert": 15,       # warn when a wireless device drops to this % (0 = never)
        "battery_headsets": True,  # download HeadsetControl to read headset batteries
        "profiles": {
            "Ocean": {"color": [0, 120, 255], "effect": "Static", "brightness": 100, "speed": 50},
            "Rainbow": {"color": [255, 0, 0], "effect": "Rainbow Wave", "brightness": 100, "speed": 40},
            "Red breathing": {"color": [255, 0, 0], "effect": "Breathing", "brightness": 100, "speed": 30},
        },
        "restore_on_start": True,
        "openrgb_boot": 0,          # boot_id() when the hidden OpenRGB last searched for hardware
        "ram_seen": False,          # RGB RAM has been found on this PC before
        "ram_note_boot": 0,         # boot_id() when the "RAM not found" pop-up was last shown
        "zone_sizes": {},           # device key -> {header/zone name: LEDs plugged in} (ARGB headers)
    }

    SAVE_DELAY = 0.6            # seconds: changes inside this window are written to disk once
    # Written straight away, not after SAVE_DELAY: rare, and they record what happened this boot (the
    # hardware search / RAM pop-up), so a hard kill right after must not lose them.
    SAVE_NOW = frozenset({"openrgb_boot", "ram_seen", "ram_note_boot"})
    _live: "list[Settings]" = []   # instances with writes possibly pending (flushed before another one loads)
    _live_lock = threading.Lock()

    def __init__(self):
        self.path = settings_dir() / "settings.json"
        self._lock = threading.RLock()        # guards self.data snapshots, the dirty flag and the file write
        self._dirty = False
        self._timer: threading.Timer | None = None
        with Settings._live_lock:
            others = [s for s in Settings._live if s.path == self.path]
            Settings._live.append(self)
        for s in others:                      # another Settings in this process may still have a change queued
            s.flush()
        atexit.register(self.flush)
        self.data = json.loads(json.dumps(self.DEFAULTS))
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
                self._migrate()
        except Exception:
            pass

    def _migrate(self):
        """Rename old preset effect names in saved lighting, profiles and per-device settings."""
        def fix(st):
            if isinstance(st, dict) and st.get("effect") in RENAMED:
                st["effect"] = RENAMED[st["effect"]]
        fix(self.data.get("state"))
        for group in ("profiles", "device_overrides"):
            for st in (self.data.get(group) or {}).values():
                fix(st)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        with self._lock:
            self.data[k] = v
            self._dirty = True
        if k in self.SAVE_NOW:
            self.flush()
        else:
            self._schedule()

    def _schedule(self):
        """Write once, SAVE_DELAY after the first of a burst of changes, on a background thread."""
        with self._lock:
            if self._timer is not None:
                return                        # already queued: it will write the newest data
            t = threading.Timer(self.SAVE_DELAY, self.flush)
            t.daemon = True
            self._timer = t
        t.start()

    def flush(self):
        """Write any pending change now (on the calling thread). Does nothing if nothing is pending."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            if not self._dirty:
                return
            self._dirty = False
            self._write()

    def save(self):
        """Write the settings file now, whether or not anything changed."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._dirty = False
            self._write()

    def _write(self):
        # caller holds self._lock, so no __setitem__ changes the dict while it is serialised
        try:
            for attempt in range(3):
                try:
                    text = json.dumps(self.data, indent=2)
                    break
                except RuntimeError:          # a nested dict changed in place on another thread: try again
                    if attempt == 2:
                        raise
                    time.sleep(0.001)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass


# --------------------------------------------------------------------------- OpenRGB
class OpenRGBManager:
    """Finds / downloads / starts OpenRGB with its SDK server enabled."""

    def __init__(self, settings: Settings, log):
        self.settings = settings
        self.log = log
        self.proc: subprocess.Popen | None = None

    def replace_visible_copy(self) -> bool:
        """An OpenRGB that Central RGB started earlier with its window / tray icon (older versions used
        --startminimized) is closed so a hidden copy can take its place. An OpenRGB the user runs
        themselves is left alone. Returns True if one was closed."""
        try:
            import psutil
        except Exception:
            return False
        ours = str(install_dir()).lower()
        closed = False
        for p in psutil.process_iter(["name", "exe", "cmdline"]):
            try:
                if (p.info["name"] or "").lower() != "openrgb.exe":
                    continue
                cmd = [c.lower() for c in (p.info["cmdline"] or [])]
                exe = (p.info["exe"] or "").lower()
                if "--startminimized" in cmd or (exe.startswith(ours) and "--noautoconnect" not in cmd):
                    p.terminate()
                    p.wait(timeout=5)
                    closed = True
            except Exception:
                continue
        if closed:
            self.log("Closed a visible OpenRGB window so it can run hidden in the background.")
        return closed

    def started_by_us(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def own_copies(self) -> list:
        """Hidden OpenRGB copies of ours, possibly left over from an earlier session that was ended in Task
        Manager: running from Central RGB's own folder, or started the way Central RGB starts it
        (--server --noautoconnect) from wherever OpenRGB is installed. Those only look for hardware when they
        start, so a rescan restarts them."""
        try:
            import psutil
        except Exception:
            return []
        ours, out = str(install_dir()).lower(), []
        for p in psutil.process_iter(["name", "exe", "cmdline"]):
            try:
                if (p.info["name"] or "").lower() != "openrgb.exe":
                    continue
                cmd = [c.lower() for c in (p.info.get("cmdline") or [])]
                if ((p.info["exe"] or "").lower().startswith(ours)
                        or ("--server" in cmd and "--noautoconnect" in cmd)):
                    out.append(p)
            except Exception:
                continue
        return out

    def stop_own_copies(self) -> bool:
        """Close every hidden OpenRGB of ours so the next start detects hardware from scratch."""
        self.stop()
        found = self.own_copies()
        for p in found:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                pass
        return bool(found)

    def stop(self):
        """Close the hidden OpenRGB this app started (when quitting)."""
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
            except Exception:
                pass

    @staticmethod
    def server_running(timeout=0.5) -> bool:
        try:
            with socket.create_connection((SDK_HOST, SDK_PORT), timeout=timeout):
                return True
        except OSError:
            return False

    def find_exe(self) -> Path | None:
        cands: list[Path] = []
        saved = self.settings["openrgb_path"]
        if saved:
            cands.append(Path(saved))
        here = app_dir()
        cands += [here / "OpenRGB.exe", here / "OpenRGB" / "OpenRGB.exe"]
        for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            if os.environ.get(env):
                cands.append(Path(os.environ[env]) / "OpenRGB" / "OpenRGB.exe")
        if os.environ.get("LOCALAPPDATA"):
            cands.append(Path(os.environ["LOCALAPPDATA"]) / "Programs" / "OpenRGB" / "OpenRGB.exe")
        for c in cands:
            if c.is_file():
                return c
        # Our own downloaded copy (zip may contain a sub-folder)
        own = install_dir() / "OpenRGB"
        if own.is_dir():
            for c in own.rglob("OpenRGB.exe"):
                return c
        return None

    def latest_zip_url(self) -> str:
        try:
            req = urllib.request.Request(RELEASES_PAGE, headers={"User-Agent": APP_NAME})
            html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
            # the newest Windows 64-bit zip on the page, 1.0 or newer (older ones can't reach RGB RAM)
            url = pick_openrgb_zip(html)
            if url:
                return url
            self.log("The OpenRGB releases page lists no Windows build of 1.0 or newer; using the known 1.1 link.")
        except Exception as e:
            self.log(f"Couldn't read the OpenRGB releases page ({e}); using known 1.1 link.")
        return FALLBACK_ZIP

    def download(self, progress=lambda pct: None) -> Path:
        url = self.latest_zip_url()
        self.log(f"Downloading OpenRGB: {url}")
        tmp = Path(tempfile.gettempdir()) / "openrgb_download.zip"
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    progress(int(got * 100 / total))
        dest = install_dir() / "OpenRGB"
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        with zipfile.ZipFile(tmp) as z:
            for member in z.namelist():  # refuse paths that escape the folder
                target = (dest / member).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise RuntimeError(f"Unsafe path in zip: {member}")
            z.extractall(dest)
        tmp.unlink(missing_ok=True)
        exe = next(dest.rglob("OpenRGB.exe"), None)
        if not exe:
            raise RuntimeError("Downloaded OpenRGB but couldn't find OpenRGB.exe inside the zip.")
        try:                       # remember which release this is (the zip's folder may not say)
            (exe.parent / OPENRGB_MARKER).write_text(url.rsplit("/", 1)[-1] + "\n", encoding="utf-8")
        except Exception:
            pass
        self.settings["openrgb_path"] = str(exe)
        self.log(f"OpenRGB installed to {exe.parent} (version {openrgb_version(exe) or 'unknown'})")
        return exe

    def launch(self, exe: Path, wait=45) -> bool:
        ver = openrgb_version(exe)
        self.log(f"Starting OpenRGB {ver or '(version unknown)'} SDK server ({exe}) ...")
        if openrgb_too_old(ver):
            self.log(f"This OpenRGB ({ver}) is older than 1.0: it can't reach RGB RAM on Windows 11. Delete it or "
                     "point Settings > OpenRGB at OpenRGB 1.0 or newer.")
        if rgb_ram_sticks():
            # RGB RAM is installed: a RAM detector switched off in OpenRGB means the sticks are never searched
            turned_on = enable_ram_detectors(openrgb_config_paths(exe))
            if turned_on:
                self.log("Turned OpenRGB's RAM detectors back on (they were switched off in OpenRGB): "
                         + ", ".join(turned_on))
        try:
            # --server alone runs OpenRGB headless: no window, no tray icon, no taskbar entry
            # (--startminimized would load its GUI into the tray). The console is hidden too.
            si = None
            if IS_WIN:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0                       # SW_HIDE
            self.proc = subprocess.Popen([str(exe), "--server", "--noautoconnect"], cwd=str(exe.parent),
                                         creationflags=NO_WINDOW, startupinfo=si, env=child_env(),
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError as e:
            self.log(f"Could not start OpenRGB: {e}")
            return False
        t0 = time.time()
        while time.time() - t0 < wait:
            if self.server_running():
                self.log("OpenRGB server is up.")
                return True
            if self.proc.poll() is not None:
                self.log("OpenRGB closed right after starting (another copy may already be open "
                         "without the SDK server - close it from the system tray and press Rescan).")
                return False
            time.sleep(0.5)
        self.log("OpenRGB didn't open its SDK server in time.")
        return False


# --------------------------------------------------------------------------- RGB RAM check
# RAM sticks Windows reports ("Manufacturer PartNumber", filled in by system_check). Empty off Windows.
RAM_INVENTORY: list[str] = []

# Part numbers of RGB memory lines OpenRGB drives over the SMBus. Used only to notice that RGB RAM is
# installed but OpenRGB found none of it; a stick that isn't listed here just isn't checked.
RGB_RAM_PARTS = (
    (re.compile(r"^CMR\d", re.I), "Corsair Vengeance RGB"),           # e.g. CMR16GX4M2C3200C16 (DDR4)
    (re.compile(r"^CMW\d", re.I), "Corsair Vengeance RGB PRO"),       # e.g. CMW32GX4M2D3600C18 (DDR4)
    (re.compile(r"^CMN\d", re.I), "Corsair Vengeance RGB PRO SL"),
    (re.compile(r"^CMG\d", re.I), "Corsair Vengeance RGB RS"),
    (re.compile(r"^CMH\d", re.I), "Corsair Vengeance RGB DDR5"),
    (re.compile(r"^CMT\d", re.I), "Corsair Dominator Platinum RGB"),
    (re.compile(r"^CMP\d", re.I), "Corsair Dominator Titanium RGB"),    # DDR5, e.g. CMP32GX5M2B6000C30
    (re.compile(r"^F5-\S*(TZ5R|TZ5NR|TZ5CK|TZ5CR)", re.I), "G.Skill Trident Z5 RGB"),   # e.g. F5-6000J3636F16GX2-TZ5RK
    (re.compile(r"^F[45]-\S*(GTZR|GTZN|GTZRX|TR5|GTZ5RK|TZ5RK|TZ5NR)", re.I), "G.Skill Trident Z RGB"),
    # Kingston FURY Beast / Renegade RGB (DDR4 and DDR5): the RGB parts end in ...A, e.g. KF560C36BBEA-16
    (re.compile(r"^KF[4-8]\d{2}C\d{2}(BB|BW|RB|RW|RS)[EK]?A", re.I), "Kingston FURY RGB"),
    (re.compile(r"^[TF]F[34]D", re.I), "T-Force Delta RGB"),          # TF3D... (DDR4), FF3D5... (DDR5)
    (re.compile(r"^AX5U\S*-\S*LAB?R", re.I), "XPG Lancer RGB"),       # e.g. AX5U6000C3016G-DCLARBK (DDR5)
)

# Vendor apps known to drive RAM lighting themselves. While one runs it uses the same SMBus as OpenRGB,
# and OpenRGB's RAM probe fails or is skipped.
SMBUS_APPS = {"MSI Center / Mystic Light", "MSI Mystic Light", "Corsair iCUE", "ASUS Armoury Crate",
              "ASUS Aura / Armoury Crate lighting service", "Gigabyte RGB Fusion", "Gigabyte Control Center",
              "SignalRGB", "ASRock Polychrome", "HyperX NGENUITY", "Thermaltake RGB Plus"}


def rgb_ram_sticks(rams=None) -> list[str]:
    """The installed sticks that are RGB memory OpenRGB can light, as friendly names (one per stick)."""
    out = []
    for entry in (RAM_INVENTORY if rams is None else rams):
        words = str(entry).split()
        part = words[-1] if words else ""
        for pat, name in RGB_RAM_PARTS:
            if pat.search(part):
                out.append(name)
                break
    return out


# Corsair memory part numbers start with CM + a letter for the product line. Windows often reports the
# maker of these sticks as "Unknown" (the BIOS leaves it blank), so the maker is taken from the part number.
CORSAIR_LINES = (
    ("CMW", "Vengeance RGB PRO"), ("CMN", "Vengeance RGB PRO SL"), ("CMG", "Vengeance RGB RS"),
    ("CMR", "Vengeance RGB"), ("CMH", "Vengeance RGB DDR5"), ("CMT", "Dominator Platinum RGB"),
    ("CMP", "Dominator Titanium RGB"), ("CMK", "Vengeance LPX, no RGB"), ("CMD", "Dominator Platinum"),
    ("CMU", "Vengeance LED"), ("CMSX", "Vengeance SODIMM"),
)
# JEDEC module-maker codes Windows sometimes shows instead of a name (with or without the bank byte).
JEDEC_MAKERS = {"029E": "Corsair", "9E": "Corsair", "04CD": "G.Skill", "CD": "G.Skill", "0198": "Kingston",
                "98": "Kingston", "859B": "Crucial", "9B": "Crucial", "802C": "Micron", "2C": "Micron",
                "80CE": "Samsung", "CE": "Samsung", "80AD": "SK Hynix", "AD": "SK Hynix", "059B": "Crucial",
                "0B0F": "T-Force", "04CB": "ADATA / XPG", "CB": "ADATA / XPG", "0902": "Patriot"}


def ram_maker(maker, part="") -> str:
    """The memory maker's name from what Windows reports ('Unknown', a JEDEC code like '029E' or
    '9E00000000000000', or a name), falling back to the part number (CM... is Corsair). '' if unknown."""
    m = str(maker or "").strip()
    code = re.sub(r"^0x", "", m, flags=re.I).upper()
    if re.fullmatch(r"[0-9A-F]{2,16}", code):
        code = code.rstrip("0") if len(code) > 4 else code
        code = code if len(code) % 2 == 0 else code + "0"
        if code in JEDEC_MAKERS:
            return JEDEC_MAKERS[code]
        if code[:4] in JEDEC_MAKERS:
            return JEDEC_MAKERS[code[:4]]
        if code[:2] in JEDEC_MAKERS:
            return JEDEC_MAKERS[code[:2]]
        m = ""
    if m.lower() in ("", "unknown", "undefined", "not specified", "manufacturer", "none", "0000", "00"):
        m = ""
    p = str(part or "").strip().upper()
    if not m and re.match(r"^CM[A-Z]{1,3}\d", p):
        return "Corsair"
    if not m and p.startswith("F4-") or not m and p.startswith("F5-"):
        return "G.Skill"
    if not m and p.startswith("KF"):
        return "Kingston"
    return m


def ram_line(part) -> str:
    """Product line for a part number, e.g. CMW32GX4M2D3600C18 -> 'Corsair Vengeance RGB PRO'. '' if unknown."""
    p = str(part or "").strip().upper()
    for prefix, line in sorted(CORSAIR_LINES, key=lambda x: -len(x[0])):
        if p.startswith(prefix) and p[len(prefix):len(prefix) + 1].isdigit():
            return "Corsair " + line
    for pat, name in RGB_RAM_PARTS:
        if pat.search(p):
            return name
    return ""


def split_ram_entry(entry) -> tuple[str, str]:
    """A RAM_INVENTORY entry ('Manufacturer PartNumber') -> (maker as Windows wrote it, part number)."""
    words = str(entry or "").split()
    if not words:
        return "", ""
    if len(words) == 1:
        return "", words[0]
    return " ".join(words[:-1]), words[-1]


def ram_label(entry) -> str:
    """Friendly name for a stick: 'Unknown CMW32GX4M2D3600C18' -> 'Corsair Vengeance RGB PRO (CMW32GX4M2D3600C18)'."""
    maker_raw, part = split_ram_entry(entry)
    maker, line = ram_maker(maker_raw, part), ram_line(part)
    if line:
        name = line if not maker or line.lower().startswith(maker.lower()) else f"{maker} {line}"
    else:
        name = maker or "Unknown maker"
    return f"{name} ({part})" if part else name


def ram_summary(rams) -> str:
    """'4x Corsair Vengeance RGB PRO (CMW32GX4M2D3600C18)' for a list of RAM_INVENTORY entries."""
    counts: dict[str, int] = {}
    for r in rams:
        lab = ram_label(r)
        counts[lab] = counts.get(lab, 0) + 1
    return ", ".join(f"{n}x {lab}" if n > 1 else lab for lab, n in sorted(counts.items()))


def _openrgb_version_from_path(path) -> str | None:
    m = re.search(r"openrgb[ _-]?v?(\d+\.\d+(?:\.\d+)?(?:[ _-]?rc\d*)?)", str(path or ""), re.I)
    return m.group(1).replace("_", "").replace(" ", "") if m else None


OPENRGB_MARKER = "CentralRGB-download.txt"   # written next to OpenRGB.exe: which zip Central RGB installed
OPENRGB_1_PLUS = "1.0 or newer"              # version exactly unknown, but it ships PawnIO modules


_file_versions: dict[str, str | None] = {}


def _file_version(path) -> str | None:
    """Windows file/product version of an exe (None elsewhere or when it has none). Read once per path."""
    if not IS_WIN or not path or not Path(path).is_file():
        return None
    if str(path) in _file_versions:
        return _file_versions[str(path)]
    r = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   f"(Get-Item -LiteralPath '{str(path).replace(chr(39), chr(39) * 2)}').VersionInfo.ProductVersion"],
                  timeout=15)
    v = ((r.stdout or "").strip() if r else "") or None
    if v and not re.search(r"[1-9]", v):          # "0.0.0.0": the exe just doesn't say (OpenRGB leaves it blank)
        v = None
    _file_versions[str(path)] = v
    return v


def openrgb_version(path) -> str | None:
    """OpenRGB's version from its install path, e.g. ...\\OpenRGB_0.9_Windows_64_b5f46e3\\OpenRGB.exe -> '0.9'.
    The release zips are named that way. When the path doesn't say: the zip Central RGB downloaded (noted
    next to the exe), then the exe's own version info on Windows. None when nothing says."""
    v = _openrgb_version_from_path(path)
    if v or not path:
        return v
    try:
        marker = Path(path).parent / OPENRGB_MARKER
        if marker.is_file():
            v = _openrgb_version_from_path(marker.read_text(encoding="utf-8", errors="replace"))
            if v:
                return v
    except Exception:
        pass
    try:
        fv = _file_version(path)
        m = re.match(r"\s*(\d+\.\d+(?:\.\d+)?(?:\s*rc\d*)?)", fv or "", re.I)
        if m and re.search(r"[1-9]", m.group(1)):
            return m.group(1).replace(" ", "")
    except Exception:
        pass
    # PawnIO SMBus modules next to the exe only ship with OpenRGB 1.0 and newer
    return OPENRGB_1_PLUS if pawnio_modules(path) else None


def _version_key(v) -> tuple:
    """Sort key for '0.9', '1.0rc1', '1.0rc2', '1.0', '1.1': a release candidate sorts before its release."""
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?(?:rc(\d*))?", str(v or ""), re.I)
    if not m:
        return (-1,)
    rc = m.group(4)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), 0 if rc is not None else 1, int(rc or 0))


def pick_openrgb_zip(html: str) -> str | None:
    """The newest Windows 64-bit OpenRGB zip linked on the releases page, never one older than 1.0 (those
    reach the SMBus through WinRing0, which Windows 11 blocks, so RAM lighting is never found)."""
    best, best_key = None, None
    for url in re.findall(r'https?://[^"\'\s>]+Windows_64[^"\'\s>]*\.zip', html or ""):
        v = _openrgb_version_from_path(url.rsplit("/", 1)[-1]) or _openrgb_version_from_path(url)
        if not v or openrgb_too_old(v):
            continue
        k = _version_key(v)
        if best_key is None or k > best_key:
            best, best_key = url, k
    return best


# --------------------------------------------------------------------------- OpenRGB's RAM detectors
# OpenRGB's detectors that look for RGB RAM on the SMBus. Any of them can be switched off in OpenRGB's
# Settings > Supported Devices; it is then saved as false in OpenRGB.json and that RAM is never searched for.
RAM_DETECTOR_WORDS = ("dram", "ddr4", "ddr5", "vengeance", "dominator", "trident", "fury", "ripjaws", "viper",
                      "spectrix", "lancer", "t-force", "tforce", "xtreem", "crucial", "ballistix", "ene smbus",
                      "sector 5", "hyperx predator", "hyperx fury")


def is_ram_detector(name) -> bool:
    n = str(name or "").lower()
    return any(w in n for w in RAM_DETECTOR_WORDS)


def openrgb_config_paths(exe=None) -> list[Path]:
    """Where OpenRGB keeps OpenRGB.json: %APPDATA%\\OpenRGB, or next to a portable OpenRGB.exe."""
    out = []
    if os.environ.get("APPDATA"):
        out.append(Path(os.environ["APPDATA"]) / "OpenRGB" / "OpenRGB.json")
    if exe:
        out.append(Path(exe).parent / "OpenRGB.json")
    return out


def ram_detector_settings(paths=None) -> tuple[Path | None, dict]:
    """(OpenRGB.json that exists, {detector name: enabled} for its RAM detectors). (None, {}) if none."""
    for p in (openrgb_config_paths() if paths is None else paths):
        try:
            if not Path(p).is_file():
                continue
            data = json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
            dets = ((data.get("Detectors") or {}).get("detectors") or {}) if isinstance(data, dict) else {}
            return Path(p), {k: bool(v) for k, v in dets.items() if is_ram_detector(k)}
        except Exception:
            continue
    return None, {}


def enable_ram_detectors(paths=None) -> list[str]:
    """Switch OpenRGB's RAM detectors back on in OpenRGB.json if they were switched off (only call this when
    RGB RAM is installed). Returns the detectors that were turned on. Leaves the file alone otherwise."""
    path, dets = ram_detector_settings(paths)
    off = sorted(k for k, on in dets.items() if not on)
    if not path or not off:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        for k in off:
            data["Detectors"]["detectors"][k] = True
        tmp = path.with_suffix(".centralrgb.tmp")
        tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
        tmp.replace(path)
        return off
    except Exception:
        return []


# --------------------------------------------------------------------------- RAM diagnostics
# Words in OpenRGB's own log that say what it did on the SMBus (buses found, RAM detectors run, PawnIO).
OPENRGB_LOG_WORDS = ("smbus", "i2c", "piix4", "i801", "pawnio", "winring0", "dram", "vengeance", "dominator",
                     "spd", "detection")
_last_ram_diag = {"text": ""}


# USB vendor ids -> brand, to say which device OpenRGB is waiting on while detection is stuck
USB_BRANDS = {"1038": "SteelSeries", "1532": "Razer", "046D": "Logitech", "1B1C": "Corsair", "0951": "HyperX",
              "03F0": "HyperX", "1E7D": "Roccat", "0B05": "ASUS", "2516": "Cooler Master", "258A": "Glorious",
              "1462": "MSI", "048D": "Gigabyte", "26CE": "ASRock", "1044": "Gigabyte", "0CF2": "Lian Li",
              "1E71": "NZXT", "3633": "Glorious", "320F": "Glorious", "1A2C": "Generic"}


def openrgb_detection_state(log_dir=None, since=None) -> tuple[str | None, str | None]:
    """Whether OpenRGB has finished looking for hardware, read from its newest log:
    ("done", None), ("running", brand of the last USB device it was checking, or None), or (None, None) when
    there is no log written since `since` (a time.time() value) to tell."""
    if log_dir is None:
        if not os.environ.get("APPDATA"):
            return None, None
        log_dir = Path(os.environ["APPDATA"]) / "OpenRGB" / "logs"
    try:
        logs = sorted(Path(log_dir).glob("OpenRGB_*.log"), key=lambda p: p.stat().st_mtime)
        if not logs or (since is not None and logs[-1].stat().st_mtime < since - 5):
            return None, None
        text = logs[-1].read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, None
    if "Detection completed" in text:
        return "done", None
    hits = re.findall(r"HID device connected: \[([0-9a-fA-F]{4}):[0-9a-fA-F]{4}", text)
    return "running", (USB_BRANDS.get(hits[-1].upper()) if hits else None)


def still_detecting_note(waiting=None, conflicts=None) -> str:
    """What to tell the user while OpenRGB is still looking for hardware well after it started."""
    apps = {"SteelSeries": ("SteelSeries GG", "SteelSeries Engine"), "Razer": ("Razer Synapse",),
            "Corsair": ("Corsair iCUE",), "Logitech": ("Logitech G HUB",)}.get(waiting or "", ())
    held = [a for a in apps if a in (conflicts or {})]
    msg = "OpenRGB is still detecting hardware" + (f" (it's waiting on a {waiting} device)" if waiting else "") + \
          ". Devices it finds later are added on their own, so keep Central RGB open."
    if held:
        msg += (f" {' and '.join(held)} is running and can hold that device for minutes; press Close them on the "
                "Devices page to let OpenRGB finish sooner.")
    return msg


def openrgb_log_lines(log_dir=None, limit=12) -> tuple[Path | None, list[str]]:
    """(newest OpenRGB log file, its lines about the SMBus / RAM detection, at most `limit`)."""
    if log_dir is None:
        if not os.environ.get("APPDATA"):
            return None, []
        log_dir = Path(os.environ["APPDATA"]) / "OpenRGB" / "logs"
    try:
        logs = sorted(Path(log_dir).glob("*.log"), key=lambda p: p.stat().st_mtime)
    except Exception:
        return None, []
    if not logs:
        return None, []
    try:
        text = logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return logs[-1], []
    hits = [ln.strip()[:160] for ln in text if any(w in ln.lower() for w in OPENRGB_LOG_WORDS)]
    return logs[-1], hits[-limit:]


def process_elevated(pid) -> bool | None:
    """True if that process runs as administrator (elevated). None off Windows or when it can't be read."""
    if not IS_WIN or not pid:
        return None
    try:
        k32, adv = ctypes.windll.kernel32, ctypes.windll.advapi32
        h = k32.OpenProcess(0x1000, False, int(pid))         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            tok = ctypes.c_void_p()
            if not adv.OpenProcessToken(h, 0x0008, ctypes.byref(tok)):   # TOKEN_QUERY
                return None
            try:
                elev, size = ctypes.c_ulong(0), ctypes.c_ulong(0)
                if not adv.GetTokenInformation(tok, 20, ctypes.byref(elev), 4, ctypes.byref(size)):  # TokenElevation
                    return None
                return bool(elev.value)
            finally:
                k32.CloseHandle(tok)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def running_openrgb() -> tuple[str | None, int | None, list[str]]:
    """(exe path, pid, command line) of a running OpenRGB.exe, or (None, None, [])."""
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe", "cmdline"]):
            if (p.info["name"] or "").lower() == "openrgb.exe":
                return p.info.get("exe"), p.pid, list(p.info.get("cmdline") or [])
    except Exception:
        pass
    return None, None, []


def pawnio_modules(exe) -> list[str]:
    """PawnIO SMBus modules shipped next to OpenRGB.exe (SmbusPIIX4.bin is the one AMD boards need)."""
    if not exe:
        return []
    try:
        folder = Path(exe).parent
        return sorted({p.name for p in folder.rglob("*.bin") if "smbus" in p.name.lower() or "pawn" in p.name.lower()
                       or "lpcio" in p.name.lower()})
    except Exception:
        return []


def cpu_vendor() -> str:
    import platform
    s = (platform.processor() or "") + " " + os.environ.get("PROCESSOR_IDENTIFIER", "")
    return "AMD" if ("amd" in s.lower() or "authenticamd" in s.lower()) else ("Intel" if "intel" in s.lower() else "")


def ram_diagnostics(found_types=(), rams=None, admin=None, pawnio=None, conflicts=None, exe=None, pid=None,
                    cmdline=None, started_by_central=None, elevated=None, openrgb_ver=None, config_paths=None,
                    log_dir=None, cpu=None) -> list[str]:
    """Everything needed to tell why OpenRGB found no RGB RAM, as plain 'name: value' lines. Every value
    can be passed in (tests); anything left out is read from this PC (and says 'unknown' off Windows)."""
    rams = RAM_INVENTORY if rams is None else rams
    if exe is None and pid is None:
        exe, pid, cmdline = running_openrgb()
    cmd = [c.lower() for c in (cmdline or [])]
    if started_by_central is None:
        started_by_central = bool(cmd) and "--server" in cmd and "--noautoconnect" in cmd
    admin = is_admin() if admin is None else admin
    if elevated is None:
        elevated = process_elevated(pid)
        if elevated is None and started_by_central:
            elevated = admin                       # a child started by Central RGB has its rights
    pawnio = pawnio_installed() if pawnio is None else pawnio
    conflicts = find_conflicts() if conflicts is None else conflicts
    ver = openrgb_ver or (openrgb_version(exe) if exe else None)
    cpu = cpu_vendor() if cpu is None else cpu
    bus = {"AMD": "AMD (piix4 SMBus, needs PawnIO module SmbusPIIX4)",
           "Intel": "Intel (i801 SMBus, needs PawnIO module SmbusI801)"}.get(cpu, cpu or "unknown")
    mods = pawnio_modules(exe)
    cfg, dets = ram_detector_settings(openrgb_config_paths(exe) if config_paths is None else config_paths)
    smbus = sorted(n for n in conflicts if n in SMBUS_APPS)
    other = sorted(n for n in conflicts if n not in SMBUS_APPS)
    log_file, log_hits = openrgb_log_lines(log_dir)
    if not exe:
        started = "not running"
    elif started_by_central:
        started = "by Central RGB (hidden, --server --noautoconnect)"
    else:
        started = "outside Central RGB (" + (" ".join(cmdline[1:]) if cmdline and len(cmdline) > 1 else "no options") + ")"
    yn = {True: "yes", False: "no", None: "unknown"}
    lines = [
        f"OpenRGB: {ver or 'version unknown'}" + (" (too old: uses WinRing0, which Windows 11 blocks)"
                                                   if openrgb_too_old(ver) else "") + f" at {exe or '-'}",
        f"OpenRGB started: {started}; running as administrator: {yn[elevated]}",
        f"Central RGB running as administrator: {yn[bool(admin)]}",
        f"PawnIO driver installed: {yn[bool(pawnio)]}; PawnIO modules next to OpenRGB: "
        + (", ".join(mods) if mods else "none found"),
        f"CPU / SMBus: {bus}",
        "OpenRGB RAM detectors" + (f" ({cfg})" if cfg else "") + ": "
        + (", ".join(f"{k} {'on' if v else 'OFF'}" for k, v in sorted(dets.items())) if dets
           else "all on (OpenRGB's defaults)" if cfg else "no OpenRGB.json yet (defaults: all on)"),
        "Devices OpenRGB reported: " + (", ".join(sorted(set(found_types))) if found_types else "none"),
        "Apps that use the RAM's SMBus running: " + (", ".join(smbus) if smbus else "none")
        + ("; other RGB apps (USB only, they don't hold the SMBus): " + ", ".join(other) if other else ""),
        "RAM part numbers (Windows): " + (_ram_raw_summary(rams) if rams else "none"),
    ]
    if log_file:
        lines.append(f"OpenRGB log {log_file.name}: " + (" | ".join(log_hits) if log_hits
                                                         else "no SMBus / RAM lines (no bus or RAM detector ran)"))
    else:
        lines.append("OpenRGB log: none found (%APPDATA%\\OpenRGB\\logs)")
    return lines


def last_ram_diagnostics() -> list[str]:
    """The RAM diagnostics from the last time RGB RAM was missing ([] if it never was)."""
    return list(_last_ram_diag.get("lines") or [])


def _ram_raw_summary(rams) -> str:
    """'4x "Unknown CMW32GX4M2D3600C18" = Corsair Vengeance RGB PRO (CMW32GX4M2D3600C18)': what Windows said, and what it is."""
    counts: dict[str, int] = {}
    for r in rams:
        counts[str(r)] = counts.get(str(r), 0) + 1
    return ", ".join(f"{n}x \"{r}\" = {ram_label(r)}" for r, n in sorted(counts.items()))


def write_ram_diagnostics(lines) -> Path | None:
    """Save the RAM diagnostics to ram-diagnostics.txt (copy it into a bug report) and add them to
    activity.log once (again only when something changed). Returns the file, None if it couldn't be written."""
    text = "\n".join(lines)
    try:
        d = settings_dir()
        out = d / "ram-diagnostics.txt"
        out.write_text(f"Central RGB {APP_VERSION} RAM diagnostics, {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                       + text + "\n", encoding="utf-8")
        if text != _last_ram_diag["text"]:
            _last_ram_diag["text"] = text
            with open(d / "activity.log", "a", encoding="utf-8") as f:
                stamp = time.strftime("%H:%M:%S  ")
                f.write(stamp + f"RAM diagnostics (also in {out}):\n")
                for ln in lines:
                    f.write(stamp + "  " + ln + "\n")
        return out
    except Exception:
        return None


def is_own_openrgb(path) -> bool:
    """True for the OpenRGB that Central RGB downloaded itself (under its own install folder)."""
    try:
        return Path(install_dir(), "OpenRGB").resolve() in Path(path).resolve().parents
    except Exception:
        return False


def openrgb_too_old(version) -> bool:
    """OpenRGB before 1.0 reached the SMBus through the WinRing0 driver, which Windows 11 now blocks."""
    m = re.match(r"(\d+)", str(version or ""))
    return bool(m) and int(m.group(1)) < 1


def running_openrgb_exe() -> str | None:
    """Path of a running OpenRGB.exe, if any (Windows; None elsewhere or when it can't be read)."""
    try:
        import psutil
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info["name"] or "").lower() == "openrgb.exe" and p.info.get("exe"):
                return p.info["exe"]
    except Exception:
        pass
    return None


def diagnose_missing_ram(found_types, rams=None, admin=None, pawnio=None, conflicts=None,
                         external_openrgb=False, openrgb_ver=None, ddr5=None,
                         searched_before=False, openrgb_path=None) -> dict | None:
    """If Windows reports RGB RAM but OpenRGB found no RAM device, explain why and what to change.

    found_types: the device type names OpenRGB reported ("RAM", "Motherboard"...).
    ddr5: the RAM is DDR5 (None: ask Windows). searched_before: OpenRGB already searched for hardware
    earlier this boot (DDR5 RGB RAM is usually only found on the first search).
    Returns None when there's nothing to report, else {"sticks", "names", "reasons", "blockers", "summary"}:
    reasons are plain sentences, blockers the vendor apps holding the SMBus (they can be closed)."""
    sticks = rgb_ram_sticks(rams)
    if not sticks or "RAM" in set(found_types):
        return None
    ddr5 = ddr5_installed() if ddr5 is None else ddr5
    admin = is_admin() if admin is None else admin
    pawnio = pawnio_installed() if pawnio is None else pawnio
    conflicts = find_conflicts() if conflicts is None else conflicts
    blockers = sorted(n for n in conflicts if n in SMBUS_APPS)
    reasons = []
    if not admin:
        reasons.append("Central RGB isn't running as administrator, so OpenRGB can't open the SMBus the RAM "
                       "lighting sits on. Right-click Central RGB > Run as administrator.")
    if not pawnio:
        reasons.append("The PawnIO driver isn't installed. OpenRGB 1.x reaches RGB RAM through it - install "
                       "it (Settings > Install PawnIO), then restart Windows.")
    if openrgb_too_old(openrgb_ver):
        reasons.append(f"Your OpenRGB is version {openrgb_ver}. Before 1.0 it reached RGB RAM through the old "
                       "WinRing0 driver, which Windows 11 blocks. Install OpenRGB 1.0 or newer (openrgb.org) "
                       "together with PawnIO.")
    if openrgb_path and not openrgb_ver and not is_own_openrgb(openrgb_path):
        reasons.append(f"Central RGB is using an OpenRGB it didn't install ({openrgb_path}) and can't tell which "
                       "version it is. If it's older than 1.0 it can't reach RGB RAM on Windows 11. Uninstall that "
                       "OpenRGB (or delete its folder) and reopen Central RGB: it then downloads OpenRGB 1.1 itself.")
    if blockers:
        reasons.append(", ".join(blockers) + " is using the RAM's SMBus, so OpenRGB can't detect the sticks. "
                       "Press Close them: its services are stopped and set to start manually, then the RAM is "
                       "detected again.")
    if external_openrgb:
        reasons.append("OpenRGB was started outside Central RGB, and it only looks for RAM when it starts. "
                       "Quit that OpenRGB (its tray icon > Exit) and press Rescan, so Central RGB starts it fresh.")
    if ddr5 and searched_before:
        reasons.append("OpenRGB already searched for your RAM earlier this boot. DDR5 RGB RAM is usually only "
                       "found on the first search after the PC starts, so searching again won't find it. "
                       + RAM_SHUTDOWN_TIP)
    if not reasons:
        reasons.append("Nothing obvious is blocking the SMBus. Restart Windows (a vendor driver may still hold "
                       "it), keep MSI Center / Mystic Light from starting with Windows, and check that OpenRGB "
                       "on its own finds the RAM.")
    if ddr5:
        reasons.append(ddr5_unsupported_note())
    try:                       # what to read off this PC next time: saved to activity.log and ram-diagnostics.txt
        diag = ram_diagnostics(found_types, rams=rams, admin=admin, pawnio=pawnio, conflicts=conflicts,
                               openrgb_ver=openrgb_ver,
                               **({"started_by_central": False} if external_openrgb else {}))
        _last_ram_diag["lines"] = diag
        write_ram_diagnostics(diag)
    except Exception:
        pass
    names = ", ".join(sorted(set(sticks)))
    kind = "DDR5 RGB RAM" if ddr5 else "RGB RAM"
    summary = f"{len(sticks)} {kind} stick(s) installed ({names}) but none were found."
    title = ("DDR5 RAM not supported by this OpenRGB" if ddr5 and openrgb_too_old(openrgb_ver)
             else f"{kind} not detected")
    return {"kind": "ram", "title": title, "sticks": len(sticks), "names": names,
            "reasons": reasons, "blockers": blockers, "summary": summary}


def ddr5_unsupported_note() -> str:
    """The last word on DDR5 RGB RAM that stays missing: OpenRGB doesn't support that kit on this PC yet."""
    return ("If it's still missing after a full shutdown with nothing else blocking it, OpenRGB doesn't support "
            "this DDR5 kit on this motherboard yet (see openrgb.org/devices.html). Central RGB only lights the "
            "RAM through OpenRGB and never writes to the RAM itself, so it can't light a kit OpenRGB doesn't find.")


# --------------------------------------------------------------------------- RGB mouse check
# What Windows reports (PNPDeviceID, "...VID_1038&PID_1836...") for pointing devices and keyboards; filled in
# by system_check, empty off Windows. Keyboards are listed so a keyboard's own mouse interface (Razer and
# others add one) isn't taken for a mouse.
MOUSE_INVENTORY: list[str] = []
KEYBOARD_INVENTORY: list[str] = []

# USB vendor IDs of RGB mouse makers whose mice OpenRGB can light -> (brand, the vendor apps that drive them).
RGB_MOUSE_VENDORS = {
    "1038": ("SteelSeries", ("SteelSeries GG", "SteelSeries Engine")),
    "1532": ("Razer", ("Razer Synapse",)),
    "046D": ("Logitech", ("Logitech G HUB",)),
    "1B1C": ("Corsair", ("Corsair iCUE",)),
    "0951": ("HyperX", ("HyperX NGENUITY",)),
    "03F0": ("HyperX", ("HyperX NGENUITY",)),
    "1E7D": ("Roccat", ()),
    "0B05": ("ASUS ROG", ("ASUS Armoury Crate",)),
    "2516": ("Cooler Master", ()),
    "258A": ("Glorious", ()),
}


# --------------------------------------------------------------------------- ARGB headers (resizable zones)
def resizable_zones(dev) -> list[dict]:
    """The zones of a device whose LED count you set yourself: ARGB headers (JRAINBOW, ADD_GEN2...) and LED
    strip ports, which OpenRGB can't count. [{"index", "name", "leds", "min", "max"}], [] if none."""
    out = []
    data_zones = getattr(getattr(dev, "data", None), "zones", None) or []
    for i, z in enumerate(getattr(dev, "zones", None) or []):
        zd = data_zones[i] if i < len(data_zones) else z
        lo, hi = getattr(zd, "leds_min", None), getattr(zd, "leds_max", None)
        ztype = getattr(z, "type", getattr(zd, "zone_type", None))
        if lo is None or hi is None or int(hi) <= int(lo) or int(ztype or 0) == 2:    # 2 = matrix (keyboards)
            continue
        out.append({"index": i, "name": z.name, "leds": len(z.leds), "min": int(lo), "max": int(hi)})
    return out


def unset_headers(devices, sizes=None) -> list[tuple[str, list[str]]]:
    """Devices with ARGB headers left at 0 LEDs (nothing set up yet): [(device name, [header names])]."""
    sizes = sizes or {}
    out = []
    for d in devices:
        names = [z["name"] for z in resizable_zones(d) if z["leds"] == 0
                 and z["name"] not in sizes.get(device_key(d), {})]      # a 0 you set yourself = not used
        if names:
            out.append((d.name, names))
    return out


def diagnose_unset_headers(devices, sizes=None) -> dict | None:
    """A Devices-page note when lights plugged into a motherboard header can't light yet: the header is set to
    0 LEDs (OpenRGB can't count what's plugged in). Same shape as diagnose_missing_ram."""
    found = unset_headers(devices, sizes)
    if not found:
        return None
    where = "; ".join(f"{dev}: {', '.join(names)}" for dev, names in found)
    headers = [n for _, names in found for n in names]
    devs = ", ".join(dev for dev, _ in found)
    return {"kind": "headers", "title": "Fan or strip lights not set up", "names": where, "blockers": [],
            "summary": f"{', '.join(headers)} {'is' if len(headers) == 1 else 'are'} at 0 LEDs ({devs})",
            "reasons": ["Lights plugged into a header at 0 LEDs stay dark, because OpenRGB can't count them. Press "
                        "Customize on that device and set Connected LEDs for each header to the number of LEDs "
                        "plugged into it (most RGB fans have 8 to 18 each; add them up if they are chained). "
                        "Central RGB remembers it and sets it again every time it starts. For a header with "
                        "nothing on it, type 0 and press Enter to hide this note."]}


def _vid_pid(entry) -> tuple[str, str] | None:
    m = re.search(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", str(entry), re.I)
    return (m.group(1).upper(), m.group(2).upper()) if m else None


def rgb_mice(mice=None, keyboards=None) -> list[tuple[str, str, str]]:
    """The connected mice from RGB mouse makers, as (brand, vendor id, product id), one per device."""
    kb = {_vid_pid(k) for k in (KEYBOARD_INVENTORY if keyboards is None else keyboards)}
    seen, out = set(), []
    for entry in (MOUSE_INVENTORY if mice is None else mice):
        vp = _vid_pid(entry)
        if not vp or vp in kb or vp in seen or vp[0] not in RGB_MOUSE_VENDORS:
            continue
        seen.add(vp)
        out.append((RGB_MOUSE_VENDORS[vp[0]][0], vp[0], vp[1]))
    return out


def diagnose_missing_mouse(found_types, mice=None, keyboards=None, conflicts=None) -> dict | None:
    """If Windows reports a mouse from an RGB mouse maker but OpenRGB found no mouse, explain why and what to do.
    Returns None when there's nothing to report, else the same shape as diagnose_missing_ram."""
    found = rgb_mice(mice, keyboards)
    if not found or "Mouse" in set(found_types):
        return None
    conflicts = find_conflicts() if conflicts is None else conflicts
    brands = sorted({b for b, _, _ in found})
    blockers = sorted({a for _, vid, _ in found for a in RGB_MOUSE_VENDORS[vid][1] if a in conflicts})
    ids = ", ".join(f"{vid}:{pid}" for _, vid, pid in found)
    reasons = []
    if blockers:
        reasons.append(", ".join(blockers) + " is running and holds the mouse's lighting (its HID interface), so "
                       "OpenRGB skips the mouse or loses it to that app. Press Close them, then Central RGB "
                       "detects your devices once more. Keep it from starting with Windows so it stays free.")
    reasons.append(f"If the mouse still doesn't show, OpenRGB doesn't support that model yet (USB ID {ids}): "
                   "check openrgb.org/devices.html. Central RGB lists every device OpenRGB reports.")
    summary = f"{' / '.join(brands)} mouse connected (USB ID {ids}) but OpenRGB didn't report it."
    return {"kind": "mouse", "title": "Mouse not detected", "names": ", ".join(brands), "reasons": reasons,
            "blockers": blockers, "summary": summary}


# Keyboards people have asked about that OpenRGB can't light yet: (vendor id, product id) -> (name, OpenRGB issue).
# Only USB IDs confirmed in OpenRGB's own issue tracker go here.
UNSUPPORTED_KEYBOARDS = {
    ("046D", "C356"): ("Logitech G915 X LIGHTSPEED", "gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4461"),
    ("046D", "C359"): ("Logitech G915 X (wired)", "gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4540"),
}


def diagnose_missing_keyboard(found_types, keyboards=None) -> dict | None:
    """If Windows reports a keyboard OpenRGB is known not to support yet, and OpenRGB found no keyboard,
    say so plainly (so nobody keeps closing apps and rescanning for it). Same shape as diagnose_missing_ram."""
    if "Keyboard" in set(found_types):
        return None
    seen = []
    for entry in (KEYBOARD_INVENTORY if keyboards is None else keyboards):
        vp = _vid_pid(entry)
        if vp in UNSUPPORTED_KEYBOARDS and vp not in seen:
            seen.append(vp)
    if not seen:
        return None
    names = ", ".join(UNSUPPORTED_KEYBOARDS[vp][0] for vp in seen)
    ids = ", ".join(f"{v}:{p}" for v, p in seen)
    reasons = [f"OpenRGB doesn't support the {names} yet (USB ID {ids}), so Central RGB can't light it. Support "
               "has been requested: " + "; ".join(UNSUPPORTED_KEYBOARDS[vp][1] for vp in seen) + ". Central RGB "
               "lights it as soon as an OpenRGB update adds it.",
               "Until then, set its lighting in Logitech G HUB, which only controls Logitech gear. Close them also "
               "closes G HUB; the keyboard then shows its built-in lighting until you open G HUB again."]
    return {"kind": "keyboard", "title": "Keyboard not supported yet", "names": names, "reasons": reasons,
            "blockers": [], "summary": f"{names} connected (USB ID {ids}); OpenRGB can't light it yet."}


def diagnose_missing_devices(found_types, conflicts=None, **ram_kw) -> list[dict]:
    """Every installed RGB device OpenRGB didn't report (RAM, mouse, keyboard), each with its reasons. [] if none."""
    conflicts = find_conflicts() if conflicts is None else conflicts
    out = [diagnose_missing_ram(found_types, conflicts=conflicts, **ram_kw),
           diagnose_missing_mouse(found_types, conflicts=conflicts),
           diagnose_missing_keyboard(found_types)]
    return [d for d in out if d]


# --------------------------------------------------------------------------- system check
def system_check() -> list[tuple[str, str]]:
    """Returns [(level, message)], level in {'ok','warn','info','bad'}."""
    out: list[tuple[str, str]] = []
    if not IS_WIN:
        out.append(("info", "Not running on Windows - skipping Windows-specific checks."))
        return out

    out.append(("ok", "Running as administrator.") if is_admin() else
               ("bad", "NOT running as administrator - RAM and many motherboards can't be controlled. "
                       "Right-click Central RGB > Run as administrator."))

    pawn = False
    r = run_quiet(["sc", "query", "PawnIO"])
    if r and r.returncode == 0:
        pawn = True
    for env in ("ProgramFiles", "ProgramW6432"):
        if os.environ.get(env) and (Path(os.environ[env]) / "PawnIO").exists():
            pawn = True
    out.append(("ok", "PawnIO driver found (needed for RAM / older motherboards).") if pawn else
               ("warn", f"PawnIO driver not found. Install it from {PAWNIO_PAGE} if your RAM or "
                        "motherboard lighting doesn't show up."))

    r = run_quiet(["tasklist", "/fo", "csv", "/nh"])
    running = set()
    if r and r.stdout:
        for line in r.stdout.splitlines():
            name = line.split('","')[0].strip('"').lower()
            if name in CONFLICTING_APPS:
                running.add(CONFLICTING_APPS[name])
    if running:
        out.append(("warn", "Other RGB software is running and may fight for control: "
                            + ", ".join(sorted(running)) + ". Close it (and disable it at startup)."))
    else:
        out.append(("ok", "No conflicting vendor RGB software detected."))

    ps = ("$o=[ordered]@{"
          "board=(Get-CimInstance Win32_BaseBoard | ForEach-Object { \"$($_.Manufacturer) $($_.Product)\" });"
          "gpu=@(Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name });"
          "ram=@(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { \"$($_.Manufacturer) $($_.PartNumber)\".Trim() });"
          "mouse=@(Get-CimInstance Win32_PointingDevice | ForEach-Object { $_.PNPDeviceID });"
          "kbd=@(Get-CimInstance Win32_Keyboard | ForEach-Object { $_.PNPDeviceID })"
          "}; $o | ConvertTo-Json -Compress")
    r = run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=30)
    try:
        inv = json.loads(r.stdout) if r and r.stdout.strip() else {}
        if inv.get("board"):
            out.append(("info", f"Motherboard: {inv['board']}"))
        gpus = inv.get("gpu") or []
        for g in ([gpus] if isinstance(gpus, str) else gpus):
            out.append(("info", f"Graphics card: {g}"))
        rams = inv.get("ram") or []
        rams = [rams] if isinstance(rams, str) else rams
        RAM_INVENTORY[:] = [str(x) for x in rams]
        if rams:
            out.append(("info", f"RAM sticks: {len(rams)} ({ram_summary(rams)})"))
        for key, inv_list in (("mouse", MOUSE_INVENTORY), ("kbd", KEYBOARD_INVENTORY)):
            items = inv.get(key) or []
            inv_list[:] = [str(x) for x in ([items] if isinstance(items, str) else items) if x]
        for brand, vid, pid in rgb_mice():
            out.append(("info", f"Mouse: {brand} (USB ID {vid}:{pid})"))
    except Exception:
        pass
    if ddr5_installed():
        out.append(("info", "DDR5 RAM: its lighting is searched for once per boot. The hidden OpenRGB keeps "
                            "running after you close Central RGB, and Rescan asks before searching again."))
    return out


# --------------------------------------------------------------------------- effects
_TO_LINEAR = [(v / 255) ** 2.2 for v in range(256)]


def _to_srgb(x: float) -> int:
    return min(255, max(0, int(round(255 * x ** (1 / 2.2))))) if x > 0 else 0


SMOOTH_SAMPLES = 3       # motion blur: time samples averaged per frame
SMOOTH_AA = 4            # anti-aliasing: sub-positions averaged per LED on short strips
SMOOTH_AA_MAX_LEDS = 48  # strips longer than this are already fine-grained enough
# effects where every LED does its own thing (drops, sparkles, embers): averaging across an LED's width would
# blend unrelated LEDs into mud, so these only get motion blur
SMOOTH_AA_SKIP = {"Drizzle", "Ember", "Frost", "Stardust", "Magma", "Cyberpunk"}


def _per_led(effect: str) -> bool:
    if effect in CUSTOM_PRESETS:
        return CUSTOM_PRESETS[effect].get("motion") == "Sparkle"
    return effect in SMOOTH_AA_SKIP


def compute_colors(effect: str, color, brightness: int, speed: int, n: int, t: float,
                   offset: float = 0.0, blur: float = 0.0, aa: bool = False) -> list[tuple[int, int, int]]:
    """Pure function: colors for n LEDs at time t.

    blur (seconds): average the effect over the frame's own time slice (motion blur), so a device updated
    at a low rate (RAM: a few times a second) fades between frames instead of jumping.
    aa: on short strips, each LED shows the average of the effect across its width, so moving edges glide
    from LED to LED instead of popping. With neither (the default) the result is exactly the plain effect."""
    effect = RENAMED.get(effect, effect)
    if (blur > 0 or aa) and is_animated(effect):
        sub = SMOOTH_AA if aa and 1 < n <= SMOOTH_AA_MAX_LEDS and not _per_led(effect) else 1
        times = [t - blur * (0.5 - (k + 0.5) / SMOOTH_SAMPLES) for k in range(SMOOTH_SAMPLES)] if blur > 0 else [t]
        # averaged in linear light (like light really adds up), so a bright spark half across an LED still
        # looks bright instead of turning muddy
        lin = _TO_LINEAR
        acc = [[0.0, 0.0, 0.0] for _ in range(n)]
        for tt in times:
            fine = _compute(effect, color, brightness, speed, n * sub, tt, offset)
            for i in range(n):
                a = acc[i]
                for c in fine[i * sub:(i + 1) * sub]:
                    a[0] += lin[c[0]]
                    a[1] += lin[c[1]]
                    a[2] += lin[c[2]]
        w = len(times) * sub
        return [(_to_srgb(a[0] / w), _to_srgb(a[1] / w), _to_srgb(a[2] / w)) for a in acc]
    return _compute(effect, color, brightness, speed, n, t, offset)


def _compute(effect: str, color, brightness: int, speed: int, n: int, t: float,
             offset: float = 0.0) -> list[tuple[int, int, int]]:
    """The plain effect: colors for n LEDs at time t (effect name already resolved)."""
    n = max(n, 1)
    b = max(0, min(100, brightness)) / 100.0
    f = 0.1 + max(0, min(100, speed)) / 100.0 * 1.4  # 0.1 .. 1.5 Hz-ish

    def scale(rgb, k=1.0):
        return tuple(int(max(0, min(255, round(c * b * k)))) for c in rgb)

    if effect == "Off":
        return [(0, 0, 0)] * n
    if effect in CUSTOM_PRESETS:
        return [scale(c) for c in _custom(CUSTOM_PRESETS[effect], n, t, f, offset)]
    if effect == "Breathing":
        k = 0.03 + 0.97 * (math.sin(2 * math.pi * f * 0.5 * t) + 1) / 2
        return [scale(color, k)] * n
    if effect == "Color Cycle":
        h = (t * f * 0.15 + offset) % 1.0
        return [scale([c * 255 for c in colorsys.hsv_to_rgb(h, 1, 1)])] * n
    if effect == "Rainbow Wave":
        base = t * f * 0.25 + offset
        return [scale([c * 255 for c in colorsys.hsv_to_rgb((base + i / n) % 1.0, 1, 1)])
                for i in range(n)]
    if effect in PRESET_EFFECTS:
        return [scale(c) for c in _preset(effect, n, t * (0.35 + f), offset)]
    return [scale(color)] * n  # Static


def _custom(defn: dict, n: int, t: float, f: float, offset: float = 0.0) -> list:
    """A user-made preset: their colours (2-5) with one of CUSTOM_MOTIONS."""
    cols = [tuple(c) for c in (defn.get("colors") or [(0, 120, 255), (160, 0, 255)])][:5]
    if len(cols) == 1:
        cols = cols * 2
    motion = defn.get("motion", "Wave")
    loop = cols + [cols[0]]                                 # wraps smoothly back to the first colour
    out = []
    if motion == "Gradient":                               # still: colours spread along the LEDs
        return [_palette(cols, i / max(1, n - 1)) for i in range(n)]
    if motion == "Wave":                                   # the gradient flows along the LEDs
        for i in range(n):
            out.append(_palette(loop, (i / max(1, n) + t * f * 0.25 + offset) % 1.0))
    elif motion == "Breathe":                              # fades in and out, a new colour each breath
        ph = t * f * 0.5 + offset
        k = 0.04 + 0.96 * (0.5 - 0.5 * math.cos(2 * math.pi * ph))
        col = cols[int(ph) % len(cols)]
        out = [_mix((0, 0, 0), col, k)] * n
    elif motion == "Cycle":                                # every LED glides through the colours together
        out = [_palette(loop, (t * f * 0.12 + offset) % 1.0)] * n
    elif motion == "Pulse":                                # bright pulses race along over a dim base
        pos = (t * f * 0.45 + offset) % 1.0
        base = _mix((0, 0, 0), cols[0], 0.18)
        for i in range(n):
            d = ((i / max(1, n)) - pos) % 1.0
            k = math.exp(-(min(d, 1 - d) / 0.06) ** 2)
            out.append(_mix(base, _palette(cols[1:] or cols, (i / max(1, n))), k))
    else:                                                  # Sparkle: palette twinkles over the first colour
        base = _mix((0, 0, 0), cols[0], 0.25)
        for i in range(n):
            rate = 0.6 + 2.0 * _rnd(i, 90)
            v = (0.5 + 0.5 * math.sin(t * f * 2.2 * rate + _rnd(i, 91) * 6.28)) ** 10
            out.append(_mix(base, cols[1 + int(_rnd(i, 92) * (len(cols) - 1))] if len(cols) > 1 else cols[0], v))
    return out


def _rnd(a: float, b: float = 0.0) -> float:
    """Repeatable pseudo-random number 0..1 (same inputs, same result), so effects need no stored state."""
    return (math.sin(a * 127.1 + b * 311.7) * 43758.5453) % 1.0


def _mix(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def _smooth(x: float) -> float:
    """0..1 ease (smoothstep), clamped."""
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def _palette(stops, x):
    x = (x % 1.0) * len(stops)
    i = int(x) % len(stops)
    return _mix(stops[i], stops[(i + 1) % len(stops)], x - int(x))


def _preset(effect, n, t, offset=0.0):
    """Colours for the preset effects. t is already scaled by the speed setting."""
    out = []
    if effect == "Tide":            # slow overlapping blue-teal waves
        for i in range(n):
            x = i / n
            w = 0.5 + 0.25 * math.sin(x * 9 + t * 0.9 + offset * 6) + 0.25 * math.sin(x * 4 - t * 0.6)
            out.append(_mix((0, 25, 90), (70, 210, 255), w))
    elif effect == "Drizzle":                # colourful drops that flash and fade on a dark background
        for i in range(n):
            period = 1.2 + 2.2 * _rnd(i, 1 + offset)
            tt = t * 1.3 + _rnd(i, 2) * period
            x, cycle = tt % period, int(tt / period)
            hue = _rnd(i, 10 + cycle)
            drop = [c * 255 for c in colorsys.hsv_to_rgb(hue, 0.9, 1)]
            out.append(_mix((0, 4, 14), drop, _smooth(x / 0.18) * math.exp(-x * 3.5)))   # quick fade in, no pop
    elif effect == "Sweep":        # a rainbow bar sweeping left and right
        pos = 0.5 + 0.5 * math.sin(t * 1.6 + offset * 6)
        for i in range(n):
            x = (i + 0.5) / n
            col = [c * 255 for c in colorsys.hsv_to_rgb((x * 0.9 + t * 0.05) % 1.0, 1, 1)]
            k = max(0.0, 1 - abs(x - pos) * 3.2) if n > 1 else 1.0
            out.append(_mix(_mix((0, 0, 0), col, 0.12), col, k))
    elif effect == "Ember":             # deep red embers that glow at their own pace
        for i in range(n):
            v = 0.5 + 0.5 * math.sin(t * (1.0 + 2.2 * _rnd(i, 3)) + _rnd(i, 4 + offset) * 6.28)
            out.append(_mix((70, 0, 4), (255, 38, 20), v * v))
    elif effect == "Pulse":              # equaliser bar bouncing green to yellow to red
        level = 0.12 + 0.88 * abs(math.sin(t * 2.3 + offset * 9) * math.sin(t * 0.9 + 1.3) + 0.12 * math.sin(t * 3.4)) / 1.12
        for i in range(n):
            x = (i + 0.5) / n
            col = _palette([(0, 255, 60), (0, 255, 60), (255, 230, 0), (255, 40, 0)], x * 0.749)
            if n == 1:
                out.append(_mix((0, 40, 10), _palette([(0, 255, 60), (255, 230, 0), (255, 40, 0)], level * 0.66), 1))
            else:
                out.append(col if x <= level else _mix((0, 0, 0), col, 0.06))
    elif effect == "Drift":       # smooth cyan, blue, violet, pink gradient drifting along
        stops = [(0, 220, 255), (40, 90, 255), (170, 60, 255), (255, 60, 190)]
        out = [_palette(stops, i / n * 0.8 + t * 0.12 + offset) for i in range(n)]
    elif effect == "Volt":          # purple-blue clouds with lightning flashes
        slot, x = int(t * 1.4), (t * 1.4) % 1.0
        strike = _rnd(slot, 7) < 0.45
        centre, flash = _rnd(slot, 8), math.exp(-x * 7) * (0.6 + 0.4 * math.sin(x * 60))
        for i in range(n):
            p = i / n
            base = _mix((70, 0, 160), (20, 40, 220), 0.5 + 0.5 * math.sin(p * 5 + t * 0.7 + offset * 6))
            k = flash * max(0.0, 1 - abs(p - centre) * 2.5) if (strike and n > 1) else (flash if strike else 0)
            out.append(_mix(base, (230, 240, 255), k))
    elif effect == "Frost":           # near-black with cold glints
        for i in range(n):
            v = (0.5 + 0.5 * math.sin(t * (0.6 + 1.5 * _rnd(i, 5)) + _rnd(i, 6 + offset) * 6.28)) ** 6
            out.append(_mix((0, 10, 22), (150, 235, 255), v))
    elif effect == "Aurora":        # green, teal and violet curtains rippling along
        stops = [(20, 255, 140), (0, 210, 220), (120, 70, 255), (20, 255, 140)]
        for i in range(n):
            x = i / max(1, n)
            ripple = 0.5 + 0.5 * math.sin(x * 11 + t * 1.1 + offset * 6) * math.sin(x * 3.7 - t * 0.45)
            col = _palette(stops, (x * 0.6 + t * 0.06 + offset) % 1.0)
            out.append(_mix((0, 8, 20), col, 0.25 + 0.75 * ripple))
    elif effect == "Supernova":     # a white-hot flash bursts from the middle and cools outwards
        period = 2.6
        ph = (t + offset * 3) % period / period
        for i in range(n):
            d = abs((i + 0.5) / n - 0.5) * 2 if n > 1 else 0.0       # 0 centre .. 1 ends
            front = ph * 1.3
            k = math.exp(-((d - front) / 0.16) ** 2)
            heat = max(0.0, 1 - (front - d) * 2.2) if d < front else 0.0
            col = _palette([(255, 250, 235), (255, 170, 60), (255, 60, 150), (90, 30, 200)], min(0.999, ph * 0.9 + d * 0.3))
            glow = _mix((8, 2, 30), col, max(k, heat * 0.55))
            out.append(glow)
    elif effect == "Cascade":       # green code streams falling down the strip, each with a fading trail
        drops = 4
        lv = [0.0] * n
        head_at = [False] * n
        for k in range(drops):
            speed = 0.035 + 0.04 * _rnd(k, 31)
            head = ((t * speed + _rnd(k, 32) + offset) % 1.5) - 0.2       # runs off the end, then restarts
            for i in range(n):
                d = head - (i + 0.5) / n
                if 0 <= d < 0.45:
                    lv[i] = max(lv[i], 1 - d / 0.45)
                    head_at[i] = head_at[i] or d < 1.5 / max(1, n)
        for i in range(n):
            k = lv[i]
            out.append((200, 255, 215) if head_at[i] else (int(30 * k ** 4), int(14 + 230 * k ** 1.5), int(30 * k ** 2)))
    elif effect == "Cyberpunk":     # neon blocks that glitch between magenta, cyan and yellow
        pal = [(255, 40, 200), (0, 240, 255), (255, 225, 30), (150, 60, 255)]
        st = t * 2.2
        slot, frac = int(st), st - int(st)
        fade = _smooth((frac - 0.65) / 0.35)                  # crossfade into the next blocks, no hard cut
        gt = t * 9
        glitch = _rnd(int(gt), 41 + offset) < 0.12
        gk = 0.55 * math.sin(math.pi * (gt - int(gt)))        # a glitch flickers in and out, half strength

        def block_col(s_, i):
            block = int(i / max(1, n) * 6 + _rnd(s_, 43) * 3)
            return int(_rnd(block, s_ + 50) * len(pal)) % len(pal)
        for i in range(n):
            a = block_col(slot, i)
            col = _mix(pal[a], pal[block_col(slot + 1, i)], fade)
            if glitch and _rnd(i, int(gt) + 60) < 0.5:
                col = _mix(col, pal[(a + 1) % len(pal)], gk)
            out.append(col)
    elif effect == "Magma":         # dark rock with slow molten veins flowing through it
        for i in range(n):
            x = i / max(1, n)
            v = math.sin(x * 13 + t * 0.6 + offset * 5) * math.sin(x * 5.3 - t * 0.35 + _rnd(i, 70))
            v = max(0.0, v) ** 2
            col = _palette([(40, 4, 2), (255, 70, 10), (255, 190, 60), (255, 240, 180)], min(0.999, v))
            out.append(_mix((22, 2, 0), col, 0.3 + 0.7 * min(1.0, v * 1.6)))
    elif effect == "Stardust":      # deep navy with warm and cool sparkles twinkling
        for i in range(n):
            rate = 0.6 + 1.8 * _rnd(i, 80)
            v = (0.5 + 0.5 * math.sin(t * rate + _rnd(i, 81 + offset) * 6.28)) ** 8
            star = (255, 225, 170) if _rnd(i, 82) < 0.5 else (190, 215, 255)
            out.append(_mix((6, 6, 28), star, v))
    elif effect == "Nebula":        # slow churning purple, pink and blue clouds
        stops = [(70, 10, 120), (255, 60, 170), (60, 120, 255), (120, 30, 200), (70, 10, 120)]
        for i in range(n):
            x = i / max(1, n)
            w = 0.5 + 0.3 * math.sin(x * 4 + t * 0.35 + offset * 4) + 0.2 * math.sin(x * 9 - t * 0.6)
            out.append(_mix((10, 2, 24), _palette(stops, (x * 0.5 + t * 0.04) % 1.0), 0.35 + 0.65 * w))
    elif effect == "Eclipse":       # a dark disc drifts along with a bright corona around it
        pos = (t * 0.18 + offset) % 1.4 - 0.2
        for i in range(n):
            d = abs((i + 0.5) / n - pos) if n > 1 else 0.3
            if d < 0.08:
                out.append((2, 2, 6))
                continue
            k = math.exp(-(d - 0.08) / 0.07)
            col = _mix((255, 150, 60), (255, 245, 225), math.exp(-(d - 0.08) / 0.025))
            out.append(_mix((14, 6, 26), col, k))
    return out or [(0, 0, 0)] * n


# --------------------------------------------------------------------------- engine
class LightingEngine(threading.Thread):
    FPS = 30
    IDLE_HZ = 4          # ticks per second while nothing animates and nothing changed

    def __init__(self, log, on_disconnect=lambda: None):
        super().__init__(daemon=True)
        self._wake_evt = threading.Event()   # set by any change, so an idling loop runs its next tick at once
        self._dirty = True
        self._paused = False
        self.log = log
        self.on_disconnect = on_disconnect
        self.lock = threading.RLock()  # guards the SDK socket + state
        self.client: OpenRGBClient | None = None
        self.state = {"color": [0, 120, 255], "effect": "Static", "brightness": 100, "speed": 50}
        self.excluded: set[str] = set()
        self.overrides: dict[str, dict] = {}   # device key -> its own lighting state
        self.key_colors: dict[str, dict] = {}  # device key -> {LED name: (r, g, b)} painted on top (per-key)
        self.broken: set[str] = set()      # devices that errored; skipped until next rescan
        self.dirty = True
        self.prepared: dict[str, bool] = {}   # device key -> True if per-LED capable
        self.last_slow_push: dict[str, float] = {}
        self.last_sent: dict[str, list] = {}
        self.frame = 0                         # main-loop tick counter (RAM runs on every Nth tick)
        self.ram_conflict_checked = False
        self.ram_pending: set[str] = set()     # RAM sticks with a change still waiting for their bus slot
        self._stop_evt = threading.Event()
        self.paused = False

    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value):
        self._dirty = value
        if value:
            self._wake_evt.set()

    @property
    def paused(self) -> bool:
        return self._paused

    @paused.setter
    def paused(self, value):
        self._paused = value
        self._wake_evt.set()

    def _is_idle(self) -> bool:
        """True when the next tick has nothing to do: no animation, no change and no RAM write waiting."""
        with self.lock:
            if self.client is None or self.paused:
                return True
            if self._dirty or self.ram_pending:
                return False
            return not (is_animated(self.state["effect"])
                        or any(is_animated(o.get("effect", "")) for o in self.overrides.values()))

    # ---- connection
    def connect(self) -> bool:
        with self.lock:
            try:
                self.client = OpenRGBClient(SDK_HOST, SDK_PORT, APP_NAME)
            except Exception as e:
                self.client = None
                self.log(f"Couldn't connect to OpenRGB SDK: {e}")
                return False
            self.prepared.clear()
            self.broken.clear()
            self.dirty = True
            self.ram_conflict_checked = False
            return True

    def disconnect(self):
        with self.lock:
            try:
                if self.client:
                    self.client.disconnect()
            except Exception:
                pass
            self.client = None

    def devices(self) -> list:
        with self.lock:
            if not self.client:
                return []
            return [d for d in self.client.devices if d is not None]

    def rescan(self):
        with self.lock:
            if self.client:
                self.client.update()
                self.broken.clear()
                self.prepared.clear()
                self.dirty = True

    # ---- state
    def set_state(self, **kw):
        with self.lock:
            self.state.update(kw)
            self.dirty = True

    def set_key_colors(self, key_colors):
        """Per-key colours for every keyboard: {device key: {LED name: (r, g, b)}}."""
        with self.lock:
            self.key_colors = {k: {n: tuple(c) for n, c in v.items()} for k, v in (key_colors or {}).items() if v}
            self.dirty = True

    def set_overrides(self, overrides):
        with self.lock:
            self.overrides = {k: dict(v) for k, v in overrides.items()}
            self.dirty = True

    def device_info(self, key) -> dict | None:
        """Details OpenRGB reports for one device (exact model, vendor, zones...)."""
        with self.lock:
            for d in self.devices():
                if device_key(d) == key:
                    md = d.metadata
                    return {"name": d.name, "type": type_name(d), "vendor": getattr(md, "vendor", "") or "",
                            "description": getattr(md, "description", "") or "", "version": getattr(md, "version", "") or "",
                            "serial": getattr(md, "serial", "") or "", "location": getattr(md, "location", "") or "",
                            "leds": len(d.leds), "zones": [(z.name, len(z.leds)) for z in d.zones],
                            "modes": [m.name for m in d.modes]}
        return None

    def zones(self, key) -> list[dict]:
        """The resizable zones (ARGB headers) of one device, see resizable_zones()."""
        with self.lock:
            for d in self.devices():
                if device_key(d) == key:
                    return resizable_zones(d)
        return []

    def resize_zone(self, key, index, size) -> int | None:
        """Tell OpenRGB how many LEDs are plugged into one header. Returns the size set (clamped), or None."""
        with self.lock:
            for d in self.devices():
                if device_key(d) != key:
                    continue
                z = next((z for z in resizable_zones(d) if z["index"] == index), None)
                if z is None:
                    return None
                size = max(z["min"], min(z["max"], int(size)))
                if z["leds"] != size:
                    d.zones[index].resize(size)
                    try:
                        d.update()
                    except Exception:
                        pass
                    self.prepared.pop(key, None)       # LED count changed: set Direct mode and colours afresh
                    self.last_sent.pop(key, None)
                    self.broken.discard(key)
                    self.dirty = True
                return size
        return None

    def apply_zone_sizes(self, sizes) -> list[str]:
        """Set every header to the size you chose before (OpenRGB forgets it when it restarts).
        Returns 'device · header: n' for each one changed."""
        done = []
        for d in self.devices():
            want = (sizes or {}).get(device_key(d)) or {}
            for z in resizable_zones(d):
                n = want.get(z["name"])
                if n is not None and int(n) != z["leds"]:
                    try:
                        got = self.resize_zone(device_key(d), z["index"], n)
                    except Exception as e:
                        self.log(f"Couldn't set {d.name} · {z['name']} to {n} LEDs: {e}")
                        continue
                    if got is not None:
                        done.append(f"{d.name} · {z['name']}: {got}")
        return done

    def set_excluded(self, keys):
        with self.lock:
            self.excluded = set(keys)
            self.dirty = True

    def force_reapply(self):
        with self.lock:
            self.prepared.clear()
            self.dirty = True

    def stop(self):
        self._stop_evt.set()
        self._wake_evt.set()

    # ---- device handling
    @staticmethod
    def _hw_static(dev):
        """The device's own 'Static' mode, if it has one that takes a color."""
        return next((m for m in dev.modes if m.name.lower() == "static"
                     and m.color_mode in (ModeColors.MODE_SPECIFIC, ModeColors.PER_LED)), None)

    @staticmethod
    def _hw_effect_mode(dev, st):
        """RGB RAM only: the stick's own hardware mode for this effect, if it can run it the way Central RGB
        would. The stick then animates by itself and nothing is streamed over the SMBus, so it can't flicker."""
        if getattr(dev, "type", None) != DeviceType.DRAM:
            return None
        effect = RENAMED.get(st.get("effect"), st.get("effect"))
        for want in HW_EFFECT_MODES.get(effect, ()):
            m = next((m for m in dev.modes if m.name.lower() == want), None)
            if m is None:
                continue
            flags = getattr(m, "flags", 0) or 0
            if effect == "Breathing" and m.color_mode == ModeColors.MODE_SPECIFIC:
                return m
            if (effect == "Color Cycle" and m.color_mode in (ModeColors.NONE, ModeColors.RANDOM)
                    and (st.get("brightness", 100) >= 100 or flags & ModeFlags.HAS_BRIGHTNESS)):
                return m
        return None

    @staticmethod
    def _push_hw_effect(dev, m, st):
        """Start a hardware effect once: speed, brightness and colour mapped onto the mode's own ranges."""
        flags = getattr(m, "flags", 0) or 0
        b = max(0, min(100, st.get("brightness", 100)))

        def span(lo, hi, pct):
            return int(round(lo + (hi - lo) * pct / 100))
        if flags & ModeFlags.HAS_SPEED and m.speed_min is not None and m.speed_max is not None:
            m.speed = span(m.speed_min, m.speed_max, max(0, min(100, st.get("speed", 50))))
        if flags & ModeFlags.HAS_BRIGHTNESS and m.brightness_min is not None and m.brightness_max is not None:
            m.brightness, b = span(m.brightness_min, m.brightness_max, b), 100
        if m.color_mode == ModeColors.MODE_SPECIFIC:
            col = compute_colors("Static", st["color"], b, 0, 1, 0)[0]
            m.colors = [RGBColor(*col)] * max(1, m.colors_max or 1)
        dev.set_mode(m)

    def _check_ram_conflicts(self):
        """Once per connection: warn if another program is also writing to the RAM."""
        self.ram_conflict_checked = True
        names = sorted(n for n in find_conflicts() if n in RAM_WRITERS)
        if names:
            self.log(f"RGB RAM: {', '.join(names)} is also writing to the RAM sticks, which makes them flicker. "
                     "Close it with 'Close them' on the Devices page.")

    def _prepare(self, dev, animated: bool) -> str:
        """Pick a mode for the device. Returns 'per_led', 'slow' or 'hw_static'.

        A still color goes into the device's own Static mode, so the hardware holds it. Direct mode is
        only used for animations: many controllers (RGB RAM especially) blink when switched into it and
        dim or drop the color when the software stops streaming frames."""
        names = [m.name.lower() for m in dev.modes]
        try:
            if not animated and self._hw_static(dev) is not None:
                return "hw_static"
            for want in ("direct", "custom", "static"):
                if want in names:
                    if dev.modes[dev.active_mode].name.lower() != want:
                        dev.set_mode(want)
                    break
            else:
                dev.set_custom_mode()
        except Exception as e:
            self.log(f"  {dev.name}: couldn't switch mode ({e})")
        try:
            return "per_led" if dev.modes[dev.active_mode].color_mode == ModeColors.PER_LED else "slow"
        except Exception:
            return "slow"

    def _push(self, dev, colors, how: str):
        if not dev.leds:
            return
        rgb = [RGBColor(*c) for c in colors]
        if how == "hw_static":
            m = self._hw_static(dev)
            if m.color_mode == ModeColors.MODE_SPECIFIC:
                m.colors = [rgb[0]] * max(1, m.colors_max or 1)
                dev.set_mode(m)                      # one write; the controller keeps the color itself
            else:
                if dev.modes[dev.active_mode].name.lower() != "static":
                    dev.set_mode(m)
                dev._set_device_colors(rgb, fast=False)
            return
        if how == "per_led":
            dev._set_device_colors(rgb, fast=True)
        else:
            dev.set_color(rgb[0])

    def _unchanged(self, key, cols, is_ram: bool) -> bool:
        """True if cols needn't be sent: identical to the last frame sent, or for RAM, no LED moved by
        DRAM_MIN_CHANGE or more (tiny steps aren't visible but each one costs a full SMBus write)."""
        last = self.last_sent.get(key)
        if last is None or len(last) != len(cols):
            return False
        if not is_ram:
            return last == cols
        return all(abs(a - b) < DRAM_MIN_CHANGE for p, q in zip(last, cols) for a, b in zip(p, q))

    def targets(self) -> list:
        skip = self.excluded | self.broken
        return [d for d in self.devices() if device_key(d) not in skip]

    def save_to_hardware(self) -> list[str]:
        """Store the current static color in the devices' own memory so it survives without software."""
        results = []
        with self.lock:
            st = dict(self.state)
            col = compute_colors("Static", st["color"], st["brightness"], 0, 1, 0)[0]
            for dev in self.targets():
                try:
                    static = next((m for m in dev.modes if m.name.lower() == "static"
                                   and m.color_mode == ModeColors.MODE_SPECIFIC), None)
                    if static is not None:
                        static.colors = [RGBColor(*col)] * max(1, static.colors_max or 1)
                        dev.set_mode(static, save=True)
                    else:
                        dev._set_device_colors([RGBColor(*col)] * len(dev.leds), fast=False)
                        dev.save_mode()
                    results.append(f"Saved: {dev.name}")
                except Exception as e:
                    results.append(f"Not supported by {dev.name}: {e}")
            self.prepared.clear()  # mode changed, re-prepare on next frame
        return results

    # ---- main loop
    def step(self):
        """One tick of the lighting loop: work out and send this frame's colours."""
        with self.lock:
            base = dict(self.state)
            ov = self.overrides
            client = self.client
            dirty = self.dirty
            any_animated = is_animated(base["effect"]) or any(is_animated(o.get("effect", "")) for o in ov.values())
            if client and not self.paused and (any_animated or dirty or self.ram_pending):
                self.dirty = False
                now = time.time()
                ram_every = max(1, round(self.FPS / DRAM_FPS))
                # One stick per tick: with more sticks than ticks in a RAM period, the cycle stretches so no two
                # sticks ever share a tick on the bus (4 sticks at 30 fps -> each stick 7.5 times a second).
                n_ram = sum(1 for d in self.targets() if getattr(d, "type", None) == DeviceType.DRAM)
                ram_cycle = max(ram_every, n_ram)
                ram_idx = 0
                for idx, dev in enumerate(self.targets()):
                    key = device_key(dev)
                    st = ov.get(key) or base            # a device can have its own lighting
                    animated = is_animated(st["effect"])
                    is_ram = getattr(dev, "type", None) == DeviceType.DRAM
                    dev_dirty = dirty or key in self.ram_pending
                    if not animated and not dev_dirty:
                        continue
                    if is_ram:
                        # Every stick shares one slow SMBus, so RAM gets a steady, lower rate (counted in loop
                        # ticks, so timing jitter can't make it uneven) and the sticks take turns on the bus.
                        # This applies to changes too (e.g. dragging a slider); they wait for the next slot.
                        ram_idx += 1
                        if not self.ram_conflict_checked:
                            self._check_ram_conflicts()
                        if self.frame % ram_cycle != (ram_idx - 1) % ram_cycle:
                            if dev_dirty:
                                self.ram_pending.add(key)
                            continue
                        self.ram_pending.discard(key)
                    # painted keys need the per-LED mode even for a still colour (the keyboard's own Static or
                    # effect modes would paint every key the same)
                    painted = bool(self.key_colors.get(key))
                    hw = self._hw_effect_mode(dev, st) if animated and not painted else None
                    pkey = (key, animated or painted, hw is not None)
                    if hw is not None:
                        # the RAM runs this effect itself: one write when something changes, then nothing
                        if not dev_dirty and pkey in self.prepared:
                            continue
                        self.prepared = {k: v for k, v in self.prepared.items() if k[0] != key}
                        self.prepared[pkey] = "hw_effect"
                        self.last_sent.pop(key, None)
                        try:
                            self._push_hw_effect(dev, hw, st)
                        except (ConnectionError, OSError):
                            raise
                        except Exception as e:
                            self.log(f"  {dev.name}: {e}")
                            self.broken.add(key)
                        continue
                    if pkey not in self.prepared:
                        self.prepared = {k: v for k, v in self.prepared.items() if k[0] != key}
                        self.prepared[pkey] = self._prepare(dev, animated or painted)
                    how = self.prepared[pkey]
                    if how == "slow" and animated:
                        # mode-specific devices are slow to update; ~2 updates/second
                        if now - self.last_slow_push.get(key, 0) < 0.5:
                            continue
                        self.last_slow_push[key] = now
                    # motion blur over this device's own update period, so slower devices fade rather than step
                    period = (ram_cycle / self.FPS) if is_ram else (0.5 if how == "slow" else 1 / self.FPS)
                    cols = compute_colors(st["effect"], st["color"], st["brightness"],
                                          st["speed"], len(dev.leds), now, offset=idx * 0.07,
                                          blur=period if animated else 0.0, aa=animated)
                    kc = self.key_colors.get(key)
                    if kc and how == "per_led":
                        cols = apply_key_colors(cols, dev, kc, st["brightness"])
                    if not dev_dirty and self._unchanged(key, cols, is_ram):
                        continue                    # nothing (visible) changed for this device: don't write
                    self.last_sent[key] = cols
                    try:
                        self._push(dev, cols, how)
                    except (ConnectionError, OSError):
                        raise
                    except Exception as e:
                        self.log(f"  {dev.name}: {e}")
                        self.broken.add(key)  # stop retrying a broken device

    def tick(self) -> float:
        """Run one loop tick and return how long to wait before the next one (seconds)."""
        budget = 1 / self.FPS
        start = time.perf_counter()
        self._wake_evt.clear()               # a change from here on wakes the wait below straight away
        try:
            self.step()
        except (ConnectionError, OSError) as e:
            with self.lock:
                self.client = None
            self.log(f"Lost connection to OpenRGB ({e}).")
            self.on_disconnect()
        self.frame += 1
        if self._is_idle():
            return 1 / self.IDLE_HZ
        return max(0.001, budget - (time.perf_counter() - start))   # steady cadence, whatever the step cost

    def run(self):
        while not self._stop_evt.is_set():
            wait = self.tick()
            if wait > 1 / self.FPS:
                self._wake_evt.wait(wait)    # idle: a state change (or stop) ends the wait at once
            else:
                self._stop_evt.wait(wait)
