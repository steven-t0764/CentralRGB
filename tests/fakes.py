# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Simulated hardware for previews and tests: a fake OpenRGB client and a fake sensor/fan backend."""
from __future__ import annotations

import math
import time
from types import SimpleNamespace

from openrgb.utils import DeviceType, ModeColors


class FakeMode:
    def __init__(self, name, color_mode):
        self.name, self.color_mode, self.colors, self.colors_max = name, color_mode, [], 1


class FakeDevice:
    def __init__(self, name, dtype, leds, zones, vendor, loc):
        self.name, self.type = name, dtype
        self.metadata = SimpleNamespace(vendor=vendor, description=f"{vendor} {name}", version="1.0",
                                        serial="", location=loc)
        self.leds = [SimpleNamespace(name=f"LED {i + 1}") for i in range(leds)]
        self.zones = [SimpleNamespace(name=z, leds=self.leds[:n]) for z, n in zones]
        self.modes = [FakeMode("Direct", ModeColors.PER_LED), FakeMode("Static", ModeColors.MODE_SPECIFIC),
                      FakeMode("Breathing", ModeColors.MODE_SPECIFIC)]
        self.active_mode = 0
        self.colors = []

    def set_mode(self, m, save=False):
        name = m if isinstance(m, str) else m.name
        self.active_mode = next(i for i, x in enumerate(self.modes) if x.name.lower() == name.lower())

    def set_custom_mode(self):
        self.active_mode = 0

    def _set_device_colors(self, cols, fast=False):
        self.colors = list(cols)

    def set_color(self, c):
        self.colors = [c] * len(self.leds)

    def save_mode(self):
        pass


def demo_devices():
    return [
        FakeDevice("ASUS ROG STRIX Z790-E", DeviceType.MOTHERBOARD, 12, [("Aura Mainboard", 8), ("Header", 4)], "ASUS", "I2C: /dev/i2c-0"),
        FakeDevice("NVIDIA GeForce RTX 4080", DeviceType.GPU, 16, [("GPU", 16)], "NVIDIA", "I2C: /dev/i2c-1"),
        FakeDevice("Corsair Vengeance RGB #1", DeviceType.DRAM, 10, [("DRAM", 10)], "Corsair", "I2C: 0x58"),
        FakeDevice("Corsair Vengeance RGB #2", DeviceType.DRAM, 10, [("DRAM", 10)], "Corsair", "I2C: 0x59"),
        FakeDevice("ARGB LED strip", DeviceType.LEDSTRIP, 30, [("Strip", 30)], "Generic", "HID: strip"),
        FakeDevice("Corsair K70 RGB", DeviceType.KEYBOARD, 104, [("Keys", 104)], "Corsair", "HID: kb"),
        FakeDevice("Logitech G502", DeviceType.MOUSE, 2, [("Logo", 1), ("DPI", 1)], "Logitech", "HID: mouse"),
    ]


class FakeClient:
    def __init__(self, *a, **kw):
        self.devices = demo_devices()

    def update(self):
        pass

    def disconnect(self):
        pass


class FakeLHM:
    """Sensor/fan backend with believable, gently varying values."""

    def __init__(self):
        self.controls = {}
        self.pct = {}
        self.t0 = time.time()

    def open(self):
        pass

    def read(self):
        t = time.time() - self.t0
        w = lambda a, b, s=1.0: a + b * (0.5 + 0.5 * math.sin(t * s))
        out = []

        def add(sid, hw, hw_type, stype, name, val, sub=""):
            out.append({"id": sid, "hw": hw, "sub": sub, "hw_type": hw_type, "type": stype, "name": name,
                        "value": val, "min": val, "max": val})
        cpu, gpu, mb, chip = "AMD Ryzen 7 7800X3D", "NVIDIA GeForce RTX 4080", "ASUS ROG STRIX Z790-E", "Nuvoton NCT6798D"
        add("/cpu/t", cpu, "Cpu", "Temperature", "CPU Package", w(48, 14, 0.4))
        add("/cpu/p", cpu, "Cpu", "Power", "Package", w(45, 40, 0.5))
        for i in range(8):
            add(f"/cpu/c{i}", cpu, "Cpu", "Clock", f"Core #{i + 1}", w(4300, 700, 0.7 + i * 0.1))
        add("/gpu/t", gpu, "GpuNvidia", "Temperature", "GPU Core", w(44, 18, 0.3))
        add("/gpu/l", gpu, "GpuNvidia", "Load", "GPU Core", w(10, 70, 0.35))
        add("/gpu/p", gpu, "GpuNvidia", "Power", "GPU Package", w(40, 200, 0.35))
        add("/gpu/c", gpu, "GpuNvidia", "Clock", "GPU Core", w(1500, 1100, 0.35))
        add("/gpu/vu", gpu, "GpuNvidia", "SmallData", "GPU Memory Used", w(2500, 5000, 0.2))
        add("/gpu/vt", gpu, "GpuNvidia", "SmallData", "GPU Memory Total", 16384.0)
        add("/nvme/t", "Samsung 990 PRO 2TB", "Storage", "Temperature", "Temperature", w(38, 6, 0.2))
        fans = [("CPU Fan", 1200), ("Chassis Fan #1", 900), ("Chassis Fan #2", 900), ("AIO Pump", 2600)]
        for i, (n, rpm) in enumerate(fans):
            sid = f"/lpc/ctrl/{i}"
            self.controls[sid] = True
            p = self.pct.get(sid, 55.0)
            add(f"/lpc/fan/{i}", mb, "Motherboard", "Fan", n, rpm * (0.6 + p / 200) + w(0, 40, 1 + i), chip)
            add(sid, mb, "Motherboard", "Control", n, p, chip)
        gsid = "/gpu/ctrl/0"
        self.controls[gsid] = True
        add("/gpu/fan/0", gpu, "GpuNvidia", "Fan", "GPU Fan 1", 1100 + w(0, 300, 0.3))
        add(gsid, gpu, "GpuNvidia", "Control", "GPU Fan 1", self.pct.get(gsid, 40.0))
        return out

    def control_min(self, sid):
        return 0.0

    def set_fan(self, sid, pct):
        self.pct[sid] = pct

    def set_default(self, sid):
        self.pct.pop(sid, None)

    def close(self):
        pass
