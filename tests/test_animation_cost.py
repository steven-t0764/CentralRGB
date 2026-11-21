# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""The live previews (Lighting, Home, Devices) cost little per frame.

  - on Lighting the effect tiles redraw at half the frame rate, staggered, and still tiles only once, so
    eng.compute_colors runs far less often than the old "every tile, every frame"
  - an LED whose colour did not change is not reconfigured (effect tiles) or repainted (LED strips)
  - a still effect, or any effect with animations off in Settings, is drawn once and then left alone until
    something it shows changes
  - the Devices page reads the excluded list and the overrides once per frame

Most checks run the frame code on a stand-in for the window (no screen needed); the widget checks need Tk.
The real-app check builds Central RGB on the simulated hardware the way tests/harness.py does, prints the
per-frame cost on Home, Lighting and Devices, and runs on Linux with a display (xvfb-run) or when
CENTRALRGB_GUI_TESTS=1 is set:  python tests/test_animation_cost.py --app-check

Run from the repo root:  python -m unittest discover tests
"""
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
APP_CHECK = "--app-check"

from test_page_switch import _gui_available  # noqa: E402

cr = None
if not (__name__ == "__main__" and APP_CHECK in sys.argv):   # the app check imports it after its fakes
    os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="centralrgb-anim-cost-"))
    try:
        import central_rgb as cr
    except Exception:  # pragma: no cover - needs tkinter/customtkinter
        cr = None

FRAMES_PER_SECOND = 25            # _animate runs every ANIM_MS = 40 ms


class FakeSettings:
    def __init__(self, data):
        self.data = data

    def __getitem__(self, k):
        return self.data[k]


class FakeStrip:
    """Stands in for LedStrip / DeviceArt: remembers what it was asked to show."""

    def __init__(self, n=48, mapped=True):
        self.n, self.mapped, self.shown = n, mapped, []
        self.leds = [None] * n

    def show(self, colors):
        self.shown.append(colors)

    def winfo_ismapped(self):
        return self.mapped


if cr is not None:
    class FakeTile(cr.EffectTile):
        """An EffectTile (so the frame code treats it as one) without a Tk window behind it."""

        def __init__(self):                       # noqa: no Canvas: nothing here needs Tk
            self.n, self.shown = cr.EffectTile.COLS, []

        def show(self, colors):
            self.shown.append(colors)


def _app(page="Lighting", effect="Static", animations=True):
    tiles = {name: FakeTile() for name in cr.eng.BASIC_EFFECTS}
    tiles["Tide"] = object()                      # a picture tile: the frame code leaves it alone
    state = {"color": [0, 120, 255], "effect": effect, "brightness": 100, "speed": 50}
    settings = FakeSettings({"animations": animations, "excluded": ["dev2"], "state": state,
                             "device_overrides": {"dev1": {"color": [255, 0, 0], "effect": "Static",
                                                           "brightness": 80, "speed": 50}}})
    app = SimpleNamespace(settings=settings, current_page=page, color=(0, 120, 255), effect=effect,
                          accent="#00e5ff", preview=FakeStrip(48),
                          preview_track=mock.Mock(spec=["create_rectangle", "coords", "itemconfigure", "winfo_width",
                                                        "delete"]),
                          home_strip=FakeStrip(40), home_light_strip=FakeStrip(24, mapped=False), tiles=tiles,
                          device_cards=[SimpleNamespace(key=k, strip=FakeStrip(12)) for k in ("dev0", "dev1", "dev2")],
                          editor=None, editor_key=None, editor_art=FakeStrip(16))
    app.preview_track.winfo_width.return_value = 300
    app._current_state = lambda: {"color": list(app.color), "effect": app.effect, "brightness": 100, "speed": 50}
    app._move_track = lambda t, speed: cr.App._move_track(app, t, speed)
    return app


def _effect_tiles(app):
    return [t for t in app.tiles.values() if isinstance(t, cr.EffectTile)]


def _run(app, frames, t0=1000.0):
    """Draw `frames` frames, 40 ms apart, and return the compute_colors calls made."""
    with mock.patch.object(cr.eng, "compute_colors", wraps=cr.eng.compute_colors) as cc:
        for i in range(frames):
            cr.App._draw_frame(app, t0 + i * cr.ANIM_MS / 1000)
    return cc.call_args_list


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class LightingPageCallsLess(unittest.TestCase):
    def test_one_second_of_frames_with_a_still_effect(self):
        app = _app("Lighting", "Static")
        calls = _run(app, FRAMES_PER_SECOND)
        old_tiles = len(_effect_tiles(app)) * FRAMES_PER_SECOND       # every tile, every frame
        old_total = old_tiles + FRAMES_PER_SECOND                       # ...plus the preview
        self.assertLess(len(calls), old_tiles / 2.5, f"{len(calls)} compute_colors calls in 1 s")
        self.assertGreaterEqual(old_total / len(calls), 3)

    def test_one_second_of_frames_with_a_moving_effect(self):
        app = _app("Lighting", "Aurora")
        calls = _run(app, FRAMES_PER_SECOND)
        tiles = {n for n, t in app.tiles.items() if isinstance(t, cr.EffectTile)}
        tile_calls = [c for c in calls if c.args[0] in tiles]
        old_tiles = len(tiles) * FRAMES_PER_SECOND
        self.assertLess(len(tile_calls), old_tiles / 2.5, f"{len(tile_calls)} tile compute_colors calls in 1 s")
        self.assertEqual(len(app.preview.shown), FRAMES_PER_SECOND)   # the main preview keeps the full rate

    def test_moving_tiles_redraw_at_half_rate_and_staggered(self):
        app = _app("Lighting", "Static")
        _run(app, 1)                                                    # first frame draws every tile
        moving = [(n, t) for n, t in app.tiles.items() if isinstance(t, cr.EffectTile) and cr.eng.is_animated(n)]
        self.assertTrue(moving)
        for _, t in moving:
            t.shown.clear()
        per_frame = []
        for i in range(1, 21):
            before = sum(len(t.shown) for _, t in moving)
            _run(app, 1, t0=1000.0 + i * 0.04)
            per_frame.append(sum(len(t.shown) for _, t in moving) - before)
        for _, t in moving:
            self.assertEqual(len(t.shown), 10)                          # 20 frames at 12.5 fps
        self.assertLess(max(per_frame), len(moving))                    # never all of them on one frame

    def test_still_tiles_draw_once(self):
        app = _app("Lighting", "Static")
        _run(app, FRAMES_PER_SECOND)
        for name in ("Static", "Off"):
            self.assertEqual(len(app.tiles[name].shown), 1, name)

    def test_colour_change_redraws_at_once(self):
        app = _app("Lighting", "Static")
        _run(app, 3)
        app.color = (255, 80, 0)
        before = len(app.tiles["Static"].shown), len(app.preview.shown)
        _run(app, 1, t0=2000.0)
        self.assertEqual(len(app.tiles["Static"].shown), before[0] + 1)
        self.assertEqual(len(app.preview.shown), before[1] + 1)
        self.assertEqual(app.preview.shown[-1][0], (255, 80, 0))

    def test_track_bars_are_made_once_and_moved(self):
        app = _app("Lighting", "Aurora")
        _run(app, 10)
        self.assertEqual(app.preview_track.create_rectangle.call_count, 2)
        app.preview_track.delete.assert_not_called()
        self.assertEqual(app.preview_track.coords.call_count, 20)


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class StillOrAnimationsOffStopsRedrawing(unittest.TestCase):
    def _assert_stops(self, app, widgets):
        first = _run(app, 1)
        self.assertTrue(first)
        shown = [len(w.shown) for w in widgets]
        self.assertEqual(_run(app, FRAMES_PER_SECOND, t0=1001.0), [])  # nothing computed...
        self.assertEqual([len(w.shown) for w in widgets], shown)         # ...and nothing drawn

    def test_still_effect_on_home_and_devices(self):
        app = _app("Home", "Static")
        self._assert_stops(app, [app.home_strip])
        app = _app("Devices", "Static")
        self._assert_stops(app, [c.strip for c in app.device_cards])

    def test_still_effect_on_lighting(self):
        """The preview and the still tiles stop; only the moving effects' own tiles keep going."""
        app = _app("Lighting", "Static")
        _run(app, 1)
        calls = _run(app, FRAMES_PER_SECOND, t0=1001.0)
        self.assertTrue(calls)
        self.assertTrue(all(cr.eng.is_animated(c.args[0]) for c in calls), [c.args[0] for c in calls])
        self.assertEqual(len(app.preview.shown), 1)
        self.assertEqual(app.preview_track.coords.call_count, 2)

    def test_animations_off_freezes_moving_effects(self):
        for page in ("Lighting", "Home", "Devices"):
            with self.subTest(page=page):
                app = _app(page, "Aurora", animations=False)
                app.settings.data["state"]["effect"] = "Aurora"
                widgets = {"Lighting": [app.preview] + _effect_tiles(app), "Home": [app.home_strip],
                           "Devices": [c.strip for c in app.device_cards]}[page]
                self._assert_stops(app, widgets)

    def test_animations_back_on_moves_again(self):
        app = _app("Home", "Aurora", animations=False)
        _run(app, 5)
        self.assertEqual(len(app.home_strip.shown), 1)
        app.settings.data["animations"] = True
        _run(app, 5, t0=1001.0)
        self.assertEqual(len(app.home_strip.shown), 6)

    def test_edited_custom_preset_redraws(self):
        cr.eng.CUSTOM_PRESETS["Mine"] = {"motion": "Gradient", "colors": [[255, 0, 0], [0, 0, 255]]}
        self.addCleanup(cr.eng.CUSTOM_PRESETS.pop, "Mine", None)
        app = _app("Home", "Mine")
        _run(app, 3)
        self.assertEqual(len(app.home_strip.shown), 1)
        cr.eng.CUSTOM_PRESETS["Mine"] = {"motion": "Gradient", "colors": [[0, 255, 0], [0, 0, 255]]}
        _run(app, 1, t0=1001.0)
        self.assertEqual(len(app.home_strip.shown), 2)


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class HomeAndDevicesPages(unittest.TestCase):
    def test_hidden_home_strip_is_not_computed(self):
        app = _app("Home", "Aurora")
        calls = _run(app, 5)
        self.assertEqual(len(calls), 5)                                 # only the visible strip
        self.assertEqual(app.home_light_strip.shown, [])

    def test_devices_cards_show_their_own_state(self):
        app = _app("Devices", "Static")
        _run(app, 1)
        dev0, dev1, dev2 = (c.strip.shown[-1] for c in app.device_cards)
        self.assertEqual(dev0[0], (0, 120, 255))                       # the main lighting
        self.assertEqual(dev1[0], (204, 0, 0))                          # its own override, at 80 %
        self.assertEqual(dev2, [(0, 0, 0)])                             # excluded: dark

    def test_excluded_and_overrides_read_once_per_frame(self):
        app = _app("Devices", "Aurora")
        reads = []
        real = app.settings.__class__.__getitem__
        with mock.patch.object(FakeSettings, "__getitem__", lambda s, k: (reads.append(k), real(s, k))[1]):
            _run(app, 4)
        self.assertEqual(reads.count("excluded"), 4)
        self.assertEqual(reads.count("state"), 4)

    def test_toggling_a_device_redraws_it(self):
        app = _app("Devices", "Static")
        _run(app, 2)
        app.settings.data["excluded"] = []
        _run(app, 1, t0=1001.0)
        self.assertEqual(app.device_cards[2].strip.shown[-1][0], (0, 120, 255))

    def test_editor_preview_follows_the_device(self):
        app = _app("Devices", "Static")
        app.editor, app.editor_key = object(), "dev1"
        _run(app, 3)
        self.assertEqual(len(app.editor_art.shown), 1)
        self.assertEqual(app.editor_art.shown[0][0], (204, 0, 0))

    def test_same_arguments_are_computed_once_per_frame(self):
        app = _app("Devices", "Aurora")
        app.device_cards = [SimpleNamespace(key="dev0", strip=FakeStrip(12)) for _ in range(1)]
        app.editor, app.editor_key, app.editor_art = object(), "dev0", FakeStrip(12)
        calls = _run(app, 1)                     # card 0 (offset 0) and the editor ask for the same frame
        self.assertEqual(len(calls), 1)
        self.assertIs(app.editor_art.shown[0], app.device_cards[0].strip.shown[0])


