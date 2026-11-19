# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Restore from the taskbar and rapid page switching.

The full check (tests/restore_check.py) opens the real app, so it runs here only on Linux with a display
(e.g. under xvfb-run) or when CENTRALRGB_GUI_TESTS=1 is set.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]


def _gui_available() -> bool:
    if os.environ.get("CENTRALRGB_GUI_TESTS") == "1":
        return True
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return False
    return all(importlib.util.find_spec(m) for m in ("tkinter", "customtkinter", "PIL"))


@unittest.skipIf(sys.platform == "win32", "Windows-only code is checked on Windows by the full check")
class WindowsHelpersFailQuietly(unittest.TestCase):
    def test_cloak_and_flush_do_nothing_elsewhere(self):
        import win_effects as fx
        self.assertFalse(fx.cloak(object(), True))
        self.assertFalse(fx.cloak(object(), False))
        fx.dwm_flush()
        self.assertEqual(fx.freeze(object()), 0)
        fx.thaw(0)


@unittest.skipUnless(_gui_available(), "needs a display (run under xvfb-run) or CENTRALRGB_GUI_TESTS=1")
class RestoreAndSwitchCheck(unittest.TestCase):
    def test_restore_and_rapid_switching(self):
        out = tempfile.mkdtemp(prefix="centralrgb-restore-test-")
        r = subprocess.run([sys.executable, str(HERE / "restore_check.py"), out, "--quick", "--warmup", "4"],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASSED", r.stdout)
        for name in ("before.png", "after_restore.png", "after_switching.png", "restore.gif", "switch.gif"):
            self.assertTrue((Path(out) / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
