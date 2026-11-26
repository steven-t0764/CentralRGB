# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Battery levels of wireless keyboards, mice, headsets and controllers, read in the background.

Each brand reports its battery its own way, so there's one reader per source:

    Logitech      HID++ 2.0 over the receiver or cable (features 0x1004 Unified Battery, 0x1000 Battery Status,
                  0x1001 Battery Voltage), the protocol Solaar and LGS Tray Battery document. Works with G HUB
                  running: Windows gives every open handle its own copy of the device's replies.
    SteelSeries   wireless mice (Aerox, Prime, Rival 3 / 650 Wireless): the battery command rivalcfg documents
    Razer         wireless mice and keyboards: the Razer report (command class 0x07, 0x80 level / 0x84
                  charging) that OpenRAZER documents
    Headsets      HeadsetControl (GPL-3.0, github.com/Sapd/HeadsetControl): Logitech, Corsair, SteelSeries,
                  HyperX, Roccat, Audeze and more. Downloaded from its own GitHub releases on first use, never
                  bundled, like OpenRGB and LibreHardwareMonitor
    Bluetooth     whatever Windows already knows (the battery level Windows shows in Settings > Bluetooth)

Readers only ever ask for the battery: nothing here changes a device's settings. Anything missing (no hidapi,
not Windows, a device that doesn't answer) is skipped quietly.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

IS_WIN = sys.platform == "win32"
APP_NAME = "Central RGB"

KINDS = ("keyboard", "mouse", "headset", "controller", "device")


@dataclass
class Battery:
    key: str                      # stable id, so the app can keep a device in place between readings
    name: str
    brand: str
    kind: str = "device"          # one of KINDS
    level: int | None = None      # 0-100, None when the device is asleep / off / didn't say
    charging: bool | None = None
    source: str = ""              # which reader found it (shown in the activity log, handy for support)
    approx: bool = False          # level estimated from a voltage or a 5-step scale
    seen: float = field(default_factory=time.time)

    @property
    def low(self) -> bool:
        return self.level is not None and not self.charging and self.level <= 15


def kind_from_name(name: str, default: str = "device") -> str:
    n = (name or "").lower()
    if re.search(r"keyboard|blackwidow|huntsman|ornata|deathstalker|apex|alloy|\bk\d{2,3}\b|mx keys|craft|"
                 r"\bg(915|815|715|713|613|513|512|413|213)\b|pro x tkl|g pro keyboard", n):
        return "keyboard"
    if re.search(r"headset|headphone|kraken|barracuda|nari|blackshark|arctis|cloud|virtuoso|void|\bhs\d{2}|buds|"
                 r"earbud|astro|airpods|\bwh-|\bwf-|\bg(935|933|733|635|633|535|533|522|435)\b|pro x 2", n):
        return "headset"
    if re.search(r"controller|gamepad|xbox|dualsense|dualshock|joy-con|8bitdo", n):
        return "controller"
    if re.search(r"mouse|aerox|prime|rival|deathadder|viper|basilisk|naga|orochi|mamba|lancehead|superlight|"
                 r"mx master|mx anywhere|pulsefire|glorious|model [od]\b|\bg(502|309|305|304|703|705|903|603|403)\b", n):
        return "mouse"
    return default


# =========================================================================== HID access
class HidBackend:
    """Thin wrapper over hidapi, so tests can swap in fake devices."""

    def enumerate(self, vid: int = 0) -> list[dict]:
        raise NotImplementedError

    def open(self, path):
        raise NotImplementedError


class RealHid(HidBackend):
    def __init__(self):
        import hid  # the "hidapi" package (cython-hidapi)
        self.hid = hid

    def enumerate(self, vid: int = 0) -> list[dict]:
        try:
            return list(self.hid.enumerate(vid, 0))
        except Exception:
            return []

    def open(self, path):
        d = self.hid.device()
        d.open_path(path)
        return d


def real_hid() -> HidBackend | None:
    try:
        return RealHid()
    except Exception:
        return None


def _close(d):
    try:
        d.close()
    except Exception:
        pass


