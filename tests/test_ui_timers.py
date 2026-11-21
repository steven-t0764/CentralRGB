# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""The window's background timers don't do work nobody sees.

  - the Activity box keeps at most LOG_LINES lines, however long the app runs, and log lines go in as one
    batch per queue tick, in order with the other queue items
  - with the overlay off and its page not showing, the overlay tick makes no Win32 calls and slows to
    OVERLAY_IDLE_MS; switching the overlay on brings the fast polling back at once
  - in the tray the overlay still follows the game but skips drawing the preview
  - closing writes any pending settings change straight away

Most checks run on stand-ins for the window (no screen needed). The real-app check builds Central RGB on the
simulated hardware the way tests/harness.py does; it runs on Linux with a display (xvfb-run) or when
CENTRALRGB_GUI_TESTS=1 is set.

Run from the repo root:  python -m unittest discover tests
"""
import io
import os
import queue
import subprocess
import sys
import tempfile
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
    os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix="centralrgb-ui-timers-"))
    try:
        import central_rgb as cr
    except Exception:  # pragma: no cover - needs tkinter/customtkinter
        cr = None


class FakeText:
    """Just enough of a Tk Text widget: lines with their tag, and Tk's rule that a disabled box ignores edits."""

    def __init__(self):
        self.lines: list[tuple[str, object]] = []
        self.state = "normal"
        self.opened = 0                           # configure(state="normal") calls
        self.seen = 0

    def configure(self, state=None, **_):
        if state is not None:
            self.state = state
            if state == "normal":
                self.opened += 1

    def insert(self, index, text, tags=None):
        assert index == "end"
        if self.state != "normal":
            return
        assert text.endswith("\n")
        for part in text[:-1].split("\n"):
            self.lines.append((part, tags))

    def index(self, i):
        assert i == "end-1c"
        return f"{len(self.lines) + 1}.0"         # every line ends in "\n", so the last character is on a new line

    def delete(self, a, b):
        if self.state != "normal":
            return
        assert a == "1.0" and b.endswith(".0")
        del self.lines[:int(b.split(".")[0]) - 1]

    def see(self, i):
        self.seen += 1


def _log_app(box):
    # _logfile set: App.log writes there instead of opening activity.log in the real settings folder
    app = SimpleNamespace(q=queue.Queue(), logbox=box, after_calls=[], _logfile=io.StringIO())
    app.after = lambda ms, fn: app.after_calls.append(ms)
    app._add_log_lines = lambda items: cr.App._add_log_lines(app, items)
    app._poll_queue = lambda: cr.App._poll_queue(app)       # it reschedules itself
    return app


def _drain(app, limit=1000):
    ticks = 0
    while not app.q.empty() and ticks < limit:
        cr.App._poll_queue(app)
        ticks += 1
    return ticks


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class LogBoxIsCapped(unittest.TestCase):
    def setUp(self):
        self.box = FakeText()
        self.app = _log_app(self.box)

    def test_2000_log_calls_keep_at_most_the_cap(self):
        for i in range(2000):
            cr.App.log(self.app, f"line {i}", ("ok", "warn", "bad", "info", "")[i % 5])
            if i % 150 == 0:
                _drain(self.app)
        _drain(self.app)
        self.assertLessEqual(len(self.box.lines), cr.LOG_LINES)
        self.assertEqual(len(self.box.lines), cr.LOG_LINES)
        self.assertTrue(self.box.lines[-1][0].endswith("line 1999"))
        self.assertTrue(self.box.lines[0][0].endswith(f"line {2000 - cr.LOG_LINES}"))
        self.assertEqual(self.box.state, "disabled")

    def test_tags_and_prefixes_stay_the_same(self):
        for level in ("ok", "warn", "bad", "info", ""):
            cr.App.log(self.app, f"msg {level or 'plain'}", level)
        _drain(self.app)
        got = [(text[10:], tag) for text, tag in self.box.lines]   # drop the "HH:MM:SS  " stamp
        self.assertEqual(got, [("✓ msg ok", "ok"), ("! msg warn", "warn"), ("✕ msg bad", "bad"),
                               ("  msg info", "info"), ("msg plain", None)])

    def test_one_insert_cycle_and_a_bounded_batch_per_tick(self):
        for i in range(cr.QUEUE_BATCH * 3):
            self.app.q.put(("log", f"line {i}", ""))
        cr.App._poll_queue(self.app)
        self.assertEqual(self.box.opened, 1)                     # one normal/insert/see/disabled cycle
        self.assertEqual(self.box.seen, 1)
        self.assertEqual(len(self.box.lines), cr.QUEUE_BATCH)    # the rest waits for the next tick
        self.assertEqual(self.app.q.qsize(), cr.QUEUE_BATCH * 2)
        self.assertLess(self.app.after_calls[-1], 100)          # ...which comes soon, as there is more
        _drain(self.app)
        cr.App._poll_queue(self.app)                             # queue empty: back to the normal pace
        self.assertEqual(self.app.after_calls[-1], 100)
        self.assertEqual(len(self.box.lines), cr.LOG_LINES)

    def test_order_with_other_queue_items_is_kept(self):
        seen = []
        self.app.q.put(("log", "before", ""))
        self.app.q.put(("call", lambda: seen.append([t for t, _ in self.box.lines])))
        self.app.q.put(("log", "after", ""))
        _drain(self.app)
        self.assertEqual(len(seen[0]), 1)
        self.assertTrue(seen[0][0].endswith("before"))           # the call ran after "before" was shown
        self.assertTrue(self.box.lines[-1][0].endswith("after"))

    def test_tray_and_devices_items_still_handled(self):
        self.app._tray_action = mock.Mock()
        self.app._fill_devices = mock.Mock()
        self.app.q.put(("tray", "show"))
        self.app.q.put(("devices", ["row"]))
        _drain(self.app)
        self.app._tray_action.assert_called_once_with("show")
        self.app._fill_devices.assert_called_once_with(["row"])

    def test_real_text_widget_is_capped(self):
        import tkinter as tk
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        try:
            root.withdraw()
            box = tk.Text(root)
            box.configure(state="disabled")
            app = _log_app(box)
            for i in range(2000):
                app.q.put(("log", f"line {i}", "ok"))
            _drain(app)
            lines = int(box.index("end-1c").split(".")[0]) - 1
            self.assertLessEqual(lines, cr.LOG_LINES)
            self.assertEqual(lines, cr.LOG_LINES)
            self.assertTrue(box.get("end-2l linestart", "end-1c").rstrip("\n").endswith("line 1999"))
            self.assertIn("ok", box.tag_names("end-2l linestart"))
        finally:
            root.destroy()


