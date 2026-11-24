# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The owner's PC (MSI B550-A PRO, Razer Huntsman V2 TKL, SteelSeries Aerox 3 Wireless, 4x Vengeance RGB PRO):
  - case fans on the board's ARGB headers stayed dark: the headers start at 0 LEDs. Their size can now be
    set (Customize -> Connected LEDs), is remembered, and is set again after every OpenRGB start
  - the Devices page says which headers are still at 0
  - the Huntsman and Aerox were found by OpenRGB only ~5 minutes in (SteelSeries GG holding the mouse held up
    detection), long after Central RGB had stopped reading the device list (26 s). Central RGB now keeps
    reading for as long as OpenRGB's log says detection is still running, and says what it's waiting on
  - none of this restarts OpenRGB or rescans hardware

Run from the repo root:  python -m unittest discover tests
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

try:
    import central_rgb as cr
except Exception:  # pragma: no cover - needs tkinter/customtkinter
    cr = None


def board():
    return fake_openrgb.FakeDevice(0, *fake_openrgb.OWNERS_BOARD)


class Headers(unittest.TestCase):
    def test_argb_headers_are_resizable_fixed_zones_are_not(self):
        zones = eng.resizable_zones(board())
        self.assertEqual([(z["name"], z["leds"], z["min"], z["max"]) for z in zones],
                         [("JRAINBOW1", 0, 0, 200), ("JRAINBOW2", 0, 0, 200)])
        kb = fake_openrgb.FakeDevice(1, *fake_openrgb.OWNERS_KEYBOARD)
        self.assertEqual(eng.resizable_zones(kb), [])

    def test_headers_at_zero_are_reported_until_sized(self):
        d = board()
        note = eng.diagnose_unset_headers([d])
        self.assertEqual(note["kind"], "headers")
        self.assertEqual(note["summary"], "JRAINBOW1, JRAINBOW2 are at 0 LEDs (MSI B550-A PRO (MS-7C56))")
        self.assertIn("Connected LEDs", note["reasons"][0])
        self.assertIsNone(eng.diagnose_unset_headers([d], {eng.device_key(d): {"JRAINBOW1": 24, "JRAINBOW2": 36}}))

    def test_an_unused_header_set_to_zero_on_purpose_is_not_reported(self):
        d = board()
        note = eng.diagnose_unset_headers([d], {eng.device_key(d): {"JRAINBOW1": 24, "JRAINBOW2": 0}})
        self.assertIsNone(note)

    def test_a_device_without_headers_never_gets_the_note(self):
        self.assertIsNone(eng.diagnose_unset_headers([fake_openrgb.FakeDevice(1, *fake_openrgb.OWNERS_MOUSE)]))


class EngineResize(unittest.TestCase):
    def setUp(self):
        fake_openrgb.install(eng, devices=fake_openrgb.OWNERS_PC)
        self.e = eng.LightingEngine(log=lambda *a, **k: None)
        self.assertTrue(self.e.connect())
        self.key = eng.device_key(self.e.devices()[0])

    def test_resize_changes_the_led_count_and_redoes_the_device(self):
        self.e.prepared[self.key] = True
        self.assertEqual(self.e.resize_zone(self.key, 1, 36), 36)
        dev = self.e.devices()[0]
        self.assertEqual(len(dev.zones[1].leds), 36)
        self.assertEqual(len(dev.leds), 1 + 36 + 0 + 6)
        self.assertNotIn(self.key, self.e.prepared)          # Direct mode and colours are set again
        self.assertTrue(self.e.dirty)

    def test_size_is_kept_inside_what_the_header_allows(self):
        self.assertEqual(self.e.resize_zone(self.key, 2, 999), 200)
        self.assertEqual(self.e.resize_zone(self.key, 2, -4), 0)
        self.assertIsNone(self.e.resize_zone(self.key, 0, 5))   # JRGB1 is a fixed single-LED header
        self.assertIsNone(self.e.resize_zone("no such device", 1, 5))

    def test_saved_sizes_are_set_again_after_openrgb_restarts(self):
        sizes = {self.key: {"JRAINBOW1": 24, "JRAINBOW2": 36}}
        self.assertEqual(len(self.e.apply_zone_sizes(sizes)), 2)
        self.assertTrue(self.e.connect())                     # a fresh OpenRGB: headers back at 0
        self.assertEqual(len(self.e.devices()[0].zones[1].leds), 0)
        done = self.e.apply_zone_sizes(sizes)
        self.assertEqual(done, ["MSI B550-A PRO (MS-7C56) · JRAINBOW1: 24", "MSI B550-A PRO (MS-7C56) · JRAINBOW2: 36"])
        self.assertEqual(self.e.apply_zone_sizes(sizes), [])  # already right: nothing sent


