# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Corsair Vengeance RGB PRO DDR4 (4x CMW32GX4M2D3600C18) on the owner's MSI B550-A PRO, which Windows lists
with the maker "Unknown" and OpenRGB didn't report:
  - the maker and product line come from the part number (and JEDEC maker codes)
  - only an OpenRGB 1.0 or newer is downloaded, and its version is known even when the folder doesn't say
  - OpenRGB RAM detectors switched off in OpenRGB.json are turned back on before OpenRGB starts
  - a "RAM diagnostics" report goes to activity.log and ram-diagnostics.txt
  - RAM that OpenRGB finds late (its SMBus scan still running) is still picked up, without a restart

Run from the repo root:  python -m unittest discover tests
"""
import json
import os
import queue
import sys
import tempfile
import time
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

PART = "CMW32GX4M2D3600C18"
WMI = fake_openrgb.CORSAIR_VENGEANCE_PRO_DDR4_WMI


class PartNumberTests(unittest.TestCase):
    def test_owners_sticks_are_corsair_vengeance_rgb_pro(self):
        self.assertEqual(eng.ram_label("Unknown " + PART), f"Corsair Vengeance RGB PRO ({PART})")
        self.assertEqual(eng.ram_line(PART), "Corsair Vengeance RGB PRO")
        self.assertEqual(eng.ram_maker("Unknown", PART), "Corsair")
        self.assertEqual(eng.ram_summary(WMI), f"4x Corsair Vengeance RGB PRO ({PART})")
        self.assertEqual(eng.rgb_ram_sticks(WMI), ["Corsair Vengeance RGB PRO"] * 4)

    def test_maker_from_jedec_code_or_part_number(self):
        for maker in ("029E", "0x029E", "9E00000000000000", "", "Unknown", "Undefined"):
            self.assertEqual(eng.ram_maker(maker, PART), "Corsair", maker)
        self.assertEqual(eng.ram_maker("CE00000000000000", "M378A2K43EB1-CWE"), "Samsung")
        self.assertEqual(eng.ram_maker("Kingston", "KF560C36BBEA-16"), "Kingston")
        self.assertEqual(eng.ram_maker("Unknown", "M378A2K43EB1-CWE"), "")

    def test_corsair_lines(self):
        self.assertEqual(eng.ram_line("CMK16GX4M2B3200C16"), "Corsair Vengeance LPX, no RGB")
        self.assertEqual(eng.ram_line("CMT32GX4M2C3600C18"), "Corsair Dominator Platinum RGB")
        self.assertEqual(eng.ram_line("CMH32GX5M2B5200C40"), "Corsair Vengeance RGB DDR5")
        self.assertEqual(eng.ram_line("CMG16GX4M2E3200C16"), "Corsair Vengeance RGB RS")
        self.assertEqual(eng.ram_line("CMR64GX4M4C3200C16"), "Corsair Vengeance RGB")
        self.assertEqual(eng.ram_label("Unknown"), "Unknown maker (Unknown)")   # nothing to go on: no crash
        self.assertEqual(eng.ram_label(""), "Unknown maker")
        # no-RGB Corsair sticks still aren't expected to light up
        self.assertEqual(eng.rgb_ram_sticks(["Unknown CMK16GX4M2B3200C16"]), [])

    def test_system_check_names_the_sticks(self):
        inv = {"board": "Micro-Star International Co., Ltd. B550-A PRO (MS-7C56)", "gpu": [], "ram": WMI,
               "mouse": [], "kbd": []}

        def run_quiet(cmd, timeout=20):
            if cmd[0] == "powershell":
                return SimpleNamespace(returncode=0, stdout=json.dumps(inv))
            return SimpleNamespace(returncode=0, stdout="")
        with mock.patch.object(eng, "IS_WIN", True), mock.patch.object(eng, "is_admin", lambda: True), \
                mock.patch.object(eng, "run_quiet", run_quiet), mock.patch.object(eng, "ddr5_installed", lambda: False):
            res = eng.system_check()
        line = next(m for _, m in res if m.startswith("RAM sticks"))
        self.assertEqual(line, f"RAM sticks: 4 (4x Corsair Vengeance RGB PRO ({PART}))")
        self.assertNotIn("Unknown", line)
        eng.RAM_INVENTORY.clear()


class OpenRGBVersionTests(unittest.TestCase):
    PAGE = ('<a href="https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_0.9/'
            'OpenRGB_0.9_Windows_64_b5f46e3.zip">0.9</a>'
            '<a href="https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_candidate_1.0rc2/'
            'OpenRGB_1.0rc2_Windows_64_0fca93e.zip">1.0rc2</a>'
            '<a href="https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_candidate_1.0rc1/'
            'OpenRGB_1.0rc1_Windows_64_1fbacde.zip">1.0rc1</a>')

    def test_newest_zip_is_picked_never_one_before_1_0(self):
        self.assertTrue(eng.pick_openrgb_zip(self.PAGE).endswith("OpenRGB_1.0rc2_Windows_64_0fca93e.zip"))
        only_old = '<a href="https://x/OpenRGB_0.9_Windows_64_b5f46e3.zip">'
        self.assertIsNone(eng.pick_openrgb_zip(only_old))
        self.assertIsNone(eng.pick_openrgb_zip(""))
        self.assertTrue(eng._version_key("1.0") > eng._version_key("1.0rc2") > eng._version_key("1.0rc1")
                        > eng._version_key("0.9"))

    def test_old_page_falls_back_to_known_link(self):
        m = eng.OpenRGBManager(SimpleNamespace(), lambda *a: None)
        page = mock.MagicMock()
        page.read.return_value = b'<a href="https://x/OpenRGB_0.9_Windows_64_b5f46e3.zip">'
        with mock.patch.object(eng.urllib.request, "urlopen", lambda *a, **k: page):
            self.assertEqual(m.latest_zip_url(), eng.FALLBACK_ZIP)

    def test_version_from_download_marker(self):
        d = Path(tempfile.mkdtemp()) / "OpenRGB Windows 64-bit"
        d.mkdir()
        exe = d / "OpenRGB.exe"
        exe.write_bytes(b"")
        self.assertIsNone(eng.openrgb_version(exe))           # the folder doesn't say
        (d / eng.OPENRGB_MARKER).write_text("OpenRGB_1.0rc2_Windows_64_0fca93e.zip\n", encoding="utf-8")
        self.assertEqual(eng.openrgb_version(exe), "1.0rc2")
        self.assertEqual(eng.openrgb_version(r"C:\x\OpenRGB_0.9_Windows_64_b5f46e3\OpenRGB.exe"), "0.9")


class DetectorTests(unittest.TestCase):
    def write_config(self, detectors):
        p = Path(tempfile.mkdtemp()) / "OpenRGB.json"
        p.write_text(json.dumps({"Detectors": {"detectors": detectors}, "Theme": {"theme": "dark"}}), encoding="utf-8")
        return p

    def test_switched_off_ram_detectors_are_turned_back_on(self):
        p = self.write_config({"Corsair Vengeance Pro": False, "Corsair Vengeance": True,
                               "Razer Huntsman V2 Tenkeyless": False})
        self.assertEqual(eng.ram_detector_settings([p])[1], {"Corsair Vengeance Pro": False, "Corsair Vengeance": True})
        self.assertEqual(eng.enable_ram_detectors([p]), ["Corsair Vengeance Pro"])
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertTrue(data["Detectors"]["detectors"]["Corsair Vengeance Pro"])
        self.assertFalse(data["Detectors"]["detectors"]["Razer Huntsman V2 Tenkeyless"])   # not a RAM detector
        self.assertEqual(data["Theme"], {"theme": "dark"})                                  # rest kept
        self.assertEqual(eng.enable_ram_detectors([p]), [])                                 # nothing left to do

    def test_missing_or_broken_config_is_left_alone(self):
        self.assertEqual(eng.enable_ram_detectors([Path(tempfile.mkdtemp()) / "OpenRGB.json"]), [])
        bad = Path(tempfile.mkdtemp()) / "OpenRGB.json"
        bad.write_text("{not json", encoding="utf-8")
        self.assertEqual(eng.enable_ram_detectors([bad]), [])
        self.assertEqual(bad.read_text(encoding="utf-8"), "{not json")

    def test_launch_turns_them_on_only_with_rgb_ram(self):
        cfg = Path(tempfile.mkdtemp())
        exe = cfg / "OpenRGB.exe"
        exe.write_bytes(b"")
        (cfg / "OpenRGB.json").write_text(json.dumps({"Detectors": {"detectors": {"Corsair Vengeance Pro": False}}}),
                                          encoding="utf-8")
        logs = []
        m = eng.OpenRGBManager(SimpleNamespace(), logs.append)
        proc = SimpleNamespace(poll=lambda: None)
        with mock.patch.object(eng.subprocess, "Popen", lambda *a, **k: proc), \
                mock.patch.object(eng, "openrgb_config_paths", lambda exe=None: [cfg / "OpenRGB.json"]), \
                mock.patch.object(eng.OpenRGBManager, "server_running", staticmethod(lambda timeout=0.5: True)):
            with mock.patch.object(eng, "RAM_INVENTORY", []):
                self.assertTrue(m.launch(exe))
            self.assertFalse(json.loads((cfg / "OpenRGB.json").read_text())["Detectors"]["detectors"]["Corsair Vengeance Pro"])
            with mock.patch.object(eng, "RAM_INVENTORY", list(WMI)):
                self.assertTrue(m.launch(exe))
        self.assertTrue(json.loads((cfg / "OpenRGB.json").read_text())["Detectors"]["detectors"]["Corsair Vengeance Pro"])
        self.assertTrue(any("Turned OpenRGB's RAM detectors back on" in x and "Corsair Vengeance Pro" in x for x in logs))


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.appdata = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"APPDATA": self.appdata})
        self.env.start()
        eng._last_ram_diag.clear()
        eng._last_ram_diag["text"] = ""
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PRO_PC, ram_blocked=True)

    def tearDown(self):
        self.env.stop()
        fake_openrgb.install(eng)
        eng.RAM_INVENTORY.clear()

    def found(self):
        return [eng.type_name(d) for d in eng.OpenRGBClient().devices]

    def owners_pc(self, **kw):
        folder = Path(tempfile.mkdtemp()) / "OpenRGB_1.0rc2_Windows_64_0fca93e"
        folder.mkdir()
        (folder / "OpenRGB.exe").write_bytes(b"")
        (folder / "SmbusPIIX4.bin").write_bytes(b"")
        (folder / "SmbusI801.bin").write_bytes(b"")
        logs = Path(self.appdata) / "OpenRGB" / "logs"
        logs.mkdir(parents=True)
        (logs / "OpenRGB_20261120_101500.log").write_text(
            "[ResourceManager] Starting detection\n"
            "Registering I2C interface: PawnIO PIIX4 port 0 at 0x0B00\n"
            "[Corsair Vengeance Pro] no device found at 0x58\n"
            "Razer Huntsman V2 Tenkeyless detected\n", encoding="utf-8")
        args = dict(rams=WMI, admin=True, pawnio=True, conflicts={"SteelSeries GG": [1], "SteelSeries Engine": [2]},
                    exe=str(folder / "OpenRGB.exe"), pid=4242, cmdline=[str(folder / "OpenRGB.exe"), "--server",
                                                                       "--noautoconnect"], cpu="AMD",
                    config_paths=[])
        args.update(kw)
        return eng.ram_diagnostics(self.found(), **args)

    def test_report_has_everything_needed(self):
        text = "\n".join(self.owners_pc())
        self.assertIn("OpenRGB: 1.0rc2", text)
        self.assertIn("by Central RGB (hidden, --server --noautoconnect)", text)
        self.assertIn("running as administrator: yes", text)                  # child of an elevated Central RGB
        self.assertIn("PawnIO driver installed: yes", text)
        self.assertIn("SmbusPIIX4.bin", text)
        self.assertIn("AMD (piix4 SMBus", text)
        self.assertIn("no OpenRGB.json yet", text)
        self.assertIn("Devices OpenRGB reported: Keyboard, Motherboard, Mouse", text)
        self.assertIn("Apps that use the RAM's SMBus running: none", text)
        self.assertIn("SteelSeries GG", text)                                  # listed, but not as an SMBus user
        self.assertIn(f'4x "Unknown {PART}" = Corsair Vengeance RGB PRO ({PART})', text)
        self.assertIn("PawnIO PIIX4 port 0", text)                            # OpenRGB's own SMBus lines
        self.assertIn("[Corsair Vengeance Pro] no device found at 0x58", text)
        self.assertNotIn("Razer Huntsman", text)                              # unrelated log lines left out

    def test_report_flags_old_openrgb_off_detectors_and_outside_start(self):
        cfg = Path(tempfile.mkdtemp()) / "OpenRGB.json"
        cfg.write_text(json.dumps({"Detectors": {"detectors": {"Corsair Vengeance Pro": False}}}), encoding="utf-8")
        text = "\n".join(self.owners_pc(openrgb_ver="0.9", started_by_central=False, elevated=False,
                                        cmdline=["OpenRGB.exe", "--startminimized"], config_paths=[cfg],
                                        conflicts={"MSI Center / Mystic Light": [9]}))
        self.assertIn("too old: uses WinRing0", text)
        self.assertIn("outside Central RGB (--startminimized)", text)
        self.assertIn("running as administrator: no", text)
        self.assertIn("Corsair Vengeance Pro OFF", text)
        self.assertIn("Apps that use the RAM's SMBus running: MSI Center / Mystic Light", text)

    def test_nothing_running_off_windows_says_unknown(self):
        with mock.patch.object(eng, "running_openrgb", lambda: (None, None, [])):
            text = "\n".join(eng.ram_diagnostics([], rams=WMI, admin=False, pawnio=False, conflicts={}, cpu=""))
        self.assertIn("OpenRGB started: not running; running as administrator: unknown", text)
        self.assertIn("OpenRGB log: none found", text)
        self.assertIn("Devices OpenRGB reported: none", text)

    def test_missing_ram_writes_the_report_to_activity_log_once(self):
        with mock.patch.object(eng, "running_openrgb", lambda: (None, None, [])):
            d = eng.diagnose_missing_ram(self.found(), rams=WMI, admin=True, pawnio=True, conflicts={}, ddr5=False)
            self.assertEqual(d["sticks"], 4)
            self.assertEqual(d["names"], "Corsair Vengeance RGB PRO")
            eng.diagnose_missing_ram(self.found(), rams=WMI, admin=True, pawnio=True, conflicts={}, ddr5=False)
        folder = Path(self.appdata) / "CentralRGB"
        log = (folder / "activity.log").read_text(encoding="utf-8")
        self.assertEqual(log.count("RAM diagnostics"), 1)                     # same report: written once
        self.assertIn(f"Corsair Vengeance RGB PRO ({PART})", log)
        saved = (folder / "ram-diagnostics.txt").read_text(encoding="utf-8")
        self.assertIn("RAM diagnostics", saved)
        self.assertIn("PawnIO driver installed: yes", saved)
        self.assertTrue(eng.last_ram_diagnostics())

    def test_found_ram_writes_no_report(self):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PRO_PC, ram_blocked=False)
        self.assertIsNone(eng.diagnose_missing_ram(self.found(), rams=WMI, admin=True, pawnio=True, conflicts={}))
        self.assertFalse((Path(self.appdata) / "CentralRGB" / "ram-diagnostics.txt").exists())


@unittest.skipIf(cr is None, "central_rgb could not be imported")
class LateRamTests(unittest.TestCase):
    """OpenRGB opens its SDK server before its SMBus scan is done: RAM found a few seconds later must still
    show up, by re-reading the device list, never by restarting OpenRGB."""

    def setUp(self):
        self.appdata = tempfile.mkdtemp()
        self.patches = [mock.patch.dict(os.environ, {"APPDATA": self.appdata}),
                        mock.patch.object(eng, "RAM_INVENTORY", list(WMI)),
                        mock.patch.object(eng, "MOUSE_INVENTORY", []),
                        mock.patch.object(eng, "is_admin", lambda: True),
                        mock.patch.object(eng, "pawnio_installed", lambda: True),
                        mock.patch.object(eng, "find_conflicts", lambda: {"SteelSeries GG": [1]}),
                        mock.patch.object(eng, "running_openrgb_exe", lambda: None),
                        mock.patch.object(eng, "running_openrgb", lambda: (None, None, []))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        fake_openrgb.install(eng)

    def settle(self, ram_late, ram_blocked=False):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PRO_PC, ram_late=ram_late, ram_blocked=ram_blocked)
        logs, restarts = [], []
        engine = eng.LightingEngine(lambda *a: None)
        self.assertTrue(engine.connect())
        app = SimpleNamespace(engine=engine, log=lambda m, level="info": logs.append((level, m)), q=queue.Queue(),
                              manager=SimpleNamespace(started_by_us=lambda: True, own_copies=lambda: []),
                              _full_rescan=lambda **k: restarts.append(1), _check_ram=lambda: None)
        app._rescan = lambda quiet=False, initial=False: engine.rescan()
        app._check_missing = lambda: cr.App._check_missing(app)
        real_sleep = time.sleep
        with mock.patch.object(cr.time, "sleep", lambda s: real_sleep(0.01)):
            cr.App._settle_devices(app, max_wait=3.0, quiet_for=0.3, min_wait=0.5)
        return engine, logs, restarts

    def test_ram_found_late_is_picked_up(self):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PRO_PC, ram_late=3)
        self.assertNotIn("RAM", [eng.type_name(d) for d in eng.OpenRGBClient().devices])   # not yet at first
        engine, logs, restarts = self.settle(ram_late=3)
        self.assertEqual([eng.type_name(d) for d in engine.devices()].count("RAM"), 4)
        self.assertTrue(any("OpenRGB found more hardware: 7 device(s)" in m for _, m in logs))
        self.assertFalse(any("RGB RAM not detected" in m for _, m in logs))
        self.assertEqual(restarts, [])

    def test_ram_never_found_is_reported_once_without_restart(self):
        engine, logs, restarts = self.settle(ram_late=0, ram_blocked=True)
        self.assertEqual(sum("RGB RAM not detected" in m for _, m in logs), 1)
        self.assertEqual(restarts, [])
        self.assertTrue((Path(self.appdata) / "CentralRGB" / "ram-diagnostics.txt").exists())


if __name__ == "__main__":
    unittest.main()
