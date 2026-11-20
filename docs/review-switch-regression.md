# Review of the page-switch and scrolling regression fix

Reviewed on 2026-11-20 by Fabian (issue #43). The fix under review is #46 (`a03e84d`, merged as `be8c9f0`), for
issue #42. Everything was run on `main` at `be8c9f0`, under Xvfb (1300x840, 24-bit) with Python 3.12, CustomTkinter
and Pillow, on the simulated hardware in `tests/`.

## Verdict

**The regression is fixed.** One small leftover was found and fixed in **#48** (merged): the sidebar highlight moved before
the page did.

| What was reported in #42 | On `main` now |
| --- | --- |
| Switching pages leaves the old page's pixels behind (Overlay header over Monitor, Monitor graphs in Fans) | **Fixed.** In 16 back-to-back switches, including Overlay → Monitor → Fans, no switch leaves more than 0.1 % of the page area unchanged from the old page. The check's limit is 3 %. I also looked at the frames by eye. |
| Scrolling Settings smears rows into repeated copies or blank bands | **Fixed.** All 16 scroll steps look exactly like the page fully redrawn at that spot. By eye, no row appears twice ("Startup animation" and "Updates" each appear once) and there are no blank bands. |
| The sidebar highlight is out of step with the page shown | **Not fixed by #46, fixed in #48.** The highlight was drawn during the layout pass, before the page was raised. See below. |
| The app feels slower than before | **Fixed (as far as Xvfb can show).** A page switch is fully drawn as fast as in 2.3.2 or a little faster, and the window no longer stays layered. See the timings. |

## What I ran

- `python -m py_compile` on the changed files: passed.
- `xvfb-run -a python -m unittest discover tests`: **154 tests, OK.** This includes `test_fan_safety.py`,
  `test_repaint.py` and `test_page_switch.py`, which runs `restore_check.py`.
- `tests/restore_check.py`, run on its own three times: **PASSED** every time. Every check is green: restore,
  no black boxes during the restore or the switching, the last page clicked is the one shown and fully laid out,
  no leftover pixels, Settings scrolls cleanly, and resizing during a click works.
- Frames looked at by eye: `stale_*.png` (each page right after a back-to-back switch), `scroll_*.png` (Settings
  after each scroll step), `switch_*.png` (the 9-click burst) and `restore_*.png`. I put them on contact sheets. No
  leftover pixels, no smear, no black boxes. One frame in the burst shows Lighting while it is still being drawn,
  as panel-coloured boxes (not black). 2.3.2 shows that on almost every frame.
- One frame of the restore is "much blacker than before" at 0 ms. That is the frame taken while the window is
  still hidden, before it comes back. 2.3.2 shows the same. The frames after it are fully drawn.

## Switch timings compared with 2.3.2 (tag `v2.3.2`)

The `restore_check.py` timings can't be compared directly. On `main` the time includes drawing the page
(`_paint_now`, about 16 ms). In 2.3.2, Tk draws after the switch call returns. So I measured "click until fully
drawn" (`show_page` plus `update()`) the same way on both versions: 40 switches each, cycling through all the
pages, two runs each.

| Version | Median until fully drawn | 90th percentile | Slowest |
| --- | --- | --- | --- |
| 2.3.2 | 21.4 – 22.9 ms | 52 – 55 ms | 64 – 71 ms |
| `main` (`be8c9f0`) | 18.9 – 19.6 ms | 45 – 49 ms | 54 – 60 ms |

Scrolling Settings takes a median of 4.5 ms per step on `main`, against 0.6 ms in 2.3.2. The 4.5 ms is
`restore_check`'s own measurement, which includes the full redraw it does at every step. It is still far below one
frame. Xvfb has no layered windows or DWM, so the "layered window redraws slowly" part of the fix can only show on
Windows (see below).

## The leftover: the sidebar moved before the page (#48)

`_swap_page` set the sidebar highlight first, then refreshed and laid out the new page with `update_idletasks()`.
That call also draws the sidebar canvas, so the sidebar showed the new page lit while the old page was still up.
Measured gap, which is refresh plus layout time:

- first visit to a page: Lighting 109 ms, Devices 32 ms, Fans 141 ms, Monitor 134 ms, Overlay 43 ms, Settings 30 ms
- later visits: under 1 ms for most pages, about 15 ms for Fans and about 24 ms for Monitor

At 240 Hz that is several frames, and on first visits up to about 30 frames. The frames from the 9-click burst show
it: six frames with "Lighting" lit in the sidebar over the Home page.

**#48** sets the highlight after the layout pass, right before the page is raised, so the same `_paint_now` draws
both. `restore_check.py` now fails if the target's highlight is already set when the layout pass runs. It fails on
the old code (6 of 16 switches) and passes with the fix. The full suite (154 tests) passes, and the frames show the
sidebar changing together with the page. #48 passed the `windows` check and merged into `main` on 2026-11-20, after I brought it up to date with 2.4.0. 171 tests pass on that branch. Trade-off: on a page's first visit,
the highlight now waits until the page is ready (about 30–170 ms), instead of lighting up at once.

## Rules that must not break

- **Fan safety:** no fan, pump or sensor code changed. `hw_monitor.py` and `rgb_engine.py` are untouched by #46,
  and the `central_rgb.py` diff contains no fan, pump, BIOS or temperature changes. `tests/test_fan_safety.py`
  passes.
- **DDR5 once-per-boot guard:** it lives only on `test-ddr5` (`7a5ce09`, last changed 2026-11-15). That branch is
  not part of `main` and #46 doesn't touch it.
- **No restyling:** #46 changes only how a page switch is drawn (order of layout, raise and paint, the erase flag,
  and the fade-in ending at 100 %). No colours, fonts, sizes or layouts changed. The screenshots match the current
  Gunmetal look.
