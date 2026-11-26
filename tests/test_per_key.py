# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Per-key lighting: paint single keys (WASD red, say) on top of whatever effect runs on the keyboard.
  - the key layout comes from OpenRGB's key matrix; WASD / arrows / numbers / F keys are found by name
  - the engine sends the painted keys on top of the effect, scaled by brightness, only to keyboards that take
    a colour per LED, and the rest of the keyboard keeps its effect
  - the key editor paints by click and drag, clears with right-click, quick-paints groups, and saves as it goes

Run from the repo root:  python -m unittest discover tests   (needs a display; xvfb-run on Linux)
"""
import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

from openrgb.utils import DeviceType, ModeColors  # noqa: E402

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

RED = (255, 0, 0)


def keyboard():
    return fake_openrgb.FakeDevice(0, *fake_openrgb.OWNERS_KEYBOARD)


class Layout(unittest.TestCase):
    def test_rows_from_the_key_matrix(self):
        lay = eng.keyboard_layout(keyboard())
        self.assertEqual(len(lay), 6)
        labels = [lb for row in lay for i, lb in row if i is not None]
        self.assertEqual(len(labels), 87)                               # TKL keys; underglow isn't drawn
        self.assertIn("W", [lb for _, lb in lay[2]])
        self.assertEqual(lay[0][0][1], "Escape")

    def test_groups_found_by_name(self):
        kb = keyboard()
        self.assertEqual(eng.find_keys(kb, eng.KEY_GROUPS["WASD"]), ["Key: W", "Key: A", "Key: S", "Key: D"])
        self.assertEqual(len(eng.find_keys(kb, eng.KEY_GROUPS["Arrows"])), 4)
        self.assertEqual(len(eng.find_keys(kb, eng.KEY_GROUPS["F keys"])), 12)
        self.assertEqual(len(eng.find_keys(kb, eng.KEY_GROUPS["Numbers"])), 10)

    def test_other_spellings_still_match(self):
        dev = SimpleNamespace(leds=[SimpleNamespace(name=n, id=i) for i, n in
                                    enumerate(["Key: Up", "Key: Number 1", "Key: Esc", "Key: W"])])
        self.assertEqual(eng.find_keys(dev, ["Up Arrow", "1", "Escape", "W"]),
                         ["Key: Up", "Key: Number 1", "Key: Esc", "Key: W"])

    def test_no_matrix_falls_back_to_rows_of_leds(self):
        dev = fake_openrgb.FakeDevice(1, "Some keyboard", DeviceType.KEYBOARD, "X", [("Keyboard", 40)],
                                      ("Direct", "Off"))
        lay = eng.keyboard_layout(dev)
        self.assertEqual([len(r) for r in lay], [16, 16, 8])

    def test_one_colour_keyboards_cant_be_painted(self):
        dev = fake_openrgb.FakeDevice(1, "Basic keyboard", DeviceType.KEYBOARD, "X", [("Keyboard", 1)],
                                      ("Static", "Off"))
        self.assertFalse(eng.per_key_capable(dev))
        self.assertTrue(eng.per_key_capable(keyboard()))


class OnTopOfTheEffect(unittest.TestCase):
    def test_painted_keys_replace_the_effect_and_dim_with_brightness(self):
        kb = keyboard()
        base = [(0, 0, 255)] * len(kb.leds)
        out = eng.apply_key_colors(base, kb, {"Key: W": RED}, brightness=100)
        w = eng.led_names(kb).index("Key: W")
        self.assertEqual(out[w], RED)
        self.assertEqual(out[w + 1], (0, 0, 255))
        dim = eng.apply_key_colors(base, kb, {"Key: W": RED}, brightness=40)
        self.assertLess(dim[w][0], 255)
        self.assertEqual(eng.apply_key_colors(base, kb, {}), base)

    def test_engine_sends_them_with_the_effect(self):
        fake_openrgb.install(eng, devices=[fake_openrgb.OWNERS_KEYBOARD])
        e = eng.LightingEngine(log=lambda *a, **k: None)
        e.client = fake_openrgb.FakeClient()
        kb = e.client.devices[0]
        e.set_state(effect="Rainbow Wave", brightness=100, speed=50)
        e.set_key_colors({eng.device_key(kb): {"Key: W": RED, "Key: A": RED}})
        with mock.patch.object(eng, "find_conflicts", lambda: {}):
            e.step()
        names = eng.led_names(kb)
        cols = [(c.red, c.green, c.blue) for c in kb.colors]
        self.assertEqual(cols[names.index("Key: W")], RED)
        self.assertEqual(cols[names.index("Key: A")], RED)
        others = {cols[i] for i, n in enumerate(names) if n not in ("Key: W", "Key: A")}
        self.assertGreater(len(others), 5)                              # the rainbow still runs on the rest

        # a still colour with painted keys: the keyboard stays in its per-LED mode so W keeps its own colour
        e.set_state(effect="Static", color=(0, 0, 255))
        with mock.patch.object(eng, "find_conflicts", lambda: {}):
            e.step()
        self.assertEqual(kb.modes[kb.active_mode].color_mode, ModeColors.PER_LED)
        cols = [(c.red, c.green, c.blue) for c in kb.colors]
        self.assertEqual(cols[names.index("Key: W")], RED)
        self.assertEqual(cols[names.index("Key: E")][:2], (0, 0))

        # nothing painted any more: back to the keyboard's own Static mode, all one colour
        e.set_key_colors({})
        with mock.patch.object(eng, "find_conflicts", lambda: {}):
            e.step()
        self.assertEqual(kb.modes[kb.active_mode].name, "Static")

    def test_saved_in_settings(self):
        s = eng.Settings()
        self.assertIn("key_colors", s.data)


class Editor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import central_rgb as cr
        cls.cr = cr
        cls.saved = saved = []

        class StubApp(cr.ctk.CTk):            # one window for the whole class: image caches belong to it
            def __init__(s):
                super().__init__()
                s.settings = SimpleNamespace(data={"key_colors": {}})

            def label(s, parent, text, size=12, weight="normal", color=None, **kw):
                return cr.ctk.CTkLabel(parent, text=text,
                                       **{k: v for k, v in kw.items() if k in ("anchor", "justify", "wraplength")})

            def primary(s, parent, text, cmd, **kw):
                return cr.ctk.CTkButton(parent, text=text, command=cmd, width=kw.get("width", 100))

            secondary = primary

            def set_key_colors(s, key, colors):
                saved.append((key, dict(colors)))

        cls.app = StubApp()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def setUp(self):
        self.saved.clear()
        self.kb = keyboard()
        self.ed = self.cr.KeyEditor(self.app, "kb", self.kb)
        self.app.update()

    def tearDown(self):
        self.ed.destroy()
        self.app.update()

    def cell(self, name):
        rect = next(r for r, n in self.ed.cells.items() if n == name)
        x0, y0, x1, y1 = self.ed.cv.coords(rect)
        return SimpleNamespace(x=(x0 + x1) / 2, y=(y0 + y1) / 2)

    def test_click_paints_and_right_click_clears(self):
        self.ed._paint_at(self.cell("Key: W"), self.ed.brush)
        self.assertEqual(self.saved[-1], ("kb", {"Key: W": RED}))
        rect = next(r for r, n in self.ed.cells.items() if n == "Key: W")
        self.assertEqual(self.ed.cv.itemcget(rect, "fill").lower(), "#ff0000")
        self.ed._paint_at(self.cell("Key: W"), None)
        self.assertEqual(self.saved[-1], ("kb", {}))

    def test_dragging_over_the_same_key_saves_once(self):
        self.ed._paint_at(self.cell("Key: Q"), self.ed.brush)
        self.ed._paint_at(self.cell("Key: Q"), self.ed.brush)
        self.assertEqual(len(self.saved), 1)

    def test_quick_paint_and_clear(self):
        self.ed._set_brush((0, 255, 255))
        self.ed._paint_group("WASD")
        self.assertEqual(set(self.saved[-1][1]), {"Key: W", "Key: A", "Key: S", "Key: D"})
        self.assertEqual(len(self.saved), 1)                            # one save for the whole group
        self.ed._clear()
        self.assertEqual(self.saved[-1][1], {})

    def test_space_is_drawn_wide(self):
        rect = next(r for r, n in self.ed.cells.items() if n == "Key: Space")
        x0, _, x1, _ = self.ed.cv.coords(rect)
        self.assertGreater(x1 - x0, 5 * self.ed.U)


if __name__ == "__main__":
    unittest.main()
