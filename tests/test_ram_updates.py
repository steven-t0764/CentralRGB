# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
RGB RAM flicker fix: the lighting loop must
  - send RGB RAM (all sticks share one slow SMBus) at a steady, lower rate than other devices,
    with the sticks taking turns on the bus, changes included
  - skip RAM frames where nothing visibly changed
  - run effects the sticks can do themselves (Breathing) in hardware, written once
  - keep the other devices at the full frame rate

Run from the repo root:  python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from openrgb.utils import DeviceType  # noqa: E402

import rgb_engine as eng  # noqa: E402
from fakes import FakeDevice  # noqa: E402


class CountingDevice(FakeDevice):
    """Fake device that counts every write the engine makes to it."""

    def __init__(self, *a, modes=None):
        super().__init__(*a)
        if modes is not None:
            self.modes = [m for m in self.modes if m.name in modes]
        self.writes = 0
        self.mode_sets = 0

    def _set_device_colors(self, cols, fast=False):
        self.writes += 1
        super()._set_device_colors(cols, fast)

    def set_color(self, c):
        self.writes += 1
        super().set_color(c)

    def set_mode(self, m, save=False):
        self.mode_sets += 1
        super().set_mode(m, save)


def ram_sticks(n=4, modes=("Direct", "Static")):
    return [CountingDevice(f"Corsair Vengeance RGB #{i + 1}", DeviceType.DRAM, 10, [("DRAM", 10)], "Corsair",
                           f"I2C: 0x5{i}", modes=modes) for i in range(n)]


def strip():
    return CountingDevice("ARGB LED strip", DeviceType.LEDSTRIP, 30, [("Strip", 30)], "Generic", "HID: strip")


class Clock:
    """Stands in for time.time(): the test moves it on one frame at a time."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class RamUpdateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patches = [mock.patch.object(eng.time, "time", self.clock),
                   mock.patch.object(eng, "find_conflicts", lambda: {})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def engine(self, devices, **state):
        e = eng.LightingEngine(lambda *a, **k: None)
        e.client = mock.Mock(devices=devices)
        e.set_state(**state)
        return e

    def run_seconds(self, e, seconds):
        for _ in range(int(seconds * e.FPS)):
            e.step()
            e.frame += 1
            self.clock.t += 1 / e.FPS

    def test_ram_is_rate_limited_and_strip_stays_smooth(self):
        sticks, led = ram_sticks(), strip()
        e = self.engine(sticks + [led], effect="Rainbow Wave", speed=100, brightness=100)
        self.run_seconds(e, 1)                  # settle (first, dirty frame)
        before = [d.writes for d in sticks] + [led.writes]
        self.run_seconds(e, 3)
        per_sec = [(d.writes - b) / 3 for d, b in zip(sticks + [led], before)]
        for rate in per_sec[:-1]:
            self.assertLessEqual(rate, eng.DRAM_FPS + 0.5)
            self.assertGreaterEqual(rate, eng.DRAM_FPS / 2)    # still animating, not frozen
        self.assertGreater(per_sec[-1], eng.LightingEngine.FPS - 2)   # the strip keeps the full rate

    def test_sticks_take_turns_on_the_bus(self):
        sticks = ram_sticks()
        e = self.engine(sticks, effect="Rainbow Wave", speed=100)
        self.run_seconds(e, 1)
        for _ in range(30):
            before = [d.writes for d in sticks]
            e.step()
            e.frame += 1
            self.clock.t += 1 / e.FPS
            written = sum(d.writes - b for d, b in zip(sticks, before))
            self.assertLessEqual(written, 1, "two sticks written in the same tick")

    def test_changes_to_ram_wait_for_their_slot_but_arrive(self):
        sticks = ram_sticks(1)
        e = self.engine(sticks, effect="Static", color=[255, 0, 0])
        self.run_seconds(e, 0.5)
        n = sticks[0].writes
        for i in range(10):                    # dragging a colour slider: a change every tick
            e.set_state(color=[255, i * 20, 0])
            e.step()
            e.frame += 1
            self.clock.t += 1 / e.FPS
        self.assertLessEqual(sticks[0].writes - n, 10 // round(e.FPS / eng.DRAM_FPS) + 1)
        self.run_seconds(e, 0.5)                # the last colour still gets there (held by the stick's Static mode)
        static = next(m for m in sticks[0].modes if m.name == "Static")
        self.assertEqual(static.colors[0], eng.RGBColor(255, 180, 0))

    def test_unchanged_ram_frames_are_skipped(self):
        sticks, led = ram_sticks(2), strip()
        e = self.engine(sticks + [led], effect="Rainbow Wave")
        # an animation that only wobbles by one step: nothing visible changes
        wobble = lambda effect, color, b, s, n, t, offset=0.0: [(100 + int(t * 30) % 2, 50, 20)] * n
        with mock.patch.object(eng, "compute_colors", wobble):
            self.run_seconds(e, 1)
            before = [d.writes for d in sticks]
            self.run_seconds(e, 2)
        for d, b in zip(sticks, before):
            self.assertEqual(d.writes - b, 0)
        self.assertGreater(led.writes, 30)      # other devices still get every real change

    def test_unchanged_rule(self):
        e = self.engine([])
        e.last_sent["k"] = [(100, 100, 100)] * 3
        self.assertTrue(e._unchanged("k", [(102, 99, 101)] * 3, is_ram=True))
        self.assertFalse(e._unchanged("k", [(100, 100, 100 + eng.DRAM_MIN_CHANGE)] * 3, is_ram=True))
        self.assertFalse(e._unchanged("k", [(101, 100, 100)] * 3, is_ram=False))
        self.assertTrue(e._unchanged("k", [(100, 100, 100)] * 3, is_ram=False))
        self.assertFalse(e._unchanged("new", [(0, 0, 0)], is_ram=True))

    def test_breathing_runs_in_ram_hardware_mode_written_once(self):
        sticks = ram_sticks(2, modes=("Direct", "Static", "Breathing"))
        e = self.engine(sticks, effect="Breathing", color=[0, 120, 255], brightness=100)
        self.run_seconds(e, 2)
        for d in sticks:
            self.assertEqual(d.modes[d.active_mode].name, "Breathing")
            self.assertEqual(d.mode_sets, 1)
            self.assertEqual(d.writes, 0)        # nothing streamed

    def test_other_devices_never_use_ram_hardware_modes(self):
        led = strip()                          # has a Breathing mode too, but isn't RAM
        e = self.engine([led], effect="Breathing")
        self.run_seconds(e, 1)
        self.assertEqual(led.modes[led.active_mode].name, "Direct")
        self.assertGreater(led.writes, 20)

    def test_ram_conflict_is_reported(self):
        logs = []
        e = eng.LightingEngine(logs.append)
        e.client = mock.Mock(devices=ram_sticks(1))
        with mock.patch.object(eng, "find_conflicts", lambda: {"MSI Center / Mystic Light": [1],
                                                                "Razer Synapse": [2]}):
            e.step()
            e.step()
        warned = [m for m in logs if "MSI Center" in m]
        self.assertEqual(len(warned), 1)
        self.assertNotIn("Razer", warned[0])


if __name__ == "__main__":
    unittest.main()
