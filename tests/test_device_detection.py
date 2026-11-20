# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Device detection on a PC like the owner's (MSI B550-A PRO, 4x Corsair Vengeance RGB DDR4, Razer Huntsman
V2 TKL, a SteelSeries mouse, with MSI Center / Mystic Light and SteelSeries GG running):
  - the RAM and the mouse are listed when OpenRGB reports them, and nothing OpenRGB reports is dropped
  - when they're missing, the Devices page names the program holding them and what to do
  - Close them really closes MSI's services and LEDKeeper2, then re-detects the hardware exactly once
  - a hidden OpenRGB left from an earlier session is restarted by Rescan; an old or self-started one is explained

Run from the repo root:  python -m unittest discover tests
"""
import os
import queue
import sys
import tempfile
import threading
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
from openrgb.utils import DeviceType  # noqa: E402

try:
    import central_rgb as cr
except Exception:  # pragma: no cover - needs tkinter/customtkinter
    cr = None

RAM_WMI = fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI
MICE_WMI = fake_openrgb.STEELSERIES_MOUSE_WMI + fake_openrgb.RAZER_KEYBOARD_POINTER_WMI
KBD_WMI = fake_openrgb.RAZER_KEYBOARD_WMI
OWNER_APPS = {"MSI Center / Mystic Light": [100], "MSI Mystic Light": [101], "SteelSeries GG": [102]}


def found_types(**blocked):
    fake_openrgb.install(eng, devices=fake_openrgb.B550_PC, **blocked)
    return [eng.type_name(d) for d in eng.OpenRGBClient().devices]


class _Inventory(unittest.TestCase):
    """What Windows reports on the owner's PC (system_check fills these on Windows)."""

    def setUp(self):
        self.patches = [mock.patch.object(eng, "RAM_INVENTORY", list(RAM_WMI)),
                        mock.patch.object(eng, "MOUSE_INVENTORY", list(MICE_WMI)),
                        mock.patch.object(eng, "KEYBOARD_INVENTORY", list(KBD_WMI))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        fake_openrgb.install(eng)


class DiagnosisTests(_Inventory):
    def test_mouse_is_recognised_but_not_the_keyboards_pointer(self):
        self.assertEqual(eng.rgb_mice(), [("SteelSeries", "1038", "1824")])
        # a plain office mouse isn't expected to light up
        self.assertEqual(eng.rgb_mice(["HID\\VID_045E&PID_0040\\1"], []), [])

    def test_nothing_reported_when_ram_and_mouse_are_found(self):
        types = found_types()
        self.assertEqual(types.count("RAM"), 4)
        self.assertEqual(types.count("Mouse"), 1)
        self.assertEqual(eng.diagnose_missing_devices(types, conflicts=OWNER_APPS, admin=True, pawnio=True), [])

    def test_blocked_by_mystic_light_and_steelseries_gg(self):
        diags = eng.diagnose_missing_devices(found_types(ram_blocked=True, mouse_blocked=True),
                                             conflicts=OWNER_APPS, admin=True, pawnio=True)
        ram, mouse = diags
        self.assertEqual(ram["kind"], "ram")
        self.assertEqual(ram["blockers"], ["MSI Center / Mystic Light", "MSI Mystic Light"])
        self.assertIn("MSI Center / Mystic Light", ram["reasons"][0])
        self.assertIn("Close them", ram["reasons"][0])
        self.assertEqual(mouse["kind"], "mouse")
        self.assertEqual(mouse["blockers"], ["SteelSeries GG"])
        self.assertIn("SteelSeries GG", mouse["reasons"][0])
        self.assertIn("Close them", mouse["reasons"][0])
        self.assertIn("1038:1824", mouse["summary"])

    def test_mouse_missing_without_a_blocker_points_to_openrgb_support(self):
        d = eng.diagnose_missing_mouse(found_types(mouse_blocked=True), conflicts={"Razer Synapse": [1]})
        self.assertEqual(d["blockers"], [])                      # Synapse doesn't drive a SteelSeries mouse
        self.assertEqual(len(d["reasons"]), 1)
        self.assertIn("openrgb.org/devices", d["reasons"][0])

    def test_self_started_and_old_openrgb_are_explained(self):
        d = eng.diagnose_missing_ram(found_types(ram_blocked=True), admin=True, pawnio=True, conflicts={},
                                     external_openrgb=True, openrgb_ver="0.9")
        text = " ".join(d["reasons"])
        self.assertIn("WinRing0", text)
        self.assertIn("started outside Central RGB", text)
        self.assertNotIn("Nothing obvious", text)
        self.assertEqual(eng.openrgb_version(r"C:\Users\s\AppData\Local\CentralRGB\OpenRGB"
                                             r"\OpenRGB_0.9_Windows_64_b5f46e3\OpenRGB.exe"), "0.9")
        self.assertIsNone(eng.openrgb_version(r"C:\Program Files\OpenRGB\OpenRGB.exe"))
        self.assertFalse(eng.openrgb_too_old("1.0rc2"))

    def test_off_windows_nothing_is_reported(self):
        with mock.patch.object(eng, "RAM_INVENTORY", []), mock.patch.object(eng, "MOUSE_INVENTORY", []):
            self.assertEqual(eng.diagnose_missing_devices(found_types(ram_blocked=True, mouse_blocked=True),
                                                          conflicts={}, admin=False, pawnio=False), [])


def _proc(name, exe="", pid=1):
    p = mock.Mock()
    p.info = {"name": name, "exe": exe}
    p.pid = pid
    return p


class CloseThemTests(unittest.TestCase):
    """eng.close_conflicts as it runs on Windows, with psutil and sc stood in for."""

    def run_close(self, procs, services, sc_ok=True):
        calls = []

        def run_quiet(cmd, timeout=20):
            calls.append(cmd)
            return SimpleNamespace(returncode=0 if sc_ok else 5, stdout="", stderr="")
        svcs = [mock.Mock(as_dict=mock.Mock(return_value=s)) for s in services]
        logs = []
        with mock.patch.object(eng, "IS_WIN", True), mock.patch.object(eng, "run_quiet", run_quiet), \
                mock.patch.object(eng.time, "sleep", lambda s: None), \
                mock.patch("psutil.win_service_iter", create=True, return_value=svcs), \
                mock.patch("psutil.process_iter", return_value=procs):
            done = eng.close_conflicts(logs.append)
        return done, calls, logs

    def test_msi_services_and_ledkeeper_are_stopped(self):
        base = "C:\\Program Files (x86)\\MSI\\MSI Center\\"
        procs = [_proc("LEDKeeper2.exe", base + "Mystic Light\\LEDKeeper2.exe"),
                 _proc("MSI.TerminalServer.exe", base + "MSI.TerminalServer.exe"),
                 _proc("explorer.exe", "C:\\Windows\\explorer.exe")]
        services = [{"name": "MSI_Central_Service", "display_name": "MSI Central Service", "start_type": "automatic",
                     "status": "running", "binpath": '"' + base + 'MSI.CentralServer.exe"'},
                    {"name": "MSI_Foundation_Service", "display_name": "MSI Foundation Service",
                     "start_type": "automatic", "status": "running", "binpath": '"' + base + 'MSI.TerminalServer.exe"'},
                    {"name": "Spooler", "start_type": "automatic", "status": "running",
                     "binpath": "C:\\Windows\\System32\\spoolsv.exe"}]
        done, calls, logs = self.run_close(procs, services)
        self.assertIn(["sc", "stop", "MSI_Central_Service"], calls)
        self.assertIn(["sc", "stop", "MSI_Foundation_Service"], calls)       # found by its MSI Center folder
        self.assertIn(["sc", "config", "MSI_Central_Service", "start=", "demand"], calls)
        self.assertNotIn(["sc", "stop", "Spooler"], calls)
        self.assertIn("Closed MSI Mystic Light (LEDKeeper2.exe)", done)
        self.assertIn("Closed MSI Center / Mystic Light (MSI.TerminalServer.exe)", done)
        procs[0].terminate.assert_called_once()
        procs[2].terminate.assert_not_called()
        self.assertEqual(logs, [])

    def test_failures_are_reported_not_hidden(self):
        led = _proc("LEDKeeper2.exe")
        led.terminate.side_effect = PermissionError("access denied")
        services = [{"name": "MSI_Central_Service", "display_name": "MSI Central Service", "start_type": "manual",
                     "status": "running", "binpath": "C:\\MSI\\MSI.CentralServer.exe"}]
        done, _, logs = self.run_close([led], services, sc_ok=False)
        self.assertEqual(done, [])
        self.assertTrue(any("Couldn't stop service 'MSI Central Service'" in m for m in logs))
        self.assertTrue(any("Couldn't close LEDKeeper2.exe" in m and "administrator" in m for m in logs))

    def test_find_conflicts_sees_msi_center_helpers_by_folder(self):
        procs = [_proc("MSI.NotifyServer.exe", "C:\\Program Files (x86)\\MSI\\MSI Center\\MSI.NotifyServer.exe", 7),
                 _proc("SteelSeriesGG.exe", "C:\\Program Files\\SteelSeries\\GG\\SteelSeriesGG.exe", 8)]
        with mock.patch("psutil.process_iter", return_value=procs):
            self.assertEqual(eng.find_conflicts(), {"MSI Center / Mystic Light": [7], "SteelSeries GG": [8]})

    def test_hidden_openrgb_from_an_earlier_session_is_ours(self):
        def p(exe, cmd):
            m = mock.Mock()
            m.info = {"name": "OpenRGB.exe", "exe": exe, "cmdline": cmd}
            return m
        hidden = p("C:\\Program Files\\OpenRGB\\OpenRGB.exe", ["OpenRGB.exe", "--server", "--noautoconnect"])
        users = p("C:\\Program Files\\OpenRGB\\OpenRGB.exe", ["OpenRGB.exe"])
        mgr = eng.OpenRGBManager(SimpleNamespace(), print)
        with mock.patch("psutil.process_iter", return_value=[hidden, users]):
            self.assertEqual(mgr.own_copies(), [hidden])


@unittest.skipIf(cr is None, "central_rgb could not be imported")
class AppDetectionTests(_Inventory):
    """The Devices page logic, run on a stand-in for the window (no screen needed)."""

    def setUp(self):
        super().setUp()
        self.conflicts = dict(OWNER_APPS)
        self.patches += [mock.patch.object(eng, "is_admin", lambda: True),
                         mock.patch.object(eng, "pawnio_installed", lambda: True),
                         mock.patch.object(eng, "running_openrgb_exe", lambda: None),
                         mock.patch.object(eng, "find_conflicts", lambda: dict(self.conflicts))]
        for p in self.patches[3:]:
            p.start()
        self.logs, self.rescans, self.statuses = [], [], []
        self.lighting = eng.LightingEngine(lambda *a: None)
        self.app = SimpleNamespace(
            engine=self.lighting, manager=SimpleNamespace(started_by_us=lambda: True, own_copies=lambda: []),
            log=lambda m, level="info": self.logs.append((level, m)), q=queue.Queue(), device_rows=[],
            status=lambda *a: self.statuses.append(a), conflict_btn=mock.Mock(),
            _update_conflict_bar=lambda found: None, _connect_flow=lambda: None,
            _full_rescan=lambda **k: self.rescans.append(k))

    def connect(self, **blocked):
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PC, **blocked)
        self.assertTrue(self.lighting.connect())

    def queued(self, kind):
        items = []
        while not self.app.q.empty():
            item = self.app.q.get_nowait()
            if item[0] == kind:
                items.append(item[1])
        return items

    def test_ram_and_mouse_are_listed(self):
        self.connect()
        cr.App._rescan(self.app, initial=True)
        rows = self.queued("devices")[-1]
        types = [r[1] for r in rows]
        self.assertEqual(types.count("RAM"), 4)
        self.assertIn(("Mouse", "SteelSeries Rival 3"), [(r[1], r[2]) for r in rows])
        self.assertEqual(cr.App._check_missing(self.app), [])

    def test_unknown_and_lightless_devices_are_not_dropped(self):
        odd = [("Some HID Gadget", DeviceType(9999), "Acme", [], ("Direct",)),
               ("Mouse Without Zones", DeviceType.MOUSE, "Acme", [], ("Direct",))]
        fake_openrgb.install(eng, devices=fake_openrgb.B550_PC + odd)
        self.assertTrue(self.lighting.connect())
        cr.App._rescan(self.app)
        rows = self.queued("devices")[-1]
        self.assertIn(("Other", "Some HID Gadget", 0), [(r[1], r[2], r[3]) for r in rows])
        self.assertIn(("Mouse", "Mouse Without Zones", 0), [(r[1], r[2], r[3]) for r in rows])
        self.assertEqual(len(rows), len(fake_openrgb.B550_PC) + 2)

    def test_devices_page_names_the_blocking_programs(self):
        self.connect(ram_blocked=True, mouse_blocked=True)
        diags = cr.App._check_missing(self.app)
        self.assertEqual(self.queued("missing"), [diags])
        title, body = cr.App._missing_texts(diags)
        self.assertEqual(title, "Not detected: RGB RAM, Mouse")
        self.assertIn("MSI Center / Mystic Light", body)
        self.assertIn("SteelSeries GG", body)
        self.assertIn("Close them", body)
        one_title, _ = cr.App._missing_texts(diags[1:])
        self.assertTrue(one_title.startswith("Mouse not detected: SteelSeries mouse connected"))
        self.assertEqual(self.rescans, [])                       # checking never starts a scan

    def test_rescan_happens_once_after_close_them(self):
        closed = []
        self.connect(ram_blocked=True, mouse_blocked=True)
        cr.App._check_missing(self.app)

        def close(log):
            closed.append(1)
            self.conflicts.clear()                               # the apps are gone
            return ["Closed MSI Mystic Light (LEDKeeper2.exe)", "Closed SteelSeries GG (SteelSeriesGG.exe)"]
        with mock.patch.object(eng, "close_conflicts", close), mock.patch.object(cr.time, "sleep", lambda s: None):
            cr.App._after_close_conflicts(self.app, settle=0)
            self.assertEqual(closed, [1])
            self.assertEqual(self.rescans, [{"wait": True, "why": "conflicts"}])     # exactly one re-detection, never skipped
            # that re-detection still missed them: the check after it reports, and doesn't scan again
            diags = cr.App._check_missing(self.app)
            self.assertEqual([d["blockers"] for d in diags], [[], []])
            cr.App._check_missing(self.app)
        self.assertEqual(self.rescans, [{"wait": True, "why": "conflicts"}])
        self.assertIn(("ok", "Closed SteelSeries GG (SteelSeriesGG.exe)"), self.logs)

    def test_app_left_running_is_named(self):
        with mock.patch.object(eng, "close_conflicts", lambda log: []), \
                mock.patch.object(eng, "wait_for_conflicts_gone", lambda: {"MSI Center / Mystic Light": [100]}), \
                mock.patch.object(cr.time, "sleep", lambda s: None):
            cr.App._after_close_conflicts(self.app, settle=0)
        self.assertTrue(any("Still running: MSI Center / Mystic Light" in m for lvl, m in self.logs if lvl == "warn"))
        self.assertEqual(len(self.rescans), 1)

    def test_rescan_after_close_them_waits_for_a_running_scan(self):
        app = SimpleNamespace(_rescan_lock=threading.Lock(), ran=[])
        app._full_rescan_locked = lambda why="button": app.ran.append(time.time())
        app._rescan_lock.acquire()
        threading.Timer(0.2, app._rescan_lock.release).start()
        cr.App._full_rescan(app)                                 # the Rescan button skips while one runs
        self.assertEqual(app.ran, [])
        cr.App._full_rescan(app, wait=True)                      # Close them waits for it instead
        self.assertEqual(len(app.ran), 1)


if __name__ == "__main__":
    unittest.main()
