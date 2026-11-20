# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Screenshot the updater: the Updates rows on the Settings page and the "new version" notice, with
GitHub replaced by tests/fake_github.py (no network).

    xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview_updater.py [output folder]

Saves updates_settings.png, update_notice.png and update_notice_settings.png (tests/preview_out/ by default).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import preview  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "preview_out"
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="centralrgb-preview-"))
    import updater as upd
    gh = FakeGitHub()
    real_check = upd.check
    upd.check = lambda current, opener=None: real_check(current, opener=gh)
    app_mod, app = preview.start_app(tmp)
    problems = []

    def grab(name):
        from PIL import ImageGrab
        app.update()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        ImageGrab.grab((x, y, x + app.winfo_width(), y + app.winfo_height())).save(out / name)
        print("saved", out / name)

    def settings():
        app.show_page("Settings")
        app.after(800, scroll)

    def scroll():
        canvas = app.update_status.master.master.master
        while canvas is not None and not hasattr(canvas, "yview_moveto"):
            canvas = canvas.master
        if canvas is not None:
            canvas.yview_moveto(0.35)
        app._check_updates(manual=True)
        app.after(1500, shot_settings)

    def shot_settings():
        if app.update_status.cget("text") != "2.9.0 available":
            problems.append(f"status label says {app.update_status.cget('text')!r}")
        if getattr(app, "update_notice", None) is None:
            problems.append("no update notice shown")
        grab("update_notice_settings.png")
        app._hide_update_notice()
        app.after(300, lambda: (grab("updates_settings.png"), home()))

    def home():
        app.show_page("Home")
        app._show_update_notice(app._update_result)
        app.after(1000, lambda: (grab("update_notice.png"), finish()))

    def finish():
        try:
            app.engine.stop()
            app.monitor.stop()
        finally:
            app.destroy()

    app.after(4000, settings)
    app.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        print("PROBLEMS: " + "; ".join(problems))
        sys.exit(1)


if __name__ == "__main__":
    main()