class DetectionState(unittest.TestCase):
    def log(self, text, age=0):
        d = Path(tempfile.mkdtemp())
        f = d / "OpenRGB_20261122_233430.log"
        f.write_text(text, encoding="utf-8")
        if age:
            t = time.time() - age
            os.utime(f, (t, t))
        return d

    STUCK = ("[1620][Info][DetectionManager] Registering RGB controller MSI B550-A PRO (MS-7C56)\n"
             "[1621][Info][DetectionManager] HID device connected: [1038:1838 - \\\\?\\HID#VID_1038&PID_1838&MI_03]\n")

    def test_still_running_names_the_device_it_waits_on(self):
        self.assertEqual(eng.openrgb_detection_state(self.log(self.STUCK)), ("running", "SteelSeries"))

    def test_finished(self):
        self.assertEqual(eng.openrgb_detection_state(self.log(self.STUCK + "|  Detection completed  |\n")),
                         ("done", None))

    def test_a_log_from_an_older_openrgb_run_tells_nothing(self):
        self.assertEqual(eng.openrgb_detection_state(self.log(self.STUCK, age=3600), since=time.time()),
                         (None, None))
        self.assertEqual(eng.openrgb_detection_state(Path(tempfile.mkdtemp())), (None, None))

    def test_note_names_steelseries_gg_when_it_runs(self):
        note = eng.still_detecting_note("SteelSeries", {"SteelSeries GG": [1]})
        self.assertIn("waiting on a SteelSeries device", note)
        self.assertIn("SteelSeries GG is running", note)
        self.assertIn("Close them", note)
        self.assertNotIn("is running", eng.still_detecting_note("SteelSeries", {}))


@unittest.skipIf(cr is None, "central_rgb could not be imported")
class LateDevices(unittest.TestCase):
    """_settle_devices keeps reading the device list while OpenRGB's log says detection is still running."""

    def run_settle(self, states, late_after):
        fake_openrgb.install(eng, devices=fake_openrgb.OWNERS_PC, late=fake_openrgb.OWNERS_LATE,
                             late_after=late_after)
        e = eng.LightingEngine(log=lambda *a, **k: None)
        e.connect()
        logs = []
        app = SimpleNamespace(engine=e, settings=SimpleNamespace(data={}), log=lambda m, *a: logs.append(m),
                              status=lambda *a, **k: None, checked=[])
        app._rescan = lambda quiet=False, initial=False: e.rescan()
        app._check_missing = lambda: app.checked.append(len(e.devices()))
        app._check_ram = lambda: None
        clock = {"t": 1000.0}
        it = iter(states)
        last = {"s": states[-1]}

        def state(since=None):
            last["s"] = next(it, last["s"])
            return last["s"]
        with mock.patch.object(cr.time, "time", lambda: clock["t"]), \
                mock.patch.object(cr.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s)), \
                mock.patch.object(eng, "openrgb_detection_state", state), \
                mock.patch.object(eng, "find_conflicts", lambda: {"SteelSeries GG": [1]}):
            cr.App._settle_devices(app)
        return app, logs, clock["t"] - 1000.0, e

    def test_keyboard_and_mouse_found_minutes_later_are_picked_up(self):
        running = ("running", "SteelSeries")
        # OpenRGB stuck for ~5 minutes (as in the owner's log), then finished
        app, logs, took, e = self.run_settle([running] * 70 + [("done", None)], late_after=60)
        names = {d.name for d in e.devices()}
        self.assertIn("Razer Huntsman V2 TKL", names)
        self.assertIn("SteelSeries Aerox 3 Wireless", names)
        self.assertGreater(took, 120)                     # waited past the old 26-90 s cut-off
        self.assertLess(took, 600)
        self.assertTrue(any("waiting on a SteelSeries device" in m and "SteelSeries GG" in m for m in logs))
        self.assertEqual(app.checked, [len(e.devices())])  # missing-device check runs once, at the end

    def test_without_a_log_it_stops_like_before(self):
        app, logs, took, e = self.run_settle([(None, None)], late_after=0)
        self.assertLess(took, 91)
        self.assertFalse(any("still detecting" in m for m in logs))

    def test_gives_up_after_ten_minutes(self):
        app, logs, took, e = self.run_settle([("running", None)], late_after=0)
        self.assertGreaterEqual(took, 600)
        self.assertLess(took, 620)


if __name__ == "__main__":
    unittest.main()
