# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""FPS overlay: reading PresentMon's output, picking the game, telling games from other apps (no counter over a
browser, Discord or a video player), and the status messages shown to the user.
Runs anywhere; PresentMon itself is replaced by fake CSV lines from fake_presentmon.py."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fps_overlay as fpo  # noqa: E402
import fake_presentmon as pm  # noqa: E402

OWN = 999999          # stands in for Central RGB's own pid
GAME, LAUNCHER, DISCORD, OTHER = 4100, 4000, 5200, 6100
RECT = (0, 0, 1920, 1080)


def counter_with(lines):
    c = fpo.FpsCounter(log=lambda *a, **k: None)
    c.read_stream(iter(lines), threading.Event())
    c.status = "running"
    return c


def tracker(counter, family=None, names=None, windows=None, clock=None):
    windows = windows if windows is not None else {}
    return fpo.GameTracker(counter, family=lambda pid: (family or {}).get(pid, set()),
                           window_state=lambda h: windows.get(h, RECT if h else None),
                           name_of=lambda pid: (names or {}).get(pid, ""), own_pid=OWN,
                           clock=clock or (lambda: 0.0), detector=detector())


class ReadStreamTests(unittest.TestCase):
    def test_presentmon_1_and_2_layouts(self):
        for v, header in ((1, pm.V1_HEADER), (2, pm.V2_HEADER)):
            c = counter_with(pm.stream(header, pm.game("THE FINALS.exe", GAME, 240, 300, v=v)))
            st = c.current(GAME)
            self.assertIsNotNone(st, v)
            self.assertAlmostEqual(st["fps"], 240, delta=1)
            self.assertEqual(st["name"], "THE FINALS.exe")

    def test_text_before_header_and_bad_values_are_ignored(self):
        rows = pm.game("RocketLeague.exe", GAME, 144, 50) + ["RocketLeague.exe,4100,0x1,DXGI,0,0,1,x,App,1,NA,1,1,1,NA"]
        c = counter_with(pm.stream(pm.V2_HEADER, rows, preamble=["warning: something", ""]))
        self.assertAlmostEqual(c.current(GAME)["fps"], 144, delta=1)
        self.assertIn("warning: something", list(c._pm_text))

    def test_extra_swap_chain_does_not_mix_into_the_number(self):
        rows = []
        for _ in range(240):
            rows.append(pm.v2_row("THE FINALS.exe", GAME, 1000 / 240, chain="0xGAME"))
        rows += [pm.v2_row("THE FINALS.exe", GAME, 1000 / 30, chain="0xSIDE") for _ in range(30)]
        c = counter_with(pm.stream(pm.V2_HEADER, rows))
        self.assertAlmostEqual(c.current(GAME)["fps"], 240, delta=1)
        self.assertEqual(c.presenting()[GAME][1], 240)

    def test_new_header_midstream_is_picked_up(self):
        lines = pm.stream(pm.V1_HEADER, pm.game("a.exe", 1, 60, 10, v=1)) + \
            pm.stream(pm.V2_HEADER, pm.game("b.exe", 2, 120, 10, v=2))
        c = counter_with(lines)
        self.assertIn(1, c.presenting())
        self.assertIn(2, c.presenting())

    def test_exclusive_mode_is_recorded(self):
        c = counter_with(pm.stream(pm.V1_HEADER, pm.game("old.exe", GAME, 60, 10, v=1, mode="Hardware: Legacy Flip")))
        self.assertTrue(c.exclusive(c.mode(GAME)))


class PickGameTests(unittest.TestCase):
    def test_foreground_game_is_picked(self):
        self.assertEqual(fpo.pick_game(GAME, "RocketLeague.exe", {GAME: ("RocketLeague.exe", 200)}, own_pid=OWN), GAME)

    def test_helpers_and_shell_are_never_picked(self):
        presenting = {DISCORD: ("Discord.exe", 60), 77: ("SteelSeriesGG.exe", 60), 78: ("dwm.exe", 240),
                      79: ("EasyAntiCheat_EOS.exe", 60)}
        for pid, (name, _n) in presenting.items():
            self.assertIsNone(fpo.pick_game(pid, name, presenting, own_pid=OWN), name)
        self.assertIsNone(fpo.pick_game(OWN, "Central RGB.exe", {OWN: ("Central RGB.exe", 60)}, own_pid=OWN))

    def test_launcher_window_resolves_to_drawing_child(self):
        presenting = {GAME: ("Discovery.exe", 240), OTHER: ("chrome.exe", 30)}
        got = fpo.pick_game(LAUNCHER, "start_protected_game.exe", presenting, related={GAME}, own_pid=OWN)
        self.assertEqual(got, GAME)

    def test_needs_a_few_frames(self):
        self.assertIsNone(fpo.pick_game(GAME, "x.exe", {GAME: ("x.exe", 1)}, own_pid=OWN))


