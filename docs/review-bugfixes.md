# Review of the four bug-fix branches (bugs 2-5)

Reviewed on 2026-11-19 against `main` at `44b761a`. Each branch was checked out on its own, then all four were
merged together in this order: test-ram-detect, fix-ram-flicker, fix-fps-counter, fix-restore-flicker.

For every branch I checked:

- `python -m unittest discover tests`, run under Xvfb with Python 3.12, CustomTkinter and Pillow
- the fan safety rules: `hw_monitor.py` and the fan code are untouched, and `tests/test_fan_safety.py` passes
- the DDR5 once-per-boot RAM guard: it lives only on `test-ddr5`, and none of the four branches touch it
- commit messages: none has a Co-Authored-By, Claude-Session, "Generated with Claude Code" or any other
  Claude/Anthropic line. Every commit is authored by steven-t0764.
- that nothing outside the bug was restyled
- that every new source file has the GPL-3.0 header

| Branch | Commit | Tests | Verdict |
| --- | --- | --- | --- |
| test-ram-detect | `3df5c92` | 24 passed | **ready** |
| fix-ram-flicker | `6ffbe4c` | 22 passed | **needs changes** (two small fixes) |
| fix-fps-counter | `a1b3530` | 34 passed | **ready** |
| fix-restore-flicker | `d740552` | 16 passed | **ready** |
| all four merged in order | - | 54 passed | merges cleanly, no conflicts |

## test-ram-detect: ready

**What it does.** When Windows reports RGB RAM (it recognises the Corsair `CMR...` part numbers, so the user's
Vengeance RGB DDR4 counts) but OpenRGB finds no RAM device, the Devices page now shows a yellow bar and the activity
log says why. The possible reasons are: not running as administrator, PawnIO missing, or MSI Center / Mystic Light
(or another app that drives RAM lighting) holding the SMBus. After **Close them**, RAM detection runs one extra time,
and only once.

**Checks.** All 24 tests pass, including the new `tests/test_ram_detect.py`. The fake 4 x Vengeance RGB DDR4 /
MSI B550 PC added to `tests/fake_openrgb.py` is opt-in, so the default demo devices are unchanged. The extra
detection is limited by the `_ram_retry` flag: Close them already re-detects once, and if the RAM is still missing
with nothing blocking the bus, one more detection runs, then the flag is cleared. There is no loop. No restyling,
and fan code is not touched.

**Notes.**

- The extra detection restarts the hidden OpenRGB. When `test-ddr5` is merged later, this path should go through
  the DDR5 guard (on a DDR5 PC, a second search in the same boot loses the RAM). The user's PC is DDR4, so it
  doesn't matter for them now.

## fix-ram-flicker: needs changes (two small fixes)

**What it does.** RAM sticks get their own steady 10 updates a second, counted in loop ticks, and take turns on the
SMBus. A RAM frame is only sent when some LED moved by 4 or more. Breathing and Color Cycle use the stick's own
hardware mode when it has one. A log line warns when iCUE, Mystic Light or a similar app is also writing to the RAM.
Other devices keep 30 FPS. The loop body moved into `LightingEngine.step()` so it can be tested.

**Checks.** All 22 tests pass, including the new `tests/test_ram_updates.py`. The `step()` refactor keeps the old
loop's behaviour for non-RAM devices. Off-slot changes are kept in `ram_pending` and sent at the stick's next slot,
so slider changes aren't lost. No restyling, and fan code is not touched.

**Changes needed.**

1. **The new log line sends the user to the wrong page.** It says "Close it with 'Close them' on the Home page",
   but the Close them button and the conflict bar are on the **Devices** page (`central_rgb.py`, `_page_devices`).
   Change "Home" to "Devices".
2. **On the user's PC, two sticks share a slot.** RAM runs every `round(30 / 10) = 3` ticks, and a stick's slot is
   `(frame + ram_idx) % 3`. With four sticks (the user has 4 x 16 GB), sticks 1 and 4 land on the same tick, so two
   sticks are written at once on the shared SMBus. That goes against what the commit says. Each stick still gets
   10 updates a second, so this is mild, but the branch exists for exactly this PC. A fix: give each stick its own
   tick in a cycle of `max(ram_every, number of sticks)`, or allow at most one RAM write per tick.

**Minor, can wait.** This branch's `RAM_WRITERS` and test-ram-detect's `SMBUS_APPS` are the same list of apps under
two names. With both merged, a blocked PC can get two similar warnings in the log, one from each.

## fix-fps-counter: ready

**What it does.** PresentMon restarts by itself (after 2 s, 5 s, then 10 s) when it stops, and its error output is
read instead of thrown away. The Overlay page and the overlay itself explain in plain English why there's no number
(needs admin, download failed, blocked by antivirus, keeps stopping, too many trace sessions, no frames yet,
exclusive fullscreen). Switching the overlay off and straight back on can no longer let the old stop kill the new
PresentMon (`stop_async`). Launchers, anti-cheat helpers, Discord, SteelSeries GG and MSI Center can't take the
overlay from the game. Frames are counted per swap chain, and both PresentMon 1.x and 2.x columns are read.

**Checks.** All 34 tests pass, including `tests/test_fps_overlay.py` with fake PresentMon CSV output. The
Windows-only calls (`foreground_window`, `game_window_state`, `monitor_rect`, the PresentMon run) all check
`eng.IS_WIN` and do nothing elsewhere. The Overlay page renders without errors in the preview on the merged code.
The `central_rgb.py` changes are limited to the overlay toggle and `_overlay_tick`: the old `_SkipStatus` trick was
removed because the new status text replaces it. No restyling, and fan code is not touched.

## fix-restore-flicker: ready

**What it does.** On restore from the taskbar, the window is cloaked (DWM, Windows 8+) while it is fully drawn, then
shown. Before, Windows showed an empty black window that Tk filled in piece by piece. After each page switch, all
pending drawing happens at once. A click that arrives during a switch no longer starts a second switch on top of it:
the last page clicked opens right after, which covers "Settings sometimes didn't open". A page left pinned at the old
size during a resize comes back at full size.

**Checks.** All 16 tests pass, including `tests/test_page_switch.py`, which runs `tests/restore_check.py` under Xvfb
(about 15 s). The window is always uncloaked: in the `finally` block, plus a 1-second backstop. `cloak()` and
`dwm_flush()` return quietly off Windows and on Windows 7. `tests/preview.py` was only reorganised into
`start_app()` so `restore_check.py` can use it, and the full preview still saves all 8 pages. No restyling, and fan
code is not touched.

## Merging all four together

Merging test-ram-detect, then fix-ram-flicker, then fix-fps-counter, then fix-restore-flicker on top of `main`
causes **no conflicts**. Git combines `rgb_engine.py`, `central_rgb.py` and `tests/README.md` automatically. On the
merged code, every `.py` file compiles, all 54 tests pass, and `tests/preview.py` renders every page without errors.
The only overlap is the duplicate RAM-app list and warning described under fix-ram-flicker.

## Not checked here (needs the real PC)

- Whether the DWM cloak really removes the black flash at 240 Hz on the Odyssey G40B, and whether page switches
  look complete. Xvfb has no DWM.
- Whether OpenRGB finds the Vengeance RGB DDR4 sticks once MSI Center / Mystic Light is closed, and whether the
  hardware Breathing / Color Cycle modes look right on those sticks.
- PresentMon's real behaviour: admin prompts, antivirus, trace-session limits, and real games in borderless vs
  exclusive fullscreen.
