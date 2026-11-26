# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Battery levels of wireless gear (battery.py), read from fake devices that speak each brand's protocol
(tests/fake_hid.py):
  - Logitech HID++ 2.0 through a receiver and on a cable: Unified Battery, Battery Status and Battery Voltage,
    the device's own name and type, empty receiver slots, a sleeping device, G HUB's replies mixed in
  - SteelSeries mice (Aerox-style and Rival-3-style), awake, charging and asleep
  - Razer wireless mice on whichever transaction id they answer; wired Razer gear is left alone
  - HeadsetControl's JSON and Windows' Bluetooth list; picking HeadsetControl's Windows download
  - merging the same device found twice, low-battery flags, and the app's tiles and warnings

Run from the repo root:  python -m unittest discover tests
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import battery as bat  # noqa: E402
import fake_hid as fh  # noqa: E402


class Logitech(unittest.TestCase):
    def test_g915x_on_its_receiver(self):
        got = bat.read_logitech(fh.FakeHid(fh.OWNERS_GEAR))
        self.assertEqual(len(got), 1)
        b = got[0]
        self.assertEqual((b.name, b.kind, b.level, b.charging, b.approx),
                         ("Logitech G915 X LIGHTSPEED", "keyboard", 64, False, False))

    def test_each_battery_feature(self):
        rx = fh.FakeLogitechReceiver({
            1: fh.PairedDevice("G502 X PLUS", 3, ("status", 33, 1)),           # 0x1000, recharging
            2: fh.PairedDevice("PRO X SUPERLIGHT", 3, ("voltage", 3922, 0)),   # 0x1001, 3922 mV
            4: fh.PairedDevice("MX Keys", 0, ("unified", 0, 3)),               # 0x1004, level flags only, full
        })
        got = {b.name: b for b in bat.read_logitech(fh.FakeHid([rx]))}
        self.assertEqual(got["Logitech G502 X PLUS"].level, 33)
        self.assertTrue(got["Logitech G502 X PLUS"].charging)
        self.assertEqual(got["Logitech PRO X SUPERLIGHT"].level, 70)
        self.assertTrue(got["Logitech PRO X SUPERLIGHT"].approx)
        self.assertEqual(got["Logitech MX Keys"].kind, "keyboard")
        self.assertTrue(got["Logitech MX Keys"].approx)

    def test_cable_or_bluetooth_device_answers_on_0xff(self):
        got = bat.read_logitech(fh.FakeHid([fh.FakeLogitechDirect(fh.PairedDevice("G915 X", 0, ("unified", 90, 1)))]))
        self.assertEqual([(b.name, b.level, b.charging) for b in got], [("Logitech G915 X", 90, True)])

    def test_sleeping_device_and_g_hub_chatter(self):
        rx = fh.FakeLogitechReceiver({1: fh.PairedDevice("G915 X LIGHTSPEED", 0, asleep=True),
                                      2: fh.PairedDevice("G PRO", 3, ("unified", 50, 0))}, chatter=True)
        got = bat.read_logitech(fh.FakeHid([rx]))
        self.assertEqual([(b.name, b.level) for b in got], [("Logitech G PRO", 50)])

    def test_only_reads_never_writes_settings(self):
        hid = fh.FakeHid(fh.OWNERS_GEAR)
        bat.read_logitech(hid)
        for _, h in hid.opened:
            for w in getattr(h, "writes", []):
                fi, fn = w[2], w[3] >> 4
                self.assertTrue(fi == 0x00 or fn in (0, 1, 2), w.hex())   # root lookups and get-calls only

    def test_voltage_curve(self):
        self.assertEqual(bat.voltage_percent(4300), 100)
        self.assertEqual(bat.voltage_percent(3400), 0)
        self.assertEqual(bat.voltage_percent(3811), 50)
        self.assertEqual(bat.voltage_percent(3795), 45)