# =========================================================================== Logitech HID++ 2.0
LOGITECH = 0x046D
HIDPP_SHORT, HIDPP_LONG = 0x10, 0x11
SW_ID = 0x0B                     # our software id: replies carry it back, so they're told apart from G HUB's
F_ROOT, F_NAME, F_BATTERY, F_VOLTAGE, F_UNIFIED = 0x0000, 0x0005, 0x1000, 0x1001, 0x1004
HIDPP_TYPES = {0: "keyboard", 1: "device", 2: "keyboard", 3: "mouse", 4: "mouse", 5: "mouse", 6: "device",
               8: "headset", 12: "controller"}
# Logitech's battery voltage curve for its rechargeable cells (as used by Solaar), mV -> %
VOLTAGE_CURVE = [(4186, 100), (4067, 90), (3989, 80), (3922, 70), (3859, 60), (3811, 50), (3778, 40),
                 (3751, 30), (3717, 20), (3671, 10), (3646, 5), (3579, 2), (3500, 0)]


def voltage_percent(mv: int) -> int:
    if mv >= VOLTAGE_CURVE[0][0]:
        return 100
    if mv <= VOLTAGE_CURVE[-1][0]:
        return 0
    for (vh, ph), (vl, pl) in zip(VOLTAGE_CURVE, VOLTAGE_CURVE[1:]):
        if vl <= mv <= vh:
            return round(pl + (ph - pl) * (mv - vl) / (vh - vl))
    return 0


class Hidpp:
    """HID++ 2.0 feature calls on one open HID collection (Windows splits short and long reports into separate
    collections; we use the long one when there is one)."""

    def __init__(self, dev, long: bool, timeout: float = 0.35):
        self.dev, self.long, self.timeout = dev, long, timeout

    def call(self, index: int, feature_index: int, function: int, params: bytes = b"") -> bytes | None:
        fn = ((function & 0x0F) << 4) | SW_ID
        if self.long:
            msg = bytes([HIDPP_LONG, index, feature_index, fn]) + params
            msg = msg + bytes(20 - len(msg))
        else:
            msg = bytes([HIDPP_SHORT, index, feature_index, fn]) + params[:3]
            msg = msg + bytes(7 - len(msg))
        try:
            self.dev.write(msg)
        except Exception:
            return None
        end = time.monotonic() + self.timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None
            try:
                r = bytes(self.dev.read(20, timeout_ms=max(1, int(left * 1000))))
            except Exception:
                return None
            if len(r) < 5 or r[0] not in (HIDPP_SHORT, HIDPP_LONG):
                continue
            if r[1] != index and not (index == 0xFF and r[1] == 0x00):
                continue
            if r[2] in (0x8F, 0xFF):                         # HID++ 1.0 / 2.0 error for our call
                if r[3] == feature_index and r[4] == fn:
                    return None
                continue
            if r[2] == feature_index and r[3] == fn:
                return r[4:]

    def feature(self, index: int, feature_id: int) -> int | None:
        r = self.call(index, 0x00, 0, bytes([feature_id >> 8, feature_id & 0xFF]))
        return r[0] if r and r[0] else None

    def name(self, index: int) -> str | None:
        fi = self.feature(index, F_NAME)
        if fi is None:
            return None
        r = self.call(index, fi, 0)
        if not r:
            return None
        length, out = r[0], b""
        while len(out) < length:
            part = self.call(index, fi, 1, bytes([len(out)]))
            chunk = part[:length - len(out)] if part else b""
            if not chunk:
                break
            out += chunk
        return out.rstrip(b"\x00").decode("utf-8", "replace").strip() or None

    def kind(self, index: int) -> str:
        fi = self.feature(index, F_NAME)
        if fi is not None:
            r = self.call(index, fi, 2)
            if r:
                return HIDPP_TYPES.get(r[0], "device")
        return "device"

    def battery(self, index: int):
        """(level, charging, approx) or None."""
        fi = self.feature(index, F_UNIFIED)
        if fi is not None:
            r = self.call(index, fi, 1)                      # getStatus
            if r and len(r) >= 3:
                soc, lvl, status = r[0], r[1], r[2]
                approx = soc == 0
                if approx:
                    soc = {8: 100, 4: 50, 2: 20, 1: 5}.get(lvl, 0)
                return soc, status in (1, 2, 3, 4), approx
        fi = self.feature(index, F_BATTERY)
        if fi is not None:
            r = self.call(index, fi, 0)
            if r and len(r) >= 3:
                return (r[0] or None), r[2] in (1, 2, 3, 4), False
        fi = self.feature(index, F_VOLTAGE)
        if fi is not None:
            r = self.call(index, fi, 0)
            if r and len(r) >= 3:
                mv = (r[0] << 8) | r[1]
                return voltage_percent(mv), bool(r[2] & 0x80), True
        return None


