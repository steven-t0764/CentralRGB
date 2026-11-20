# Review: RAM and mouse detection (PR #23)

Reviewed: `main` at `d1f6525` (merge of PR #23, commit `12e7cf7`). Issue #21, review issue #22.
Product code was only read, never changed.

## Verdict: needs changes

The RAM fix and the **Close them** flow are sound, and OpenRGB is never restarted in a loop. All
checks pass. **There is one defect in the new mouse check.** The Devices page shows a permanent
"Mouse not detected" warning for ordinary mice that have no RGB at all: any Logitech mouse, any HP
mouse (reported as "HyperX"), and ASUS or Corsair office mice. Finding 1 needs a follow-up task.
The other findings are small.

## What was checked

| Check | Result |
| --- | --- |
| `python -m py_compile` on the 6 changed `.py` files | OK |
| `xvfb-run -a python -m unittest tests.test_device_detection` | 16 tests OK, 0 skipped (with the full requirements: Python 3.12 + tkinter + Pillow with ImageTk) |
| `xvfb-run -a python -m unittest discover tests` | **98 tests OK, 0 skipped**, including `test_fan_safety.py` |
| `tests/preview_user_pc.py --pages Devices --warmup 45` | Under "Other RGB software is running: MSI Center / Mystic Light, SteelSeries GG", the note reads **"Not detected: RGB RAM, Mouse"**. It names MSI Center / Mystic Light as holding the RAM's SMBus and SteelSeries GG as holding the mouse (USB ID 1038:1824), and says to press **Close them** for both. It also shows the "OpenRGB was started outside Central RGB… press Rescan" line. Only the board and keyboard cards are shown. |
| Same with `--ram-visible --mouse-visible` | No note. 7 cards: MSI B550-A PRO, Razer Huntsman V2 TKL, SteelSeries Rival 3, Corsair Vengeance RGB DDR4 DIMM 1-4 |
| No restart loop | Confirmed (see below) |
| Fan safety | Unchanged. The diff touches no fan, pump, curve or BIOS-handback code, `tests/test_fan_safety.py` is untouched and passes. |
| DDR5 once-per-boot guard | Unchanged. PR #23 didn't touch `test-ddr5` (still at `7a5ce09`) or any DDR5 code. |
| GPL-3.0 header | Present on all 6 changed `.py` files |
| Restyling outside the task | None. `ram_bar` was renamed to `missing_bar` with the same colours, fonts and placement. |
| CHANGELOG / README / tests README | All updated in the same PR |
| Claude/Anthropic lines in commit `12e7cf7`, merge `d1f6525` or the PR text | None |

## Each cause in the PR

1. **"Central RGB never drops devices"**: correct. `test_unknown_and_lightless_devices_are_not_dropped` and `test_ram_and_mouse_are_listed` cover it.
2. **OpenRGB version / WinRing0**: sound. `openrgb_version()` reads the version from the release-zip folder name, and `openrgb_too_old()` flags versions below 1.0. `1.0rc1` correctly counts as new enough. If OpenRGB is installed in a folder with no version in its name (for example `Program Files\OpenRGB`), the check is skipped and nothing is wrongly flagged.
3. **MSI Center / Mystic Light**: sound. Processes and services are now matched by exe name *or* by the MSI Center / Mystic Light install folder, so LEDKeeper2 and the other helpers are caught too. When `sc config`, `sc stop` or terminate fails, the user is told to run Central RGB as administrator instead of seeing nothing. `wait_for_conflicts_gone()` waits up to 10 s. Folder matching also stops non-RGB MSI Center services. That is the intended effect, and the README says so.
4. **Stale hidden OpenRGB**: sound. `own_copies()` now also recognises an OpenRGB started with `--server --noautoconnect` from any folder, so both start-up and **Rescan** restart it. See finding 4 for a side effect.
5. **Mouse**: the diagnosis and wording are right for the owner's SteelSeries mouse. The new check's coverage is too broad, though (finding 1), and in one case too narrow (finding 2).

## OpenRGB is never restarted in a loop

- `_check_missing()` runs at the end of `_settle_devices()`. It only logs and updates the note, and never starts a scan. The old `_ram_retry` path that could restart OpenRGB again is gone.
- **Close them** runs `_after_close_conflicts()`, which calls `_full_rescan(wait=True)` exactly once.
- `_connect_flow_locked()` restarts a stale copy only once, at start-up.
- `test_rescan_happens_once_after_close_them` and `test_still_missing_after_close_them_does_not_loop` pass.

## Findings

1. **`rgb_engine.py`: `RGB_MOUSE_VENDORS` / `rgb_mice()`. Defect: false "Mouse not detected" warnings.**
   A mouse counts as an RGB mouse if its USB vendor ID is on the list, whatever the model. Checked against `main`:
   - `diagnose_missing_mouse(['Motherboard'], mice=['HID\\VID_046D&PID_C077…'])` gives "Logitech mouse connected (USB ID 046D:C077) but OpenRGB didn't report it". C077 is a plain Logitech M105.
   - `…VID_03F0&PID_094A…` gives "**HyperX** mouse connected". 03F0 is HP Inc.'s vendor ID, so every HP USB mouse is reported as a HyperX mouse.
   - The same applies to non-RGB ASUS (0B05) and Corsair (1B1C) mice.

   On such PCs the yellow warning never goes away, and it tells the user to look up openrgb.org/devices.html for a mouse that has no lighting.

   **Fix:** report a missing mouse only when one of these is true:
   - (a) that brand's RGB app is running (a `blocker` exists), or
   - (b) the vendor *and* product ID appear on an allow-list of RGB mouse PIDs (for example taken from OpenRGB's supported-devices list). For 03F0, use HyperX product IDs only.

   Otherwise drop the "doesn't support that model yet" message. Add tests for 046D:C077 and 03F0:094A that expect `None`.
2. **`rgb_engine.py`: `rgb_mice()` drops any mouse whose VID:PID also appears in `KEYBOARD_INVENTORY`. Minor.**
   Wireless receivers (Logitech Lightspeed 046D:C539, SteelSeries and Razer dongles) show up as both a keyboard and a mouse, so a missing wireless RGB mouse is never reported. Checked: `…VID_046D&PID_C539&MI_01` with a keyboard on `…C539&MI_00` gives `None`.
   **Fix:** exclude only matching keyboard interfaces (same VID:PID *and* same `MI_xx`), or exclude a VID:PID only when the device is a known keyboard, not a receiver.
3. **`central_rgb.py`: `_full_rescan()` / `_full_rescan_locked()`. Minor.**
   The rescan lock is released as soon as OpenRGB has been restarted. `_settle_devices()`, the 25-90 s detection pass, then runs on a separate background thread outside the lock. So `wait=True` only waits for the restart part, not for detection to finish. A **Rescan** click during detection restarts OpenRGB mid-probe and starts a second `_settle_devices()`. This is not a loop, since each click gives one restart, but the docstring claims more than the code does. Also, if `acquire(timeout=120)` runs out, the rescan after Close them is skipped with no log line.
   **Fix:** hold the lock (or a separate `_detecting` flag) until `_settle_devices()` returns, and log when the timeout skips the rescan.
4. **`rgb_engine.py`: `own_copies()`. Minor.**
   Any OpenRGB running with `--server --noautoconnect` now counts as Central RGB's own copy, so start-up and Rescan will terminate it. That includes one the user started from a shortcut with those flags, which is rare. The "started outside Central RGB" message never appears for that copy either.
   **Fix:** acceptable as is. Alternatively, record the PID of every OpenRGB Central RGB starts (in the settings folder) and match on that PID as well as the flags.
5. **Devices page: the combined "Not detected: RGB RAM, Mouse" note. Nit.**
   The RAM summary line and the mouse summary line look the same as the bullet text, so the two sections run into each other (see the preview).
   **Fix:** put a blank line between the sections in `_missing_texts()`, or start each summary with "RAM:" / "Mouse:".
6. **`README.md`: troubleshooting row. Nit.**
   The row says the note is titled **RGB RAM not detected**. When the RAM and the mouse are both missing, the title is "Not detected: RGB RAM, Mouse". **Fix:** mention both titles.

## Not verifiable here

These need the real PC: whether every MSI Center service on that install stops (admin rights, dependent services), whether OpenRGB 1.x then finds the four sticks through PawnIO, and whether OpenRGB supports the exact SteelSeries mouse model.
