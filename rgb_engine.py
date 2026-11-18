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
from openrgb.utils import DeviceType, ModeColors, RGBColor

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


def find_conflicts() -> dict[str, list[int]]:
    """Running vendor RGB apps: friendly name -> process ids."""
    out: dict[str, list[int]] = {}
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            name = (p.info["name"] or "").lower()
            if name in CONFLICTING_APPS:
                out.setdefault(CONFLICTING_APPS[name], []).append(p.pid)
    except Exception:
        pass
    return out


def close_conflicts(log=print) -> list[str]:
    """Close the vendor RGB apps that hold the hardware, including their background services
    (e.g. MSI's Mystic Light service keeps running after MSI Center is closed). Services are set to
    start manually so they don't grab the hardware again at the next sign-in; the vendor app still
    works if the user opens it. Returns what was done."""
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
                if not any(e in binpath for e in exes):
                    continue
                name = info["name"]
                if info.get("start_type") == "automatic":
                    run_quiet(["sc", "config", name, "start=", "demand"])
                    done.append(f"Service '{info.get('display_name') or name}' set to start manually")
                if info.get("status") == "running":
                    run_quiet(["sc", "stop", name])
                    done.append(f"Stopped service '{info.get('display_name') or name}'")
            except Exception:
                continue
    except Exception as e:
        log(f"Couldn't check services: {e}")
    time.sleep(1.0)
    for p in psutil.process_iter(["name"]):
        try:
            name = (p.info["name"] or "").lower()
            if name in CONFLICTING_APPS:
                p.terminate()
                try:
                    p.wait(timeout=4)
                except psutil.TimeoutExpired:
                    p.kill()
                done.append(f"Closed {CONFLICTING_APPS[name]} ({p.info['name']})")
        except Exception:
            continue
    return done


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


def type_name(dev) -> str:
    return TYPE_NAMES.get(dev.type, "Other")


