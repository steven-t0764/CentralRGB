# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
RGB RAM that Windows reports but OpenRGB doesn't find (Corsair Vengeance RGB DDR4 on an MSI B550 board):
  - the sticks are recognised from their part numbers
  - the app says exactly why (not admin, no PawnIO, Mystic Light / another app holding the SMBus)
  - after Close them, RAM detection is retried once, never in a loop

Run from the repo root:  python -m unittest discover tests
"""
import os
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

try:
    import central_rgb as cr
except Exception:  # pragma: no cover - needs tkinter/customtkinter
    cr = None

MSI = {"MSI Center / Mystic Light": [100], "MSI Mystic Light": [101]}


def found_types(ram_blocked):
    fake_openrgb.install(eng, devices=fake_openrgb.B550_PC, ram_blocked=ram_blocked)
    return [eng.type_name(d) for d in eng.OpenRGBClient().devices]


class RamDetectTests(unittest.TestCase):
    def tearDown(self):
        fake_openrgb.install(eng)              # back to the normal demo devices
        eng.RAM_INVENTORY.clear()

    def test_vengeance_ddr4_is_recognised(self):
        self.assertEqual(eng.rgb_ram_sticks(fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI), ["Corsair Vengeance RGB"] * 4)
        # Vengeance LPX (no lighting) and unknown sticks aren't expected to show up
        self.assertEqual(eng.rgb_ram_sticks(["Corsair CMK16GX4M2B3200C16", "Samsung M378A2K43EB1-CWE", ""]), [])

    def test_fake_device_is_a_ram_stick(self):
        types = found_types(ram_blocked=False)
        self.assertEqual(types.count("RAM"), 4)
        self.assertNotIn("RAM", found_types(ram_blocked=True))

    def test_nothing_reported_when_ram_is_found(self):
        self.assertIsNone(eng.diagnose_missing_ram(found_types(False), fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI,
                                                   admin=True, pawnio=True, conflicts=MSI))
        # no RGB RAM installed: nothing to miss
        self.assertIsNone(eng.diagnose_missing_ram(found_types(True), ["Corsair CMK16GX4M2B3200C16"],
                                                   admin=True, pawnio=True, conflicts={}))

    def test_mystic_light_holding_the_bus_is_named(self):
        conflicts = dict(MSI, **{"SteelSeries GG": [102], "Razer Synapse": [103]})
        d = eng.diagnose_missing_ram(found_types(True), fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI,
                                     admin=True, pawnio=True, conflicts=conflicts)
        self.assertEqual(d["sticks"], 4)
        self.assertEqual(d["blockers"], ["MSI Center / Mystic Light", "MSI Mystic Light"])
        self.assertEqual(len(d["reasons"]), 1)
        self.assertIn("Close them", d["reasons"][0])
        self.assertIn("Corsair Vengeance RGB", d["summary"])

    def test_admin_and_pawnio_reasons(self):
        d = eng.diagnose_missing_ram(found_types(True), fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI,
                                     admin=False, pawnio=False, conflicts={})
        text = " ".join(d["reasons"])
        self.assertIn("administrator", text)
        self.assertIn("PawnIO", text)
        self.assertEqual(d["blockers"], [])

    def test_unknown_cause_still_explained(self):
        d = eng.diagnose_missing_ram(found_types(True), fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI,
                                     admin=True, pawnio=True, conflicts={"SteelSeries GG": [1]})
        self.assertEqual(len(d["reasons"]), 1)
        self.assertIn("Restart Windows", d["reasons"][0])

    def test_inventory_from_system_check_is_used(self):
        eng.RAM_INVENTORY[:] = fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI
        d = eng.diagnose_missing_ram(found_types(True), admin=True, pawnio=True, conflicts={})
        self.assertEqual(d["sticks"], 4)


@unittest.skipIf(cr is None, "central_rgb could not be imported")
class RamRetryTests(unittest.TestCase):
    """App._check_ram, run on a stand-in for the window (no screen needed)."""

    def setUp(self):
        eng.RAM_INVENTORY[:] = fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI
        self.conflicts = dict(MSI)
        self.patches = [mock.patch.object(eng, "is_admin", lambda: True),
                        mock.patch.object(eng, "pawnio_installed", lambda: True),
                        mock.patch.object(eng, "find_conflicts", lambda: dict(self.conflicts)),
                        mock.patch.object(cr.time, "sleep", lambda s: None)]
        for p in self.patches:
            p.start()
        self.logs, self.rescans = [], []
        self.app = SimpleNamespace(engine=SimpleNamespace(devices=lambda: eng.OpenRGBClient().devices),
                                   log=lambda m, level="info": self.logs.append((level, m)), q=queue.Queue(),
                                   _full_rescan=lambda: self.rescans.append(1))

    def tearDown(self):
        for p in self.patches:
            p.stop()
        fake_openrgb.install(eng)
        eng.RAM_INVENTORY.clear()

    def check(self, ram_blocked):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PC, ram_blocked=ram_blocked)
        return cr.App._check_ram(self.app)

    def test_blocked_ram_is_reported_without_restarting(self):
        d = self.check(ram_blocked=True)
        self.assertEqual(d["blockers"], ["MSI Center / Mystic Light", "MSI Mystic Light"])
        self.assertEqual(self.rescans, [])               # Mystic Light still holds the bus: don't retry
        self.assertEqual(self.app.q.get_nowait(), ("ram", d))
        self.assertTrue(any("RGB RAM not detected" in m for lvl, m in self.logs if lvl == "warn"))
        self.check(ram_blocked=True)                     # same result again: no repeated warning
        self.assertEqual(sum("RGB RAM not detected" in m for _, m in self.logs), 1)

    def test_retry_once_after_close_them(self):
        self.check(ram_blocked=True)
        self.conflicts.clear()                           # Close them closed Mystic Light ...
        self.app._ram_retry = True                       # ... and armed one retry
        self.check(ram_blocked=True)                     # first pass after closing still missed the RAM
        self.assertEqual(self.rescans, [1])
        self.check(ram_blocked=True)                     # the retry missed it too: stop, no loop
        self.check(ram_blocked=True)
        self.assertEqual(self.rescans, [1])

    def test_found_after_retry_clears_the_warning(self):
        self.check(ram_blocked=True)
        self.conflicts.clear()
        self.app._ram_retry = True
        self.assertIsNone(self.check(ram_blocked=False))
        self.assertEqual(self.rescans, [])
        self.assertFalse(self.app._ram_retry)
        self.assertIn(("ok", "RGB RAM detected."), self.logs)


if __name__ == "__main__":
    unittest.main()