def read_logitech(hid: HidBackend) -> list[Battery]:
    out, done = [], set()
    infos = [i for i in hid.enumerate(LOGITECH) if i.get("usage_page") == 0xFF00]
    # one collection per physical interface: prefer the long-report one (usage 2)
    infos.sort(key=lambda i: 0 if i.get("usage") == 2 else 1)
    for info in infos:
        ident = (info.get("product_id"), info.get("serial_number"), info.get("interface_number"))
        if ident in done:
            continue
        done.add(ident)
        try:
            dev = hid.open(info["path"])
        except Exception:
            continue
        try:
            pp = Hidpp(dev, long=info.get("usage") == 2)
            product = (info.get("product_string") or "").strip()
            receiver = "receiver" in product.lower() or "lightspeed" in product.lower() or "unifying" in product.lower()
            for index in ((1, 2, 3, 4, 5, 6) if receiver else (0xFF,)):
                b = pp.battery(index)
                if b is None:
                    continue
                level, charging, approx = b
                name = pp.name(index) or product or "Logitech device"
                kind = pp.kind(index)
                if kind == "device":
                    kind = kind_from_name(name)
                if not name.lower().startswith("logitech"):
                    name = f"Logitech {name}"
                out.append(Battery(key=f"logitech:{name}", name=name, brand="Logitech", kind=kind, level=level,
                                   charging=charging, source="Logitech HID++", approx=approx))
        finally:
            _close(dev)
    return out


# =========================================================================== SteelSeries mice
STEELSERIES = 0x1038
# product id -> (name, protocol, interface). Protocols (from rivalcfg):
#   "aerox"   wired: send 0x92 (wireless: 0x92 | 0x40), reply byte 1: bit 7 charging, rest = level/5 + 1
#   "rival3"  send 0xAA 0x01, reply byte 0 = level %, byte 2 = charging
STEELSERIES_MICE = {
    0x183A: ("SteelSeries Aerox 3 Wireless", "aerox", 3), 0x1838: ("SteelSeries Aerox 3 Wireless", "aerox_w", 3),
    0x187A: ("SteelSeries Aerox 3 Wireless", "aerox", 3), 0x1878: ("SteelSeries Aerox 3 Wireless", "aerox_w", 3),
    0x1854: ("SteelSeries Aerox 5 Wireless", "aerox", 3), 0x1852: ("SteelSeries Aerox 5 Wireless", "aerox_w", 3),
    0x185E: ("SteelSeries Aerox 5 Wireless", "aerox", 3), 0x185C: ("SteelSeries Aerox 5 Wireless", "aerox_w", 3),
    0x1862: ("SteelSeries Aerox 5 Wireless", "aerox", 3), 0x1860: ("SteelSeries Aerox 5 Wireless", "aerox_w", 3),
    0x185A: ("SteelSeries Aerox 9 Wireless", "aerox", 3), 0x1858: ("SteelSeries Aerox 9 Wireless", "aerox_w", 3),
    0x1876: ("SteelSeries Aerox 9 Wireless", "aerox", 3), 0x1874: ("SteelSeries Aerox 9 Wireless", "aerox_w", 3),
    0x1842: ("SteelSeries Prime Wireless", "aerox", 3), 0x1840: ("SteelSeries Prime Wireless", "aerox_w", 3),
    0x184A: ("SteelSeries Prime Mini Wireless", "aerox", 3), 0x1848: ("SteelSeries Prime Mini Wireless", "aerox_w", 3),
    0x1830: ("SteelSeries Rival 3 Wireless", "rival3", 3), 0x1872: ("SteelSeries Rival 3 Wireless Gen 2", "rival3", 3),
    0x172B: ("SteelSeries Rival 650 Wireless", "rival3", 0), 0x1726: ("SteelSeries Rival 650 Wireless", "rival3", 0),
}