class SteelSeries(unittest.TestCase):
    def test_aerox3_wireless(self):
        got = bat.read_steelseries(fh.FakeHid(fh.OWNERS_GEAR))
        self.assertEqual([(b.name, b.kind, b.level, b.charging) for b in got],
                         [("SteelSeries Aerox 3 Wireless", "mouse", 55, False)])

    def test_sends_the_wireless_command_on_the_right_interface(self):
        hid = fh.FakeHid([fh.FakeSteelSeries()])
        bat.read_steelseries(hid)
        (path, h), = hid.opened
        self.assertTrue(path.endswith(b"-3"))
        self.assertEqual(h.writes, [b"\x00\xd2"])

    def test_wired_charging_and_asleep(self):
        got = bat.read_steelseries(fh.FakeHid([fh.FakeSteelSeries(pid=0x183A, protocol="aerox", level=100,
                                                                  charging=True)]))
        self.assertEqual((got[0].level, got[0].charging), (100, True))
        got = bat.read_steelseries(fh.FakeHid([fh.FakeSteelSeries(asleep=True)]))
        self.assertIsNone(got[0].level)                         # shown as "asleep or off"

    def test_rival3_style(self):
        got = bat.read_steelseries(fh.FakeHid([fh.FakeSteelSeries(pid=0x1830, protocol="rival3", level=42,
                                                                  name="Rival 3 Wireless")]))
        self.assertEqual((got[0].name, got[0].level), ("SteelSeries Rival 3 Wireless", 42))


class Razer(unittest.TestCase):
    def test_tries_transaction_ids_until_one_answers(self):
        for tid in bat.RAZER_TRANSACTION_IDS:
            got = bat.read_razer(fh.FakeHid([fh.FakeRazer(tid=tid, level_raw=255, charging=False)]))
            self.assertEqual([(b.level, b.charging) for b in got], [(100, False)], hex(tid))

    def test_report_layout_and_checksum(self):
        r = bat.razer_report(0x1F, 0x07, 0x80, 0x02)
        self.assertEqual(len(r), 90)
        self.assertEqual((r[1], r[5], r[6], r[7]), (0x1F, 0x02, 0x07, 0x80))
        crc = 0
        for b in r[2:88]:
            crc ^= b
        self.assertEqual(r[88], crc)

    def test_wired_razer_gear_is_left_alone(self):
        hid = fh.FakeHid([fh.FakeRazer(name="Razer Huntsman V2 Tenkeyless")])
        self.assertEqual(bat.read_razer(hid), [])
        self.assertEqual(hid.opened, [])                       # not even opened: OpenRGB may be busy on it


class OtherSources(unittest.TestCase):
    def test_headsetcontrol_json(self):
        got = bat.parse_headsetcontrol(fh.HEADSETCONTROL_JSON)
        self.assertEqual([(b.name, b.brand, b.kind, b.level) for b in got],
                         [("Logitech G PRO X 2 LIGHTSPEED", "Logitech", "headset", 81)])
        off = json.loads(fh.HEADSETCONTROL_JSON)
        off["devices"][0]["battery"] = {"status": "BATTERY_UNAVAILABLE", "level": -1}
        self.assertIsNone(bat.parse_headsetcontrol(json.dumps(off))[0].level)
        self.assertEqual(bat.parse_headsetcontrol("not json"), [])

    def test_picks_the_windows_download_and_its_checksum(self):
        assets = [{"name": n, "browser_download_url": "https://x/" + n} for n in (
            "headsetcontrol-linux-x86_64.zip", "headsetcontrol-windows-x86_64.zip",
            "headsetcontrol-windows-x86_64.zip.sha256", "headsetcontrol-windows-x86_64.exe",
            "headsetcontrol-macos-arm64.zip")]
        main, sha = bat.pick_headsetcontrol_asset(assets)
        self.assertEqual(main["name"], "headsetcontrol-windows-x86_64.zip")
        self.assertEqual(sha["name"], "headsetcontrol-windows-x86_64.zip.sha256")
        main, sha = bat.pick_headsetcontrol_asset(assets[:1])
        self.assertIsNone(main)

    def test_bluetooth_list(self):
        got = bat.parse_bluetooth(fh.BLUETOOTH_JSON)
        self.assertEqual([(b.name, b.kind, b.level) for b in got],
                         [("Xbox Wireless Controller", "controller", 40), ("WH-1000XM5", "headset", 12)])
        self.assertEqual(len(bat.parse_bluetooth(json.dumps({"Name": "Pad", "Level": 70}))), 1)
        self.assertEqual(bat.parse_bluetooth(""), [])


