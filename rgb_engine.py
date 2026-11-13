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
SDK_HOST = "127.0.0.1"
SDK_PORT = 6742
RELEASES_PAGE = "https://openrgb.org/releases.html"
FALLBACK_ZIP = ("https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_1.1/"
                "OpenRGB_1.1_Windows_64_8e16de2.zip")
PAWNIO_PAGE = "https://pawnio.eu"
IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW for helper commands

EFFECTS = ["Static", "Breathing", "Color Cycle", "Rainbow Wave", "Off"]
ANIMATED = {"Breathing", "Color Cycle", "Rainbow Wave"}

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
        except Exception:
            pass

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
            self.proc = subprocess.Popen([str(exe), "--server", "--startminimized"], cwd=str(exe.parent))
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
    n = max(n, 1)
    b = max(0, min(100, brightness)) / 100.0
    f = 0.1 + max(0, min(100, speed)) / 100.0 * 1.4  # 0.1 .. 1.5 Hz-ish

    def scale(rgb, k=1.0):
        return tuple(int(max(0, min(255, round(c * b * k)))) for c in rgb)

    if effect == "Off":
        return [(0, 0, 0)] * n
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
    return [scale(color)] * n  # Static


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
        self.broken: set[str] = set()      # devices that errored; skipped until next rescan
        self.dirty = True
        self.prepared: dict[str, bool] = {}   # device key -> True if per-LED capable
        self.last_slow_push: dict[str, float] = {}
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
    def _prepare(self, dev) -> bool:
        """Put device into the most controllable mode. Returns True if it accepts per-LED colors."""
        names = [m.name.lower() for m in dev.modes]
        try:
            for want in ("direct", "custom", "static"):
                if want in names:
                    dev.set_mode(want)
                    break
            else:
                dev.set_custom_mode()
        except Exception as e:
            self.log(f"  {dev.name}: couldn't switch mode ({e})")
        try:
            return dev.modes[dev.active_mode].color_mode == ModeColors.PER_LED
        except Exception:
            return False

    def _push(self, dev, colors, per_led: bool):
        if not dev.leds:
            return
        rgb = [RGBColor(*c) for c in colors]
        if per_led:
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
                    st = dict(self.state)
                    client = self.client
                    dirty = self.dirty
                    animated = st["effect"] in ANIMATED
                    if client and not self.paused and (animated or dirty):
                        self.dirty = False
                        now = time.time()
                        for idx, dev in enumerate(self.targets()):
                            key = device_key(dev)
                            if key not in self.prepared:
                                self.prepared[key] = self._prepare(dev)
                            per_led = self.prepared[key]
                            if not per_led and animated:
                                # mode-specific devices are slow to update; ~2 updates/second
                                if now - self.last_slow_push.get(key, 0) < 0.5:
                                    continue
                                self.last_slow_push[key] = now
                            cols = compute_colors(st["effect"], st["color"], st["brightness"],
                                                  st["speed"], len(dev.leds), now, offset=idx * 0.07)
                            try:
                                self._push(dev, cols, per_led)
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
