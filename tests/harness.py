# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run Central RGB on simulated hardware and screenshot pages (Linux + Xvfb).

xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/harness.py <theme> <outdir> [page ...]
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
theme, out = sys.argv[1], Path(sys.argv[2])
pages = sys.argv[3:] or ["Home", "Lighting", "Devices", "Fans", "Monitor", "Profiles", "Settings"]
out.mkdir(parents=True, exist_ok=True)
tmp = tempfile.mkdtemp()
os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = tmp
(Path(tmp) / "CentralRGB").mkdir()
(Path(tmp) / "CentralRGB" / "settings.json").write_text(json.dumps({"theme": theme, "animations": False,
                                                                   "state": {"color": [0, 120, 255], "effect": "Aurora",
                                                                             "brightness": 100, "speed": 30}}))

import fakes  # noqa: E402
import rgb_engine as eng  # noqa: E402

eng.OpenRGBClient = fakes.FakeClient
eng.OpenRGBManager.server_running = staticmethod(lambda timeout=0.5: True)
eng.OpenRGBManager.replace_visible_copy = lambda self: False
import central_rgb as cr  # noqa: E402

assert cr.THEME == theme, (cr.THEME, theme)
cr.App.TEST_BACKEND = fakes.FakeLHM()
app = cr.App()
app.monitor.INTERVAL = 0.2
app.after(6000, lambda: setattr(app.monitor, "INTERVAL", 1.0))


def shot(i=0):
    if i >= len(pages):
        app.after(300, finish)
        return
    app.show_page(pages[i], animate=False)
    app.after(1500, lambda: (subprocess.run(["import", "-window", "root", str(out / f"{pages[i].lower()}.png")]),
                             shot(i + 1)))


def finish():
    app.engine.stop()
    app.monitor.stop()
    app.destroy()


app.after(9000, shot)
app.mainloop()
