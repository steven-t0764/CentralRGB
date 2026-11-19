# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Simulated OpenRGB for tests and previews: a stand-in for openrgb-python's OpenRGBClient that
reports a set of demo RGB devices, so Central RGB can run on a machine with no RGB hardware
(or no Windows).

    import fake_openrgb
    fake_openrgb.install()      # before creating central_rgb.App()
    fake_openrgb.install(devices=fake_openrgb.B550_PC, ram_blocked=True)   # RAM hidden, as when the SMBus is held

The devices only record what they were told (mode, colors); nothing is sent anywhere.
"""
from __future__ import annotations

from types import SimpleNamespace

from openrgb.utils import DeviceType, ModeColors, RGBColor

# name, type, vendor, zones [(zone name, LED count)], modes
DEMO_DEVICES = [
    ("ASUS ROG STRIX B650-A GAMING WIFI", DeviceType.MOTHERBOARD, "ASUS",
     [("Aura Mainboard", 4), ("Aura Addressable 1", 12)], ("Direct", "Static", "Breathing", "Rainbow", "Off")),
    ("NVIDIA GeForce RTX 4070 SUPER", DeviceType.GPU, "ASUS",
     [("GPU", 8)], ("Direct", "Static", "Breathing", "Off")),
    ("Corsair Vengeance RGB DDR5 (DIMM 1)", DeviceType.DRAM, "Corsair",
     [("DRAM", 10)], ("Direct", "Static", "Color Pulse", "Off")),
    ("Corsair Vengeance RGB DDR5 (DIMM 2)", DeviceType.DRAM, "Corsair",
     [("DRAM", 10)], ("Direct", "Static", "Color Pulse", "Off")),
    ("Lian Li UNI FAN SL-INF Controller", DeviceType.LEDSTRIP, "Lian Li",
     [("Fan 1", 20), ("Fan 2", 20), ("Fan 3", 20)], ("Direct", "Static", "Rainbow", "Off")),
    ("NZXT Kraken Elite 360", DeviceType.COOLER, "NZXT",
     [("Pump Ring", 24)], ("Direct", "Fixed", "Breathing", "Spectrum Wave")),
    ("Razer BlackWidow V4", DeviceType.KEYBOARD, "Razer",
     [("Keyboard", 104)], ("Direct", "Static", "Spectrum Cycle", "Off")),
    ("Logitech G502 X Plus", DeviceType.MOUSE, "Logitech",
     [("Logo", 1), ("Strip", 8)], ("Direct", "Static", "Breathing", "Off")),
]

# Corsair Vengeance RGB DDR4 (the original, non-Pro line: part numbers CMR...). OpenRGB's "Corsair
# Vengeance" detector finds each stick on the SMBus (AMD: the piix4 bus) at addresses 0x58-0x5F.
CORSAIR_VENGEANCE_DDR4 = [
    (f"Corsair Vengeance RGB DDR4 (DIMM {i})", DeviceType.DRAM, "Corsair",
     [("Corsair Vengeance RGB", 1)], ("Direct", "Static", "Breathing", "Color Pulse", "Off"))
    for i in range(1, 5)
]
# What Windows reports for those four sticks (Win32_PhysicalMemory "Manufacturer PartNumber").
CORSAIR_VENGEANCE_DDR4_WMI = ["Corsair CMR64GX4M4C3200C16"] * 4

# A Ryzen PC on an MSI B550 board with four Vengeance RGB DDR4 sticks and a USB keyboard.
B550_PC = [
    ("MSI B550-A PRO (MS-7C56)", DeviceType.MOTHERBOARD, "MSI",
     [("JRGB1", 1), ("JRAINBOW1", 30), ("Onboard LEDs", 6)], ("Direct", "Static", "Breathing", "Rainbow", "Off")),
    ("Razer Huntsman V2 Tenkeyless", DeviceType.KEYBOARD, "Razer",
     [("Keyboard", 87)], ("Direct", "Static", "Spectrum Cycle", "Off")),
] + CORSAIR_VENGEANCE_DDR4


class FakeDevice:
    def __init__(self, idx, name, dtype, vendor, zones, mode_names):
        self.id = idx
        self.name = name
        self.type = dtype
        self.metadata = SimpleNamespace(vendor=vendor, description=f"{vendor} {name}", version="1.0",
                                        serial=f"DEMO{idx:04d}", location=f"DEMO:{idx}")
        self.zones, self.leds = [], []
        for zname, count in zones:
            zl = [SimpleNamespace(name=f"{zname} LED {i + 1}", id=len(self.leds) + i) for i in range(count)]
            self.leds += zl
            self.zones.append(SimpleNamespace(name=zname, leds=zl, colors=[RGBColor(0, 0, 0)] * count))
        self.modes = []
        for i, mname in enumerate(mode_names):
            direct = mname.lower() == "direct"
            self.modes.append(SimpleNamespace(
                id=i, name=mname, colors=[RGBColor(0, 120, 255)], colors_min=0 if direct else 1,
                colors_max=0 if direct else 1,
                color_mode=ModeColors.PER_LED if direct else ModeColors.MODE_SPECIFIC))
        self.active_mode = 0
        self.colors = [RGBColor(0, 0, 0)] * len(self.leds)
        self.saved = False

    # ---- what the lighting engine calls
    def set_mode(self, mode, save=False):
        name = mode if isinstance(mode, str) else mode.name
        for i, m in enumerate(self.modes):
            if m.name.lower() == name.lower():
                self.active_mode = i
                break
        else:
            raise ValueError(f"{self.name} has no mode {name!r}")
        if save:
            self.saved = True

    def set_custom_mode(self):
        self.set_mode("Direct")

    def set_color(self, color, fast=False):
        self.colors = [color] * len(self.leds)

    def _set_device_colors(self, colors, fast=False):
        self.colors = list(colors)[:len(self.leds)]

    def save_mode(self):
        self.saved = True

    def update(self):
        pass


class FakeClient:
    """Drop-in for openrgb.OpenRGBClient(host, port, name).

    DEVICES is the device list it reports. RAM_BLOCKED leaves the RAM sticks out, the way OpenRGB misses
    them when another app holds the SMBus (or PawnIO / admin rights are missing)."""
    DEVICES = DEMO_DEVICES
    RAM_BLOCKED = False

    def __init__(self, address="127.0.0.1", port=6742, name="test", protocol_version=None):
        devs = [d for d in self.DEVICES if not (self.RAM_BLOCKED and d[1] == DeviceType.DRAM)]
        self.devices = [FakeDevice(i, *d) for i, d in enumerate(devs)]
        self.ee_devices = []
        self.profiles = []

    def update(self):
        pass

    def disconnect(self):
        pass


def install(eng=None, devices=None, ram_blocked=False):
    """Point Central RGB's lighting engine at the fake devices. Pass rgb_engine, or it's imported.
    devices picks the device list (DEMO_DEVICES by default); ram_blocked hides its RAM sticks."""
    if eng is None:
        import rgb_engine as eng
    FakeClient.DEVICES = DEMO_DEVICES if devices is None else devices
    FakeClient.RAM_BLOCKED = ram_blocked
    eng.OpenRGBClient = FakeClient
    eng.OpenRGBManager.server_running = staticmethod(lambda timeout=0.5: True)
    eng.OpenRGBManager.replace_visible_copy = lambda self: False
    return eng
