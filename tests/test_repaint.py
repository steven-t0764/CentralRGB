# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""No black flashes when the window comes back from the taskbar or when switching sections, no pixels of the
previous page left behind after a switch, and no smearing when Settings scrolls.

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


class StaleAndSmearDetectors(unittest.TestCase):
    """The checks that judge page switches and scrolling must see left-behind pixels and smears, and only those."""

    def _page(self, box, colour="#d0d0d0"):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (400, 240), "#111214")
        ImageDraw.Draw(im).rectangle(box, fill=colour)
        return im

    def test_clean_switch_has_nothing_left_behind(self):
        old, new = self._page((20, 20, 180, 120)), self._page((220, 120, 380, 220))
        self.assertEqual(rc.stale_share(new.copy(), old, new), 0.0)

    def test_old_header_left_on_top_of_new_page_is_found(self):
        old, new = self._page((20, 20, 180, 120)), self._page((220, 120, 380, 220))
        frame = new.copy()
        frame.paste(old.crop((0, 0, 400, 130)), (0, 0))          # the old page's top still on screen
        self.assertGreater(rc.stale_share(frame, old, new), 0.1)

    def test_live_numbers_changing_do_not_count(self):
        old, new = self._page((20, 20, 180, 120)), self._page((220, 120, 380, 220))
        frame = self._page((220, 120, 380, 220), colour="#e8e8e8")  # same page, slightly different values
        self.assertEqual(rc.stale_share(frame, old, new), 0.0)

    def test_smear_is_found_and_same_picture_is_not(self):
        page = self._page((20, 20, 380, 60))
        smeared = page.copy()
        smeared.paste(page.crop((0, 20, 400, 60)), (0, 80))         # a row copied into a band below
        smeared.paste(page.crop((0, 20, 400, 60)), (0, 140))
        self.assertEqual(rc.changed_share(page, page.copy()), 0.0)
        self.assertGreater(rc.changed_share(smeared, page), 0.02)


class WindowsDrawingFlags(unittest.TestCase):
    def test_thaw_erases_to_the_panel_colour(self):
        """thaw must erase what it marks for repainting (the class brush is the panel colour), or the previous
        page's pixels stay wherever Tk doesn't repaint."""
        self.assertTrue(fx.THAW_FLAGS & fx.RDW_ERASE)
        self.assertFalse(fx.THAW_FLAGS & fx.RDW_UPDATENOW)
        self.assertTrue(fx.THAW_FLAGS & fx.RDW_INVALIDATE and fx.THAW_FLAGS & fx.RDW_ALLCHILDREN)

    def test_window_is_not_left_layered(self):
        """A window left at 254/255 stays layered, which smeared scrolling and slowed redraws."""
        self.assertEqual(fx.OPAQUE, 1.0)

    @unittest.skipIf(sys.platform == "win32", "on Windows it really sets the brush")
    def test_panel_background_does_nothing_elsewhere(self):
        self.assertFalse(fx.panel_background(object(), "#111214"))


class FadeInEndsOpaque(unittest.TestCase):
    """The fade-in after start-up, the tray and a theme change ends at exactly 100 % and then draws at once."""

    def test_reaches_full_and_paints_once(self):
        import central_rgb as cr

        class Win:
            def __init__(self):
                self.alphas, self.paints = [], 0

            def attributes(self, name, value):
                self.alphas.append(value)

            def after(self, ms, fn):
                fn()

            def _paint_now(self):
                self.paints += 1
        w = Win()
        w._fade_in = lambda a: cr.App._fade_in(w, a)
        cr.App._fade_in(w, 0.0)
        self.assertEqual(w.alphas[-1], 1.0)
        self.assertEqual(w.alphas, sorted(w.alphas))
        self.assertEqual(w.paints, 1)


class PageSwitchDoesNotFreezeDrawing(unittest.TestCase):
    """Switching pages raises a page that is already filled in and laid out, without WM_SETREDRAW (freezing
    drawing is what left the previous page's pixels behind on Windows)."""

    def test_swap_page_never_freezes(self):
        import inspect
        import central_rgb as cr
        src = inspect.getsource(cr.App._swap_page)
        self.assertNotIn("fx.freeze(", src)
        self.assertLess(src.index("update_idletasks()"), src.index("tkraise()"))
        self.assertLess(src.index("tkraise()"), src.index("_paint_now()"))


@unittest.skipUnless(_gui_available(), "needs a display (run under xvfb-run) or CENTRALRGB_GUI_TESTS=1")
class NoBlackFramesOnRestoreOrSwitch(unittest.TestCase):
    def test_frames_have_no_black_boxes(self):
        out = tempfile.mkdtemp(prefix="centralrgb-repaint-test-")
        r = subprocess.run([sys.executable, str(HERE / "restore_check.py"), out, "--quick", "--warmup", "4"],
                           capture_output=True, text=True, timeout=240)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for line in ("every frame, canvas and window has its own background colour",
                     "no frame during the restore has near-black boxes",
                     "no frame during rapid page switching has near-black boxes",
                     "no page switch leaves pixels of the previous page behind",
                     "scrolling really moved the Settings page",
                     "Settings scrolls cleanly"):
            self.assertIn(line, r.stdout)
            self.assertNotIn("FAIL  " + line, r.stdout)


if __name__ == "__main__":
    unittest.main()