class Together(unittest.TestCase):
    def test_same_device_found_twice_shows_once(self):
        a = bat.Battery("steelseries:x", "SteelSeries Aerox 3 Wireless", "SteelSeries", "mouse", None)
        b = bat.Battery("bt:x", "SteelSeries Aerox 3", "SteelSeries", "mouse", 60, source="Windows Bluetooth")
        got = bat.merge([[a], [b]])
        self.assertEqual([(x.level, x.source) for x in got], [(60, "Windows Bluetooth")])

    def test_order_and_low_flag(self):
        got = bat.merge([[bat.Battery("m", "Mouse A", "X", "mouse", 10),
                          bat.Battery("k", "Keys", "X", "keyboard", 80),
                          bat.Battery("h", "Head", "X", "headset", 12, charging=True)]])
        self.assertEqual([x.kind for x in got], ["keyboard", "mouse", "headset"])
        self.assertEqual([x.low for x in got], [False, True, False])

    def test_monitor_reads_everything_in_the_background(self):
        seen = []
        mon = bat.BatteryMonitor(on_update=seen.append, log=lambda *a: None, hid=fh.FakeHid(fh.OWNERS_GEAR),
                                 headsets=False, bluetooth=False, interval=999)
        mon.start()
        end = time.time() + 3
        while not seen and time.time() < end:
            time.sleep(0.02)
        mon.stop()
        self.assertTrue(seen)
        self.assertEqual([b.name for b in seen[0]], ["Logitech G915 X LIGHTSPEED", "SteelSeries Aerox 3 Wireless"])

    def test_no_hidapi_means_no_batteries_not_a_crash(self):
        mon = bat.BatteryMonitor(log=lambda *a: None, headsets=False, bluetooth=False)
        mon._hid = None
        real = bat.real_hid
        bat.real_hid = lambda: None
        try:
            self.assertEqual(mon.read_once(), [])
        finally:
            bat.real_hid = real

    def test_names_sort_into_kinds(self):
        for name, kind in [("G915 X LIGHTSPEED", "keyboard"), ("Razer BlackWidow V4 Pro", "keyboard"),
                           ("Arctis Nova 7", "headset"), ("Logitech G733", "headset"), ("DualSense Wireless Controller",
                                                                                           "controller"),
                           ("Viper V3 Pro", "mouse"), ("G502 X PLUS", "mouse"), ("Something", "device")]:
            self.assertEqual(bat.kind_from_name(name), kind, name)


class InTheApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import central_rgb as cr
        cls.cr = cr
        cls.root = cr.ctk.CTk()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_tile_shows_level_charging_and_asleep(self):
        cr = self.cr
        b = bat.Battery("k", "Logitech G915 X LIGHTSPEED", "Logitech", "keyboard", 64)
        t = cr.BatteryTile(self.root, b)
        self.assertEqual(t.name.cget("text"), "G915 X LIGHTSPEED")
        self.assertEqual(t.pct.cget("text"), "64%")
        b.charging = True
        t.update_battery(b)
        self.assertIn("⚡", t.pct.cget("text"))
        self.assertEqual(t.sub.cget("text"), "Charging")
        b.level, b.charging = None, None
        t.update_battery(b)
        self.assertEqual(t.sub.cget("text"), "Asleep or off")
        t.destroy()

    def test_low_battery_warns_once_until_charged(self):
        cr = self.cr
        notes, logs = [], []

        class Stub:
            settings = type("S", (), {"data": {"battery_alert": 15}})()
            tray = type("T", (), {"notify": lambda s, m: notes.append(m)})()
            _batt_warned = set()
            log = staticmethod(logs.append)
        s = Stub()
        low = bat.Battery("m", "SteelSeries Aerox 3 Wireless", "SteelSeries", "mouse", 12)
        cr.App._battery_alerts(s, [low])
        cr.App._battery_alerts(s, [low])
        self.assertEqual(len(notes), 1)
        self.assertIn("12%", notes[0])
        low.charging = True
        cr.App._battery_alerts(s, [low])                      # charging: armed again
        low.charging, low.level = False, 14
        cr.App._battery_alerts(s, [low])
        self.assertEqual(len(notes), 2)
        s.settings.data["battery_alert"] = 0                  # Off
        s._batt_warned.clear()
        cr.App._battery_alerts(s, [low])
        self.assertEqual(len(notes), 2)


if __name__ == "__main__":
    unittest.main()
