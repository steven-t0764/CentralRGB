# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Keeping OpenRGB's CPU use down while it is still detecting hardware (for minutes, when a vendor app such as
SteelSeries GG holds a device it is probing):
  - the background re-reads of the device list don't make Central RGB set every device up again and resend
    every colour (RAM frames are slow SMBus writes) unless the list actually changed
  - the Rescan button still sets everything up again
  - only one watcher runs at a time, however many times detection is (re)started
  - once OpenRGB has been detecting a while, the list is read every 15 s, not every 5

Run from the repo root:  python -m unittest discover tests
"""
import os
import queue
import sys
import tempfile
import threading
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


class Rescan(unittest.TestCase):
    def setUp(self):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PRO_PC)
        self.e = eng.LightingEngine(lambda *a, **k: None)
        self.assertTrue(self.e.connect())
        self.e.prepared[("x", False, False)] = "per_led"
        self.e.dirty = False

    def tearDown(self):
        fake_openrgb.install(eng)

    def test_background_check_with_nothing_new_resends_nothing(self):
        self.e.rescan(reapply=False)
        self.assertFalse(self.e.dirty)
        self.assertIn(("x", False, False), self.e.prepared)

    def test_rescan_button_sets_everything_up_again(self):
        self.e.rescan()
        self.assertTrue(self.e.dirty)
        self.assertEqual(self.e.prepared, {})

    def test_new_device_is_set_up(self):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PRO_PC + [fake_openrgb.OWNERS_KEYBOARD])
        self.e.client.devices.append(fake_openrgb.FakeDevice(99, *fake_openrgb.OWNERS_KEYBOARD))
        before = self.e.client.update
        self.e.client.update = lambda: None              # the list already grew (as update() would have done)
        try:
            self.e.rescan(reapply=False)
        finally:
            self.e.client.update = before
        self.assertFalse(self.e.dirty)                   # same list before and after this read: nothing to do
        self.e.client.devices.pop()
        grow = lambda: self.e.client.devices.append(fake_openrgb.FakeDevice(99, *fake_openrgb.OWNERS_KEYBOARD))
        self.e.client.update = grow
        try:
            self.e.rescan(reapply=False)
        finally:
            self.e.client.update = before
        self.assertTrue(self.e.dirty)                    # the list changed during the read: set devices up


class OneWatcher(unittest.TestCase):
    def test_second_settle_returns_at_once(self):
        import central_rgb as cr
        calls = []
        app = SimpleNamespace(_settling=False)
        started = threading.Event()
        release = threading.Event()

        def loop(self_, *a):
            calls.append(1)
            started.set()
            release.wait(2)
        with mock.patch.object(cr.App, "_settle_loop", loop):
            t = threading.Thread(target=cr.App._settle_devices, args=(app,))
            t.start()
            started.wait(2)
            cr.App._settle_devices(app)                  # a reconnect asks for another watcher
            release.set()
            t.join(2)
        self.assertEqual(calls, [1])
        self.assertFalse(app._settling)

    def test_slow_checks_while_detection_drags_on(self):
        import central_rgb as cr
        self.assertGreaterEqual(cr.App.SETTLE_SLOW_EVERY, 15)
        sleeps, rescans = [], []
        app = SimpleNamespace(engine=SimpleNamespace(devices=lambda: [1, 2, 3, 4]), log=lambda *a, **k: None,
                              status=lambda *a, **k: None, _check_missing=lambda: None, _check_ram=lambda: None,
                              _rescan=lambda **k: rescans.append(k))
        clock = [1000.0]
        with mock.patch.object(cr.time, "time", lambda: clock[0]), \
                mock.patch.object(cr.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s))), \
                mock.patch.object(cr.eng, "openrgb_detection_state", lambda since=None: ("running", ["SteelSeries"])), \
                mock.patch.object(cr.eng, "still_detecting_note", lambda *a: "note"), \
                mock.patch.object(cr.eng, "find_conflicts", lambda: {}):
            cr.App._settle_devices(app, max_wait=90, long_wait=600)
        self.assertLess(len(rescans), 100)               # 10 minutes: was 162 reads, now 96
        self.assertTrue(all(k.get("reapply") is False for k in rescans[:-1]))
        self.assertIn(15.0, sleeps)


if __name__ == "__main__":
    unittest.main()
