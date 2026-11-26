# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Run Central RGB on simulated hardware and save a screenshot of every page.

    python tests/preview.py [output folder] [--pages Home,Fans] [--warmup 8] [--keep-open] [--appearance light]

On Linux with no display, wrap it:  xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview.py
On Windows it also works and leaves your real settings alone (a temporary settings folder is used).
Screenshots go to tests/preview_out/ by default (ignored by git). Nothing touches real hardware:
lighting goes to fake_openrgb, sensors and fans come from fake_lhm.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]


def _demo_stats(hwm):
    """Believable, moving CPU/RAM/network/disk values (the parts that normally come from psutil)."""
    import math
    import random
    real = hwm.HardwareMonitor._basic_metrics
    t0 = time.time()

    def demo(self):
        m = real(self)
        k = time.time() - t0
        m["cpu_load"] = max(2.0, 28 + 14 * math.sin(k / 1.3) + random.uniform(-4, 4))
        m["cores"] = [max(0.0, min(100.0, m["cpu_load"] + random.uniform(-15, 15))) for _ in range(16)]
        m["ram_total"] = 31.9
        m["ram_used"] = 14.6 + 0.4 * math.sin(k / 7)
        m["ram_pct"] = m["ram_used"] / m["ram_total"] * 100
        m["net_down"] = max(0.0, 180 + 140 * math.sin(k / 0.9) + random.uniform(-30, 30))
        m["net_up"] = max(0.0, 22 + 15 * math.sin(k / 1.7) + random.uniform(-5, 5))
        m["disk_read"] = max(0.0, 42 + 30 * math.sin(k / 1.1) + random.uniform(-8, 8))
        m["disk_write"] = max(0.0, 11 + 8 * math.sin(k / 2.3) + random.uniform(-3, 3))
        m["disks"] = [("C:\\", 612.0, 1863.0, 32.8), ("D:\\", 1210.0, 1863.0, 64.9)]
        m["uptime"] = 3 * 3600 + 27 * 60 + k
        m["procs"] = 241
        return m

    hwm.HardwareMonitor._basic_metrics = demo


def start_app(tmp: Path, effect: str | None = None, real_stats: bool = False, appearance: str | None = None,
              theme: str | None = None):
    """Build the real app on simulated hardware, with its settings in the temporary folder `tmp`.
    Returns (central_rgb module, App). Also used by restore_check.py and test_appearance.py."""
    os.environ["APPDATA"] = str(tmp / "roaming")          # fresh settings, never the real ones
    os.environ["LOCALAPPDATA"] = str(tmp / "local")
    seed = {}
    if effect:                                          # seed the saved lighting state
        seed["state"] = {"effect": effect, "color": [150, 0, 255], "brightness": 100, "speed": 50}
    if appearance:                                      # "dark" or "light"
        seed["appearance"] = appearance
    if theme:
        seed["theme"] = theme
    if seed:
        import json
        (tmp / "roaming" / "CentralRGB").mkdir(parents=True, exist_ok=True)
        (tmp / "roaming" / "CentralRGB" / "settings.json").write_text(json.dumps(seed))

    import fake_openrgb
    import rgb_engine as eng
    fake_openrgb.install(eng)
    eng.OpenRGBManager.find_exe = lambda self: None
    import central_rgb as app_mod
    from fake_lhm import FakeLHM

    class _NoSplash:                                    # the splash is a separate process; skip it
        def __init__(self, *a, **k):
            raise RuntimeError("no splash in previews")
    app_mod.SplashProcess = _NoSplash
    app_mod.App.TEST_BACKEND = FakeLHM()
    import fake_hid                                     # the owner's wireless gear, plus a sample headset
    app_mod.App.BATTERY_HID = fake_hid.FakeHid(fake_hid.OWNERS_GEAR)
    app_mod.bat.read_headsets = lambda exe: app_mod.bat.parse_headsetcontrol(fake_hid.HEADSETCONTROL_JSON)
    if not real_stats:
        _demo_stats(app_mod.hwm)
    return app_mod, app_mod.App()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=str(HERE / "preview_out"))
    ap.add_argument("--pages", help="comma-separated page names (default: all)")
    ap.add_argument("--warmup", type=float, default=8.0, help="seconds to let graphs fill before capturing")
    ap.add_argument("--settle", type=float, default=1.5, help="seconds to wait after opening each page")
    ap.add_argument("--keep-open", action="store_true", help="leave the window open after capturing")
    ap.add_argument("--effect", help="start with this lighting effect, e.g. Nebula or \"Rainbow Wave\"")
    ap.add_argument("--real-stats", action="store_true",
                    help="show this machine's real CPU/RAM/network/disk use instead of demo values")
    ap.add_argument("--appearance", choices=["dark", "light"], help="start in Dark or Light appearance")
    ap.add_argument("--theme", help="start with this theme key, e.g. gunmetal or cyber_cyan")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="centralrgb-preview-"))
    app_mod, app = start_app(tmp, args.effect, args.real_stats, args.appearance, args.theme)

    pages = [n for n, *_ in app_mod.NAV]
    if args.pages:
        want = [p.strip().lower() for p in args.pages.split(",")]
        pages = [p for p in pages if p.lower() in want]

    app.monitor.INTERVAL = 0.2                          # fill the graphs quickly
    saved = []

    def grab(name):
        from PIL import ImageGrab
        app.update()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        img = ImageGrab.grab((x, y, x + app.winfo_width(), y + app.winfo_height()))
        path = out / f"{name.lower()}.png"
        img.save(path)
        saved.append(path)

    def step(i=0):
        if i < len(pages):
            app.show_page(pages[i])
            app.after(int(args.settle * 1000), lambda: (grab(pages[i]), step(i + 1)))
            return
        app.monitor.INTERVAL = 1.0
        print(f"Saved {len(saved)} screenshots to {out}")
        for p in saved:
            print("  " + p.name)
        if not args.keep_open:
            app.after(200, finish)

    def finish():
        try:
            app.engine.stop()
            app.monitor.stop()
        finally:
            app.destroy()

    app.after(int(args.warmup * 1000), step)
    app.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
