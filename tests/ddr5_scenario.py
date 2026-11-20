# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Walk the whole app through the DDR5 RAM guard on simulated hardware (needs a display; on Linux wrap it in
xvfb-run). Not part of `unittest discover` because it opens the real window.

    python tests/ddr5_scenario.py          # DDR5: the guard is on
    python tests/ddr5_scenario.py --ddr4   # DDR4: everything works as before (rescan restarts, quit stops)

Checks, with DDR5 RAM found:
  1. Rescan asks first, and answering No keeps OpenRGB running (no restart).
  2. Closing conflicting apps doesn't restart OpenRGB.
  3. Quitting leaves the hidden OpenRGB running.
And with DDR5 RAM missing after an earlier search this boot, the "shut down fully" note is shown.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
tmp = Path(tempfile.mkdtemp(prefix="centralrgb-ddr5-"))
os.environ["APPDATA"], os.environ["LOCALAPPDATA"] = str(tmp / "r"), str(tmp / "l")
DDR4 = "--ddr4" in sys.argv
os.environ["CENTRALRGB_FAKE_DDR5"] = "0" if DDR4 else "1"

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

fake_openrgb.install(eng)
import central_rgb as app_mod  # noqa: E402
from fake_lhm import FakeLHM  # noqa: E402


class _NoSplash:
    def __init__(self, *a, **k):
        raise RuntimeError("no splash")


app_mod.SplashProcess = _NoSplash
app_mod.App.TEST_BACKEND = FakeLHM()

calls = {"ask": [], "warn": [], "restart": 0, "stop": 0}
app_mod.messagebox.askyesno = lambda *a, **k: (calls["ask"].append(a[1] if len(a) > 1 else ""), False)[1]
app_mod.messagebox.showwarning = lambda *a, **k: calls["warn"].append(a[1] if len(a) > 1 else "")

app = app_mod.App()
# act as if this app started the hidden OpenRGB itself (the fake reports one already running)
app.manager.started_by_us = lambda: True
app.manager.own_copies = lambda: []
app.manager.stop_own_copies = lambda: calls.__setitem__("restart", calls["restart"] + 1) or True
app.manager.stop = lambda: calls.__setitem__("stop", calls["stop"] + 1)
results = []


def check(name, ok):
    results.append((name, bool(ok)))


def ddr4_run():
    import threading
    check("DDR4: not treated as DDR5", not getattr(app, "ddr5", True))
    app.manager.launch = lambda exe, wait=45: False          # don't really start anything
    app.manager.find_exe = lambda: None
    eng.OpenRGBManager.server_running = staticmethod(lambda timeout=0.5: False)
    t = threading.Thread(target=app._full_rescan, args=("button",), daemon=True)   # like the real button
    t.start()
    app.after(200, lambda: ddr4_after(t))


def ddr4_after(t):
    if t.is_alive():
        app.after(200, lambda: ddr4_after(t))
        return
    check("DDR4: Rescan restarts OpenRGB without asking", calls["restart"] == 1 and not calls["ask"])
    app._check_ram()
    check("DDR4: no RAM pop-up", not calls["warn"])
    app._quit()


def step1():
    check("DDR5 detected (simulated)", getattr(app, "ddr5", False))
    check("RAM lighting found", app._ram_found())
    import threading
    t = threading.Thread(target=app._full_rescan, args=("button",), daemon=True)   # like the real button
    t.start()
    app.after(200, lambda: step2(t))


def step2(t):
    if t.is_alive():                           # waiting for the question to be answered on the main thread
        app.after(200, lambda: step2(t))
        return
    check("Rescan asked before re-detecting", len(calls["ask"]) == 1 and "DDR5" in calls["ask"][0])
    check("Answering No kept OpenRGB running", calls["restart"] == 0)
    app._full_rescan("conflicts")
    check("Closing conflicting apps didn't restart OpenRGB", calls["restart"] == 0 and len(calls["ask"]) == 1)
    # RAM missing after an earlier search this boot -> the note
    app.settings["ram_seen"] = True
    app.settings["ram_note_boot"] = 0
    app._searched_before = True
    app._ram_found = lambda: False
    app._check_ram()
    app.after(500, step3)


def step3():
    check("Missing-RAM pop-up shown once", len(calls["warn"]) == 1 and "Shift" in calls["warn"][0])
    app._check_ram()
    app.after(300, step4)


def step4():
    check("...and not again the same boot", len(calls["warn"]) == 1)
    app._quit()


app.after(9000, ddr4_run if DDR4 else step1)
try:
    app.mainloop()
except Exception:
    pass
if DDR4:
    check("DDR4: quitting stops the hidden OpenRGB", calls["stop"] == 1)
else:
    check("Quitting left the hidden OpenRGB running", calls["stop"] == 0)
shutil.rmtree(tmp, ignore_errors=True)
for name, ok in results:
    print(("PASS  " if ok else "FAIL  ") + name)
sys.exit(0 if all(ok for _, ok in results) else 1)