def _tk_root(test):
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        test.skipTest("no display")
    root.withdraw()
    test.addCleanup(root.destroy)
    return root


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class UnchangedLedsAreNotRedrawn(unittest.TestCase):
    def test_effect_tile_skips_unchanged_bars(self):
        root = _tk_root(self)
        tile = cr.EffectTile(root, "Rainbow Wave", lambda name: None)
        tile._layout()
        cols = cr.eng.compute_colors("Rainbow Wave", (0, 0, 0), 100, 50, tile.n, 1.0)
        tile.show(cols)
        with mock.patch.object(tile, "itemconfigure", wraps=tile.itemconfigure) as ic:
            tile.show(list(cols))                               # same colours again
            self.assertEqual(ic.call_count, 0)
            changed = list(cols)
            before = tile._fills[5]
            changed[5] = (255, 255, 255)
            tile.show(changed)
            self.assertEqual(ic.call_count, 1)                  # just the one LED that changed
        self.assertNotEqual(tile._fills[5], before)
        self.assertEqual(tile.itemcget(tile.bars[5], "fill"), tile._fills[5])

    def test_effect_tile_relayout_keeps_its_colours(self):
        root = _tk_root(self)
        tile = cr.EffectTile(root, "Static", lambda name: None)
        tile._layout()
        tile.show([(255, 0, 0)] * tile.n)
        lit = tile._fills[0]
        self.assertNotEqual(lit, cr.P["TRACK"])
        tile.select(True, "#00e5ff")                            # rebuilds the tile's items
        self.assertEqual(tile.itemcget(tile.bars[0], "fill"), lit)

    def test_led_strip_skips_an_unchanged_frame(self):
        root = _tk_root(self)
        strip = cr.LedStrip(root, n=24, height=20)
        strip._layout()
        pastes = []
        real = strip._photo.paste
        strip._photo.paste = lambda im: (pastes.append(1), real(im))
        cols = cr.eng.compute_colors("Rainbow Wave", (0, 0, 0), 100, 50, 24, 1.0)
        strip.show(cols)
        strip.show([tuple(c) for c in cols])
        self.assertEqual(len(pastes), 1)
        strip.show(cr.eng.compute_colors("Rainbow Wave", (0, 0, 0), 100, 50, 24, 2.0))
        self.assertEqual(len(pastes), 2)


