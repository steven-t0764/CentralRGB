# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Central RGB - hardware monitoring + fan control.

Sensors and fan control come from LibreHardwareMonitor (LHM, open source, MPL-2.0),
loaded through pythonnet. LHM is downloaded automatically the first time and uses the
same PawnIO driver OpenRGB needs. If LHM can't load, basic stats still come from psutil.

Everything that touches LHM runs on ONE worker thread (LHM isn't thread-safe);
the UI talks to it through thread-safe methods.
"""
from __future__ import annotations

import collections
import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import psutil

import rgb_engine as eng

LHM_API = "https://api.github.com/repos/LibreHardwareMonitor/LibreHardwareMonitor/releases/latest"
LHM_FALLBACK = ("https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/"
                "v0.9.6/LibreHardwareMonitor.zip")

FAN_FLOOR = 20          # never drive a fan below this % (unless the hardware's own minimum is higher)
PUMP_FLOOR = 70         # liquid-cooler pumps need to keep flowing
EMERGENCY_TEMP = 90     # °C - any CPU/GPU at or above this forces every fan to 100 %
PRESETS = {             # temperature (°C) -> fan %
    "Silent":      [(40, 25), (60, 35), (75, 60), (85, 100)],
    "Balanced":    [(40, 35), (60, 50), (75, 75), (85, 100)],
    "Performance": [(40, 50), (60, 70), (70, 90), (80, 100)],
    "Max":         [(0, 100), (100, 100)],
}
PROFILES = ["Auto", "Silent", "Balanced", "Performance", "Max", "Custom"]
DEFAULT_CURVE = [(35, 30), (55, 45), (70, 70), (82, 100)]


def interp_curve(points, t: float) -> float:
    pts = sorted(points)
    if t <= pts[0][0]:
        return pts[0][1]
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if t <= t1:
            return p0 + (p1 - p0) * (t - t0) / max(t1 - t0, 1e-6)
    return pts[-1][1]


# ============================================================================ LHM backend
class LHMBackend:
    """Thin wrapper around LibreHardwareMonitorLib. Only call from the monitor thread."""

    def __init__(self, log, ram_temps=False):
        self.log = log
        self.ram_temps = ram_temps   # DIMM temps are read over the SMBus, which RGB RAM also uses
        self.computer = None
        self.controls = {}   # sensor id -> IControl

    # ---------- install / load
    @staticmethod
    def lhm_dir() -> Path:
        return eng.install_dir() / "LHM"

    def _find_dll(self):
        for base in (eng.app_dir() / "LHM", self.lhm_dir()):
            if base.is_dir():
                hit = next(base.rglob("LibreHardwareMonitorLib.dll"), None)
                if hit:
                    return hit
        return None

    def _download(self):
        url = LHM_FALLBACK
        try:
            req = urllib.request.Request(LHM_API, headers={"User-Agent": eng.APP_NAME,
                                                           "Accept": "application/vnd.github+json"})
            rel = json.loads(urllib.request.urlopen(req, timeout=15).read())
            zips = [a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")]
            # Prefer the .NET Framework build (plain "LibreHardwareMonitor.zip"); it's built into Windows.
            plain = [a for a in zips if "net." not in a["name"].lower()]
            if plain or zips:
                url = (plain or zips)[0]["browser_download_url"]
        except Exception as e:
            self.log(f"Couldn't check the latest LibreHardwareMonitor ({e}); using v0.9.6.")
        self.log(f"Downloading hardware-monitor components: {url}")
        tmp = Path(tempfile.gettempdir()) / "lhm_download.zip"
        req = urllib.request.Request(url, headers={"User-Agent": eng.APP_NAME})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        dest = self.lhm_dir()
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        with zipfile.ZipFile(tmp) as z:
            root = dest.resolve()
            for m in z.namelist():
                if not str((dest / m).resolve()).startswith(str(root)):
                    raise RuntimeError(f"Unsafe path in zip: {m}")
            z.extractall(dest)
        tmp.unlink(missing_ok=True)

    def open(self):
        if not eng.IS_WIN:
            raise RuntimeError("Detailed sensors and fan control are Windows-only.")
        dll = self._find_dll()
        if not dll:
            self._download()
            dll = self._find_dll()
            if not dll:
                raise RuntimeError("LibreHardwareMonitorLib.dll not found in the download.")
        dll_dir = dll.parent

        from pythonnet import load
        last_err = None
        for runtime in ("netfx", "coreclr"):
            try:
                load(runtime)
                break
            except Exception as e:  # already loaded, or runtime missing
                last_err = e
                if "already" in str(e).lower():
                    break
        else:
            raise RuntimeError(f"Couldn't start .NET ({last_err})")
        import clr  # noqa: F401  (pythonnet)
        from System import AppDomain, ResolveEventHandler
        from System.Reflection import Assembly, AssemblyName

        def resolve(_sender, args):  # find LHM's dependency DLLs next to it
            p = dll_dir / (AssemblyName(args.Name).Name + ".dll")
            return Assembly.LoadFrom(str(p)) if p.exists() else None
        try:
            AppDomain.CurrentDomain.AssemblyResolve += ResolveEventHandler(resolve)
        except Exception:
            pass
        sys.path.append(str(dll_dir))
        clr.AddReference(str(dll))
        from LibreHardwareMonitor.Hardware import Computer

        c = Computer()
        props = ["IsCpuEnabled", "IsGpuEnabled", "IsMotherboardEnabled", "IsControllerEnabled",
                 "IsStorageEnabled", "IsNetworkEnabled", "IsPsuEnabled"]
        # LHM's memory group polls each DIMM's temperature chip over the SMBus (and switches SPD pages).
        # OpenRGB drives RGB RAM over the same bus, so polling it makes RGB RAM flicker. Off by default;
        # memory usage comes from Windows (psutil) either way.
        if self.ram_temps:
            props.append("IsMemoryEnabled")
        for prop in props:
            try:
                setattr(c, prop, True)
            except Exception:
                pass
        c.Open()
        self.computer = c
        self.log(f"Hardware monitor loaded ({dll_dir.name}).")

    # ---------- reading
    def read(self) -> list[dict]:
        out = []
        self.controls.clear()

        def walk(hw, parent_name=None):
            hw.Update()
            hw_name = str(hw.Name)
            hw_type = str(hw.HardwareType)
            for s in hw.Sensors:
                v = s.Value
                sid = str(s.Identifier)
                stype = str(s.SensorType)
                out.append({"id": sid, "hw": parent_name or hw_name, "sub": hw_name if parent_name else "",
                            "hw_type": hw_type, "type": stype, "name": str(s.Name),
                            "value": float(v) if v is not None else None,
                            "min": float(s.Min) if s.Min is not None else None,
                            "max": float(s.Max) if s.Max is not None else None})
                if stype == "Control" and s.Control is not None:
                    self.controls[sid] = s.Control
            for sub in hw.SubHardware:
                walk(sub, parent_name or hw_name)

        for hw in self.computer.Hardware:
            walk(hw)
        return out

    def control_min(self, sid) -> float:
        try:
            return float(self.controls[sid].MinSoftwareValue)
        except Exception:
            return 0.0

    def set_fan(self, sid, pct: float):
        self.controls[sid].SetSoftware(float(pct))

    def set_default(self, sid):
        try:
            self.controls[sid].SetDefault()
        except Exception:
            pass

    def close(self):
        try:
            if self.computer:
                self.computer.Close()
        except Exception:
            pass


# ============================================================================ monitor thread
class ProcBackend:
    """Runs LibreHardwareMonitor in a separate helper process.

    LibreHardwareMonitor is .NET, reached through pythonnet, which holds Python's interpreter lock for the
    whole of every .NET call. Loading it (drivers, SMBus scans) can take seconds, and in-process that froze
    the window even though nothing showed up as CPU use. In its own process it can't block the app.
    Same interface as LHMBackend. If the app dies, the helper sees its input close and hands every fan
    back to the BIOS before exiting."""

    def __init__(self, log, ram_temps=False, cmd=None):
        self.log = log
        self.ram_temps = ram_temps
        self.cmd = cmd
        self.proc = None
        self.controls: dict[str, float] = {}   # control sensor id -> minimum allowed %
        self.lock = threading.Lock()

    def _command(self):
        if self.cmd:
            return list(self.cmd)
        if getattr(sys, "frozen", False):
            return [sys.executable, "--sensor-worker"]
        return [sys.executable, str(Path(__file__).resolve()), "--sensor-worker"]

    def _send(self, msg: dict) -> dict:
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                raise RuntimeError("sensor helper is not running")
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError("sensor helper stopped")
                reply = json.loads(line)
                if "log" in reply:
                    self.log(reply["log"])
                    continue
                if "error" in reply:
                    raise RuntimeError(reply["error"])
                return reply

    def open(self):
        if not eng.IS_WIN and not self.cmd:
            raise RuntimeError("Detailed sensors and fan control are Windows-only.")
        args = self._command() + (["--ram-temps"] if self.ram_temps else [])
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", bufsize=1,
                                     # below-normal priority: the helper can never starve the window
                                     creationflags=eng.NO_WINDOW | (0x00004000 if eng.IS_WIN else 0))
        self._send({"cmd": "open"})

    def read(self) -> list[dict]:
        r = self._send({"cmd": "read"})
        self.controls = r.get("controls", {})
        return r.get("sensors", [])

    def control_min(self, sid) -> float:
        return float(self.controls.get(sid, 0.0))

    def set_fan(self, sid, pct: float):
        self._send({"cmd": "set", "id": sid, "pct": float(pct)})

    def set_default(self, sid):
        try:
            self._send({"cmd": "default", "id": sid})
        except Exception:
            pass

    def close(self):
        try:
            self._send({"cmd": "close"})
        except Exception:
            pass
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _std_stream(which: int, mode: str):
    """stdin/stdout for the helper; a windowed exe may start with sys.stdin/stdout set to None."""
    cur = sys.stdin if which == 0 else sys.stdout
    if cur is not None:
        return cur
    import ctypes, msvcrt
    h = ctypes.windll.kernel32.GetStdHandle(-10 if which == 0 else -11)
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY if which == 0 else os.O_WRONLY)
    return open(fd, mode, encoding="utf-8", buffering=1)


def sensor_worker(backend=None):
    """Entry point of the helper process: answers one JSON request per line on stdin."""
    inp, out = _std_stream(0, "r"), _std_stream(1, "w")

    def reply(obj):
        out.write(json.dumps(obj) + "\n")
        out.flush()

    b = backend or LHMBackend(lambda m: reply({"log": m}), ram_temps="--ram-temps" in sys.argv)
    touched: set[str] = set()
    try:
        for line in inp:
            try:
                req = json.loads(line)
                cmd = req.get("cmd")
                if cmd == "open":
                    b.open()
                    reply({"ok": True})
                elif cmd == "read":
                    sensors = b.read()
                    reply({"sensors": sensors, "controls": {k: b.control_min(k) for k in b.controls}})
                elif cmd == "set":
                    b.set_fan(req["id"], req["pct"])
                    touched.add(req["id"])
                    reply({"ok": True})
                elif cmd == "default":
                    b.set_default(req["id"])
                    touched.discard(req["id"])
                    reply({"ok": True})
                elif cmd == "close":
                    reply({"ok": True})
                    break
                else:
                    reply({"error": f"unknown command {cmd}"})
            except Exception as e:
                reply({"error": str(e)})
    finally:
        for sid in touched:                 # app went away: give the fans back to the BIOS
            b.set_default(sid)
        b.close()


class HardwareMonitor(threading.Thread):
    INTERVAL = 1.0

    def __init__(self, log, settings, backend=None):
        super().__init__(daemon=True)
        self.log = log
        self.settings = settings
        self.backend = backend
        self.lock = threading.Lock()
        self.cmds: queue.Queue = queue.Queue()
        self._stop_evt = threading.Event()
        self.status = "starting"
        self.status_msg = "Loading sensors…"
        self.sensors: list[dict] = []
        self.fans: dict[str, dict] = {}     # control sensor id -> fan info
        self.metrics: dict = {}
        self.hist = collections.defaultdict(lambda: collections.deque(maxlen=90))
        fan_cfg = settings.data.setdefault("fans", {})
        self.profile = fan_cfg.get("profile", "Auto")
        self.curve = [tuple(p) for p in fan_cfg.get("curve", DEFAULT_CURVE)]
        self.manual: dict[str, float] = dict(fan_cfg.get("manual", {}))
        self._net_last = None
        self._disk_last = None

    # ---------------- public, thread-safe
    def snapshot(self):
        with self.lock:
            return {"status": self.status, "msg": self.status_msg, "sensors": list(self.sensors),
                    "fans": {k: dict(v) for k, v in self.fans.items()}, "metrics": dict(self.metrics),
                    "hist": {k: list(v) for k, v in self.hist.items()},
                    "profile": self.profile, "curve": list(self.curve), "manual": dict(self.manual)}

    def set_profile(self, name):
        self.cmds.put(("profile", name))

    def set_curve(self, pts):
        self.cmds.put(("curve", [tuple(map(float, p)) for p in pts]))

    def set_manual(self, fan_id, pct):
        self.cmds.put(("manual", fan_id, pct))

    def stop(self):
        """Hand every fan back to the BIOS / firmware and stop."""
        self.cmds.put(("quit",))
        self._stop_evt.set()
        self.join(timeout=3)

    # ---------------- worker
    def _save_cfg(self):
        self.settings["fans"] = {"profile": self.profile, "curve": [list(p) for p in self.curve],
                                 "manual": self.manual}

    def run(self):
        psutil.cpu_percent(None)
        if self.backend is None:
            self.backend = ProcBackend(self.log, ram_temps=bool(self.settings.data.get("ram_temps", False)))
        try:
            self.backend.open()
            self.status, self.status_msg = "ok", "Sensors online"
        except Exception as e:
            self.backend = None
            self.status = "basic"
            self.status_msg = f"Basic stats only - {e}"
            self.log(f"Detailed sensors / fan control unavailable: {e}")
        while True:
            t0 = time.time()
            quitting = False
            while not self.cmds.empty():
                cmd = self.cmds.get()
                if cmd[0] == "quit":
                    quitting = True
                elif cmd[0] == "profile":
                    self.profile = cmd[1]
                    self.manual.clear()
                    self._save_cfg()
                elif cmd[0] == "curve":
                    self.curve = cmd[1]
                    self._save_cfg()
                elif cmd[0] == "manual":
                    if cmd[2] is None:
                        self.manual.pop(cmd[1], None)
                    else:
                        self.manual[cmd[1]] = float(cmd[2])
                    self._save_cfg()
            if quitting or self._stop_evt.is_set():
                self._restore_all()
                if self.backend:
                    self.backend.close()
                return
            try:
                self._tick()
            except Exception as e:
                self.log(f"Monitor error: {e}")
            time.sleep(max(0.1, self.INTERVAL - (time.time() - t0)))

    def _restore_all(self):
        if not self.backend:
            return
        for fid, f in self.fans.items():
            if f.get("controlled"):
                self.backend.set_default(fid)
        self.log("Fans handed back to BIOS control.")

    # ---------------- one update
    def _tick(self):
        sensors = self.backend.read() if self.backend else []
        m = self._basic_metrics()
        self._derive(sensors, m)
        fans = self._fan_logic(sensors, m) if self.backend else {}
        with self.lock:
            self.sensors = sensors
            self.metrics = m
            self.fans = fans
            for k in ("cpu_load", "cpu_temp", "gpu_load", "gpu_temp", "ram_pct", "net_down", "net_up",
                      "disk_read", "disk_write"):
                if m.get(k) is not None:
                    self.hist[k].append(m[k])

    def _basic_metrics(self) -> dict:
        m = {"cpu_load": psutil.cpu_percent(None), "cores": psutil.cpu_percent(None, percpu=True)}
        vm = psutil.virtual_memory()
        m.update(ram_used=vm.used / 2**30, ram_total=vm.total / 2**30, ram_pct=vm.percent)
        try:
            freq = psutil.cpu_freq()
            m["cpu_clock"] = freq.current if freq else None
        except Exception:
            m["cpu_clock"] = None
        now = time.time()
        n = psutil.net_io_counters()
        if self._net_last:
            dt = max(now - self._net_last[0], 1e-3)
            m["net_down"] = (n.bytes_recv - self._net_last[1]) / dt / 2**20 * 8   # Mbit/s
            m["net_up"] = (n.bytes_sent - self._net_last[2]) / dt / 2**20 * 8
        self._net_last = (now, n.bytes_recv, n.bytes_sent)
        try:
            d = psutil.disk_io_counters()
            if d and self._disk_last:
                dt = max(now - self._disk_last[0], 1e-3)
                m["disk_read"] = (d.read_bytes - self._disk_last[1]) / dt / 2**20   # MB/s
                m["disk_write"] = (d.write_bytes - self._disk_last[2]) / dt / 2**20
            if d:
                self._disk_last = (now, d.read_bytes, d.write_bytes)
        except Exception:
            pass
        disks = []
        for p in psutil.disk_partitions(all=False):
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
                if u.total < 2**30:
                    continue
                disks.append((p.mountpoint, u.used / 2**30, u.total / 2**30, u.percent))
            except Exception:
                pass
        m["disks"] = disks[:6]
        m["uptime"] = now - psutil.boot_time()
        m["procs"] = len(psutil.pids())
        return m

    @staticmethod
    def _pick(sensors, hw_prefix, stype, names=(), agg=max):
        cands = [s for s in sensors if s["hw_type"].startswith(hw_prefix) and s["type"] == stype
                 and s["value"] is not None]
        for n in names:
            for s in cands:
                if s["name"] == n:
                    return s["value"]
        vals = [s["value"] for s in cands]
        return agg(vals) if vals else None

    def _derive(self, sensors, m):
        if not sensors:
            return
        p = self._pick
        m["cpu_temp"] = p(sensors, "Cpu", "Temperature", ("CPU Package", "Core (Tctl/Tdie)", "Tctl/Tdie", "Core Max"))
        m["cpu_power"] = p(sensors, "Cpu", "Power", ("CPU Package", "Package"))
        clk = [s["value"] for s in sensors if s["hw_type"] == "Cpu" and s["type"] == "Clock"
               and s["name"].startswith("Core") and s["value"]]
        if clk:
            m["cpu_clock"] = max(clk)
        m["gpu_name"] = next((s["hw"] for s in sensors if s["hw_type"].startswith("Gpu")), None)
        m["gpu_load"] = p(sensors, "Gpu", "Load", ("GPU Core", "D3D 3D"))
        m["gpu_temp"] = p(sensors, "Gpu", "Temperature", ("GPU Core", "GPU Hot Spot"))
        m["gpu_power"] = p(sensors, "Gpu", "Power", ("GPU Package", "GPU Power", "GPU Core"))
        m["gpu_clock"] = p(sensors, "Gpu", "Clock", ("GPU Core",))
        m["vram_used"] = p(sensors, "Gpu", "SmallData", ("GPU Memory Used", "D3D Dedicated Memory Used"))
        m["vram_total"] = p(sensors, "Gpu", "SmallData", ("GPU Memory Total",))
        temps = {}
        for s in sensors:
            if s["hw_type"] == "Storage" and s["type"] == "Temperature" and s["value"] is not None:
                temps.setdefault(s["hw"], s["value"])
        m["disk_temps"] = temps

    def _fan_logic(self, sensors, m) -> dict:
        prev = self.fans
        by_hw = collections.defaultdict(list)
        for s in sensors:
            by_hw[s["hw"] + "|" + s["sub"]].append(s)
        fans = {}
        cpu_t, gpu_t = m.get("cpu_temp"), m.get("gpu_temp")
        emergency = any(t is not None and t >= EMERGENCY_TEMP for t in (cpu_t, gpu_t))
        m["fan_emergency"] = emergency
        for key, group in by_hw.items():
            rpms = [s for s in group if s["type"] == "Fan"]
            ctrls = [s for s in group if s["type"] == "Control"]
            for i, c in enumerate(ctrls):
                if c["id"] not in self.backend.controls:
                    continue
                rpm = next((r for r in rpms if r["name"] == c["name"]), rpms[i] if i < len(rpms) else None)
                src = "gpu" if c["hw_type"].startswith("Gpu") else "cpu"
                old = prev.get(c["id"], {})
                f = {"id": c["id"], "name": c["name"], "hw": c["sub"] or c["hw"], "src": src,
                     "rpm": rpm["value"] if rpm else None, "pct": c["value"],
                     "controlled": old.get("controlled", False), "last": old.get("last"),
                     "manual": self.manual.get(c["id"])}
                floor = max(PUMP_FLOOR if "pump" in c["name"].lower() else FAN_FLOOR, self.backend.control_min(c["id"]))
                temp = gpu_t if src == "gpu" else cpu_t
                if emergency:
                    target = 100.0
                elif f["manual"] is not None:
                    target = f["manual"]
                elif self.profile == "Auto":
                    if f["controlled"]:
                        self.backend.set_default(c["id"])
                        f["controlled"] = False
                    f["target"] = None
                    fans[c["id"]] = f
                    continue
                else:
                    curve = self.curve if self.profile == "Custom" else PRESETS[self.profile]
                    target = interp_curve(curve, temp) if temp is not None else 60.0
                target = max(floor, min(100.0, target))
                if f["last"] is not None and target < f["last"] and not emergency and f["manual"] is None:
                    target = max(target, f["last"] - 4)    # ramp down gently, ramp up instantly
                if f["last"] is None or abs(target - f["last"]) >= 0.5 or not f["controlled"]:
                    try:
                        self.backend.set_fan(c["id"], target)
                        f["controlled"] = True
                    except Exception as e:
                        f["error"] = str(e)
                f["last"] = f["target"] = target
                fans[c["id"]] = f
        return fans


# ============================================================================ static system info
def system_info() -> list[tuple[str, list[tuple[str, str]]]]:
    """[(section, [(label, value)])] - slow (PowerShell); call from a background thread."""
    out = []
    if eng.IS_WIN:
        ps = r"""
$os=Get-CimInstance Win32_OperatingSystem; $cs=Get-CimInstance Win32_ComputerSystem
$r=[ordered]@{
 os=[ordered]@{Name=$os.Caption; Version=$os.Version; Build=$os.BuildNumber; Arch=$os.OSArchitecture;
   Installed=$os.InstallDate.ToString('yyyy-MM-dd'); Boot=$os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm');
   Computer=$cs.Name; Model="$($cs.Manufacturer) $($cs.Model)"}
 cpu=@(Get-CimInstance Win32_Processor | % {[ordered]@{Name=$_.Name.Trim(); Cores=$_.NumberOfCores; Threads=$_.NumberOfLogicalProcessors; MaxMHz=$_.MaxClockSpeed; L2KB=$_.L2CacheSize; L3KB=$_.L3CacheSize; Socket=$_.SocketDesignation}})
 board=[ordered]@{Board=(Get-CimInstance Win32_BaseBoard | % {"$($_.Manufacturer) $($_.Product)"}); BIOS=(Get-CimInstance Win32_BIOS | % {"$($_.Manufacturer) $($_.SMBIOSBIOSVersion) ($($_.ReleaseDate.ToString('yyyy-MM-dd')))"})}
 ram=@(Get-CimInstance Win32_PhysicalMemory | % {[ordered]@{Slot=$_.DeviceLocator; Maker=$_.Manufacturer; Part="$($_.PartNumber)".Trim(); GB=[math]::Round($_.Capacity/1GB); MHz=$_.ConfiguredClockSpeed}})
 gpu=@(Get-CimInstance Win32_VideoController | % {[ordered]@{Name=$_.Name; Driver=$_.DriverVersion; Res="$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate)Hz"}})
 disk=@(Get-CimInstance Win32_DiskDrive | % {[ordered]@{Model=$_.Model; GB=[math]::Round($_.Size/1GB); Bus=$_.InterfaceType}})
 net=@(Get-CimInstance Win32_NetworkAdapter -Filter 'PhysicalAdapter=True' | ? {$_.NetEnabled} | % {[ordered]@{Name=$_.Name; Mbps=[math]::Round($_.Speed/1e6)}})
}; $r | ConvertTo-Json -Depth 4 -Compress"""
        r = eng.run_quiet(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=45)
        try:
            d = json.loads(r.stdout)
        except Exception:
            d = {}
        L = lambda x: x if isinstance(x, list) else ([x] if x else [])
        if d.get("os"):
            o = d["os"]
            out.append(("Operating system", [("Windows", o.get("Name", "")), ("Version", f"{o.get('Version')} (build {o.get('Build')})"),
                                             ("Architecture", o.get("Arch", "")), ("Installed", o.get("Installed", "")),
                                             ("Last boot", o.get("Boot", "")), ("Computer", o.get("Computer", "")),
                                             ("System", o.get("Model", ""))]))
        for c in L(d.get("cpu")):
            out.append(("Processor", [("Model", c["Name"]), ("Cores / threads", f"{c['Cores']} / {c['Threads']}"),
                                      ("Max clock", f"{c['MaxMHz']} MHz"), ("L2 / L3 cache", f"{c['L2KB']//1024} MB / {c['L3KB']//1024} MB"),
                                      ("Socket", c.get("Socket", ""))]))
        if d.get("board"):
            out.append(("Motherboard", [("Board", d["board"].get("Board", "")), ("BIOS", d["board"].get("BIOS", ""))]))
        rams = L(d.get("ram"))
        if rams:
            total = sum(x["GB"] or 0 for x in rams)
            out.append(("Memory", [("Installed", f"{total} GB in {len(rams)} sticks")] +
                        [(x["Slot"], f"{x['GB']} GB  {x['Maker']} {x['Part']}  @ {x['MHz']} MHz") for x in rams]))
        gpus = L(d.get("gpu"))
        if gpus:
            out.append(("Graphics", [(f"GPU {i+1}", f"{g['Name']}  (driver {g['Driver']})") for i, g in enumerate(gpus)] +
                        [("Display", g["Res"]) for g in gpus if g.get("Res", "x").strip(" x@Hz")]))
        disks = L(d.get("disk"))
        if disks:
            out.append(("Storage", [(x["Bus"] or "Disk", f"{x['Model']}  ({x['GB']} GB)") for x in disks]))
        nets = L(d.get("net"))
        if nets:
            out.append(("Network", [(x["Name"], f"{x['Mbps']} Mbps") for x in nets]))
    if not out:  # non-Windows / fallback
        u = platform.uname()
        out.append(("Operating system", [("System", f"{u.system} {u.release}"), ("Machine", u.machine),
                                         ("Computer", u.node)]))
        model = ""
        try:
            for line in open("/proc/cpuinfo"):
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
        except Exception:
            model = platform.processor()
        out.append(("Processor", [("Model", model or "Unknown"),
                                  ("Cores / threads", f"{psutil.cpu_count(False)} / {psutil.cpu_count(True)}")]))
        out.append(("Memory", [("Installed", f"{psutil.virtual_memory().total / 2**30:.1f} GB")]))
    out.append(("Python runtime", [("Central RGB", eng.APP_VERSION), ("Python", platform.python_version())]))
    return out


if __name__ == "__main__" and "--sensor-worker" in sys.argv:
    sensor_worker()
