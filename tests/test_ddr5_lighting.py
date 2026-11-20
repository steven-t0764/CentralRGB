# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
DDR5 RGB RAM lighting (a Kingston FURY Beast RGB DDR5 kit on an Intel Z790 board, fake_openrgb.Z790_DDR5_PC):
  - DDR5 RGB sticks are recognised from their part numbers and listed as RAM when OpenRGB reports them
  - effects reach them through OpenRGB: Direct for animations, one stick per tick at the RAM rate,
    their own Static / Breathing modes where they have them
  - the Devices page explains a kit that is blocked (admin, PawnIO, a vendor app), searched for twice
    this boot, or not supported (OpenRGB too old, or OpenRGB doesn't support the kit)
  - the DDR5 guard still allows only one hardware search per boot

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

from openrgb.utils import DeviceType, ModeColors  # noqa: E402

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

try:
    import central_rgb as cr
except Exception:  # pragma: no cover - needs tkinter/customtkinter
    cr = None

OK = dict(admin=True, pawnio=True, conflicts={}, openrgb_ver="1.0")


def ddr5_client(ram_blocked=False):
    fake_openrgb.install(eng, devices=fake_openrgb.Z790_DDR5_PC, ram_blocked=ram_blocked)
    return eng.OpenRGBClient()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Detection(unittest.TestCase):
    def tearDown(self):
        fake_openrgb.install(eng)

    def test_ddr5_part_numbers_are_recognised(self):
        self.assertEqual(eng.rgb_ram_sticks(fake_openrgb.KINGSTON_FURY_DDR5_WMI), ["Kingston FURY RGB"] * 2)
        known = {"Corsair CMH32GX5M2B6000C30": "Corsair Vengeance RGB DDR5",
                 "Corsair CMT32GX5M2B6000C30": "Corsair Dominator Platinum RGB",
                 "Corsair CMP32GX5M2B6000C30": "Corsair Dominator Titanium RGB",
                 "G.Skill F5-6000J3636F16GX2-TZ5RK": "G.Skill Trident Z5 RGB",
                 "G.Skill F5-6000J3038F16GX2-TZ5NR": "G.Skill Trident Z5 RGB",
                 "Kingston KF564C32RSA-16": "Kingston FURY RGB",
                 "TeamGroup FF3D532G6000HC38ADC01": "T-Force Delta RGB",
                 "ADATA AX5U6000C3016G-DCLARBK": "XPG Lancer RGB"}
        for part, name in known.items():
            self.assertEqual(eng.rgb_ram_sticks([part]), [name], part)
        # the same lines without lighting aren't expected to show up
        for plain in ("Kingston KF560C36BBE-16", "G.Skill F5-6000J3636F16GX2-TZ5K", "Corsair CMK32GX5M2B5600C36",
                      "ADATA AX5U5200C3816G-CLABK"):
            self.assertEqual(eng.rgb_ram_sticks([plain]), [], plain)

    def test_ddr5_sticks_are_listed_as_ram(self):
        types = [eng.type_name(d) for d in ddr5_client().devices]
        self.assertEqual(types.count("RAM"), 2)
        self.assertNotIn("RAM", [eng.type_name(d) for d in ddr5_client(ram_blocked=True).devices])

    def test_nothing_reported_when_found(self):
        found = [eng.type_name(d) for d in ddr5_client().devices]
        self.assertIsNone(eng.diagnose_missing_ram(found, rams=fake_openrgb.KINGSTON_FURY_DDR5_WMI,
                                                   ddr5=True, **OK))


class Effects(unittest.TestCase):
    """The detected DDR5 sticks get the same treatment as DDR4: through OpenRGB, on the RAM's own rate."""

    def setUp(self):
        self.clock = Clock()
        for p in (mock.patch.object(eng.time, "time", self.clock),
                  mock.patch.object(eng, "find_conflicts", lambda: {})):
            p.start()
            self.addCleanup(p.stop)
        self.devs = ddr5_client().devices
        self.sticks = [d for d in self.devs if d.type == DeviceType.DRAM]
        self.addCleanup(fake_openrgb.install, eng)

    def engine(self, **state):
        e = eng.LightingEngine(lambda *a, **k: None)
        e.client = mock.Mock(devices=self.devs)
        e.set_state(**state)
        return e

    def tick(self, e, n=1):
        for _ in range(n):
            e.step()
            e.frame += 1
            self.clock.t += 1 / e.FPS

    def test_animation_uses_direct_and_reaches_every_stick(self):
        e = self.engine(effect="Rainbow Wave", speed=100, brightness=100)
        self.tick(e, e.FPS)
        for s in self.sticks:
            self.assertEqual(s.modes[s.active_mode].name, "Direct")
            self.assertTrue(any(c != eng.RGBColor(0, 0, 0) for c in s.colors), s.name)

    def test_one_stick_per_tick_at_the_ram_rate(self):
        writes = {s.name: 0 for s in self.sticks}
        for s in self.sticks:
            orig = s._set_device_colors

            def counted(cols, fast=False, _o=orig, _n=s.name):
                writes[_n] += 1
                _o(cols, fast)
            s._set_device_colors = counted
        e = self.engine(effect="Rainbow Wave", speed=100)
        self.tick(e, e.FPS)
        for _ in range(e.FPS * 2):
            before = dict(writes)
            self.tick(e)
            self.assertLessEqual(sum(writes[k] - before[k] for k in writes), 1, "two sticks in one tick")
        for n in writes.values():
            self.assertLessEqual(n / 3, eng.DRAM_FPS + 0.5)

    def test_still_color_goes_into_the_sticks_static_mode(self):
        e = self.engine(effect="Static", color=[255, 0, 0], brightness=100)
        self.tick(e, e.FPS)
        for s in self.sticks:
            self.assertEqual(s.modes[s.active_mode].name, "Static")
            self.assertEqual(s.modes[s.active_mode].colors[0], eng.RGBColor(255, 0, 0))

    def test_breathing_runs_in_the_sticks_own_mode(self):
        e = self.engine(effect="Breathing", color=[0, 255, 0], brightness=100)
        self.tick(e, e.FPS)
        for s in self.sticks:
            m = s.modes[s.active_mode]
            self.assertEqual(m.name, "Breathing")
            self.assertEqual(m.color_mode, ModeColors.MODE_SPECIFIC)


class Messages(unittest.TestCase):
    """What the Devices page says when a DDR5 kit is blocked or unsupported."""
    RAMS = fake_openrgb.KINGSTON_FURY_DDR5_WMI

    def diag(self, **kw):
        args = dict(OK, rams=self.RAMS, ddr5=True)
        args.update(kw)
        return eng.diagnose_missing_ram(["Motherboard", "GPU"], **args)

    def test_blocked_by_a_vendor_app(self):
        d = self.diag(conflicts={"MSI Center / Mystic Light": [1]})
        self.assertEqual(d["title"], "DDR5 RGB RAM not detected")
        self.assertIn("2 DDR5 RGB RAM stick(s) installed (Kingston FURY RGB)", d["summary"])
        self.assertEqual(d["blockers"], ["MSI Center / Mystic Light"])
        self.assertTrue(any("MSI Center / Mystic Light is using the RAM's SMBus" in r for r in d["reasons"]))

    def test_blocked_by_admin_and_pawnio(self):
        d = self.diag(admin=False, pawnio=False)
        self.assertTrue(any("administrator" in r for r in d["reasons"]))
        self.assertTrue(any("PawnIO" in r for r in d["reasons"]))

    def test_searched_twice_this_boot_says_shut_down(self):
        d = self.diag(searched_before=True)
        text = " ".join(d["reasons"])
        self.assertIn("first search after the PC starts", text)
        self.assertIn("Shift", text)

    def test_old_openrgb_is_named_unsupported(self):
        d = self.diag(openrgb_ver="0.9")
        self.assertEqual(d["title"], "DDR5 RAM not supported by this OpenRGB")
        self.assertTrue(any("1.0 or newer" in r for r in d["reasons"]))

    def test_unsupported_kit_is_explained(self):
        d = self.diag()
        self.assertIn("doesn't support this DDR5 kit", d["reasons"][-1])
        self.assertIn("never writes to the RAM itself", d["reasons"][-1])

    def test_ddr4_wording_is_unchanged(self):
        d = eng.diagnose_missing_ram([], rams=fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI, ddr5=False, **OK)
        self.assertEqual(d["title"], "RGB RAM not detected")
        self.assertFalse(any("DDR5" in r for r in d["reasons"]))


@unittest.skipIf(cr is None, "central_rgb could not be imported")
class OneSearchPerBoot(unittest.TestCase):
    """The DDR5 guard (from test-ddr5) still lets OpenRGB search for hardware only once per boot."""

    def setUp(self):
        eng.RAM_INVENTORY[:] = fake_openrgb.KINGSTON_FURY_DDR5_WMI
        self.calls = []
        for p in (mock.patch.object(eng, "boot_id", lambda: 4242),
                  mock.patch.object(eng, "is_admin", lambda: True),
                  mock.patch.object(eng, "pawnio_installed", lambda: True),
                  mock.patch.object(eng, "find_conflicts", lambda: {}),
                  mock.patch.object(eng, "running_openrgb_exe", lambda: None),
                  mock.patch.object(eng, "MOUSE_INVENTORY", []),
                  mock.patch.object(cr.time, "sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(fake_openrgb.install, eng)
        self.addCleanup(eng.RAM_INVENTORY.clear)
        self.logs = []
        self.client = ddr5_client()
        manager = SimpleNamespace(started_by_us=lambda: True, own_copies=lambda: [],
                                  stop_own_copies=lambda: self.calls.append("stop"),
                                  launch=lambda exe: self.calls.append("launch") or True,
                                  find_exe=lambda: Path("OpenRGB.exe"), server_running=lambda: False)
        self.app = SimpleNamespace(
            engine=SimpleNamespace(devices=lambda: self.client.devices, client=object()),
            manager=manager, settings={"openrgb_boot": 0, "ram_seen": False, "ram_note_boot": 0},
            ddr5=True, _searched_before=False, background=True, q=queue.Queue(),
            log=lambda m, level="info": self.logs.append((level, m)),
            status=lambda *a, **k: None, _rescan=lambda *a, **k: self.calls.append("refresh"),
            _ask_on_main=lambda title, text: self.calls.append("asked") or False)
        for name in ("_ram_found", "engine_rows", "_note_hardware_search", "_ram_guard_allows_restart"):
            setattr(self.app, name, getattr(cr.App, name).__get__(self.app))

    def test_second_search_this_boot_is_noticed(self):
        self.app._note_hardware_search()
        self.assertFalse(self.app._searched_before)
        self.app._note_hardware_search()
        self.assertTrue(self.app._searched_before)

    def test_found_ram_is_never_searched_for_again_without_asking(self):
        cr.App._full_rescan_locked(self.app, "conflicts")      # after Close them: kept, no question
        cr.App._full_rescan_locked(self.app, "button")         # Rescan: asks, the answer is No
        self.assertEqual(self.calls, ["refresh", "asked", "refresh"])
        self.assertNotIn("launch", self.calls)
        self.assertNotIn("stop", self.calls)

    def test_missing_after_an_earlier_search_points_to_a_full_shutdown(self):
        self.client = ddr5_client(ram_blocked=True)
        self.app._note_hardware_search()
        self.app._note_hardware_search()                      # a second search this boot
        diags = cr.App._check_missing(self.app)
        self.assertEqual(diags[0]["title"], "DDR5 RGB RAM not detected")
        self.assertTrue(any("first search after the PC starts" in r for r in diags[0]["reasons"]))
        # the guard's own note says the same
        self.assertIn("already looked earlier this boot",
                      eng.ram_missing_note(True, False, self.app._searched_before, False))

    def test_ddr5_keeps_openrgb_running_on_close(self):
        self.assertTrue(eng.keep_openrgb_running(True))
        self.assertFalse(eng.keep_openrgb_running(False))


if __name__ == "__main__":
    unittest.main()
