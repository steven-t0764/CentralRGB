# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
DDR5 RAM guard: on many PCs OpenRGB finds DDR5 RGB RAM only on its first hardware search after the PC
starts, so with DDR5 the hidden OpenRGB must not be searched again (restart, Rescan, quit + reopen).

Run from the repo root:  python -m unittest discover tests
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rgb_engine as eng  # noqa: E402


class DDR5Detection(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("CENTRALRGB_FAKE_DDR5", None)

    def test_override(self):
        os.environ["CENTRALRGB_FAKE_DDR5"] = "1"
        self.assertTrue(eng.ddr5_installed())
        os.environ["CENTRALRGB_FAKE_DDR5"] = "0"
        self.assertFalse(eng.ddr5_installed())

    def test_boot_id_is_stable(self):
        self.assertEqual(eng.boot_id(), eng.boot_id())


class Guard(unittest.TestCase):
    def test_keep_openrgb_only_with_ddr5(self):
        self.assertTrue(eng.keep_openrgb_running(True))
        self.assertFalse(eng.keep_openrgb_running(False))

    def test_rescan_asks_only_when_it_would_lose_ram(self):
        self.assertTrue(eng.rescan_needs_ok(ddr5=True, ours=True, ram_found=True))
        self.assertFalse(eng.rescan_needs_ok(ddr5=True, ours=True, ram_found=False))   # nothing to lose
        self.assertFalse(eng.rescan_needs_ok(ddr5=True, ours=False, ram_found=True))   # user's own OpenRGB
        self.assertFalse(eng.rescan_needs_ok(ddr5=False, ours=True, ram_found=True))   # DDR4 is fine

    def test_missing_note(self):
        self.assertIsNone(eng.ram_missing_note(False, False, True, True))    # not DDR5
        self.assertIsNone(eng.ram_missing_note(True, True, True, True))      # RAM found
        again = eng.ram_missing_note(True, False, True, False)
        self.assertIn("already looked earlier this boot", again)
        self.assertIn("Shift", again)
        first = eng.ram_missing_note(True, False, False, False)
        self.assertIn("close other RGB apps", first)
        self.assertIn("Shift", first)


if __name__ == "__main__":
    unittest.main()