def steelseries_query(dev, protocol: str):
    """(level, charging) or None."""
    if protocol in ("aerox", "aerox_w"):
        cmd, n = [0x92 | (0x40 if protocol == "aerox_w" else 0)], 2
    else:
        cmd, n = [0xAA, 0x01], 3
    dev.write(bytes([0x00] + cmd))
    data = bytes(dev.read(n, timeout_ms=250))
    if len(data) < n:
        return None
    if protocol.startswith("aerox"):
        level, charging = ((data[1] & 0x7F) - 1) * 5, bool(data[1] & 0x80)
    else:
        level, charging = int(data[0]), bool(data[2])
    if not 0 <= level <= 100:
        return None                                          # asleep or off: rivalcfg treats it the same
    return level, charging


def read_steelseries(hid: HidBackend) -> list[Battery]:
    out, done = [], set()
    for info in hid.enumerate(STEELSERIES):
        model = STEELSERIES_MICE.get(info.get("product_id"))
        if not model or info.get("interface_number") != model[2] or info.get("product_id") in done:
            continue
        done.add(info.get("product_id"))
        name, protocol, _ = model
        try:
            dev = hid.open(info["path"])
        except Exception:
            continue
        try:
            got = steelseries_query(dev, protocol)
        except Exception:
            got = None
        finally:
            _close(dev)
        level, charging = got if got else (None, None)
        out.append(Battery(key=f"steelseries:{name}", name=name, brand="SteelSeries", kind="mouse", level=level,
                           charging=charging, source="SteelSeries", approx=protocol.startswith("aerox")))
    return out


# =========================================================================== Razer
RAZER = 0x1532
RAZER_WIRELESS_WORDS = ("wireless", "hyperspeed", "receiver", "dongle", "dock", "lightspeed")
RAZER_TRANSACTION_IDS = (0x1F, 0x3F, 0xFF)       # differs by model; a wrong one just gets no answer


def razer_report(tid: int, cls: int, cmd: int, size: int) -> bytes:
    r = bytearray(90)
    r[1], r[5], r[6], r[7] = tid, size, cls, cmd
    crc = 0
    for b in r[2:88]:
        crc ^= b
    r[88] = crc
    return bytes(r)


def razer_ask(dev, tid: int, cls: int, cmd: int) -> int | None:
    """Send one Razer get-command and return arguments[1] of a successful reply."""
    dev.send_feature_report(b"\x00" + razer_report(tid, cls, cmd, 0x02))
    time.sleep(0.06)
    raw = bytes(dev.get_feature_report(0, 91))
    resp = raw[1:] if len(raw) == 91 else raw
    if len(resp) < 10 or resp[0] != 0x02 or resp[6] != cls or resp[7] != cmd:
        return None
    return resp[9]


def read_razer(hid: HidBackend) -> list[Battery]:
    out, done = [], set()
    for info in hid.enumerate(RAZER):
        product = (info.get("product_string") or "").strip()
        if not any(w in product.lower() for w in RAZER_WIRELESS_WORDS):
            continue                                         # wired gear: no battery, and OpenRGB may be busy on it
        if info.get("interface_number") not in (0, -1) or info.get("product_id") in done:
            continue
        try:
            dev = hid.open(info["path"])
        except Exception:
            continue
        try:
            level = charging = None
            for tid in RAZER_TRANSACTION_IDS:
                try:
                    raw = razer_ask(dev, tid, 0x07, 0x80)
                except Exception:
                    raw = None
                if raw is not None:
                    level = round(raw * 100 / 255)
                    try:
                        c = razer_ask(dev, tid, 0x07, 0x84)
                        charging = bool(c) if c is not None else None
                    except Exception:
                        pass
                    break
        finally:
            _close(dev)
        if level is None:
            continue
        done.add(info.get("product_id"))
        name = product if product.lower().startswith("razer") else f"Razer {product}"
        out.append(Battery(key=f"razer:{name}", name=name, brand="Razer", kind=kind_from_name(name, "mouse"),
                           level=level, charging=charging, source="Razer"))
    return out


# =========================================================================== headsets: HeadsetControl
HEADSETCONTROL_API = "https://api.github.com/repos/Sapd/HeadsetControl/releases/latest"
NO_WINDOW = 0x08000000 if IS_WIN else 0


