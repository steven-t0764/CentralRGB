# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Settings writes are coalesced: a burst of changes (dragging a slider) writes settings.json once, a
short moment later on a background thread, instead of once per change on the UI thread.
flush() writes at once, and the file format and old files keep working.

Run from the repo root:  python -m unittest discover tests
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rgb_engine as eng  # noqa: E402


class SettingsSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"APPDATA": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.file = Path(self.tmp.name) / "CentralRGB" / "settings.json"
        self.writes = 0
        real = eng.Settings._write

        def counting(s):
            self.writes += 1
            real(s)
        p = mock.patch.object(eng.Settings, "_write", counting)
        p.start()
        self.addCleanup(p.stop)

    def new(self, delay=0.15):
        s = eng.Settings()
        s.SAVE_DELAY = delay
        self.addCleanup(s.flush)
        return s

    def wait_for_writes(self, n, timeout=3.0):
        end = time.monotonic() + timeout
        while self.writes < n and time.monotonic() < end:
            time.sleep(0.01)

    def test_many_rapid_sets_produce_one_write(self):
        s = self.new()
        for b in range(100):                       # a slider drag
            s["state"] = {"color": [255, 0, 0], "effect": "Static", "brightness": b, "speed": 50}
        self.assertEqual(self.writes, 0, "nothing should be written on the caller's thread")
        self.wait_for_writes(1)
        time.sleep(s.SAVE_DELAY * 2)               # and no second write trails behind
        self.assertEqual(self.writes, 1)
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["state"]["brightness"], 99)

    def test_write_happens_off_the_calling_thread(self):
        s = self.new()
        threads = []
        real = eng.Settings._write

        def where(obj):
            threads.append(threading.current_thread())
            real(obj)
        with mock.patch.object(eng.Settings, "_write", where):
            s["theme"] = "x"
            end = time.monotonic() + 3
            while not threads and time.monotonic() < end:
                time.sleep(0.01)
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.current_thread())

    def test_flush_writes_at_once_and_twice_is_safe(self):
        s = self.new(delay=60)                    # the timer would never fire during this test
        s["theme"] = "ember"
        self.assertEqual(self.writes, 0)
        s.flush()
        self.assertEqual(self.writes, 1)
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["theme"], "ember")
        s.flush()                                  # nothing pending: no second write
        self.assertEqual(self.writes, 1)
        self.assertIsNone(s._timer, "flush cancels the queued background write")

    def test_flush_is_registered_with_atexit(self):
        with mock.patch.object(eng.atexit, "register") as reg:
            s = eng.Settings()
        reg.assert_called_once_with(s.flush)

    def test_data_set_before_flush_survives_reload(self):
        s = self.new(delay=60)
        s["theme"] = "ember"
        s["excluded"] = ["dev|loc|serial"]
        s["profiles"] = dict(s["profiles"], Mine={"color": [1, 2, 3], "effect": "Breathing",
                                                  "brightness": 40, "speed": 10})
        s.flush()
        again = eng.Settings()
        self.assertEqual(again.data, s.data)

    def test_new_instance_sees_a_change_still_pending(self):
        s = self.new(delay=60)
        s["close_to_tray"] = False
        self.assertFalse(eng.Settings()["close_to_tray"])

    def test_boot_markers_are_written_straight_away(self):
        s = self.new(delay=60)
        s["openrgb_boot"] = 12345
        self.assertEqual(self.writes, 1)
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8"))["openrgb_boot"], 12345)

    def test_write_is_atomic_and_format_unchanged(self):
        s = self.new(delay=60)
        s["theme"] = "ember"
        s.flush()
        self.assertFalse(self.file.with_suffix(".tmp").exists())
        self.assertEqual(self.file.read_text(encoding="utf-8"), json.dumps(s.data, indent=2))

    def test_older_settings_files_still_load(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps({                 # an old file: few keys, an old effect name
            "state": {"color": [9, 8, 7], "effect": "Static", "brightness": 30, "speed": 20},
            "excluded": ["a|b|c"],
        }), encoding="utf-8")
        s = self.new()
        self.assertEqual(s["state"]["color"], [9, 8, 7])
        self.assertEqual(s["excluded"], ["a|b|c"])
        self.assertIn("profiles", s.data)                  # defaults fill the missing keys
        self.assertTrue(s["restore_on_start"])
        self.assertEqual(self.writes, 0, "loading alone doesn't rewrite the file")

    def test_old_effect_names_still_migrate(self):
        if not eng.RENAMED:
            self.skipTest("no renamed effects")
        old, new = next(iter(eng.RENAMED.items()))
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps({"state": {"color": [1, 1, 1], "effect": old,
                                                   "brightness": 100, "speed": 50}}), encoding="utf-8")
        self.assertEqual(self.new()["state"]["effect"], new)

    def test_concurrent_sets_never_break_the_file(self):
        s = self.new(delay=0.01)
        stop = time.monotonic() + 0.5

        def hammer(n):
            i = 0
            while time.monotonic() < stop:
                s[f"k{n}"] = {"i": i, "list": list(range(i % 50))}
                i += 1
        ts = [threading.Thread(target=hammer, args=(n,)) for n in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        s.flush()
        self.assertEqual(json.loads(self.file.read_text(encoding="utf-8")), s.data)


if __name__ == "__main__":
    unittest.main()
