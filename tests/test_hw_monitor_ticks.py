# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Monitor tick cost: slow extras (process count, CPU clock, disk usage) refresh on a slower cadence,
while the live readings stay per tick, and snapshot() keeps its shape.

Run from the repo root:  python -m unittest discover tests
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import hw_monitor as hwm  # noqa: E402


class FakeSettings(dict):
    def __init__(self):
        super().__init__()
        self.data = {}


def fake_psutil(clock):
    p = mock.MagicMock()
    p.cpu_percent.side_effect = lambda interval=None, percpu=False: [10.0, 20.0] if percpu else 15.0
    p.virtual_memory.return_value = SimpleNamespace(used=4 * 2**30, total=16 * 2**30, percent=25.0)
    p.cpu_freq.return_value = SimpleNamespace(current=3600.0)
    p.net_io_counters.return_value = SimpleNamespace(bytes_recv=1000, bytes_sent=500)
    p.disk_io_counters.return_value = SimpleNamespace(read_bytes=10, write_bytes=20)
    p.disk_partitions.return_value = [SimpleNamespace(mountpoint="C:\\", opts="rw", fstype="NTFS")]
    p.disk_usage.return_value = SimpleNamespace(total=100 * 2**30, used=40 * 2**30, percent=40.0)
    p.boot_time.return_value = 0.0
    p.pids.return_value = list(range(123))
    return p


class TickCostTests(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.ps = fake_psutil(self.now)
        for patcher in (mock.patch.object(hwm, "psutil", self.ps),
                        mock.patch.object(hwm.time, "time", lambda: self.now[0])):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.mon = hwm.HardwareMonitor(lambda *_: None, FakeSettings(), backend=None)

    def tick(self, n, step=1.0):
        for _ in range(n):
            self.mon._tick()
            self.now[0] += step

    def test_pids_only_once_per_slow_interval(self):
        self.tick(5)                       # t = 0..4 s
        self.assertEqual(self.ps.pids.call_count, 1)
        self.tick(5)                       # t = 5..9 s
        self.assertEqual(self.ps.pids.call_count, 2)
        self.assertLessEqual(self.ps.cpu_freq.call_count, 2)
        self.assertLessEqual(self.ps.disk_usage.call_count, 2)

    def test_last_slow_value_is_reused_between_refreshes(self):
        self.tick(1)
        self.ps.pids.return_value = list(range(500))
        self.tick(2)
        self.assertEqual(self.mon.snapshot()["metrics"]["procs"], 123)
        self.tick(3)                       # crosses the slow interval
        self.assertEqual(self.mon.snapshot()["metrics"]["procs"], 500)

    def test_live_readings_still_update_every_tick(self):
        self.ps.cpu_percent.side_effect = None
        self.ps.cpu_percent.return_value = 11.0
        self.tick(1)
        self.ps.cpu_percent.return_value = 77.0
        self.tick(1)
        snap = self.mon.snapshot()
        self.assertEqual(snap["metrics"]["cpu_load"], 77.0)
        self.assertEqual(list(snap["hist"]["cpu_load"]), [11.0, 77.0])

    def test_snapshot_shape(self):
        self.tick(3)
        snap = self.mon.snapshot()
        self.assertEqual(set(snap), {"status", "msg", "sensors", "fans", "metrics", "hist",
                                     "profile", "curve", "manual"})
        m = snap["metrics"]
        for key in ("cpu_load", "cores", "ram_used", "ram_total", "ram_pct", "cpu_clock", "net_down",
                    "net_up", "disks", "uptime", "procs"):
            self.assertIn(key, m)
        self.assertEqual(m["cpu_clock"], 3600.0)
        self.assertEqual(m["disks"], [("C:\\", 40.0, 100.0, 40.0)])
        self.assertEqual(snap["profile"], "Auto")
        self.assertEqual(snap["sensors"], [])
        self.assertEqual(snap["fans"], {})
        self.assertEqual(len(snap["hist"]["cpu_load"]), 3)

    def test_snapshot_is_a_copy(self):
        self.tick(2)
        snap = self.mon.snapshot()
        snap["hist"]["cpu_load"].append(-1)
        snap["metrics"]["procs"] = -1
        again = self.mon.snapshot()
        self.assertNotIn(-1, again["hist"]["cpu_load"])
        self.assertEqual(again["metrics"]["procs"], 123)


if __name__ == "__main__":
    unittest.main()