class TrackerTests(unittest.TestCase):
    def test_follows_game_and_ignores_discord_in_front(self):
        lines = pm.stream(pm.V2_HEADER, pm.game("RocketLeague.exe", GAME, 240, 240) + pm.game("Discord.exe", DISCORD, 60, 60))
        t = tracker(counter_with(lines))
        st = t.update(1, GAME, True)
        self.assertEqual(st["pid"], GAME)
        self.assertTrue(st["in_front"])
        self.assertEqual(st["note"], "")
        self.assertIn("Tracking RocketLeague.exe", st["text"])
        st = t.update(2, DISCORD, False)               # alt-tab to Discord: stay on the game
        self.assertEqual(st["pid"], GAME)
        self.assertFalse(st["in_front"])

    def test_game_window_recreated_keeps_tracking(self):
        windows = {1: RECT, 3: RECT}
        c = counter_with(pm.stream(pm.V2_HEADER, pm.game("THE FINALS.exe", GAME, 200, 200)))
        t = tracker(c, windows=windows)
        t.update(1, GAME, True)
        windows[1] = None                              # old window destroyed (display mode change)
        st = t.update(3, GAME, True)
        self.assertEqual((st["pid"], st["hwnd"]), (GAME, 3))

    def test_launcher_owned_window(self):
        c = counter_with(pm.stream(pm.V2_HEADER, pm.game("Discovery.exe", GAME, 200, 200)))
        t = tracker(c, family={LAUNCHER: {GAME}}, names={LAUNCHER: "start_protected_game.exe"})
        st = t.update(1, LAUNCHER, True)
        self.assertEqual(st["pid"], GAME)
        self.assertTrue(st["in_front"])

    def test_no_frames_message_after_a_few_seconds(self):
        now = [0.0]
        c = counter_with(pm.stream(pm.V2_HEADER, []))
        t = tracker(c, names={GAME: "THE FINALS.exe"}, clock=lambda: now[0])
        self.assertEqual(t.update(1, GAME, True)["note"], "")
        now[0] = fpo.WAIT_SECS + 0.1
        st = t.update(1, GAME, True)
        self.assertEqual(st["note"], "No frames from this game yet")
        self.assertIn("THE FINALS.exe", st["text"])
        self.assertEqual(st["level"], "warn")
        self.assertEqual(t.update(1, GAME, False)["note"], "")      # not fullscreen: say nothing

    def test_exclusive_fullscreen_message(self):
        c = counter_with(pm.stream(pm.V1_HEADER, pm.game("old.exe", GAME, 60, 60, v=1, mode="Hardware: Legacy Flip")))
        st = tracker(c).update(1, GAME, True)
        self.assertEqual(st["note"], "Exclusive fullscreen hides overlays")
        self.assertIn("Borderless", st["text"])

    def test_counter_errors_reach_the_overlay(self):
        c = fpo.FpsCounter(log=lambda *a, **k: None)
        c.status, (c.kind, c.message) = "error", fpo.classify_pm_exit(pm.ACCESS_DENIED, 1)
        st = tracker(c).update(1, GAME, True)
        self.assertEqual((st["level"], st["note"]), ("bad", "PresentMon needs admin"))
        self.assertIn("administrator", st["text"])
        self.assertIsNone(st["pid"])


class StatusMessageTests(unittest.TestCase):
    def test_classify_presentmon_errors(self):
        self.assertEqual(fpo.classify_pm_exit(pm.ACCESS_DENIED, 1)[0], "admin")
        self.assertEqual(fpo.classify_pm_exit(pm.TOO_MANY, 1)[0], "sessions")
        kind, msg = fpo.classify_pm_exit("", 3221225477)
        self.assertEqual(kind, "crashed")
        self.assertIn("3221225477", msg)

    def test_classify_launch_errors(self):
        def err(code):
            e = OSError(code, "x")
            e.winerror = code
            return e
        self.assertEqual(fpo.classify_launch_error(err(193))[0], "corrupt")
        self.assertEqual(fpo.classify_launch_error(err(225))[0], "blocked")
        self.assertEqual(fpo.classify_launch_error(err(5))[0], "admin")

    def test_every_state_has_a_message(self):
        for status in ("starting", "restarting", "running"):
            self.assertTrue(fpo.status_text(status)[2])
        for kind in fpo.ERROR_SHORT:
            level, note, text = fpo.status_text("error", kind, "")
            self.assertEqual(level, "bad")
            self.assertEqual(note, fpo.ERROR_SHORT[kind])
            self.assertTrue(text)
        self.assertEqual(fpo.status_text("off"), ("off", "", "Off"))

    def test_covers_monitor(self):
        self.assertTrue(fpo.covers_monitor((1920, 0, 1920, 1080), (1920, 0, 1920, 1080)))
        self.assertFalse(fpo.covers_monitor((100, 100, 1280, 720), (0, 0, 1920, 1080)))
        self.assertFalse(fpo.covers_monitor("minimized", (0, 0, 1920, 1080)))


