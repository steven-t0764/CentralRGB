# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Preview the key editor on a simulated copy of the owner's PC (Razer Huntsman V2 TKL with a key matrix):

    xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview_keys.py [out]

Saves devices.png (the keyboard card with its Keys button), keys.png (the editor, nothing painted),
keys-wasd.png (WASD painted red, the arrows cyan, over a Rainbow Wave) and devices-after.png.
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
    tmp = Path(tempfile.mkdtemp(prefix="centralrgb-keys-"))
    app_mod, app = preview.start_app(tmp)

    def grab(name, win=None):
        from PIL import ImageGrab
        w = win or app
        app.update()
        x, y = w.winfo_rootx(), w.winfo_rooty()
        ImageGrab.grab((x, y, x + w.winfo_width(), y + w.winfo_height())).save(out / f"{name}.png")
        print("  " + name + ".png")

    def kb_key():
        return next(r[0] for r in app.device_rows if r[1] == "Keyboard")

    def paint():
        ed = app.key_editor
        ed._paint_group("WASD")
        ed._set_brush((0, 255, 255))
        ed._paint_group("Arrows")

    def finish():
        try:
            app.engine.stop()
            app.monitor.stop()
        finally:
            app.destroy()

    steps = [(9000, lambda: (app.engine.set_state(effect="Rainbow Wave"), app.show_page("Devices"))),
             (2000, lambda: grab("devices")),
             (300, lambda: app.open_key_editor(kb_key())), (1500, lambda: grab("keys", app.key_editor)),
             (300, paint), (1200, lambda: grab("keys-wasd", app.key_editor)),
             (300, lambda: app.key_editor.destroy()), (1500, lambda: grab("devices-after")),
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
