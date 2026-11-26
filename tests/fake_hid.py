# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Fake wireless devices for the battery readers (battery.py), speaking each brand's protocol:

    FakeLogitechReceiver   a LIGHTSPEED receiver answering HID++ 2.0 for the devices paired to it
    FakeLogitechDirect     a Logitech device on its cable / Bluetooth (device index 0xFF)
    FakeSteelSeries        an Aerox-style or Rival-3-style SteelSeries mouse
    FakeRazer              a Razer wireless mouse answering the 90-byte Razer report on one transaction id
    FakeHid                the hidapi stand-in that lists and opens them

OWNERS_GEAR is the owner's wireless setup as far as we know it: a G915 X LIGHTSPEED on its receiver and an
Aerox 3 Wireless on its 2.4 GHz dongle. HEADSETCONTROL_JSON / BLUETOOTH_JSON are sample outputs of
HeadsetControl (`headsetcontrol -b -o json`) and of the Windows Bluetooth query.
"""
from __future__ import annotations

import json
from collections import deque

F_ROOT, F_NAME, F_BATTERY, F_VOLTAGE, F_UNIFIED = 0x0000, 0x0005, 0x1000, 0x1001, 0x1004


class PairedDevice:
    """One HID++ 2.0 device: its name, type and battery, answered through whichever feature it has."""

    def __init__(self, name, dtype, battery=("unified", 72, 0), asleep=False):
        self.name, self.dtype, self.battery, self.asleep = name, dtype, battery, asleep
        kind = battery[0]
        fid = {"unified": F_UNIFIED, "status": F_BATTERY, "voltage": F_VOLTAGE}[kind]
        self.features = {F_ROOT: 0x00, F_NAME: 0x03, fid: 0x07}

    def answer(self, feature_index, function, params) -> bytes | None:
        """Reply payload, or None for an HID++ error."""
        if self.asleep:
            return None
        if feature_index == 0x00 and function == 0:                    # root: getFeature(id)
            fid = (params[0] << 8) | params[1]
            return bytes([self.features.get(fid, 0)])
        fid = next((f for f, i in self.features.items() if i == feature_index), None)
        if fid == F_NAME:
            if function == 0:
                return bytes([len(self.name)])
            if function == 1:
                start = params[0]
                return self.name.encode()[start:start + 16]
            if function == 2:
                return bytes([self.dtype])
        kind, a, b = self.battery
        if fid == F_UNIFIED and function == 1:
            level_flags = 8 if a > 80 else 4 if a > 30 else 2 if a > 10 else 1
            return bytes([a, level_flags, b, 0])
        if fid == F_BATTERY and function == 0:
            return bytes([a, max(0, a - 10), b])
        if fid == F_VOLTAGE and function == 0:
            return bytes([a >> 8, a & 0xFF, b])
        return None


class _HidppEndpoint:
    """Shared HID++ answering: index -> PairedDevice. Replies go into a queue read() hands out."""

    def __init__(self, devices: dict, chatter=False):
        self.devices, self.queue, self.chatter = devices, deque(), chatter
        self.writes = []

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        report, index, fi, fn = data[0], data[1], data[2], data[3]
        function, swid = fn >> 4, fn & 0x0F
        params = data[4:]
        if self.chatter:                       # someone else (G HUB) talking on the same device
            self.queue.append(bytes([0x11, index, fi, (function << 4) | 0x01]) + bytes(16))
        dev = self.devices.get(index)
        if dev is None:
            # empty receiver slot: HID++ 1.0 error (unknown device)
            self.queue.append(bytes([0x10, index, 0x8F, fi, fn, 0x08, 0x00]))
            return len(data)
        payload = dev.answer(fi, function, params)
        if payload is None:
            if not dev.asleep:
                self.queue.append(bytes([0x11, index, 0xFF, fi, fn, 0x05]) + bytes(14))
            return len(data)
        msg = bytes([report, index, fi, fn]) + payload
        size = 20 if report == 0x11 else 7
        self.queue.append(msg[:size] + bytes(max(0, size - len(msg))))
        return len(data)

    def read(self, n, timeout_ms=0):
        return list(self.queue.popleft()[:n]) if self.queue else []

    def close(self):
        pass


class FakeLogitechReceiver:
    product_string = "USB Receiver"

    def __init__(self, paired: dict, pid=0xC547, chatter=False):
        self.paired, self.pid, self.chatter = paired, pid, chatter

    def infos(self):
        base = dict(vendor_id=0x046D, product_id=self.pid, serial_number="", interface_number=2,
                    manufacturer_string="Logitech", product_string=self.product_string, usage_page=0xFF00)
        return [dict(base, path=f"logi-{self.pid:x}-short".encode(), usage=1),
                dict(base, path=f"logi-{self.pid:x}-long".encode(), usage=2)]

    def open(self, path):
        return _HidppEndpoint(self.paired, chatter=self.chatter)


class FakeLogitechDirect(FakeLogitechReceiver):
    product_string = "G915 X Wired Gaming Keyboard"

    def __init__(self, device: PairedDevice, pid=0xC359):
        super().__init__({0xFF: device}, pid=pid)


class _SteelSeriesEndpoint:
    def __init__(self, protocol, level, charging, asleep):
        self.protocol, self.level, self.charging, self.asleep = protocol, level, charging, asleep
        self.reply = None
        self.writes = []

    def write(self, data):
        data = bytes(data)
        self.writes.append(data)
        cmd = data[1]
        if self.asleep:
            self.reply = bytes([cmd, 0x00, 0x00]) if self.protocol != "rival3" else bytes([0xFF, 0, 0])
        elif self.protocol.startswith("aerox") and cmd in (0x92, 0xD2):
            self.reply = bytes([cmd, (self.level // 5 + 1) | (0x80 if self.charging else 0)])
        elif self.protocol == "rival3" and data[1:3] == b"\xAA\x01":
            self.reply = bytes([self.level, 0, 1 if self.charging else 0])
        return len(data)

    def read(self, n, timeout_ms=0):
        r, self.reply = self.reply, None
        return list(r[:n]) if r else []

    def close(self):
        pass


class FakeSteelSeries:
    def __init__(self, pid=0x1838, protocol="aerox_w", level=55, charging=False, asleep=False, interface=3,
                 name="Aerox 3 Wireless"):
        self.pid, self.protocol, self.level, self.charging = pid, protocol, level, charging
        self.asleep, self.interface, self.name = asleep, interface, name

    def infos(self):
        return [dict(vendor_id=0x1038, product_id=self.pid, serial_number="", interface_number=i,
                     manufacturer_string="SteelSeries", product_string=f"SteelSeries {self.name}",
                     usage_page=0xFFC0 if i == self.interface else 0x0001, usage=1,
                     path=f"ss-{self.pid:x}-{i}".encode()) for i in (0, 1, 2, 3)]

    def open(self, path):
        return _SteelSeriesEndpoint(self.protocol, self.level, self.charging, self.asleep)


class _RazerEndpoint:
    def __init__(self, tid, level_raw, charging):
        self.tid, self.level_raw, self.charging = tid, level_raw, charging
        self.last = None
        self.sent = []

    def send_feature_report(self, data):
        data = bytes(data)
        self.sent.append(data)
        self.last = data[1:]
        return len(data)

    def get_feature_report(self, report_id, n):
        req = self.last
        resp = bytearray(req) if req else bytearray(90)
        if req and req[1] == self.tid and req[6] == 0x07 and req[7] in (0x80, 0x84):
            resp[0] = 0x02
            resp[9] = self.level_raw if req[7] == 0x80 else (1 if self.charging else 0)
        else:
            resp[0] = 0x05                                  # not supported / wrong transaction id
        return list(bytes([0x00]) + bytes(resp))

    def close(self):
        pass


class FakeRazer:
    def __init__(self, pid=0x00B7, name="Razer DeathAdder V3 Pro (Wireless)", tid=0x1F, level_raw=204,
                 charging=True):
        self.pid, self.name, self.tid, self.level_raw, self.charging = pid, name, tid, level_raw, charging

    def infos(self):
        return [dict(vendor_id=0x1532, product_id=self.pid, serial_number="", interface_number=i,
                     manufacturer_string="Razer", product_string=self.name, usage_page=1, usage=2,
                     path=f"razer-{self.pid:x}-{i}".encode()) for i in (0, 1, 2)]

    def open(self, path):
        return _RazerEndpoint(self.tid, self.level_raw, self.charging)


class FakeHid:
    """hidapi stand-in: enumerate(vid) lists every fake's interfaces; open(path) opens the one it belongs to."""

    def __init__(self, devices):
        self.devices = list(devices)
        self.opened = []

    def enumerate(self, vid=0):
        out = []
        for d in self.devices:
            out += [i for i in d.infos() if not vid or i["vendor_id"] == vid]
        return out

    def open(self, path):
        for d in self.devices:
            if any(i["path"] == path for i in d.infos()):
                h = d.open(path)
                self.opened.append((path, h))
                return h
        raise OSError(f"no such device {path!r}")


# the owner's wireless gear
G915X = PairedDevice("G915 X LIGHTSPEED", 0, ("unified", 64, 0))
OWNERS_GEAR = [FakeLogitechReceiver({1: G915X}), FakeSteelSeries()]

HEADSETCONTROL_JSON = json.dumps({
    "name": "HeadsetControl", "version": "4.0.0", "api_version": "1.4", "device_count": 1,
    "devices": [{"status": "success", "device": "Logitech G PRO X 2 LIGHTSPEED", "vendor": "Logitech",
                 "product": "PRO X 2 LIGHTSPEED", "id_vendor": "0x046d", "id_product": "0x0af7",
                 "capabilities": ["CAP_SIDETONE", "CAP_BATTERY_STATUS"],
                 "battery": {"status": "BATTERY_AVAILABLE", "level": 81}}]})

BLUETOOTH_JSON = json.dumps([{"Name": "Xbox Wireless Controller", "Level": 40},
                             {"Name": "WH-1000XM5", "Level": 12}])