- **Headers and quiet failure:** every changed source file has the GPL-3.0 header. `cloak`, `freeze`, `thaw` and
  `dwm_flush` do nothing off Windows (`test_page_switch.WindowsHelpersFailQuietly`).
- **Commits:** #46 is authored by steven-t0764 and its message has no Co-Authored-By or Claude line.

## What can only be confirmed on Steven's Windows PC

Xvfb has no DWM, no layered windows, no cloaking and no 240 Hz compositor. Please check these on the real PC with a
build that includes #46 and #48:

1. **Old page under the new one:** click quickly between Overlay → Monitor → Fans and the other pages. No part
   of the previous page should stay visible. The fix depends on Windows erasing to the panel colour (`RDW_ERASE` with
   the class brush), and that only happens on Windows.
2. **Settings scroll smear:** scroll Settings up and down quickly with the wheel and by dragging. "Startup
   animation" and "Updates" should never repeat, and there should be no blank bands. The cause, a window kept at
   254/255 opacity and so layered, only exists on Windows.
3. **Responsiveness:** switching should feel as quick as 2.3.2 or quicker. The first visit to Fans or Monitor can
   take about 0.1 s before both the page and the highlight change.
4. **Restore from the taskbar:** minimize and restore several times, including after leaving it minimized for a
   while. It should come back fully drawn, with no black frame and no old page. This relies on DWM cloaking
   (Windows 8 and later) now that the window is no longer layered.
5. **Fade-in at startup and from the tray:** at the end of the fade there should be no black flash. Reaching
   exactly 100 % makes Tk redraw the whole window once, so watch for a single flash of panel colour.
6. Optional: run `python tests/restore_check.py` on the PC. It records the real restore and switching and writes
   `report.txt` and GIFs to `tests/preview_out/restore_check/`.

## Notes

- Python 3.11 in this container has no tkinter, so I ran everything with Python 3.12 after installing `python3-tk`
  and `python3-pil.imagetk`.
- To get comparable 2.3.2 numbers I ran a scratch copy of the current `restore_check.py` against the 2.3.2 code,
  with `_paint_now` replaced by `update()` because 2.3.2 doesn't have it. Nothing in the repo was changed for that.
  2.3.2 fails some of today's checks (leftover pixels on Home → Lighting, resize, restore path). That is expected:
  those checks were written later, and some of the failures are because the check grabs the screen before 2.3.2
  has drawn.
- In the Settings screenshots, the activity log shows "UI paused 12629 ms". That comes from the check itself (its
  stack shows `restore_check.py` analysing frames on the main thread), not from the app.
