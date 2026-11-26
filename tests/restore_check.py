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
  stale_NNN.png                                         the page area right after each back-to-back switch
  scroll_NNN.png / scroll.gif                           the Settings page after each scroll step
  report.txt                                            what was checked and the result

Checks (exit code 1 if any fails):
  - rapid sidebar clicks, including clicks that arrive while a page is still being drawn, end on the page
    clicked last, and that page is fully laid out and on top
  - a sidebar click during a window resize still opens its page, and the page that was open when the resize
    began comes back at the new size (not stuck at the old one)
  - frames grabbed during the restore that are much blacker than the window before minimizing (reported)
  - no frame grabbed during the restore (once the window is back on screen) or during the page switching has
    near-black boxes in it (the black flashes), as long as the theme itself has no colour that dark
  - every frame, canvas and window in the app has its own background colour (none left at Tk's default)
  - right after a page switch (including back-to-back switches such as Overlay -> Monitor -> Fans) the page
    area shows none of the previous page: no part that matches the old page and not the new one
  - scrolling Settings up and down draws cleanly: after every step the page looks the same as when it is
    fully redrawn at that spot (no rows smeared into repeated copies, no blank bands)
  - the sidebar highlight is not drawn before the new page is laid out (it moves in the same repaint as the page)
  - page-switch timings (App._switch_phases) and scroll-step timings are reported
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


DARK = 6          # brightness (0-255) counted as "near-black"
TILE = 16         # black boxes are looked for in squares of this size


def black_tiles(img, tile=TILE, dark=DARK, share=0.9) -> int:
    """How many tile x tile squares of the image are (almost) entirely near-black: a black box shows up as some.
    Thin dark lines or a few dark pixels never fill a square, so normal content counts as 0."""
    g = img.convert("L").point(lambda v: 255 if v < dark else 0)
    n = 0
    for y in range(0, g.height - tile + 1, tile):
        for x in range(0, g.width - tile + 1, tile):
            if g.crop((x, y, x + tile, y + tile)).histogram()[255] >= share * tile * tile:
                n += 1
    return n


def theme_has_black(palette) -> bool:
    """True if one of the theme's own colours is near-black (then black boxes can't be told from content)."""
    for v in palette.values():
        if isinstance(v, str) and v.startswith("#") and len(v) == 7:
            r, g, b = (int(v[i:i + 2], 16) for i in (1, 3, 5))
            if 0.299 * r + 0.587 * g + 0.114 * b < DARK:
                return True
    return False


def default_backgrounds(app) -> list[str]:
    """Frames, canvases and windows still on Tk's default background (they show it, or black on Windows, before
    their content is drawn)."""
    import tkinter as tk
    probe = tk.Frame(app)
    default = str(probe.tk.call(probe._w, "cget", "-background"))
    probe.destroy()
    bad = []

    def walk(w):
        for c in w.winfo_children():
            if isinstance(c, (tk.Frame, tk.Canvas, tk.Toplevel)):
                try:
                    bg = str(c.tk.call(c._w, "cget", "-background"))
                except Exception:
                    bg = ""
                if bg in ("", default) or bg.lower() in ("black", "#000000", "#000", "systembuttonface"):
                    bad.append(f"{c} ({bg or 'none'})")
            walk(c)
    walk(app)
    return bad


def stale_share(frame, old, new, tol=10, diff=40) -> float:
    """Share of the page area that still shows the previous page: pixels that match `old` (the previous page
    drawn on its own) but not `new` (the page that should be showing), counted only where the two pages
    really differ. Live content (graphs, numbers) changing a little never matches the old page, so it
    doesn't count."""
    from PIL import ImageChops
    a, b, f = (im.convert("L") for im in (old, new, frame))
    if not (a.size == b.size == f.size):
        return 0.0
    pages_differ = ImageChops.difference(a, b).point(lambda v: 255 if v > diff else 0)
    like_old = ImageChops.difference(f, a).point(lambda v: 255 if v <= tol else 0)
    unlike_new = ImageChops.difference(f, b).point(lambda v: 255 if v > diff else 0)
    hit = ImageChops.multiply(ImageChops.multiply(pages_differ, like_old), unlike_new)
    return hit.histogram()[255] / max(1, f.width * f.height)


def changed_share(a, b, diff=40) -> float:
    """Share of pixels that differ clearly between two pictures of the same spot."""
    from PIL import ImageChops
    d = ImageChops.difference(a.convert("L"), b.convert("L")).point(lambda v: 255 if v > diff else 0)
    return d.histogram()[255] / max(1, a.width * a.height)


def walk_widgets(w):
    """Every widget inside w."""
    for c in w.winfo_children():
        yield c
        yield from walk_widgets(c)


def black_share(img) -> float:
    """Share of pixels that are (almost) pure black."""
    g = img.convert("L")
    hist = g.histogram()
    return sum(hist[:6]) / max(1, g.width * g.height)


class FrameGrabber:
    """Grabs the window's area of the screen as fast as it can, in a background thread (no Tk calls)."""

    def __init__(self, box):
        self.box, self.frames, self._stop = box, [], threading.Event()
        self._t, self.t0 = None, time.perf_counter()

    def start(self):
        self.frames, self._stop = [], threading.Event()
        self.t0 = time.perf_counter()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        from PIL import ImageGrab
        while not self._stop.is_set():
            try:
                self.frames.append((time.perf_counter() - self.t0, ImageGrab.grab(self.box)))
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
    for old in [f for stem in ("restore", "switch", "stale", "scroll") for f in out.glob(f"{stem}_*.png")]:
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
            dark_theme_colour = theme_has_black(app_mod.P)
            if dark_theme_colour:
                report.append("INFO  this theme has a near-black colour, so black boxes in frames are only reported")

            def no_black_boxes(frames, what, since=0.0):
                boxes = [(round(t * 1000), n) for t, im in frames if t >= since and (n := black_tiles(im)) >= 2]
                text = (f"no frame during {what} has near-black boxes"
                        + (f" (got {len(boxes)} frames with them, at ms/boxes {boxes[:8]})" if boxes else ""))
                if dark_theme_colour:
                    report.append("INFO  " + text)
                else:
                    ok(not boxes, text)

            missing = default_backgrounds(app)
            ok(not missing, "every frame, canvas and window has its own background colour"
                            + (f" (left at the default: {', '.join(missing[:8])})" if missing else ""))

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
            restores, mapped = [], []
            app.bind("<Map>", lambda e: (e.widget is app and not mapped
                                         and mapped.append(time.perf_counter())), add="+")
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
            # frames before the window is back on screen show the desktop / taskbar, not the window
            no_black_boxes(frames, "the restore", since=(mapped[0] - g.t0) if mapped else 0.0)
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
            no_black_boxes(frames, "rapid page switching")
            ok(app.current_page == "Settings", f"clicks 25 ms apart end on the page clicked last (got {app.current_page})")
            ok(on_top_and_full("Settings"), "Settings is fully laid out and on top")
            save_frames(frames, out, "switch", limit)

            # ---- no pixels of the previous page left behind, and Settings scrolls cleanly
            from PIL import ImageGrab
            app.monitor.INTERVAL = 30                  # hold the live numbers still while pages are compared

            def page_box():
                app.update_idletasks()
                hd = app._holder
                x, y = hd.winfo_rootx(), hd.winfo_rooty()
                return (x, y, x + hd.winfo_width(), y + hd.winfo_height())

            def full_redraw():
                """Have the whole page area drawn again from scratch: cover it with another window and uncover
                it (X11), and on Windows freeze, erase and repaint it."""
                x0, y0, x1, y1 = page_box()
                cover = app_mod.tk.Toplevel(app, bg="#7f007f")
                cover.overrideredirect(True)
                cover.geometry(f"{x1 - x0}x{y1 - y0}+{x0}+{y0}")
                app.update()
                cover.destroy()
                app.update()
                app_mod.fx.thaw(app_mod.fx.freeze(app._holder))
                app._paint_now()
                wait(40)

            wait(1200)
            refs = {}
            for name in pages:
                app.show_page(name)
                wait(250)
                full_redraw()
                refs[name] = ImageGrab.grab(page_box())
            pairs = [("Overlay", "Monitor"), ("Monitor", "Fans")] + list(zip(pages, pages[1:])) \
                + list(zip(pages[::-1], pages[::-1][1:]))
            pairs = [(a, b) for a, b in pairs if a in refs and b in refs]
            worst, shot, times = [], 0, []
            early = []                                 # switches whose sidebar highlight was drawn before the page
            for a, b in pairs:
                app.show_page(a)                       # back to back, nothing in between
                lit = []
                app.update_idletasks = lambda: (lit.append(getattr(app.nav[b], "on", False)),
                                                type(app).update_idletasks(app))
                t0 = time.perf_counter()
                try:
                    app.show_page(b)
                finally:
                    del app.update_idletasks
                if any(lit):
                    early.append(f"{a} -> {b}")
                times.append(((time.perf_counter() - t0) * 1000, dict(getattr(app, "_switch_phases", {}))))
                img = ImageGrab.grab(page_box())
                if shot < limit:
                    img.save(out / f"stale_{shot:03d}.png")
                    shot += 1
                share = stale_share(img, refs[a], refs[b])
                worst.append((share, a, b))
            worst.sort(reverse=True)
            bad = [(f"{a} -> {b}", round(sh * 100, 1)) for sh, a, b in worst if sh > 0.03]
            ok(not bad, f"no page switch leaves pixels of the previous page behind ({len(pairs)} back-to-back "
                        f"switches, worst {worst[0][0] * 100:.1f} % of the page area)"
                        + (f" (left behind, % of the page: {bad[:6]})" if bad else ""))
            ok(not early, "the sidebar highlight moves in the same repaint as the page, not before it is laid out"
                          + (f" (lit early: {early[:6]})" if early else ""))
            ms = sorted(t for t, _ in times)
            phases = {}
            for _, ph in times:
                for k, v in ph.items():
                    phases.setdefault(k, []).append(v)
            report.append(f"INFO  page switch: median {ms[len(ms) // 2]:.1f} ms, slowest {ms[-1]:.1f} ms; phases "
                          f"(median ms): " + ", ".join(f"{k} {sorted(v)[len(v) // 2]:.1f}" for k, v in phases.items()))

            app.show_page("Settings")
            wait(300)
            areas = [w for w in walk_widgets(app.pages["Settings"]) if isinstance(w, app_mod.LightScroll)]
            ok(bool(areas), "the Settings page has a scrolling area")
            if areas:
                area = max(areas, key=lambda w: w.inner.winfo_reqheight())
                area.cv.yview_moveto(0)
                wait(100)
                frames, smears, steps = [], [], []
                for i, d in enumerate([3] * 8 + [-3] * 8):
                    t0 = time.perf_counter()
                    area.cv.yview_scroll(d, "units")
                    app._paint_now()
                    steps.append((time.perf_counter() - t0) * 1000)
                    img = ImageGrab.grab(page_box())
                    frames.append((i * 0.05, img))
                    full_redraw()
                    ref = ImageGrab.grab(page_box())
                    if (sh := changed_share(img, ref)) > 0.02:
                        smears.append((i, round(sh * 100, 1)))
                moved = changed_share(frames[0][1], frames[7][1])
                ok(moved > 0.02, f"scrolling really moved the Settings page ({moved * 100:.0f} % of it changed)")
                ok(not smears, f"Settings scrolls cleanly: each of {len(frames)} scroll steps looks the same as the "
                               f"page fully redrawn there" + (f" (step, % different: {smears[:6]})" if smears else ""))
                st = sorted(steps)
                report.append(f"INFO  Settings scroll step: median {st[len(st) // 2]:.1f} ms, slowest {st[-1]:.1f} ms")
                save_frames(frames, out, "scroll", limit)
            app.monitor.INTERVAL = 0.3

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