def headsetcontrol_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "CentralRGB" / "HeadsetControl"


def headsetcontrol_exe() -> Path | None:
    d = headsetcontrol_dir()
    hit = next(iter(sorted(d.rglob("headsetcontrol*.exe"))), None) if d.is_dir() else None
    return hit


def pick_headsetcontrol_asset(assets: list[dict]) -> tuple[dict | None, dict | None]:
    """The Windows build (zip preferred, else exe) and its .sha256 file, from a GitHub release's assets."""
    win = [a for a in assets if "windows" in a["name"].lower() and not a["name"].lower().endswith((".sha256", ".sig", ".asc"))]
    win.sort(key=lambda a: (0 if a["name"].lower().endswith(".zip") else 1 if a["name"].lower().endswith(".exe") else 2))
    main = win[0] if win and win[0]["name"].lower().endswith((".zip", ".exe")) else None
    sha = next((a for a in assets if main and a["name"].lower() == main["name"].lower() + ".sha256"), None)
    return main, sha


def download_headsetcontrol(log=print) -> Path | None:
    """Fetch the latest HeadsetControl Windows build from its GitHub releases. Returns the .exe or None."""
    if not IS_WIN:
        return None
    try:
        req = urllib.request.Request(HEADSETCONTROL_API, headers={"User-Agent": APP_NAME,
                                                                  "Accept": "application/vnd.github+json"})
        rel = json.loads(urllib.request.urlopen(req, timeout=15).read())
        main, sha = pick_headsetcontrol_asset(rel.get("assets", []))
        if main is None:
            log("Headset batteries: no Windows build in HeadsetControl's latest release.")
            return None
        log(f"Downloading HeadsetControl {rel.get('tag_name', '')} for headset batteries: {main['browser_download_url']}")
        tmp = Path(tempfile.gettempdir()) / main["name"]
        with urllib.request.urlopen(urllib.request.Request(main["browser_download_url"],
                                                           headers={"User-Agent": APP_NAME}), timeout=60) as r, \
                open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        if sha is not None:
            want = urllib.request.urlopen(urllib.request.Request(sha["browser_download_url"],
                                                                 headers={"User-Agent": APP_NAME}),
                                          timeout=15).read().decode().split()[0].lower()
            got = hashlib.sha256(tmp.read_bytes()).hexdigest()
            if got != want:
                tmp.unlink(missing_ok=True)
                log("Headset batteries: the HeadsetControl download didn't match its checksum, so it wasn't used.")
                return None
        dest = headsetcontrol_dir()
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        if tmp.suffix.lower() == ".zip":
            with zipfile.ZipFile(tmp) as z:
                root = dest.resolve()
                for m in z.namelist():
                    if not str((dest / m).resolve()).startswith(str(root)):
                        raise RuntimeError(f"Unsafe path in zip: {m}")
                z.extractall(dest)
        else:
            shutil.copy2(tmp, dest / "headsetcontrol.exe")
        tmp.unlink(missing_ok=True)
        return headsetcontrol_exe()
    except Exception as e:
        log(f"Headset batteries: couldn't download HeadsetControl ({e}).")
        return None


def parse_headsetcontrol(text: str) -> list[Battery]:
    try:
        data = json.loads(text)
    except Exception:
        return []
    out = []
    for d in data.get("devices", []) if isinstance(data, dict) else []:
        b = d.get("battery") or {}
        status = str(b.get("status", ""))
        if not status or status == "BATTERY_ERROR":
            continue
        name = (d.get("device") or d.get("product") or "Headset").strip()
        vendor = (d.get("vendor") or "").strip()
        brand = vendor.split()[0].title() if vendor else name.split()[0]
        level = b.get("level")
        level = int(level) if isinstance(level, (int, float)) and 0 <= level <= 100 else None
        if status in ("BATTERY_UNAVAILABLE", "BATTERY_TIMEOUT"):
            level = None                                     # headset off or out of range
        out.append(Battery(key=f"headset:{name}", name=name, brand=brand, kind="headset", level=level,
                           charging=status == "BATTERY_CHARGING", source="HeadsetControl"))
    return out


