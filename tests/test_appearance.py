# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings > Appearance: Dark / Light.

  - a missing or unknown "appearance" setting means Dark, so older settings files load unchanged
  - every theme has a complete light palette (all SOLID keys, valid hex) with readable text (WCAG AA 4.5:1)
  - switching to Light and back to Dark gives every dark theme its exact original colours
  - in the real app (Linux + display, e.g. xvfb-run), flipping the toggle rebuilds the Settings page in place
    without errors and saves the choice
  - Light-mode polish (review of the toggle): slider knobs stay visible on hover, the white swatch has an outline,
    Breathing fades into the panel instead of to black, sensor-tree selection and chart guides show, and the
    title bar / panel colour switch before the window is rebuilt. Each helper gives Dark its old value exactly.

Run from the repo root:  python -m unittest discover tests
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _gui_available() -> bool:
    if os.environ.get("CENTRALRGB_GUI_TESTS") == "1":
        return True
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return False
    return all(importlib.util.find_spec(m) for m in ("tkinter", "customtkinter", "PIL"))


def _cr():
    import central_rgb as cr
    return cr


class SavedAppearance(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("APPDATA")
        self.tmp = tempfile.mkdtemp(prefix="centralrgb-appearance-")
        os.environ["APPDATA"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._old

    def _write(self, data):
        d = Path(self.tmp) / "CentralRGB"
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").write_text(json.dumps(data), encoding="utf-8")

    def test_default_is_dark_when_key_is_missing(self):
        cr = _cr()
        self._write({"theme": "emerald", "state": {"effect": "Static"}})       # an older settings file
        self.assertEqual(cr._saved_appearance(), "dark")

    def test_no_settings_file_is_dark(self):
        self.assertEqual(_cr()._saved_appearance(), "dark")

    def test_unknown_values_are_dark(self):
        cr = _cr()
        for v in (None, "", "Light", "sepia", 1, ["light"]):
            with self.subTest(value=v):
                self.assertEqual(cr.appearance_of(v), "dark")
        self.assertEqual(cr.appearance_of("light"), "light")

    def test_saved_light_is_read(self):
        self._write({"appearance": "light"})
        self.assertEqual(_cr()._saved_appearance(), "light")


class LightPalettes(unittest.TestCase):
    def test_every_theme_has_a_complete_light_palette(self):
        cr = _cr()
        self.assertEqual(set(cr.LIGHT_THEMES), set(cr.THEMES))
        for key, pal in cr.LIGHT_THEMES.items():
            for k in list(cr.SOLID) + ["accent", "PURPLE", "TEAL", "BLUE", "PINK", "VIOLET"]:
                with self.subTest(theme=key, key=k):
                    self.assertIn(k, pal)
                    self.assertRegex(pal[k], HEX)

    def test_body_text_contrast_is_aa_in_light_mode(self):
        cr = _cr()
        for key, pal in cr.LIGHT_THEMES.items():
            with self.subTest(theme=key):
                for bg in ("CARD", "CARD2", "BG"):
                    self.assertGreaterEqual(cr.contrast(pal["TEXT"], pal[bg]), 4.5, bg)
                self.assertGreaterEqual(cr.contrast(pal["MUTED"], pal["CARD"]), 4.5)
                self.assertGreaterEqual(cr.contrast(pal["FAINT"], pal["CARD"]), 4.5)
                # text on the accent (buttons) picked by the readable-text helper
                self.assertGreaterEqual(cr.contrast(cr.on_color(pal["accent"]), pal["accent"]), 4.5)
                self.assertGreaterEqual(cr.contrast(pal["accent"], pal["CARD"]), 4.5)

    def test_light_panels_are_light(self):
        cr = _cr()
        for key, pal in cr.LIGHT_THEMES.items():
            with self.subTest(theme=key):
                for k in ("BG", "SIDE", "CARD", "CARD2", "BTN"):
                    self.assertGreater(cr._lum(pal[k]), 0.75, k)

    def test_light_accent_keeps_the_theme_hue(self):
        import colorsys
        cr = _cr()
        for key, t in cr.THEMES.items():
            dark = t.get("accent", cr._BASE_COLORS[0])
            light = cr.LIGHT_THEMES[key]["accent"]
            h1 = colorsys.rgb_to_hls(*(c / 255 for c in cr.hex2rgb(dark)))[0]
            h2 = colorsys.rgb_to_hls(*(c / 255 for c in cr.hex2rgb(light)))[0]
            with self.subTest(theme=key):
                self.assertLess(min(abs(h1 - h2), 1 - abs(h1 - h2)), 0.03)

    def test_status_colours_read_on_light_panels(self):
        cr = _cr()
        for k in ("OK", "WARN", "BAD", "INFO"):
            with self.subTest(colour=k):
                self.assertGreaterEqual(cr.contrast(cr._LIGHT_EXTRA[k], "#fcfcfc"), 4.5)
        self.assertGreaterEqual(cr.contrast(cr._LIGHT_EXTRA["WARN_TEXT"], cr._LIGHT_EXTRA["WARN_BG"]), 4.5)


class DarkStaysIdentical(unittest.TestCase):
    def _snapshot(self, cr):
        return (dict(cr.SOLID), dict(cr.P), cr.CYAN, cr.PURPLE, cr.TEAL, cr.BLUE, cr.PINK, cr.VIOLET, cr.GRAD,
                cr.CARD_BORDER, cr.CARD_BORDER_W, cr.DEFAULT_ACCENT, cr.OK, cr.WARN, cr.BAD, cr.INFO,
                cr.WARN_BG, cr.WARN_TEXT, cr.ON_STATUS, cr.DEL_HOVER)

    def test_light_then_dark_restores_every_theme_exactly(self):
        cr = _cr()
        start_theme, start_app = cr.THEME, cr.APPEARANCE
        try:
            for key in cr.THEMES:
                with self.subTest(theme=key):
                    cr._apply_theme(key)                   # the old call (no appearance) is Dark
                    before = self._snapshot(cr)
                    cr._apply_theme(key, "light")
                    self.assertNotEqual(cr.SOLID["BG"], before[0]["BG"])
                    cr._apply_theme(key, "dark")
                    self.assertEqual(self._snapshot(cr), before)
            cr._apply_theme("cyber_cyan", "dark")
            self.assertEqual(dict(cr.SOLID), cr._BASE_SOLID)
            self.assertEqual((cr.WARN_BG, cr.WARN_TEXT, cr.ON_STATUS, cr.DEL_HOVER),
                             ("#2a2112", "#ffd166", "#1a1a1a", "#4a1f28"))
        finally:
            cr._apply_theme(start_theme, start_app)


class LightModePolish(unittest.TestCase):
    """The fixes from docs/review-theme-toggle.md, and Dark staying exactly as it was for each of them."""

    def setUp(self):
        self.cr = _cr()
        self._start = (self.cr.THEME, self.cr.APPEARANCE)

    def tearDown(self):
        self.cr._apply_theme(*self._start)

    def _each(self, mode):
        for key in self.cr.THEMES:
            self.cr._apply_theme(key, mode)
            yield key

    # 1. slider knobs on hover / drag
    def test_slider_hover_is_white_in_dark(self):
        cr = self.cr
        for key in self._each("dark"):
            with self.subTest(theme=key):
                self.assertEqual(cr.slider_hover(cr.DEFAULT_ACCENT), "white")
                self.assertEqual(cr.slider_hover(cr.P["TEXT"]), "white")

    def test_slider_hover_is_visible_on_light_cards(self):
        cr = self.cr
        for key in self._each("light"):
            for knob in (cr.DEFAULT_ACCENT, cr.CYAN, cr.P["TEXT"]):
                with self.subTest(theme=key, knob=knob):
                    hov = cr.slider_hover(knob)
                    self.assertRegex(hov, HEX)
                    self.assertGreaterEqual(cr.contrast(hov, cr.P["CARD"]), 3.0)
                    self.assertGreaterEqual(cr.contrast(hov, cr.P["TRACK"]), 1.5)

    # 2. white swatch outline
    def test_swatch_outline_is_the_card_in_dark(self):
        cr = self.cr
        for key in self._each("dark"):
            for c in cr.SWATCHES:
                with self.subTest(theme=key, swatch=c):
                    self.assertEqual(cr.swatch_outline(c), cr.P["CARD"])

    def test_white_swatches_are_outlined_in_light(self):
        cr = self.cr
        soft_white = tuple(int(v) for v in cr.mix((255, 255, 255), (230, 230, 240), 0.42))
        for key in self._each("light"):
            for c in ((255, 255, 255), soft_white):
                with self.subTest(theme=key, swatch=c):
                    line = cr.swatch_outline(c)
                    self.assertNotEqual(line, cr.P["CARD"])
                    self.assertGreaterEqual(cr.contrast(line, cr.P["CARD"]), 1.8)
            for c in cr.SWATCHES:
                with self.subTest(theme=key, swatch=c):
                    self.assertNotEqual(cr.swatch_outline(c), cr.P["CARD"])

    # 3. Breathing fades into the panel
    def test_led_on_is_unchanged_in_dark(self):
        cr = self.cr
        cr._apply_theme("gunmetal", "dark")
        for c in ((255, 0, 0), (40, 0, 0), (3, 2, 1), (0, 0, 0)):
            self.assertEqual(cr.led_on(c, (250, 250, 250)), c)

    def test_breathing_low_point_fades_into_the_light_panel(self):
        cr = self.cr
        for key in self._each("light"):
            bg = cr.hex2rgb(cr.P["CARD"])
            with self.subTest(theme=key):
                full = cr.led_on((255, 0, 0), bg)
                self.assertEqual(tuple(round(v) for v in full), (255, 0, 0))     # full brightness: the colour
                low = cr.led_on((12, 0, 0), bg)                                  # breath low point
                self.assertLess(max(abs(a - b) for a, b in zip(low, bg)), 20)    # close to the card, not black
                self.assertGreater(cr._lum(cr.hexcol(low)), 0.6)

    # sensor tree selection, chart guides, theme switch order
    def test_tree_selection_shows_in_light(self):
        cr = self.cr
        for key in self._each("light"):
            with self.subTest(theme=key):
                self.assertNotEqual(cr.P["SEL"], cr.P["CARD"])
                self.assertGreater(cr.contrast(cr.P["SEL"], cr.P["CARD"]),
                                   cr.contrast(cr.P["CARD2"], cr.P["CARD"]))

    def test_source_uses_the_helpers(self):
        src = (HERE.parent / "central_rgb.py").read_text(encoding="utf-8")
        self.assertNotIn('button_hover_color="white"', src)
        self.assertIn("button_hover_color=slider_hover(acc)", src)          # accent changes keep it right
        self.assertNotIn('outline=P["CARD"], width=2', src)
        self.assertIn('sel = P["SEL"] if APPEARANCE == "light" else P["CARD2"]', src)
        self.assertIn("imix(bgc, (0, 0, 0), 0.07)", src)                     # chart guides darken in Light
        sw = src[src.index("    def _switch_theme"):src.index("    def _restart")]
        # title bar and Windows clear colour change before the old widgets are destroyed and rebuilt
        self.assertLess(sw.index("self._window_effects()"), sw.index("for w in self.winfo_children()"))


@unittest.skipIf(sys.platform == "win32", "the Windows title bar is checked on Windows by the full check")
class TitleBarFailsQuietly(unittest.TestCase):
    def test_light_title_bar_is_a_no_op_elsewhere(self):
        import win_effects as fx
        fx.dark_titlebar(object(), False)
        fx.dark_titlebar(object())


TOGGLE_SCRIPT = r"""
import json, sys, tempfile, traceback
from pathlib import Path
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/tests"]
import preview
tmp = Path(tempfile.mkdtemp(prefix="centralrgb-appearance-gui-"))
cr, app = preview.start_app(tmp)
errors = []
app.report_callback_exception = lambda e, v, tb: errors.append("".join(traceback.format_exception(e, v, tb)))
result = {}

def settings_file():
    return json.loads((tmp / "roaming" / "CentralRGB" / "settings.json").read_text(encoding="utf-8"))

def step1():
    result["start"] = cr.APPEARANCE
    result["dark_bg"] = cr.P["BG"]
    app.show_page("Settings", animate=False)
    app.after(800, step2)

def step2():
    result["seg_start"] = app.appearance_seg.get()
    app.appearance_seg._click("Light")             # a real click on the pill
    app.after(2500, step3)

def step3():
    result["after_light"] = cr.APPEARANCE
    result["light_bg_ok"] = cr.P["BG"] == cr.LIGHT_THEMES[cr.THEME]["BG"]
    result["page"] = app.current_page
    result["seg_light"] = app.appearance_seg.get()
    result["saved_light"] = settings_file().get("appearance")
    result["window_bg"] = app.cget("fg_color")
    result["engine_alive"] = app.engine is not None
    app.appearance_seg._click("Dark")
    app.after(2500, step4)

def step4():
    result["after_dark"] = cr.APPEARANCE
    result["dark_bg_back"] = cr.P["BG"] == result["dark_bg"]
    result["saved_dark"] = settings_file().get("appearance")
    result["seg_dark"] = app.appearance_seg.get()
    result["errors"] = errors
    try:
        app.engine.stop(); app.monitor.stop()
    finally:
        app.destroy()

app.after(3000, step1)
app.mainloop()
print("RESULT " + json.dumps(result))
"""


@unittest.skipUnless(_gui_available(), "needs a display (run under xvfb-run) or CENTRALRGB_GUI_TESTS=1")
class ToggleInTheRealApp(unittest.TestCase):
    def test_toggle_rebuilds_settings_and_persists(self):
        r = subprocess.run([sys.executable, "-c", TOGGLE_SCRIPT, str(HERE.parent)],
                           capture_output=True, text=True, timeout=240)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), None)
        self.assertIsNotNone(line, r.stdout + r.stderr)
        res = json.loads(line[7:])
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["start"], "dark")
        self.assertEqual(res["seg_start"], "Dark")
        self.assertEqual(res["after_light"], "light")
        self.assertTrue(res["light_bg_ok"])
        self.assertEqual(res["page"], "Settings")              # rebuilt in place, still on Settings
        self.assertEqual(res["seg_light"], "Light")
        self.assertEqual(res["saved_light"], "light")
        self.assertTrue(res["engine_alive"])
        self.assertEqual(res["after_dark"], "dark")
        self.assertTrue(res["dark_bg_back"])
        self.assertEqual(res["saved_dark"], "dark")
        self.assertEqual(res["seg_dark"], "Dark")


if __name__ == "__main__":
    unittest.main()
