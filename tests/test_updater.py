# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""One-click updater (updater.py) against a fake GitHub API: no network is used."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import updater as upd  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402


class VersionOrder(unittest.TestCase):
    def test_numeric_not_text_order(self):
        self.assertTrue(upd.is_newer("v2.10.0", "2.9.9"))
        self.assertTrue(upd.is_newer("2.3.10", "2.3.9"))
        self.assertFalse(upd.is_newer("v2.3.2", "2.3.2"))
        self.assertFalse(upd.is_newer("v2.3.1", "2.3.2"))
        self.assertFalse(upd.is_newer("2.3", "2.3.0"))
        self.assertTrue(upd.is_newer("3", "2.99.99"))

    def test_suffix_sorts_before_release(self):
        self.assertLess(upd.parse_version("2.4.0-beta"), upd.parse_version("2.4.0"))
        self.assertTrue(upd.is_newer("2.4.0-beta", "2.3.2"))

    def test_garbage_is_never_newer(self):
        self.assertFalse(upd.is_newer("test-build", "2.3.2"))
        self.assertFalse(upd.is_newer("", "2.3.2"))


class LatestRelease(unittest.TestCase):
    def test_skips_drafts_prereleases_and_test_builds(self):
        gh = FakeGitHub()
        rel = upd.latest_release(gh)
        self.assertEqual(rel.tag, "v2.9.0")          # not v4.0.0 (draft), v3.0.0-beta or test-build

    def test_check_reports_newer(self):
        res = upd.check("2.3.2", opener=FakeGitHub())
        self.assertTrue(res.newer)
        self.assertIn("2.9.0", res.message)
        self.assertFalse(upd.check("2.9.0", opener=FakeGitHub()).newer)
        self.assertFalse(upd.check("3.1.0", opener=FakeGitHub()).newer)

    def test_only_prereleases_means_nothing_new(self):
        gh = FakeGitHub()
        gh.releases = [r for r in gh.releases if r["prerelease"] or r["draft"]]
        res = upd.check("2.3.2", opener=gh)
        self.assertIsNone(res.latest)
        self.assertFalse(res.newer)

    def test_offline_is_a_clear_message(self):
        gh = FakeGitHub()
        gh.offline = True
        with self.assertRaises(upd.UpdateError) as cm:
            upd.check("2.3.2", opener=gh)
        self.assertIn("offline", str(cm.exception))

    def test_rate_limit_is_a_clear_message(self):
        gh = FakeGitHub()
        gh.rate_limited = True
        with self.assertRaises(upd.UpdateError) as cm:
            upd.check("2.3.2", opener=gh)
        self.assertIn("limit", str(cm.exception))


class PickAsset(unittest.TestCase):
    def setUp(self):
        self.rel = upd.latest_release(FakeGitHub())

    def test_installed_gets_installer_portable_gets_exe(self):
        self.assertEqual(upd.pick_asset(self.rel, "installed")[0], "CentralRGB-Setup.exe")
        self.assertEqual(upd.pick_asset(self.rel, "portable")[0], "Central.RGB.exe")

    def test_source_cannot_self_update(self):
        with self.assertRaises(upd.UpdateError):
            upd.pick_asset(self.rel, "source")

    def test_install_kind(self):
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "Central RGB.exe"
            exe.write_bytes(b"")
            self.assertEqual(upd.install_kind(str(exe), frozen=False), "source")
            self.assertEqual(upd.install_kind(str(exe), frozen=True, meipass=str(Path(d) / "_MEI12345")), "portable")
            self.assertEqual(upd.install_kind(str(exe), frozen=True, meipass=str(Path(d) / "_internal"),
                                              registry_dir=None), "portable")
            self.assertEqual(upd.install_kind(str(exe), frozen=True, meipass=str(Path(d) / "_internal"),
                                              registry_dir=Path(d)), "installed")
            (Path(d) / "unins000.exe").write_bytes(b"")
            self.assertEqual(upd.install_kind(str(exe), frozen=True, meipass=str(Path(d) / "_internal"),
                                              registry_dir=None), "installed")