# --------------------------------------------------------------------------- settings
class Settings:
    DEFAULTS = {
        "openrgb_path": "",
        "state": {"color": [0, 120, 255], "effect": "Static", "brightness": 100, "speed": 50},
        "excluded": [],
        "device_overrides": {},
        "profiles": {
            "Ocean": {"color": [0, 120, 255], "effect": "Static", "brightness": 100, "speed": 50},
            "Rainbow": {"color": [255, 0, 0], "effect": "Rainbow Wave", "brightness": 100, "speed": 40},
            "Red breathing": {"color": [255, 0, 0], "effect": "Breathing", "brightness": 100, "speed": 30},
        },
        "restore_on_start": True,
    }

    def __init__(self):
        self.path = settings_dir() / "settings.json"
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
        self.data[k] = v
        self.save()

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
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
        """OpenRGB processes running from Central RGB's own folder (its hidden copies, possibly left over
        from an earlier session that was ended in Task Manager)."""
        try:
            import psutil
        except Exception:
            return []
        ours, out = str(install_dir()).lower(), []
        for p in psutil.process_iter(["name", "exe"]):
            try:
                if (p.info["name"] or "").lower() == "openrgb.exe" and (p.info["exe"] or "").lower().startswith(ours):
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
            # First Windows 64-bit portable zip on the page is the newest stable release
            m = re.search(r'https?://[^"\'\s>]+Windows_64[^"\'\s>]*\.zip', html)
            if m:
                return m.group(0)
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
        self.settings["openrgb_path"] = str(exe)
        self.log(f"OpenRGB installed to {exe.parent}")
        return exe

    def launch(self, exe: Path, wait=45) -> bool:
        self.log(f"Starting OpenRGB SDK server ({exe}) ...")
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
          "ram=@(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { \"$($_.Manufacturer) $($_.PartNumber)\".Trim() })"
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
        if rams:
            out.append(("info", f"RAM sticks: {len(rams)} ({', '.join(sorted(set(rams)))})"))
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------- effects
def compute_colors(effect: str, color, brightness: int, speed: int, n: int, t: float,
                   offset: float = 0.0) -> list[tuple[int, int, int]]:
    """Pure function: colors for n LEDs at time t."""
    effect = RENAMED.get(effect, effect)
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
            out.append(_mix((0, 4, 14), drop, math.exp(-x * 3.5)))
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
        level = 0.12 + 0.88 * abs(math.sin(t * 2.3 + offset * 9) * math.sin(t * 0.9 + 1.3) + 0.25 * math.sin(t * 5.1)) / 1.25
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
        slot = int(t * 2.2)
        glitch = _rnd(int(t * 9), 41 + offset) < 0.12
        for i in range(n):
            block = int(i / max(1, n) * 6 + _rnd(slot, 43) * 3)
            col = pal[int(_rnd(block, slot + 50) * len(pal)) % len(pal)]
            if glitch and _rnd(i, int(t * 9) + 60) < 0.5:
                col = pal[(pal.index(col) + 1) % len(pal)]
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
            rate = 0.8 + 2.4 * _rnd(i, 80)
            v = (0.5 + 0.5 * math.sin(t * rate + _rnd(i, 81 + offset) * 6.28)) ** 12
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

    def __init__(self, log, on_disconnect=lambda: None):
        super().__init__(daemon=True)
        self.log = log
        self.on_disconnect = on_disconnect
        self.lock = threading.RLock()  # guards the SDK socket + state
        self.client: OpenRGBClient | None = None
        self.state = {"color": [0, 120, 255], "effect": "Static", "brightness": 100, "speed": 50}
        self.excluded: set[str] = set()
        self.overrides: dict[str, dict] = {}   # device key -> its own lighting state
        self.broken: set[str] = set()      # devices that errored; skipped until next rescan
        self.dirty = True
        self.prepared: dict[str, bool] = {}   # device key -> True if per-LED capable
        self.last_slow_push: dict[str, float] = {}
        self.last_ram_push: dict[str, float] = {}
        self.last_sent: dict[str, list] = {}
        self._stop_evt = threading.Event()
        self.paused = False

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

    # ---- device handling
    @staticmethod
    def _hw_static(dev):
        """The device's own 'Static' mode, if it has one that takes a color."""
        return next((m for m in dev.modes if m.name.lower() == "static"
                     and m.color_mode in (ModeColors.MODE_SPECIFIC, ModeColors.PER_LED)), None)

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
    def run(self):
        while not self._stop_evt.is_set():
            try:
                with self.lock:
                    base = dict(self.state)
                    ov = self.overrides
                    client = self.client
                    dirty = self.dirty
                    any_animated = is_animated(base["effect"]) or any(is_animated(o.get("effect", "")) for o in ov.values())
                    if client and not self.paused and (any_animated or dirty):
                        self.dirty = False
                        now = time.time()
                        for idx, dev in enumerate(self.targets()):
                            key = device_key(dev)
                            st = ov.get(key) or base            # a device can have its own lighting
                            animated = is_animated(st["effect"])
                            if not animated and not dirty:
                                continue
                            if animated and not dirty and getattr(dev, "type", None) == DeviceType.DRAM:
                                # RGB RAM is driven over the SMBus; streaming 30 frames a second makes some sticks
                                # (e.g. Corsair Vengeance Pro) glitch now and then. ~15 a second still looks smooth.
                                if now - self.last_ram_push.get(key, 0) < 1 / 15:
                                    continue
                                self.last_ram_push[key] = now
                            pkey = (key, animated)
                            if pkey not in self.prepared:
                                self.prepared = {k: v for k, v in self.prepared.items() if k[0] != key}
                                self.prepared[pkey] = self._prepare(dev, animated)
                            how = self.prepared[pkey]
                            if how == "slow" and animated:
                                # mode-specific devices are slow to update; ~2 updates/second
                                if now - self.last_slow_push.get(key, 0) < 0.5:
                                    continue
                                self.last_slow_push[key] = now
                            cols = compute_colors(st["effect"], st["color"], st["brightness"],
                                                  st["speed"], len(dev.leds), now, offset=idx * 0.07)
                            if not dirty and self.last_sent.get(key) == cols:
                                continue                    # nothing changed for this device: don't write
                            self.last_sent[key] = cols
                            try:
                                self._push(dev, cols, how)
                            except (ConnectionError, OSError):
                                raise
                            except Exception as e:
                                self.log(f"  {dev.name}: {e}")
                                self.broken.add(key)  # stop retrying a broken device
            except (ConnectionError, OSError) as e:
                with self.lock:
                    self.client = None
                self.log(f"Lost connection to OpenRGB ({e}).")
                self.on_disconnect()
            time.sleep(1 / self.FPS)