def _app_check():
    """Build the real app on simulated hardware (as tests/harness.py does), time its frames on Home, Lighting
    and Devices, and check the Lighting page's compute_colors calls and the animations-off case."""
    import json
    tmp = tempfile.mkdtemp(prefix="centralrgb-anim-cost-app-")
    os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = tmp
    (Path(tmp) / "CentralRGB").mkdir()
    (Path(tmp) / "CentralRGB" / "settings.json").write_text(json.dumps(
        {"animations": True, "state": {"color": [0, 120, 255], "effect": "Aurora", "brightness": 100, "speed": 30}}))
    import fakes
    import rgb_engine as eng
    eng.OpenRGBClient = fakes.FakeClient
    eng.OpenRGBManager.server_running = staticmethod(lambda timeout=0.5: True)
    eng.OpenRGBManager.replace_visible_copy = lambda self: False
    import central_rgb as app_mod
    app_mod.App.TEST_BACKEND = fakes.FakeLHM()
    app = app_mod.App()
    failures, times, calls = [], [], [0]
    real_cc = eng.compute_colors

    def counted(*a, **k):
        if threading.current_thread() is threading.main_thread():   # the window's calls, not the engine's
            calls[0] += 1
        return real_cc(*a, **k)
    eng.compute_colors = counted

    def timed(t):
        t0 = time.perf_counter()
        app_mod.App._draw_frame(app, t)
        times.append(time.perf_counter() - t0)
    app._draw_frame = timed

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.update()
            time.sleep(0.005)

    def measure(seconds=2.0):
        pump(0.5)
        times.clear()
        calls[0] = 0
        t0 = time.time()
        pump(seconds)
        return len(times), calls[0] / (time.time() - t0)

    try:
        app.deiconify()
        pump(3)
        n_tiles = sum(isinstance(t, app_mod.EffectTile) for t in app.tiles.values())
        for page in ("Home", "Lighting", "Devices"):
            app.show_page(page, animate=False)
            frames, per_s = measure()
            if not times:
                failures.append(f"no frames drawn on {page}")
                continue
            print(f"{page}: {frames} frames, per frame mean {statistics.mean(times) * 1000:.2f} ms, "
                  f"median {statistics.median(times) * 1000:.2f} ms, compute_colors {per_s:.0f}/s")
            if page == "Lighting":
                old = (1 + n_tiles) * 1000 / app_mod.ANIM_MS
                print(f"Lighting: before this change {old:.0f} compute_colors/s ({n_tiles} tiles + preview)")
                if per_s * 2 > old:
                    failures.append(f"Lighting makes {per_s:.0f} compute_colors calls/s (was {old:.0f})")
        app.show_page("Lighting", animate=False)
        app.settings.data["animations"] = False
        frames, per_s = measure(1.0)
        print(f"Lighting, animations off: {frames} frames, compute_colors {per_s:.0f}/s")
        if per_s:
            failures.append("animations off still redraws")
    finally:
        app.engine.stop()
        app.monitor.stop()
        app.destroy()
    print("FAILED: " + "; ".join(failures) if failures else "PASSED")
    return 1 if failures else 0


@unittest.skipUnless(_gui_available(), "needs a display (run under xvfb-run) or CENTRALRGB_GUI_TESTS=1")
class RealAppFrameCost(unittest.TestCase):
    def test_real_app(self):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), APP_CHECK],
                           capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASSED", r.stdout)


if __name__ == "__main__":
    if APP_CHECK in sys.argv:
        sys.exit(_app_check())
    unittest.main()