class Download(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_verified_download_with_progress(self):
        gh = FakeGitHub()
        rel = upd.latest_release(gh)
        seen = []
        path = upd.download(rel, "installed", self.dir, lambda d, t: seen.append((d, t)), opener=gh)
        self.assertEqual(path.read_bytes(), gh.files["CentralRGB-Setup.exe"])
        self.assertTrue(seen and seen[-1][0] == seen[-1][1] == len(gh.files["CentralRGB-Setup.exe"]))
        path = upd.download(rel, "portable", self.dir, opener=gh)
        self.assertEqual(path.name, "Central RGB.exe.new")

    def test_checksum_mismatch_is_refused_and_deleted(self):
        gh = FakeGitHub()
        rel = upd.latest_release(gh)
        gh.files["CentralRGB-Setup.exe"] = b"tampered" * 10
        gh.sums_override = "0" * 64 + "  CentralRGB-Setup.exe\n"
        with self.assertRaises(upd.UpdateError) as cm:
            upd.download(rel, "installed", self.dir, opener=gh)
        self.assertIn("doesn't match", str(cm.exception))
        self.assertEqual(list(self.dir.iterdir()), [])            # nothing left behind to run

    def test_missing_checksum_is_refused(self):
        gh = FakeGitHub()
        rel = upd.latest_release(gh)
        rel.assets.pop("SHA256SUMS.txt")
        with self.assertRaises(upd.UpdateError) as cm:
            upd.download(rel, "portable", self.dir, opener=gh)
        self.assertIn("checksum", str(cm.exception))
        gh.sums_override = ""
        rel = upd.latest_release(gh)
        with self.assertRaises(upd.UpdateError):
            upd.download(rel, "portable", self.dir, opener=gh)

    def test_offline_during_download(self):
        gh = FakeGitHub()
        rel = upd.latest_release(gh)
        gh.offline = True
        with self.assertRaises(upd.UpdateError):
            upd.download(rel, "installed", self.dir, opener=gh)

    def test_checksum_file_formats(self):
        h = "ab" * 32
        sums = upd.parse_checksums(f"{h}  Central RGB.exe\n{h.upper()} *CentralRGB-Setup.exe\nnot a line\n")
        self.assertEqual(sums["central.rgb.exe"], h)
        self.assertEqual(sums["centralrgb-setup.exe"], h)


class Apply(unittest.TestCase):
    def test_helper_waits_for_app_then_runs_installer_silently(self):
        script = upd.helper_script("installed", 4321, Path("C:/Temp/CentralRGB-Setup-update.exe"), "C:/x/Central RGB.exe")
        self.assertTrue(script.startswith("Wait-Process -Id 4321"))
        for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/RELAUNCH=1"):
            self.assertIn(flag, script)

    def test_portable_swap_and_relaunch(self):
        script = upd.helper_script("portable", 99, Path("C:/x/Central RGB.exe.new"), "C:/x/it's/Central RGB.exe")
        self.assertTrue(script.startswith("Wait-Process -Id 99"))
        self.assertIn("it''s", script)                           # quotes in paths are escaped
        self.assertIn("Move-Item", script)
        self.assertIn("Start-Process", script)

    @unittest.skipIf(os.name == "nt", "checks the non-Windows behaviour")
    def test_apply_fails_quietly_off_windows(self):
        with self.assertRaises(upd.UpdateError):
            upd.start_apply("installed", Path("x.exe"))

    def test_installer_supports_relaunch(self):
        iss = (HERE.parent / "central_rgb.iss").read_text(encoding="utf-8")
        self.assertIn("RelaunchAfterUpdate", iss)
        self.assertIn("{param:RELAUNCH|0}", iss)

    def test_release_workflow_publishes_checksums(self):
        wf = (HERE.parent / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
        self.assertIn("SHA256SUMS.txt", wf)
        self.assertIn("installer/*.exe", wf)                     # the stable latest-download names stay


class AutoCheckSetting(unittest.TestCase):
    def test_default_on_and_once_a_day(self):
        now = time.time()
        self.assertTrue(upd.should_auto_check({}, now))                         # older settings: on
        self.assertFalse(upd.should_auto_check({upd.AUTO_KEY: False}, now))
        self.assertFalse(upd.should_auto_check({upd.LAST_KEY: now - 3600}, now))
        self.assertTrue(upd.should_auto_check({upd.LAST_KEY: now - 25 * 3600}, now))
        self.assertTrue(upd.should_auto_check({upd.LAST_KEY: "garbage"}, now))

    def test_old_settings_file_still_loads_and_toggle_saves(self):
        import rgb_engine as eng
        with tempfile.TemporaryDirectory() as d:
            old_env = os.environ.get("APPDATA")
            os.environ["APPDATA"] = d
            try:
                (Path(d) / "CentralRGB").mkdir()
                (Path(d) / "CentralRGB" / "settings.json").write_text(json.dumps(
                    {"state": {"effect": "Static", "color": [1, 2, 3], "brightness": 50, "speed": 50}}))
                s = eng.Settings()
                self.assertEqual(s["state"]["brightness"], 50)
                self.assertTrue(upd.auto_check_enabled(s.data))
                s[upd.AUTO_KEY] = False
                self.assertFalse(upd.auto_check_enabled(eng.Settings().data))
            finally:
                if old_env is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = old_env


if __name__ == "__main__":
    unittest.main()
