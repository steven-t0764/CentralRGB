# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Fan-safety rules, checked against the simulated sensors:
  - fans never below 20 %, pumps never below 70 %
  - every fan to 100 % when the CPU or GPU reaches 90 °C
  - Auto hands fans to the BIOS, and stopping the monitor hands every fan back

Run from the repo root:  python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hw_monitor as hwm  # noqa: E402
from fake_lhm import FakeLHM  # noqa: E402

# The project's safety rules. Fixed here on purpose, so lowering them in hw_monitor.py fails the tests.
FAN_FLOOR, PUMP_FLOOR, EMERGENCY_TEMP = 20, 70, 90


class _Settings:
    def __init__(self):
        self.data = {}

    def __setitem__(self, k, v):
        self.data[k] = v


def _monitor(profile="Custom", curve=None, manual=None):
    m = hwm.HardwareMonitor(lambda *a, **k: None, _Settings(), backend=FakeLHM())
    m.backend.open()
    m.profile = profile
    if curve is not None:
        m.curve = curve
    if manual:
        m.manual = dict(manual)
    return m


def _targets(m, cpu=60.0, gpu=55.0, ticks=1):
    m.backend.cpu_temp, m.backend.gpu_temp = cpu, gpu
    for _ in range(ticks):
        m._tick()
    return {f["name"]: f["target"] for f in m.fans.values()}


class FanSafety(unittest.TestCase):
    def test_floors(self):
        m = _monitor(curve=[(0, 0), (100, 0)])          # a curve that asks for 0 % everywhere
        for name, t in _targets(m, cpu=30, gpu=30, ticks=40).items():
            floor = PUMP_FLOOR if "pump" in name.lower() else FAN_FLOOR
            self.assertGreaterEqual(t, floor, name)

    def test_manual_below_floor_is_raised(self):
        m = _monitor()
        m._tick()
        pump = next(fid for fid, f in m.fans.items() if "pump" in f["name"].lower())
        fan = next(fid for fid, f in m.fans.items() if "pump" not in f["name"].lower())
        m.manual = {pump: 10.0, fan: 5.0}
        m._tick()
        self.assertGreaterEqual(m.fans[pump]["target"], PUMP_FLOOR)
        self.assertGreaterEqual(m.fans[fan]["target"], FAN_FLOOR)

    def test_emergency_cpu(self):
        m = _monitor(profile="Silent")
        for name, t in _targets(m, cpu=EMERGENCY_TEMP, gpu=50).items():
            self.assertEqual(t, 100.0, name)

    def test_emergency_gpu_overrides_manual(self):
        m = _monitor()
        m._tick()
        m.manual = {fid: 30.0 for fid in m.fans}
        for name, t in _targets(m, cpu=50, gpu=EMERGENCY_TEMP + 3).items():
            self.assertEqual(t, 100.0, name)

    def test_auto_leaves_fans_to_bios(self):
        m = _monitor(profile="Balanced")
        _targets(m)
        self.assertTrue(m.backend.software)
        m.profile = "Auto"
        _targets(m)
        self.assertFalse(m.backend.software, "Auto should hand every fan back to the BIOS")

    def test_stop_hands_fans_back(self):
        m = _monitor(profile="Performance")
        _targets(m)
        self.assertTrue(m.backend.software)
        m._restore_all()
        self.assertFalse(m.backend.software, "closing should hand every fan back to the BIOS")


if __name__ == "__main__":
    unittest.main()
