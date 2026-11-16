# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""User-made lighting presets (Lighting -> Create preset) and the RAM update limit."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import rgb_engine as eng  # noqa: E402


class CustomPresetTests(unittest.TestCase):
    def setUp(self):
        eng.CUSTOM_PRESETS.clear()

    def tearDown(self):
        eng.CUSTOM_PRESETS.clear()

    def test_every_motion_gives_valid_colours(self):
        for motion in eng.CUSTOM_MOTIONS:
            eng.CUSTOM_PRESETS["Mine"] = {"motion": motion, "colors": [[255, 0, 80], [0, 200, 255], [255, 200, 0]]}
            for t in (0.0, 0.7, 3.3):
                cols = eng.compute_colors("Mine", (0, 0, 0), 100, 50, 30, t)
                self.assertEqual(len(cols), 30, motion)
                for c in cols:
                    self.assertTrue(all(0 <= v <= 255 for v in c), (motion, c))

    def test_gradient_is_still_and_others_animate(self):
        eng.CUSTOM_PRESETS["Still"] = {"motion": "Gradient", "colors": [[255, 0, 0], [0, 0, 255]]}
        eng.CUSTOM_PRESETS["Moving"] = {"motion": "Wave", "colors": [[255, 0, 0], [0, 0, 255]]}
        self.assertFalse(eng.is_animated("Still"))
        self.assertTrue(eng.is_animated("Moving"))
        self.assertEqual(eng.compute_colors("Still", (0, 0, 0), 100, 50, 10, 0),
                         eng.compute_colors("Still", (0, 0, 0), 100, 50, 10, 5))

    def test_brightness_scales_custom_presets(self):
        eng.CUSTOM_PRESETS["Dim"] = {"motion": "Gradient", "colors": [[200, 200, 200], [200, 200, 200]]}
        full = eng.compute_colors("Dim", (0, 0, 0), 100, 50, 4, 0)[0]
        half = eng.compute_colors("Dim", (0, 0, 0), 50, 50, 4, 0)[0]
        self.assertEqual(half, tuple(round(v / 2) for v in full))

    def test_built_in_effects_unchanged(self):
        self.assertTrue(eng.is_animated("Rainbow Wave"))
        self.assertFalse(eng.is_animated("Static"))


if __name__ == "__main__":
    unittest.main()
