# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Minimize / restore the window and switch pages rapidly on simulated hardware, recording frames.

    python tests/restore_check.py [output folder] [--warmup 6] [--quick]

On Linux with no display:  xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/restore_check.py
On Windows it runs the real minimize/restore path (the window is hidden while it redraws) and records what
the screen showed, so it can be run on the real PC to record the restore.

Saved to tests/preview_out/restore_check/ (ignored by git):
  before.png, after_restore.png, after_switching.png   still screenshots
  restore_NNN.png / restore.gif                         frames grabbed while the window came back
  switch_NNN.png / switch.gif                           frames grabbed during rapid page switching
  report.txt                                            what was checked and the result

Checks (exit code 1 if any fails):
  - rapid sidebar clicks, including clicks that arrive while a page is still being drawn, end on the page
    clicked last, and that page is fully laid out and on top
  - a sidebar click during a window resize still opens its page, and the page that was open when the resize
    began comes back at the new size (not stuck at the old one)
  - frames grabbed during the restore that are much blacker than the window before minimizing (reported)
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

import preview  # noqa: E402


def black_share(img) -> float:
    """Share of pixels that are (almost) pure black."""
    g = img.convert("L")
    hist = g.histogram()
    return sum(hist[:6]) / max(1, g.width * g.height)


class FrameGrabber:
    """Grabs the window's area of the screen as fast as it can, in a background thread (no Tk calls)."""

    def __init__(self, box):
        self.box, self.frames, self._stop = box, [], threading.Event()
        self._t = None

    def start(self):
        self.frames, self._stop = [], threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        from PIL import ImageGrab
        t0 = time.perf_counter()
        while not self._stop.is_set():
            try:
                self.frames.append((time.perf_counter() - t0, ImageGrab.grab(self.box)))
            except Exception:
                return
            time.sleep(0.004)

    def stop(self):
        self._stop.set()
        if self._t is not None:
            self._t.join(2)
        return self.frames


