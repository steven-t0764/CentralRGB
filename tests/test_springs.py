# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Spring motion (springs.py) and where the interface uses it:
  - the spring reaches its target, overshoots a little when meant to and not at all when not, and the same
    motion comes out whatever the frame rate
  - an Animator stops by itself once settled, and jumps when animations are off
  - the pill selector glides its highlight to a new pick, jumps when set while hidden, and keeps get()/set()
  - readings count to the new value; the sidebar LED pops in on the page you open

Run from the repo root:  python -m unittest discover tests   (needs a display; xvfb-run on Linux)
"""
import os
import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import springs  # noqa: E402


def run(spring, secs, fps=60):
    peak, vals = spring.value, []
    for _ in range(int(secs * fps)):
        v = spring.step(1 / fps)
        vals.append(v)
        peak = max(peak, v)
    return peak, vals


class SpringPhysics(unittest.TestCase):
    def test_snappy_reaches_target_with_a_small_overshoot(self):
        sp = springs.Spring(0, **springs.SNAPPY)
        sp.target = 1
        peak, vals = run(sp, 1.0)
        self.assertTrue(sp.settled)
        self.assertEqual(sp.value, 1)
        self.assertTrue(1.005 < peak < 1.08, peak)                    # a touch of bounce, not a wobble
        settle = next(i for i, v in enumerate(vals) if all(abs(x - 1) < 0.01 for x in vals[i:])) / 60
        self.assertLess(settle, 0.45)

    def test_gentle_never_overshoots(self):
        sp = springs.Spring(40, **springs.GENTLE)
        self.assertFalse(sp.overshoots)
        sp.target = 70
        peak, _ = run(sp, 2.0)
        self.assertLessEqual(peak, 70.0001)
        self.assertEqual(sp.value, 70)

    def test_pop_bounces(self):
        sp = springs.Spring(0, **springs.POP)
        sp.target = 1
        peak, _ = run(sp, 1.5)
        self.assertGreater(peak, 1.1)
        self.assertTrue(sp.settled)

    def test_same_motion_at_any_frame_rate(self):
        a, b = springs.Spring(0), springs.Spring(0)
        a.target = b.target = 100
        for _ in range(30):
            a.step(1 / 30)
        for _ in range(144):                                            # the same second at 144 fps
            b.step(1 / 144)
        self.assertAlmostEqual(a.value, b.value, delta=0.5)

    def test_a_stalled_frame_does_not_fling_it(self):
        sp = springs.Spring(0)
        sp.target = 10
        sp.step(5.0)                                                    # the PC froze for 5 s
        self.assertLess(abs(sp.value), 25)

    def test_slot_interpolation(self):
        slots = [(0, 50), (60, 80), (150, 40)]
        self.assertEqual(springs.lerp_slots(slots, 0), (0, 50))
        self.assertEqual(springs.lerp_slots(slots, 2), (150, 40))
        x, w = springs.lerp_slots(slots, 0.5)
        self.assertEqual((x, w), (30, 65))
        x, _ = springs.lerp_slots(slots, 2.05)                          # overshoot: a little past the end
        self.assertGreater(x, 150)


class AnimatorOnTk(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("300x100")
        self.seen = []
        self.prev = springs.Animator.enabled
        springs.Animator.enabled = True

    def tearDown(self):
        springs.Animator.enabled = self.prev
        self.root.destroy()

    def pump(self, secs):
        end = time.perf_counter() + secs
        while time.perf_counter() < end:
            self.root.update()
            time.sleep(0.004)

    def test_glides_then_stops(self):
        a = springs.Animator(self.root, self.seen.append, value=0)
        a.to(100)
        self.assertTrue(a.running)
        self.pump(0.9)
        self.assertFalse(a.running)
        self.assertEqual(self.seen[-1], 100)
        self.assertGreater(len(self.seen), 10)                          # many in-between frames
        self.assertTrue(any(0 < v < 100 for v in self.seen))

    def test_jumps_when_animations_are_off(self):
        springs.Animator.enabled = False
        a = springs.Animator(self.root, self.seen.append, value=0)
        a.to(100)
        self.assertEqual(self.seen, [100])
        self.assertFalse(a.running)

    def test_env_switch_turns_animation_off(self):
        os.environ["CENTRALRGB_NO_ANIM"] = "1"
        try:
            self.assertFalse(springs.animations_on())
        finally:
            del os.environ["CENTRALRGB_NO_ANIM"]


class InTheApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import central_rgb as cr
        cls.cr = cr

    def setUp(self):
        self.prev = springs.Animator.enabled
        springs.Animator.enabled = True
        self.root = tk.Tk()
        self.root.geometry("520x120")
        self.frame = self.cr.ctk.CTkFrame(self.root, fg_color=self.cr.P["CARD"])
        self.frame.pack(fill="both", expand=True)

    def tearDown(self):
        springs.Animator.enabled = self.prev
        self.root.destroy()

    def pump(self, secs):
        end = time.perf_counter() + secs
        while time.perf_counter() < end:
            self.root.update()
            time.sleep(0.004)

    def test_pill_glides_to_the_new_pick(self):
        picked = []
        ps = self.cr.PillSwitcher(self.frame, values=["Auto", "Silent", "Balanced", "Max"], command=picked.append)
        ps.pack(fill="x")
        self.pump(0.2)
        x0 = ps.cv.coords(ps._pill_item)[0]
        ps._click("Max")
        self.assertEqual(picked, ["Max"])
        self.assertEqual(ps.get(), "Max")
        self.pump(0.06)
        mid = ps.cv.coords(ps._pill_item)[0]
        self.pump(0.8)
        end = ps.cv.coords(ps._pill_item)[0]
        self.assertTrue(x0 < mid < end, (x0, mid, end))                 # seen on its way across
        self.assertAlmostEqual(end, ps._slots[3][0], delta=1)
        self.assertEqual(ps.cv.itemcget(ps._texts[3], "fill").lower(), ps.accent.lower())

    def test_pill_click_picks_the_option_under_the_mouse(self):
        picked = []
        ps = self.cr.PillSwitcher(self.frame, values=["Dark", "Light"], command=picked.append)
        ps.pack(fill="x")
        self.pump(0.1)
        x, w = ps._slots[1]
        ps._release(type("E", (), {"x": x + w / 2, "y": 5})())
        self.assertEqual(picked, ["Light"])

    def test_pill_set_while_hidden_jumps(self):
        ps = self.cr.PillSwitcher(self.frame, values=["Overview", "Advanced"])
        ps.set("Advanced")                                              # not packed yet
        self.assertFalse(ps.anim.running)
        self.assertEqual(ps.anim.value, 1)

    def test_reading_counts_to_the_new_value(self):
        lbl = self.cr.ctk.CTkLabel(self.frame, text="")
        lbl.pack()
        self.pump(0.05)
        fmt = lambda v: self.cr.fmt(v, "°C")
        self.cr.count_to(lbl, 40, fmt)
        self.assertEqual(lbl.cget("text"), "40°C")                      # first reading shows at once
        self.cr.count_to(lbl, 80, fmt)
        texts = set()
        end = time.perf_counter() + 1.0
        while time.perf_counter() < end:
            self.root.update()
            texts.add(lbl.cget("text"))
            time.sleep(0.004)
        self.assertEqual(lbl.cget("text"), "80°C")
        between = [t for t in texts if t not in ("40°C", "80°C")]
        self.assertGreater(len(between), 3)
        self.assertTrue(all(40 < int(t[:-2]) < 80 for t in between))     # never past the real value
        self.cr.count_to(lbl, None, fmt)
        self.assertEqual(lbl.cget("text"), "—")

    def test_sidebar_led_pops_in(self):
        item = self.cr.NavItem(self.frame, "Home", None, "H", lambda: None)
        item.pack(fill="x")
        self.pump(0.05)
        item.set(True, "#00aaff")
        self.assertTrue(item.pop.running)
        self.pump(0.8)
        self.assertEqual(item.pop.value, 1)
        self.assertEqual(len(item.pill.find_all()), 2)                  # halo + core
        item.set(False, "#00aaff")
        self.assertEqual(item.pill.find_all(), ())


if __name__ == "__main__":
    unittest.main()