def read_headsets(exe: Path | None) -> list[Battery]:
    if exe is None or not exe.exists():
        return []
    try:
        r = subprocess.run([str(exe), "-b", "-o", "json"], capture_output=True, text=True, timeout=10,
                           creationflags=NO_WINDOW)
    except Exception:
        return []
    return parse_headsetcontrol(r.stdout)


# =========================================================================== Bluetooth (Windows)
# DEVPKEY_Bluetooth_Battery: the level Windows shows for a Bluetooth device in Settings
BT_SCRIPT = (
    "$k='{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2';"
    "Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -like 'BTH*' } | ForEach-Object {"
    " $p = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $k -ErrorAction SilentlyContinue;"
    " if ($p -and $p.Data -ne $null) { [pscustomobject]@{Name=$_.FriendlyName; Level=[int]$p.Data} } }"
    " | ConvertTo-Json -Compress"
)


def parse_bluetooth(text: str) -> list[Battery]:
    try:
        data = json.loads(text) if text.strip() else []
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    out, seen = [], set()
    for d in data:
        name = str(d.get("Name") or "").strip()
        level = d.get("Level")
        if not name or not isinstance(level, int) or not 0 <= level <= 100 or name in seen:
            continue
        seen.add(name)
        brand = name.split()[0] if name else "Bluetooth"
        out.append(Battery(key=f"bt:{name}", name=name, brand=brand, kind=kind_from_name(name), level=level,
                           source="Windows Bluetooth"))
    return out


def read_bluetooth() -> list[Battery]:
    if not IS_WIN:
        return []
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", BT_SCRIPT],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    except Exception:
        return []
    return parse_bluetooth(r.stdout)


# =========================================================================== putting it together
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("wireless", "").replace("lightspeed", ""))


def merge(groups: list[list[Battery]]) -> list[Battery]:
    """One entry per device: the same mouse can show up over its receiver and over Bluetooth; keep the reading
    that has a level, from the first (most direct) reader."""
    out: dict[str, Battery] = {}
    for group in groups:
        for b in group:
            k = _norm(b.name)
            have = out.get(k)
            if have is None or (have.level is None and b.level is not None):
                out[k] = b
    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(out.values(), key=lambda b: (order.get(b.kind, 9), b.name.lower()))


class BatteryMonitor:
    """Reads every source in a background thread: HID readers every `interval` seconds, Bluetooth and headsets
    less often (they start a helper process). on_update(list[Battery]) is called from that thread."""

    def __init__(self, on_update=None, log=print, interval=120, slow_every=3, hid: HidBackend | None = None,
                 headsets=True, bluetooth=True):
        self.on_update, self.log = on_update, log
        self.interval, self.slow_every = interval, slow_every
        self._hid = hid
        self.headsets, self.bluetooth = headsets, bluetooth
        self.batteries: list[Battery] = []
        self._slow: list[Battery] = []
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._round = 0
        self._hc_tried = False
        self._logged = set()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="batteries", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def refresh(self):
        self._wake.set()

    def read_once(self) -> list[Battery]:
        hid = self._hid if self._hid is not None else real_hid()
        groups = []
        if hid is not None:
            for reader in (read_logitech, read_steelseries, read_razer):
                try:
                    groups.append(reader(hid))
                except Exception as e:
                    self.log(f"Battery reader {reader.__name__[5:]} failed: {e}")
        if self._round % max(1, self.slow_every) == 0:
            slow = []
            if self.headsets:
                exe = headsetcontrol_exe()
                if exe is None and not self._hc_tried and IS_WIN:
                    self._hc_tried = True
                    exe = download_headsetcontrol(self.log)
                slow += read_headsets(exe)
            if self.bluetooth:
                slow += read_bluetooth()
            self._slow = slow
        groups.append(self._slow)
        self._round += 1
        found = merge(groups)
        for b in found:
            if b.key not in self._logged:
                self._logged.add(b.key)
                lvl = f"{b.level}%" if b.level is not None else "asleep or off"
                self.log(f"Battery: {b.name} ({b.kind}) {lvl}{', charging' if b.charging else ''} via {b.source}")
        return found

    def _run(self):
        while not self._stop.is_set():
            try:
                self.batteries = self.read_once()
                if self.on_update:
                    self.on_update(list(self.batteries))
            except Exception as e:
                self.log(f"Battery check failed: {e}")
            self._wake.wait(self.interval)
            self._wake.clear()
