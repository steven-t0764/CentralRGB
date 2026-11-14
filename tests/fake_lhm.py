# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Simulated LibreHardwareMonitor for tests and previews: a sensor/fan backend with the same
methods as hw_monitor.LHMBackend (open, read, control_min, set_fan, set_default, close).

    from fake_lhm import FakeLHM
    central_rgb.App.TEST_BACKEND = FakeLHM()

Readings drift smoothly so graphs move. Set `cpu_temp` / `gpu_temp` to a number to pin a
temperature (the fan-safety tests use this); leave them None for the simulated values.
"""
from __future__ import annotations

import math
import random
import time

CPU = ("AMD Ryzen 7 7800X3D", "Cpu")
GPU = ("NVIDIA GeForce RTX 4070 SUPER", "GpuNvidia")
BOARD = ("ASUS ROG STRIX B650-A GAMING WIFI", "Motherboard")
SUPERIO = ("Nuvoton NCT6799D", "SuperIO")
DISK = ("Samsung SSD 990 PRO 2TB", "Storage")

# fan name, max RPM, belongs to the GPU?
FANS = [("CPU Fan", 1900, False), ("AIO Pump", 2800, False), ("Chassis Fan 1", 1500, False),
        ("Chassis Fan 2", 1500, False), ("GPU Fan 1", 2600, True)]


class FakeLHM:
    def __init__(self, seed=7):
        self.rng = random.Random(seed)
        self.t0 = time.time()
        self.controls: dict[str, bool] = {}
        self.pct = {self._cid(n, g): 45.0 for n, _, g in FANS}
        self.software: set[str] = set()      # fans under app control (not BIOS)
        self.cpu_temp = None
        self.gpu_temp = None
        self.opened = False

    @staticmethod
    def _cid(name, gpu):
        base = "/gpu-nvidia/0" if gpu else "/lpc/nct6799d/0"
        return f"{base}/control/{name.lower().replace(' ', '')}"

    def _wave(self, base, amp, period, noise=0.0):
        k = time.time() - self.t0
        return base + amp * math.sin(k / period) + self.rng.uniform(-noise, noise)

    def _s(self, hw, stype, name, value, sub=None, sid=None):
        hname, htype = hw
        if sub:
            hname, htype, parent = sub[0], sub[1], hw[0]
        else:
            parent = None
        return {"id": sid or f"/{htype.lower()}/{name.lower().replace(' ', '')}/{stype.lower()}",
                "hw": parent or hname, "sub": hname if parent else "", "hw_type": htype, "type": stype,
                "name": name, "value": value, "min": None, "max": None}

    # ---------- LHMBackend interface
    def open(self):
        self.opened = True

    def read(self) -> list[dict]:
        self.controls.clear()
        cpu_t = self.cpu_temp if self.cpu_temp is not None else self._wave(58, 7, 2.1, 0.6)
        gpu_t = self.gpu_temp if self.gpu_temp is not None else self._wave(52, 6, 2.7, 0.5)
        out = [
            self._s(CPU, "Temperature", "CPU Package", cpu_t),
            self._s(CPU, "Load", "CPU Total", self._wave(30, 14, 1.3, 4)),
            self._s(CPU, "Power", "Package", self._wave(62, 18, 1.6, 3)),
        ]
        for i in range(8):
            out.append(self._s(CPU, "Clock", f"Core #{i + 1}", self._wave(4650, 250, 1.1 + i / 7, 40)))
            out.append(self._s(CPU, "Temperature", f"Core #{i + 1}", cpu_t - self.rng.uniform(2, 6)))
        out += [
            self._s(GPU, "Temperature", "GPU Core", gpu_t),
            self._s(GPU, "Temperature", "GPU Hot Spot", gpu_t + 9),
            self._s(GPU, "Load", "GPU Core", max(0, self._wave(38, 25, 1.9, 5))),
            self._s(GPU, "Power", "GPU Package", self._wave(120, 50, 1.9, 6)),
            self._s(GPU, "Clock", "GPU Core", self._wave(2450, 200, 2.3, 20)),
            self._s(GPU, "SmallData", "GPU Memory Used", self._wave(5400, 600, 4.0, 30)),
            self._s(GPU, "SmallData", "GPU Memory Total", 12288.0),
            self._s(BOARD, "Temperature", "System", self._wave(36, 2, 5.0, 0.3), sub=SUPERIO),
            self._s(BOARD, "Voltage", "Vcore", self._wave(1.18, 0.03, 1.4, 0.005), sub=SUPERIO),
            self._s(DISK, "Temperature", "Composite Temperature", self._wave(41, 2, 6.0, 0.2)),
            self._s(DISK, "Load", "Used Space", 47.3),
        ]
        for name, rpm_max, gpu in FANS:
            cid = self._cid(name, gpu)
            pct = self.pct[cid]
            hw, sub = (GPU, None) if gpu else (BOARD, SUPERIO)
            out.append(self._s(hw, "Fan", name, rpm_max * pct / 100 + self.rng.uniform(-15, 15), sub=sub))
            out.append(self._s(hw, "Control", name, pct, sub=sub, sid=cid))
            self.controls[cid] = True
        return out

    def control_min(self, sid) -> float:
        return 0.0

    def set_fan(self, sid, pct: float):
        self.pct[sid] = float(pct)
        self.software.add(sid)

    def set_default(self, sid):
        self.software.discard(sid)
        self.pct[sid] = 45.0

    def close(self):
        self.opened = False