def _overlay_app(enabled=False, page="Home", hidden=False):
    app = SimpleNamespace(overlay_cfg={"enabled": enabled, "items": {}}, current_page=page, overlay_win=None,
                          snap={"metrics": {}}, fps=mock.Mock(), after_calls=[], cancelled=[])
    app._hidden = lambda: hidden

    def after(ms, fn):
        app.after_calls.append(ms)
        return f"after#{len(app.after_calls)}"
    app.after = after
    app.after_cancel = app.cancelled.append
    app.game_tracker = mock.Mock()
    app.game_tracker.update.return_value = None
    app.overlay_preview = mock.Mock()
    app.overlay_preview_note = mock.Mock()
    app.overlay_status = mock.Mock()
    app._overlay_tick = lambda: cr.App._overlay_tick(app)
    return app


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class OverlayPollingOnlyWhenNeeded(unittest.TestCase):
    def setUp(self):
        self.fg = mock.patch.object(cr.fpo, "foreground_window", return_value=(0, 0))
        self.win_state = mock.patch.object(cr.fpo, "game_window_state", return_value=None)
        self.mon = mock.patch.object(cr.fpo, "monitor_rect", return_value=None)
        self.foreground = self.fg.start()
        self.game_state = self.win_state.start()
        self.monitor = self.mon.start()
        self.addCleanup(mock.patch.stopall)

    def test_disabled_on_another_page_makes_no_win32_calls(self):
        app = _overlay_app(enabled=False, page="Home")
        for _ in range(5):
            cr.App._overlay_tick(app)
        self.foreground.assert_not_called()
        self.game_state.assert_not_called()
        self.monitor.assert_not_called()
        app.overlay_preview.render.assert_not_called()
        self.assertEqual(app.after_calls, [cr.OVERLAY_IDLE_MS] * 5)

    def test_disabled_hides_an_overlay_left_on_screen(self):
        app = _overlay_app(enabled=False, page="Settings")
        app.overlay_win = mock.Mock()
        cr.App._overlay_tick(app)
        app.overlay_win.hide.assert_called_once()

    def test_enabling_brings_polling_back(self):
        app = _overlay_app(enabled=False, page="Home")
        cr.App._overlay_tick(app)
        self.foreground.assert_not_called()
        app.overlay_cfg["enabled"] = True
        cr.App._overlay_wake(app)
        self.assertEqual(app.cancelled, ["after#1"])            # the slow wait is dropped...
        self.assertEqual(app.after_calls[-1], 0)                # ...and the tick runs right away
        cr.App._overlay_tick(app)
        self.foreground.assert_called_once()
        app.game_tracker.update.assert_called_once()
        self.assertEqual(app.after_calls[-1], cr.OVERLAY_FAST_MS)
        cr.App._overlay_wake(app)                               # already fast: nothing to cancel
        self.assertEqual(app.cancelled, ["after#1"])

    def test_overlay_page_open_polls_and_draws_the_preview(self):
        app = _overlay_app(enabled=False, page="Overlay")
        cr.App._overlay_tick(app)
        self.foreground.assert_called_once()
        app.overlay_preview.render.assert_called_once()
        self.assertEqual(app.after_calls[-1], cr.OVERLAY_FAST_MS)

    def test_in_the_tray_follows_the_game_but_skips_the_preview(self):
        app = _overlay_app(enabled=True, page="Overlay", hidden=True)
        cr.App._overlay_tick(app)
        self.foreground.assert_called_once()
        app.game_tracker.update.assert_called_once()
        app.overlay_preview.render.assert_not_called()
        self.assertEqual(app.after_calls[-1], cr.OVERLAY_FAST_MS)

    def test_in_the_tray_with_overlay_off_does_nothing(self):
        app = _overlay_app(enabled=False, page="Overlay", hidden=True)
        cr.App._overlay_tick(app)
        self.foreground.assert_not_called()
        self.assertEqual(app.after_calls[-1], cr.OVERLAY_IDLE_MS)