class LifecycleTests(unittest.TestCase):
    def test_stop_then_start_is_not_undone_by_the_late_stop(self):
        c = fpo.FpsCounter(log=lambda *a, **k: None)
        old = c._stop
        c._life.acquire()                  # a stop that is still closing the old session
        c.stop_async()
        self.assertTrue(old.is_set())
        c.start()                          # switched back on right away
        new = c._stop
        self.assertIsNot(new, old)
        c._life.release()
        c._thread.join(5)
        threading.Event().wait(0.2)        # let the late stop finish
        with c._life:
            pass
        self.assertFalse(new.is_set())     # the new run's flag was never touched by the old stop
        self.assertNotEqual(c.status, "off")   # and the late stop didn't report the new run as off


BROWSER, PLAYER, WINAPP = 7100, 7200, 7300
EXES = {GAME: r"D:\SteamLibrary\steamapps\common\rocketleague\Binaries\Win64\RocketLeague.exe",
        BROWSER: r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        PLAYER: r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        WINAPP: r"C:\Windows\System32\SomeTool.exe",
        OTHER: r"C:\Indie\MyGame.exe",
        LAUNCHER: r"C:\Program Files\Epic Games\Fortnite\FortniteLauncher.exe"}


def detector(known=()):
    return fpo.GameDetector(exe_of=lambda pid: EXES.get(pid, ""), known_games=lambda: {k.lower() for k in known})


class GameDetectionTests(unittest.TestCase):
    def test_everyday_apps_are_never_games(self):
        d = detector()
        for pid, name in ((BROWSER, "chrome.exe"), (PLAYER, "vlc.exe"), (DISCORD, "Discord.exe"),
                          (WINAPP, "SomeTool.exe"), (LAUNCHER, "FortniteLauncher.exe")):
            self.assertFalse(d.verdict(pid, name, fills_screen=True)[0], name)     # not even full screen

    def test_games_by_library_folder_windows_list_or_full_screen(self):
        self.assertEqual(detector().verdict(GAME, "RocketLeague.exe"), (True, "installed in a game library"))
        self.assertFalse(detector().verdict(OTHER, "MyGame.exe")[0])               # windowed, unknown: no
        self.assertEqual(detector().verdict(OTHER, "MyGame.exe", fills_screen=True), (True, "fills the screen"))
        self.assertEqual(detector(known=[EXES[OTHER]]).verdict(OTHER, "MyGame.exe"),
                         (True, "Windows lists it as a game"))
        self.assertTrue(detector().verdict(8800, "javaw.exe")[0])                  # Minecraft Java

    def test_windows_list_is_reread_now_and_then(self):
        calls, now = [], [0.0]
        d = fpo.GameDetector(exe_of=lambda pid: "", known_games=lambda: calls.append(1) or set(),
                             clock=lambda: now[0])
        d.known()
        d.known()
        now[0] += fpo.GameDetector.KNOWN_EVERY + 1
        d.known()
        self.assertEqual(len(calls), 2)

    def test_no_counter_over_a_browser_or_video(self):
        lines = pm.stream(pm.V2_HEADER, pm.game("chrome.exe", BROWSER, 144, 144) + pm.game("vlc.exe", PLAYER, 60, 60))
        t = tracker(counter_with(lines))
        t.detector = detector()
        for pid in (BROWSER, PLAYER):
            st = t.update(1, pid, True)                                            # even full screen
            self.assertIsNone(st["pid"])
            self.assertEqual(st["note"], "")                                       # and no "no frames" note
        st = t.update(1, BROWSER, True)
        self.assertNotIn("chrome", st["text"].lower())

    def test_game_is_still_picked_and_browser_in_front_keeps_it(self):
        lines = pm.stream(pm.V2_HEADER, pm.game("RocketLeague.exe", GAME, 240, 240) + pm.game("chrome.exe", BROWSER, 144, 144))
        t = tracker(counter_with(lines))
        t.detector = detector()
        self.assertEqual(t.update(1, GAME, False)["pid"], GAME)                    # windowed, from Steam
        st = t.update(2, BROWSER, True)                                            # alt-tab to the browser
        self.assertEqual(st["pid"], GAME)
        self.assertFalse(st["in_front"])

    def test_only_in_games_off_follows_any_app(self):
        lines = pm.stream(pm.V2_HEADER, pm.game("chrome.exe", BROWSER, 144, 144))
        t = tracker(counter_with(lines))
        t.detector = detector()
        t.games_only = False
        self.assertEqual(t.update(1, BROWSER, False)["pid"], BROWSER)

    def test_setting_defaults_to_games_only(self):
        self.assertTrue(fpo.DEFAULTS["games_only"])
        cfg = fpo.overlay_settings(type("S", (), {"data": {"overlay": {"enabled": True, "style": 2}}})())
        self.assertTrue(cfg["games_only"])                                         # older settings get it on


if __name__ == "__main__":
    unittest.main()
