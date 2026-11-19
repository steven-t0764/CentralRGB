# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Screenshot the Overlay page's preview showing each FPS-counter status note ("PresentMon needs admin"...),
so the 'say why instead of failing silently' messages can be checked without a real game.

    xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview_overlay_notes.py [out folder]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import preview  # noqa: E402

NOTES = ["PresentMon needs admin", "No frames from this game yet", "Exclusive fullscreen hides overlays"]
out = Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "preview_out")
sys.argv = [sys.argv[0], str(out), "--pages", "Overlay", "--warmup", "4", "--keep-open"]

import central_rgb  # noqa: E402

_init = central_rgb.App.__init__


def _patched(self, *a, **k):
    _init(self, *a, **k)

    def shoot(i=0):
        from PIL import ImageGrab
        if i >= len(NOTES):
            self.engine.stop(); self.monitor.stop(); self.destroy()
            return
        self.overlay_preview.render(self.overlay_cfg, None, {}, note=NOTES[i])
        self.update()
        x, y = self.winfo_rootx(), self.winfo_rooty()
        name = NOTES[i].lower().replace(" ", "-")
        ImageGrab.grab((x, y, x + self.winfo_width(), y + self.winfo_height())).save(out / f"overlay-note-{name}.png")
        print("saved", name)
        self.after(600, lambda: shoot(i + 1))

    self.after(9000, shoot)


central_rgb.App.__init__ = _patched
preview.main()
