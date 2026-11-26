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
    fake_openrgb.install(devices=fake_openrgb.B550_PC, mouse_blocked=True) # mouse hidden, as when its app holds it
    fake_openrgb.install(devices=fake_openrgb.Z790_DDR5_PC)                   # a DDR5 kit (Kingston FURY RGB)

The devices only record what they were told (mode, colors); nothing is sent anywhere.
"""
from __future__ import annotations

from types import SimpleNamespace

from openrgb.utils import DeviceType, ModeColors, RGBColor, ZoneType

# A tenkeyless key matrix the way OpenRGB reports one: rows of key names, None where there's no key.
TKL_MATRIX = [
    ["Escape", None, "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
     "Print Screen", "Scroll Lock", "Pause/Break"],
    ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "Backspace", "Insert", "Home", "Page Up"],
    ["Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]", "\\", "Delete", "End", "Page Down"],
    ["Caps Lock", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "Enter", None, None, None, None],
    ["Left Shift", "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/", "Right Shift", None, None, None, "Up Arrow",
     None],
    ["Left Control", "Left Windows", "Left Alt", "Space", None, None, None, None, None, None, "Right Alt",
     "Right Fn", "Menu", "Right Control", "Left Arrow", "Down Arrow", "Right Arrow"],
]


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
     [("Keyboard", 104, 104, 104, TKL_MATRIX)], ("Direct", "Static", "Spectrum Cycle", "Off")),
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

# Corsair Vengeance RGB PRO DDR4 (part numbers CMW...), the sticks in the owner's PC: two 2x16 GB kits of
# CMW32GX4M2D3600C18. OpenRGB's "Corsair Vengeance Pro" detector finds them on the SMBus at 0x58-0x5B.
# Windows reports their maker as "Unknown" (the BIOS leaves it blank).
CORSAIR_VENGEANCE_PRO_DDR4 = [
    (f"Corsair Vengeance Pro RGB (DIMM {i})", DeviceType.DRAM, "Corsair",
     [("Corsair Vengeance Pro RGB", 10)], ("Direct", "Static", "Breathing", "Color Shift", "Rainbow Wave", "Off"))
    for i in range(1, 5)
]
CORSAIR_VENGEANCE_PRO_DDR4_WMI = ["Unknown CMW32GX4M2D3600C18"] * 4

# A SteelSeries RGB mouse (USB HID, lit by OpenRGB's SteelSeries Rival detector; SteelSeries GG drives it too).
STEELSERIES_MOUSE = ("SteelSeries Rival 3", DeviceType.MOUSE, "SteelSeries",
                     [("Logo", 1), ("Strip", 3)], ("Direct", "Static", "Breathing", "Off"))
# What Windows reports for that mouse (Win32_PointingDevice PNPDeviceID), and for the Razer keyboard, which
# also shows up as a pointing device (Win32_Keyboard PNPDeviceID; the same USB ID, so it isn't a mouse).
STEELSERIES_MOUSE_WMI = ["HID\\VID_1038&PID_1824&MI_00\\7&2A1B3C4D&0&0000"]
RAZER_KEYBOARD_POINTER_WMI = ["HID\\VID_1532&PID_026B&MI_02&COL01\\8&1F2E3D4C&0&0000"]
RAZER_KEYBOARD_WMI = ["HID\\VID_1532&PID_026B&MI_00\\8&3A2B1C0D&0&0000"]

# A Ryzen PC on an MSI B550 board with four Vengeance RGB DDR4 sticks, a USB keyboard and an RGB mouse.
B550_PC = [
    ("MSI B550-A PRO (MS-7C56)", DeviceType.MOTHERBOARD, "MSI",
     [("JRGB1", 1), ("JRAINBOW1", 30), ("Onboard LEDs", 6)], ("Direct", "Static", "Breathing", "Rainbow", "Off")),
    ("Razer Huntsman V2 Tenkeyless", DeviceType.KEYBOARD, "Razer",
     [("Keyboard", 87, 87, 87, TKL_MATRIX)], ("Direct", "Static", "Spectrum Cycle", "Off")),
    STEELSERIES_MOUSE,
] + CORSAIR_VENGEANCE_DDR4

# The owner's PC as of 2026-11-20: the same MSI B550-A PRO and Razer keyboard, with four Vengeance RGB PRO sticks.
B550_PRO_PC = B550_PC[:3] + CORSAIR_VENGEANCE_PRO_DDR4

# A DDR5 PC: Intel Z790 board with two Kingston FURY Beast RGB DDR5 sticks. OpenRGB's Kingston Fury detector
# finds each stick behind the DDR5 SPD hub on the Intel (i801) SMBus, through PawnIO, on its first search
# after boot. The sticks have Direct plus their own hardware modes.
# The owner's PC as OpenRGB 1.1 reports it: the MSI B550-A PRO's two ARGB headers start at 0 LEDs (so case
# fans on them stay dark until sized), a Razer Huntsman V2 TKL and a SteelSeries Aerox 3 Wireless (both of
# which OpenRGB found only minutes in while SteelSeries GG held the mouse), and 4x Vengeance RGB PRO.
OWNERS_BOARD = ("MSI B550-A PRO (MS-7C56)", DeviceType.MOTHERBOARD, "MSI",
                [("JRGB1", 1), ("JRAINBOW1", 0, 0, 200), ("JRAINBOW2", 0, 0, 200), ("Onboard LEDs", 6)],
                ("Direct", "Static", "Breathing", "Rainbow", "Off"))
OWNERS_KEYBOARD = ("Razer Huntsman V2 TKL", DeviceType.KEYBOARD, "Razer", [("Keyboard", 102, 102, 102, TKL_MATRIX)],
                   ("Direct", "Static", "Spectrum Cycle", "Off"))
OWNERS_MOUSE = ("SteelSeries Aerox 3 Wireless", DeviceType.MOUSE, "SteelSeries", [("Logo", 1), ("Strip", 2)],
                ("Direct", "Static", "Off"))
OWNERS_PC = [OWNERS_BOARD, OWNERS_KEYBOARD, OWNERS_MOUSE] + CORSAIR_VENGEANCE_PRO_DDR4
OWNERS_LATE = {"Razer Huntsman V2 TKL", "SteelSeries Aerox 3 Wireless"}

KINGSTON_FURY_DDR5 = [
    (f"Kingston Fury DDR5 DRAM (DIMM {i})", DeviceType.DRAM, "Kingston",
     [("Kingston Fury DDR5", 12)], ("Direct", "Static", "Breathing", "Spectrum Cycle", "Rainbow", "Off"))
    for i in (1, 2)
]
# What Windows reports for them: "Manufacturer PartNumber", and SMBIOSMemoryType 34 (DDR5).
KINGSTON_FURY_DDR5_WMI = ["Kingston KF560C36BBEA-16"] * 2
Z790_DDR5_PC = [
    ("MSI MAG Z790 TOMAHAWK WIFI (MS-7D91)", DeviceType.MOTHERBOARD, "MSI",
     [("JRGB1", 1), ("JARGB_V2_1", 30)], ("Direct", "Static", "Breathing", "Rainbow", "Off")),
    ("NVIDIA GeForce RTX 4070 SUPER", DeviceType.GPU, "ASUS",
     [("GPU", 8)], ("Direct", "Static", "Breathing", "Off")),
] + KINGSTON_FURY_DDR5


class FakeDevice:
    def __init__(self, idx, name, dtype, vendor, zones, mode_names):
        self.id = idx
        self.name = name
        self.type = dtype
        self.metadata = SimpleNamespace(vendor=vendor, description=f"{vendor} {name}", version="1.0",
                                        serial=f"DEMO{idx:04d}", location=f"DEMO:{idx}")
        # zones: (name, LEDs) or, for an ARGB header you size yourself, (name, LEDs, min, max), or for a keyboard
        # (name, LEDs, LEDs, LEDs, matrix): the matrix's keys come first (named "Key: W" like OpenRGB does), any
        # LEDs left over are underglow
        self._zone_specs = [list(z) + ([z[1], z[1]] if len(z) == 2 else []) for z in zones]
        for spec in self._zone_specs:
            if len(spec) == 4:
                spec.append(None)
        self.resized = []                      # (zone index, size) for every resize OpenRGB was asked for
        self._build_zones()
        self.modes = []
        for i, mname in enumerate(mode_names):
            direct = mname.lower() == "direct"
            self.modes.append(SimpleNamespace(
                id=i, name=mname, colors=[RGBColor(0, 120, 255)], colors_min=0 if direct else 1,
                colors_max=0 if direct else 1,
                color_mode=ModeColors.PER_LED if direct else ModeColors.MODE_SPECIFIC))
        self.active_mode = 0
        self.saved = False

    def _build_zones(self):
        self.zones, self.leds, data_zones = [], [], []
        for zi, (zname, count, lo, hi, matrix) in enumerate(self._zone_specs):
            names = [f"{zname} LED {i + 1}" for i in range(count)]
            mat = None
            if matrix:
                keys = [k for row in matrix for k in row if k]
                names = [f"Key: {k}" for k in keys][:count] + [f"Underglow {i + 1}" for i in range(count - len(keys))]
                pos = {k: i for i, k in enumerate(keys)}
                mat = [[pos[k] if k and pos.get(k, count) < count else None for k in row] for row in matrix]
            zl = [SimpleNamespace(name=names[i], id=len(self.leds) + i) for i in range(count)]
            self.leds += zl
            zone = SimpleNamespace(name=zname, leds=zl, colors=[RGBColor(0, 0, 0)] * count, matrix_map=mat,
                                   type=ZoneType.MATRIX if mat else ZoneType.LINEAR if hi > lo else ZoneType.SINGLE)
            zone.resize = (lambda n, zi=zi: self._resize(zi, n))
            self.zones.append(zone)
            data_zones.append(SimpleNamespace(name=zname, zone_type=zone.type, leds_min=lo, leds_max=hi,
                                              num_leds=count))
        self.data = SimpleNamespace(zones=data_zones)
        self.colors = [RGBColor(0, 0, 0)] * len(self.leds)

    def _resize(self, zi, n):
        self.resized.append((zi, n))
        self._zone_specs[zi][1] = n
        self._build_zones()

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
    them when another app holds the SMBus (or PawnIO / admin rights are missing). MOUSE_BLOCKED leaves the
    mice out, the way OpenRGB misses one when its vendor app holds the HID interface."""
    DEVICES = DEMO_DEVICES
    RAM_BLOCKED = False
    MOUSE_BLOCKED = False
    RAM_LATE = 0          # the RAM only shows up after this many update() calls (SMBus scan still running)
    LATE_NAMES: set = set()   # these devices only show up after LATE_AFTER update() calls (detection held up)
    LATE_AFTER = 0

    def __init__(self, address="127.0.0.1", port=6742, name="test", protocol_version=None):
        self.updates = 0
        self._build()
        self.ee_devices = []
        self.profiles = []

    def _build(self):
        hide_ram = self.RAM_BLOCKED or self.updates < self.RAM_LATE
        hide_late = self.updates < self.LATE_AFTER
        devs = [d for d in self.DEVICES if not (hide_ram and d[1] == DeviceType.DRAM)
                and not (self.MOUSE_BLOCKED and d[1] == DeviceType.MOUSE)
                and not (hide_late and d[0] in self.LATE_NAMES)]
        old = {d.name: d for d in getattr(self, "devices", [])}
        self.devices = [old.get(d[0]) or FakeDevice(i, *d) for i, d in enumerate(devs)]   # keep sizes set so far
        for i, d in enumerate(self.devices):
            d.id = i

    def update(self):
        self.updates += 1
        if (self.RAM_LATE and self.updates == self.RAM_LATE) or (self.LATE_AFTER and self.updates == self.LATE_AFTER):
            self._build()

    def disconnect(self):
        pass


def install(eng=None, devices=None, ram_blocked=False, mouse_blocked=False, ram_late=0, late=(), late_after=0):
    """Point Central RGB's lighting engine at the fake devices. Pass rgb_engine, or it's imported.
    devices picks the device list (DEMO_DEVICES by default); ram_blocked hides its RAM sticks and
    mouse_blocked its mice; ram_late shows the RAM only after that many device-list refreshes; the devices
    named in late show up only after late_after refreshes (OpenRGB's detection held up by a vendor app)."""
    if eng is None:
        import rgb_engine as eng
    FakeClient.DEVICES = DEMO_DEVICES if devices is None else devices
    FakeClient.RAM_BLOCKED = ram_blocked
    FakeClient.MOUSE_BLOCKED = mouse_blocked
    FakeClient.RAM_LATE = ram_late
    FakeClient.LATE_NAMES = set(late)
    FakeClient.LATE_AFTER = late_after
    eng.OpenRGBClient = FakeClient
    eng.OpenRGBManager.server_running = staticmethod(lambda timeout=0.5: True)
    eng.OpenRGBManager.replace_visible_copy = lambda self: False
    return eng
