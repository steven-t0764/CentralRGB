# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""No black flashes when the window comes back from the taskbar or when switching sections.

The frame check (tests/restore_check.py) opens the real app, so it runs here only on Linux with a display
(e.g. under xvfb-run) or when CENTRALRGB_GUI_TESTS=1 is set. The rest runs everywhere.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import restore_check as rc  # noqa: E402
import win_effects as fx  # noqa: E402
from test_page_switch import _gui_available  # noqa: E402


class BlackBoxDetector(unittest.TestCase):
    """The check that judges the captured frames must really see black boxes, and nothing else."""

    def _img(self, colour="#111214", box=None):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (400, 240), colour)
        d = ImageDraw.Draw(im)
        d.line((0, 120, 400, 120), fill="#000000", width=2)        # thin black line: content, not a box
        d.rectangle((60, 60, 64, 64), fill="#000000")              # a few dark pixels
        if box:
            d.rectangle(box, fill="#020202")
        return im

    def test_normal_frame_has_no_boxes(self):
        self.assertEqual(rc.black_tiles(self._img()), 0)

    def test_label_sized_black_box_is_found(self):
        self.assertGreaterEqual(rc.black_tiles(self._img(box=(100, 30, 190, 62))), 2)

    def test_all_black_window_is_found(self):
        self.assertGreater(rc.black_tiles(self._img(colour="#000000")), 100)

    def test_no_theme_uses_near_black(self):
        """Every theme's colours are brighter than near-black, so black boxes always fail the check."""
        import central_rgb as cr
        for key, theme in cr.THEMES.items():
            with self.subTest(theme=key):
                self.assertFalse(rc.theme_has_black({**cr.SOLID, **theme}))
        self.assertTrue(rc.theme_has_black({"BG": "#000000"}))


class WindowsDrawingFlags(unittest.TestCase):
    def test_thaw_does_not_erase(self):
        """Erasing before Tk has drawn is what left every widget as a black box after a section switch."""
        self.assertFalse(fx.THAW_FLAGS & fx.RDW_ERASE)
        self.assertFalse(fx.THAW_FLAGS & fx.RDW_UPDATENOW)
        self.assertTrue(fx.THAW_FLAGS & fx.RDW_INVALIDATE and fx.THAW_FLAGS & fx.RDW_ALLCHILDREN)

    def test_opaque_keeps_the_window_layered_on_windows(self):
        if sys.platform == "win32":
            self.assertGreaterEqual(fx.OPAQUE, 0.99)    # looks fully opaque (the self-test wants >= 0.99)
            self.assertLess(fx.OPAQUE, 1.0)             # but never exactly 100 %
        else:
            self.assertEqual(fx.OPAQUE, 1.0)

    @unittest.skipIf(sys.platform == "win32", "on Windows it really sets the brush")
    def test_panel_background_does_nothing_elsewhere(self):
        self.assertFalse(fx.panel_background(object(), "#111214"))


class FadeInEndsLayered(unittest.TestCase):
    """The fade-in after start-up, the tray and a theme change stops at fx.OPAQUE, never at exactly 1.0."""

    def _run(self, opaque):
        import central_rgb as cr

        class Win:
            def __init__(self):
                self.alphas = []

            def attributes(self, name, value):
                self.alphas.append(value)

            def after(self, ms, fn):
                fn()
        w = Win()
        old, fx.OPAQUE = fx.OPAQUE, opaque
        try:
            w._fade_in = lambda a: cr.App._fade_in(w, a)
            cr.App._fade_in(w, 0.0)
        finally:
            fx.OPAQUE = old
        return w.alphas

    def test_windows_value(self):
        alphas = self._run(254 / 255)
        self.assertEqual(alphas[-1], 254 / 255)
        self.assertLess(max(alphas), 1.0)
        self.assertEqual(alphas, sorted(alphas))

    def test_other_systems_reach_full(self):
        self.assertEqual(self._run(1.0)[-1], 1.0)


@unittest.skipUnless(_gui_available(), "needs a display (run under xvfb-run) or CENTRALRGB_GUI_TESTS=1")
class NoBlackFramesOnRestoreOrSwitch(unittest.TestCase):
    def test_frames_have_no_black_boxes(self):
        out = tempfile.mkdtemp(prefix="centralrgb-repaint-test-")
        r = subprocess.run([sys.executable, str(HERE / "restore_check.py"), out, "--quick", "--warmup", "4"],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for line in ("every frame, canvas and window has its own background colour",
                     "no frame during the restore has near-black boxes",
                     "no frame during rapid page switching has near-black boxes"):
            self.assertIn(line, r.stdout)
            self.assertNotIn("FAIL  " + line, r.stdout)


if __name__ == "__main__":
    unittest.main()