@unittest.skipIf(cr is None, "needs tkinter/customtkinter")
class ClosingWritesSettings(unittest.TestCase):
    def _app(self, close_to_tray):
        settings = mock.MagicMock()
        settings.data = {"close_to_tray": close_to_tray, "tray_hint_shown": True}
        return SimpleNamespace(settings=settings, tray=mock.Mock(), withdraw=mock.Mock(),
                               _current_state=lambda: {"effect": "Static"}, _confirm_quit=mock.Mock())

    def test_close_to_tray_flushes(self):
        app = self._app(True)
        cr.App.on_close(app)
        app.withdraw.assert_called_once()
        app.settings.__setitem__.assert_called_with("state", {"effect": "Static"})
        app.settings.flush.assert_called()

    def test_close_to_quit_flushes(self):
        app = self._app(False)
        cr.App.on_close(app)
        app.settings.flush.assert_called()
        app._confirm_quit.assert_called_once()


def _app_check():
    """Build the real app on simulated hardware (as tests/harness.py does) and check the timers on it."""
    import json
    tmp = tempfile.mkdtemp(prefix="centralrgb-ui-timers-app-")
    os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = tmp
    (Path(tmp) / "CentralRGB").mkdir()
    (Path(tmp) / "CentralRGB" / "settings.json").write_text(json.dumps({"animations": False}))
    import fakes
    import rgb_engine as eng
    eng.OpenRGBClient = fakes.FakeClient
    eng.OpenRGBManager.server_running = staticmethod(lambda timeout=0.5: True)
    eng.OpenRGBManager.replace_visible_copy = lambda self: False
    import central_rgb as app_mod
    app_mod.App.TEST_BACKEND = fakes.FakeLHM()
    app = app_mod.App()
    failures = []

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            app.update()
            time.sleep(0.01)

    try:
        pump(2)
        for i in range(2000):
            app.log(f"check line {i}", "info")
        pump(3)
        lines = int(app.logbox.index("end-1c").split(".")[0]) - 1
        print(f"log box lines after 2000 log() calls: {lines} (cap {app_mod.LOG_LINES})")
        if lines > app_mod.LOG_LINES:
            failures.append(f"log box holds {lines} lines")

        app.overlay_cfg["enabled"] = False
        app.show_page("Home", animate=False)
        pump(1.5)                                     # let a tick already on the fast schedule finish
        real = app_mod.fpo.foreground_window
        calls = []
        app_mod.fpo.foreground_window = lambda: (calls.append(1), real())[1]
        pump(2.5)
        print(f"foreground_window calls with the overlay off: {len(calls)}")
        if calls:
            failures.append("overlay polled while off")
        app.overlay_cfg["enabled"] = True
        app._overlay_wake()
        pump(1.5)
        print(f"foreground_window calls with the overlay on: {len(calls)}")
        if len(calls) < 3:
            failures.append("overlay polling did not come back")
        app.overlay_cfg["enabled"] = False
    finally:
        app.engine.stop()
        app.monitor.stop()
        app.destroy()
    print("FAILED: " + "; ".join(failures) if failures else "PASSED")
    return 1 if failures else 0


@unittest.skipUnless(_gui_available(), "needs a display (run under xvfb-run) or CENTRALRGB_GUI_TESTS=1")
class RealAppTimers(unittest.TestCase):
    def test_real_app(self):
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()), APP_CHECK],
                           capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PASSED", r.stdout)


if __name__ == "__main__":
    if APP_CHECK in sys.argv:
        sys.exit(_app_check())
    unittest.main()
