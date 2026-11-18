# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening Central RGB while it's already running: same version shows the running window, a newer version
takes over (the older copy quits properly so fans go back to the BIOS)."""
import os
import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())
try:
    import central_rgb as cr
except Exception as e:  # pragma: no cover - needs tkinter/customtkinter
    cr = None
    _err = e


@unittest.skipIf(cr is None, "central_rgb could not be imported")
class SingleInstance(unittest.TestCase):
    def setUp(self):
        self._port = cr.INSTANCE_PORT
        import socket                                # a fresh port the OS says is free (never the real one)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cr.INSTANCE_PORT = probe.getsockname()[1]

    def tearDown(self):
        cr.INSTANCE_PORT = self._port

    def test_version_order(self):
        self.assertGreater(cr.version_tuple("2.3.10"), cr.version_tuple("2.3.9"))
        self.assertGreater(cr.version_tuple("v2.4.0"), cr.version_tuple("2.3.3"))
        self.assertEqual(cr.version_tuple("2.3.3"), cr.version_tuple("2.3.3"))
        self.assertEqual(cr.version_tuple("junk"), (0,))

    def _running(self, version):
        q = queue.Queue()
        self.assertTrue(cr.claim_single_instance(q, version=version))
        return q

    def test_same_version_shows_running_window(self):
        q = self._running("2.3.3")
        self.assertFalse(cr.claim_single_instance(queue.Queue(), version="2.3.3"))
        self.assertEqual(q.get(timeout=2), ("tray", "show"))
        self.assertTrue(q.empty())

    def test_older_launch_shows_running_window(self):
        q = self._running("2.3.4")
        self.assertFalse(cr.claim_single_instance(queue.Queue(), version="2.3.3"))
        self.assertEqual(q.get(timeout=2), ("tray", "show"))

    def test_newer_launch_takes_over(self):
        q = self._running("2.3.3")
        old_server = cr._instance_server

        def old_copy_quits():
            # What the app does on ("tray", "quit"): shut down (fans back to the BIOS) and exit, which frees the
            # port. The exit is emulated here by closing the old copy's listening socket.
            self.assertEqual(q.get(timeout=3), ("tray", "quit"))
            time.sleep(0.3)
            old_server.close()
        threading.Thread(target=old_copy_quits, daemon=True).start()
        t0 = time.time()
        self.assertTrue(cr.claim_single_instance(queue.Queue(), version="2.3.4"))
        self.assertLess(time.time() - t0, 10)
        self.assertIsNot(cr._instance_server, old_server)

if __name__ == "__main__":
    unittest.main()
