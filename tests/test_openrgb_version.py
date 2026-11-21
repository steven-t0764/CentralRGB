# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
OpenRGB.exe leaves its Windows version info blank ("0.0.0.0"). That must read as "unknown", never as
"version 0.0.0, older than 1.0" (the owner's Devices page said exactly that for an OpenRGB 1.x).
  - a blank / all-zero exe version is unknown
  - PawnIO SMBus modules next to the exe mean OpenRGB 1.0 or newer (older versions never shipped them)
  - an OpenRGB Central RGB didn't install, with no known version, is named with its folder and what to do
  - Central RGB's own downloaded copy never gets that message

Run from the repo root:  python -m unittest discover tests
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())
os.environ.setdefault("LOCALAPPDATA", tempfile.mkdtemp())

import rgb_engine as eng  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_openrgb  # noqa: E402

STICKS = fake_openrgb.CORSAIR_VENGEANCE_PRO_DDR4_WMI     # the owner's 4x Corsair Vengeance RGB PRO DDR4
OK = dict(rams=STICKS, admin=True, pawnio=True, conflicts={}, ddr5=False)


def exe_in(folder: Path, modules=()) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "OpenRGB.exe").write_bytes(b"")
    for m in modules:
        (folder / m).write_bytes(b"")
    return str(folder / "OpenRGB.exe")


class BlankExeVersion(unittest.TestCase):
    def setUp(self):
        eng._file_versions.clear()
        self.tmp = Path(tempfile.mkdtemp())

    def version_with_file_info(self, info, modules=()):
        exe = exe_in(self.tmp / "OpenRGB", modules)            # folder name doesn't say the version
        with mock.patch.object(eng, "IS_WIN", True), \
                mock.patch.object(eng, "run_quiet", return_value=mock.Mock(stdout=info + "\n")):
            return eng.openrgb_version(exe)

    def test_all_zero_exe_version_is_unknown_not_old(self):
        v = self.version_with_file_info("0.0.0.0")
        self.assertIsNone(v)
        self.assertFalse(eng.openrgb_too_old(v))

    def test_real_exe_version_is_used(self):
        self.assertEqual(self.version_with_file_info("1.0.0"), "1.0.0")
        eng._file_versions.clear()
        self.assertEqual(self.version_with_file_info("0.9"), "0.9")

    def test_pawnio_modules_mean_1_0_or_newer(self):
        v = self.version_with_file_info("0.0.0.0", modules=("SmbusPIIX4.bin", "SmbusI801.bin"))
        self.assertEqual(v, eng.OPENRGB_1_PLUS)
        self.assertFalse(eng.openrgb_too_old(v))


class UnknownOpenRGBIsExplained(unittest.TestCase):
    def reasons(self, **kw):
        d = eng.diagnose_missing_ram(["Motherboard"], **{**OK, **kw})
        return " ".join(d["reasons"]) if d else ""

    def test_zero_version_no_longer_says_too_old(self):
        text = self.reasons(openrgb_ver=None)
        self.assertNotIn("version 0.0.0", text)
        self.assertNotIn("WinRing0", text)

    def test_outside_openrgb_with_unknown_version_names_its_folder(self):
        path = exe_in(Path(tempfile.mkdtemp()) / "Program Files" / "OpenRGB")
        text = self.reasons(openrgb_ver=None, openrgb_path=path)
        self.assertIn(path, text)
        self.assertIn("can't tell which version", text)
        self.assertIn("downloads OpenRGB 1.1 itself", text)

    def test_own_downloaded_copy_gets_no_such_message(self):
        path = exe_in(eng.install_dir() / "OpenRGB" / "OpenRGB Windows 64-bit")
        self.assertTrue(eng.is_own_openrgb(path))
        self.assertNotIn("didn't install", self.reasons(openrgb_ver=None, openrgb_path=path))

    def test_known_new_version_gets_no_such_message(self):
        path = exe_in(Path(tempfile.mkdtemp()) / "OpenRGB")
        self.assertNotIn("didn't install", self.reasons(openrgb_ver="1.1", openrgb_path=path))

    def test_old_version_is_still_called_out(self):
        self.assertIn("WinRing0", self.reasons(openrgb_ver="0.9"))

    def test_msi_mystic_light_is_still_named_as_the_blocker(self):
        text = self.reasons(conflicts={"MSI Mystic Light": [1]})
        self.assertIn("MSI Mystic Light", text)
        self.assertIn("Close them", text)


if __name__ == "__main__":
    unittest.main()
