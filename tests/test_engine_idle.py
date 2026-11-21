# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
The lighting loop is cheap when nothing moves: with a still colour it stops working out colours every
frame and ticks slowly, but a change still reaches the devices within one frame.
While animating it keeps a steady frame rate (it sleeps what is left of the frame, not a fixed 1/FPS).

Run from the repo root:  python -m unittest discover tests
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openrgb.utils import DeviceType  # noqa: E402

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402
from fakes import FakeDevice  # noqa: E402


class SignalDevice(FakeDevice):
    """Fake device that sets an event whenever the engine writes to it."""

    def __init__(self, *a):
        super().__init__(*a)
        self.written = threading.Event()

    def set_mode(self, m, save=False):
        super().set_mode(m, save)
        self.written.set()

    def _set_device_colors(self, cols, fast=False):
        super()._set_device_colors(cols, fast)
        self.written.set()

    def set_color(self, c):
        super().set_color(c)
        self.written.set()


class EngineIdleTests(unittest.TestCase):
    def setUp(self):
        self.calls = 0
        real = eng.compute_colors

        def counting(*a, **kw):
            self.calls += 1
            return real(*a, **kw)
        for p in (mock.patch.object(eng, "compute_colors", counting),
                  mock.patch.object(eng, "find_conflicts", lambda: {}),
                  mock.patch.object(fake_openrgb.FakeClient, "DEVICES", fake_openrgb.DEMO_DEVICES)):
            p.start()
            self.addCleanup(p.stop)
        self.engine = eng.LightingEngine(lambda *_: None)
        self.engine.state.update(effect="Static", color=[0, 120, 255])

    def test_static_effect_stops_recomputing_colours(self):
        e = self.engine
        e.client = fake_openrgb.FakeClient()
        e.dirty = True
        e.tick()                                    # the first frame pushes the colour once
        self.assertGreater(self.calls, 0)
        for _ in range(20):                         # the RAM sticks take turns on the bus: let them finish
            if e._is_idle():
                break
            e.tick()
        self.assertTrue(e._is_idle(), "a still colour settles to idle once every device has it")
        self.assertFalse(e.ram_pending)
        after_first = self.calls
        waits = [e.tick() for _ in range(30)]       # a second of frames with nothing changing
        self.assertEqual(self.calls, after_first, "a still colour must not be recomputed every frame")
        for w in waits:
            self.assertGreater(w, 1 / e.FPS, "idle ticks back off")
            self.assertLessEqual(w, 1 / 4 + 1e-9, "but still tick a few times a second")

    def test_animated_effect_keeps_frame_cadence(self):
        e = self.engine
        e.client = fake_openrgb.FakeClient()
        e.set_state(effect="Rainbow Wave")
        e.tick()
        before = self.calls
        w = e.tick()
        self.assertGreater(self.calls, before)       # animating: colours every frame
        self.assertGreaterEqual(w, 0.001)
        self.assertLessEqual(w, 1 / e.FPS)           # what is left of the frame, never more

        def slow_step():
            time.sleep(2 / e.FPS)                    # a step that overruns its frame
        with mock.patch.object(e, "step", slow_step):
            self.assertEqual(e.tick(), 0.001)        # at least 1 ms, so the thread still yields

    def test_change_after_idling_is_pushed_within_one_frame(self):
        strip = SignalDevice("ARGB LED strip", DeviceType.LEDSTRIP, 30, [("Strip", 30)], "Generic", "HID: strip")
        client = mock.Mock(devices=[strip])
        e = self.engine
        e.client = client
        e.start()
        self.addCleanup(e.join, 2)
        self.addCleanup(e.stop)
        self.assertTrue(strip.written.wait(2), "the first colour is pushed")
        time.sleep(0.6)                              # long enough to be in the slow idle tick
        strip.written.clear()
        calls = self.calls
        t0 = time.perf_counter()
        e.set_state(color=[255, 0, 0])
        self.assertTrue(strip.written.wait(2))
        took = time.perf_counter() - t0
        self.assertLess(took, 1 / e.FPS, f"change took {took * 1000:.0f} ms to reach the device")
        self.assertGreater(self.calls, calls)
        self.assertEqual(strip.modes[strip.active_mode].name, "Static")

    def test_unpausing_wakes_the_loop(self):
        e = self.engine
        e.client = fake_openrgb.FakeClient()
        e.paused = True
        e.tick()
        self.assertEqual(self.calls, 0)
        e._wake_evt.clear()
        e.paused = False
        self.assertTrue(e._wake_evt.is_set())
        e.dirty = True
        e.tick()
        self.assertGreater(self.calls, 0)

    def test_stop_ends_an_idle_wait_at_once(self):
        e = self.engine
        e.client = fake_openrgb.FakeClient()
        e.start()
        time.sleep(0.4)                              # idling
        t0 = time.perf_counter()
        e.stop()
        e.join(2)
        self.assertFalse(e.is_alive())
        self.assertLess(time.perf_counter() - t0, 0.2)


if __name__ == "__main__":
    unittest.main()
