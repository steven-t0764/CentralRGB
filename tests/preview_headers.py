# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Preview the ARGB header set-up on a simulated copy of the owner's PC (fake_openrgb.OWNERS_PC: MSI B550-A PRO
with JRAINBOW1/2 at 0 LEDs, Razer Huntsman V2 TKL, SteelSeries Aerox 3 Wireless, 4x Vengeance RGB PRO):

    xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview_headers.py [out]

Saves devices.png (with the "Fan or strip lights not set up" note), editor.png (the motherboard's Customize
page with Connected LEDs), editor-set.png (JRAINBOW1 set to 24 LEDs) and devices-after.png.
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

_install = fake_openrgb.install
fake_openrgb.install = lambda e=None, **k: _install(e, devices=fake_openrgb.OWNERS_PC)
eng.find_conflicts = lambda: {}
eng.is_admin = lambda: True

sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if not a.startswith("--")]
import preview  # noqa: E402


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "preview_out")
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="centralrgb-headers-"))
    app_mod, app = preview.start_app(tmp)

    def grab(name):
        from PIL import ImageGrab
        app.update()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab((x, y, x + app.winfo_width(), y + app.winfo_height())).save(out / f"{name}.png")
        print("  " + name + ".png")

    def board_key():
        return next(r[0] for r in app.device_rows if r[1] == "Motherboard")

    def set_header():
        key = board_key()
        zone = next(z for z in app.engine.zones(key) if z["name"] == "JRAINBOW1")
        app._set_header(key, zone, 24)
        app._close_device()
        app._open_device(key)

    def finish():
        try:
            app.engine.stop()
            app.monitor.stop()
        finally:
            app.destroy()

    steps = [(9000, lambda: (app._check_missing(), app.show_page("Devices"))), (2000, lambda: grab("devices")),
             (300, lambda: app._open_device(board_key())), (1500, lambda: grab("editor")),
             (300, set_header), (1500, lambda: grab("editor-set")),
             (300, lambda: (app._close_device(), app._check_missing())), (1500, lambda: grab("devices-after")),
             (300, finish)]
    t = 0
    for delay, fn in steps:
        t += delay
        app.after(t, fn)
    app.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