def save_frames(frames, out: Path, stem: str, limit: int):
    if not frames:
        return
    step = max(1, len(frames) // limit)
    kept = frames[::step][:limit]
    for i, (_, img) in enumerate(kept):
        img.save(out / f"{stem}_{i:03d}.png")
    dur = [max(20, int((kept[i + 1][0] - kept[i][0]) * 1000)) if i + 1 < len(kept) else 600 for i in range(len(kept))]
    imgs = [im.convert("P", palette=1, colors=255) for _, im in kept]
    imgs[0].save(out / f"{stem}.gif", save_all=True, append_images=imgs[1:], duration=dur, loop=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", nargs="?", default=str(HERE / "preview_out" / "restore_check"))
    ap.add_argument("--warmup", type=float, default=6.0, help="seconds to let the app settle first")
    ap.add_argument("--quick", action="store_true", help="fewer frames saved (used by the unit test)")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("restore_*.png")) + list(out.glob("switch_*.png")):
        old.unlink()
    tmp = Path(tempfile.mkdtemp(prefix="centralrgb-restore-"))
    app_mod, app = preview.start_app(tmp)
    app.monitor.INTERVAL = 0.3
    pages = [n for n, *_ in app_mod.NAV]
    limit = 12 if args.quick else 60
    report, failures = [], []

    def ok(cond, what):
        report.append(("PASS  " if cond else "FAIL  ") + what)
        if not cond:
            failures.append(what)

    def box():
        app.update_idletasks()
        x, y = app.winfo_rootx(), app.winfo_rooty()
        return (x, y, x + app.winfo_width(), y + app.winfo_height())

    def grab(name):
        from PIL import ImageGrab
        app.update()
        img = ImageGrab.grab(box())
        img.save(out / name)
        return img

    def click(name):
        """A real sidebar click: the same <Button-1> binding a mouse click runs."""
        app.nav[name].pill.event_generate("<Button-1>", x=4, y=4, when="tail")

    def wait(ms):
        end = time.perf_counter() + ms / 1000
        while time.perf_counter() < end:
            app.update()
            time.sleep(0.005)

    def on_top_and_full(name):
        page = app.pages[name]
        placed = [w for w in app._holder.winfo_children() if w in app.pages.values() and w.winfo_manager()]
        info = page.place_info()
        return (bool(placed) and placed[-1] is page and info.get("relwidth") == "1"
                and abs(page.winfo_width() - app._holder.winfo_width()) <= 2)

    def run():
        try:
            # ---- minimize and restore
            app.show_page("Home")
            wait(400)
            before = grab("before.png")
            base = black_share(before)
            g = FrameGrabber(box())
            app.iconify()
            wait(500)
            if app.state() == "iconic":
                report.append("PASS  window minimizes")
            else:                                      # e.g. bare Xvfb: no window manager, so no minimizing
                report.append("INFO  no window manager here, so the window can't really minimize; "
                              "hiding it and running the restore-from-taskbar path instead")
                app.withdraw()
                wait(300)
                app._was_minimized = True
            restores = []
            real_restore = getattr(app, "_restore_drawn", None)
            if real_restore is not None:
                app._restore_drawn = lambda: (restores.append(1), real_restore())
            g.start()
            app.deiconify()
            wait(700)
            frames = g.stop()
            after = grab("after_restore.png")
            ok(app.state() == "normal", "window restores")
            ok(bool(restores), "coming back runs the draw-before-showing path")
            app.__dict__.pop("_restore_drawn", None)
            blackish = [round(t * 1000) for t, im in frames if black_share(im) > base + 0.25]
            report.append(f"INFO  {len(frames)} frames grabbed during the restore; much blacker than before "
                          f"minimizing: {len(blackish)}" + (f" (at ms {blackish[:10]})" if blackish else ""))
            ok(black_share(after) <= base + 0.05, "window is fully drawn after the restore")
            save_frames(frames, out, "restore", limit)

            # ---- rapid page switching: a burst of clicks queued at once, then clicks every 25 ms
            g = FrameGrabber(box())
            g.start()
            for name in pages:                       # all queued before the first one is handled
                click(name)
            click("Lighting")
            wait(800)
            ok(app.current_page == "Lighting", f"a burst of {len(pages) + 1} clicks ends on the page clicked last "
                                               f"(got {app.current_page})")
            ok(on_top_and_full("Lighting"), "that page is fully laid out and on top")
            seq = pages[::-1] + ["Fans", "Monitor", "Settings"]
            for i, name in enumerate(seq):
                app.after(25 * i, lambda n=name: click(n))
            wait(25 * len(seq) + 900)
            frames = g.stop()
            ok(app.current_page == "Settings", f"clicks 25 ms apart end on the page clicked last (got {app.current_page})")
            ok(on_top_and_full("Settings"), "Settings is fully laid out and on top")
            save_frames(frames, out, "switch", limit)

            # ---- a sidebar click while the window is being resized
            app.show_page("Home")
            wait(300)
            w, h = app.winfo_width(), app.winfo_height()
            app.geometry(f"{w + 120}x{h + 60}")
            wait(30)                                   # inside the resize: Home is pinned at the old size
            click("Settings")
            wait(600)
            ok(app.current_page == "Settings" and on_top_and_full("Settings"),
               "a click during a resize opens its page at the new size")
            click("Home")
            wait(500)
            ok(on_top_and_full("Home"), "the page open when the resize began comes back at the new size")
            app.geometry(f"{w}x{h}")
            wait(500)
            grab("after_switching.png")
        except Exception as e:                         # report, never hang
            import traceback
            ok(False, f"check crashed: {e}\n{traceback.format_exc()}")
        finally:
            text = "\n".join(report) + f"\n\n{'FAILED' if failures else 'PASSED'}\n"
            (out / "report.txt").write_text(text, encoding="utf-8")
            print(text + f"Saved to {out}")
            try:
                app.engine.stop()
                app.monitor.stop()
            finally:
                app.destroy()

    app.after(int(args.warmup * 1000), run)
    app.mainloop()
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
