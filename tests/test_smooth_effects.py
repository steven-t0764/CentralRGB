# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Smooth preset animations: compute_colors can average an effect over each LED's width (anti-aliasing) and over
the frame's time slice (motion blur). The tests check that
  - without those options every effect gives exactly what it gave before
  - with them, the frame-to-frame jumps of the preset effects drop, on RAM (7.5 updates/s) and at 30 fps
  - the lighting engine asks for smoothing, with the blur set to each device's own update period
  - a still colour is never blurred, and smoothing costs little
  - a G915 X keyboard gets a plain "not supported yet" note instead of nothing

Run from the repo root:  python -m unittest discover tests
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rgb_engine as eng  # noqa: E402
from test_ram_updates import ram_sticks, strip  # noqa: E402

COLOR = (150, 0, 255)


def avg_jump(effect, hz, smooth, n=10, secs=12, speed=100):
    """Mean of the biggest per-LED colour change between consecutive frames."""
    dt, prev, tot, k = 1 / hz, None, 0, 0
    for i in range(int(secs * hz)):
        c = eng.compute_colors(effect, COLOR, 100, speed, n, 1000 + i * dt,
                               blur=dt if smooth else 0.0, aa=smooth)
        if prev:
            tot += max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(prev, c))
            k += 1
        prev = c
    return tot / k


class SmoothingOptions(unittest.TestCase):
    def test_off_by_default_and_same_as_before(self):
        for effect in list(eng.PRESET_EFFECTS) + ["Rainbow Wave", "Static", "Breathing"]:
            for t in (0.0, 3.3, 1234.5):
                plain = eng.compute_colors(effect, COLOR, 80, 60, 12, t)
                self.assertEqual(eng.compute_colors(effect, COLOR, 80, 60, 12, t, blur=0.0, aa=False), plain, effect)
                self.assertEqual(len(plain), 12)

    def test_still_colour_is_untouched(self):
        plain = eng.compute_colors("Static", COLOR, 100, 50, 10, 5.0)
        self.assertEqual(eng.compute_colors("Static", COLOR, 100, 50, 10, 5.0, blur=0.5, aa=True), plain)

    def test_smoothed_frames_have_the_right_shape(self):
        for effect in eng.PRESET_EFFECTS:
            cols = eng.compute_colors(effect, COLOR, 100, 100, 10, 50.0, blur=0.13, aa=True)
            self.assertEqual(len(cols), 10)
            for c in cols:
                self.assertTrue(all(isinstance(v, int) and 0 <= v <= 255 for v in c), (effect, c))

    # average frame-to-frame jump of each preset in v2.6.0 (10 LEDs, speed 100), at RAM rate and at 30 fps
    BEFORE = {"Drizzle": (149, 85), "Stardust": (128, 36), "Eclipse": (144, 60), "Cascade": (94, 30),
              "Cyberpunk": (170, 63), "Pulse": (189, 123), "Supernova": (108, 30)}

    def test_preset_jumps_drop_on_ram_and_at_full_rate(self):
        worse = []
        for effect in eng.PRESET_EFFECTS:
            for hz in (7.5, 30):
                before, after = avg_jump(effect, hz, False), avg_jump(effect, hz, True)
                if after > before * 1.1 + 1:
                    worse.append(f"{effect} @ {hz} Hz: {before:.0f} -> {after:.0f}")
        self.assertEqual(worse, [])
        for effect, (ram, full) in self.BEFORE.items():
            self.assertLess(avg_jump(effect, 7.5, True), ram, effect)
            self.assertLess(avg_jump(effect, 30, True), full, effect)
        # the choppiest ones drop a lot
        for effect in ("Drizzle", "Stardust", "Eclipse", "Cascade"):
            self.assertLess(avg_jump(effect, 7.5, True), self.BEFORE[effect][0] * 0.7, effect)

    def test_cyberpunk_crossfades_instead_of_cutting(self):
        self.assertLess(avg_jump("Cyberpunk", 30, True), 50)

    def test_cost_is_small(self):
        t0 = time.perf_counter()
        for i in range(60):
            eng.compute_colors("Aurora", COLOR, 100, 100, 102, i / 30, blur=1 / 30, aa=True)
        self.assertLess((time.perf_counter() - t0) / 60, 0.01)       # < 10 ms for a full keyboard


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class EngineAsksForSmoothing(unittest.TestCase):
    def test_blur_matches_each_devices_update_period(self):
        e = eng.LightingEngine(lambda *a, **k: None)
        e.client = mock.Mock(devices=ram_sticks() + [strip()])
        e.set_state(effect="Aurora", speed=100, brightness=100)
        seen = {}
        real = eng.compute_colors

        def spy(effect, color, b, s, n, t, offset=0.0, blur=0.0, aa=False):
            seen.setdefault(n, set()).add((round(blur, 4), aa))
            return real(effect, color, b, s, n, t, offset=offset, blur=blur, aa=aa)
        clock = Clock()
        with mock.patch.object(eng, "compute_colors", spy), mock.patch.object(eng.time, "time", clock), \
                mock.patch.object(eng, "find_conflicts", lambda: {}):
            for _ in range(e.FPS * 2):
                e.step()
                e.frame += 1
                clock.t += 1 / e.FPS
        ram_cycle = max(round(e.FPS / eng.DRAM_FPS), 4)
        self.assertEqual(seen[10], {(round(ram_cycle / e.FPS, 4), True)})     # RAM: blur over its own slot
        self.assertEqual(seen[30], {(round(1 / e.FPS, 4), True)})             # strip: one frame


class UnsupportedKeyboardNote(unittest.TestCase):
    G915X_WIRED = r"HID\VID_046D&PID_C359&MI_00\8&11178375&0&0000"

    def test_g915x_gets_a_plain_note(self):
        d = eng.diagnose_missing_keyboard(["RAM", "Motherboard"], keyboards=[self.G915X_WIRED])
        self.assertEqual(d["kind"], "keyboard")
        self.assertIn("G915 X", d["summary"])
        self.assertIn("046D:C359", d["summary"])
        self.assertIn("issues/4540", d["reasons"][0])
        self.assertIn("G HUB", d["reasons"][1])

    def test_no_note_when_a_keyboard_was_found_or_none_is_known(self):
        self.assertIsNone(eng.diagnose_missing_keyboard(["Keyboard"], keyboards=[self.G915X_WIRED]))
        self.assertIsNone(eng.diagnose_missing_keyboard([], keyboards=[r"HID\VID_1532&PID_026C&MI_00\x"]))
        self.assertIsNone(eng.diagnose_missing_keyboard([], keyboards=[]))

    def test_listed_with_the_other_missing_devices(self):
        with mock.patch.object(eng, "KEYBOARD_INVENTORY", [self.G915X_WIRED]), \
                mock.patch.object(eng, "RAM_INVENTORY", []), mock.patch.object(eng, "MOUSE_INVENTORY", []):
            kinds = [d["kind"] for d in eng.diagnose_missing_devices(["Motherboard"], conflicts={})]
        self.assertIn("keyboard", kinds)


if __name__ == "__main__":
    unittest.main()
