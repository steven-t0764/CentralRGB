# Review: DDR5 RGB RAM lighting (PR #26, issue #24)

Reviewed: `main` at `4568eee` (merge of PR #26, head `2707b1c`), compared against `origin/test-ddr5` at `7a5ce09`.
Reviewer: Fabian (read-only; no product code changed).

## Verdict: **ready**

No defects found. The DDR5 guard on main behaves exactly like `test-ddr5` at 7a5ce09. Central RGB never touches SPD or SMBus itself. The README matches the code, and every test passes. The three findings below are minor wording or robustness notes. None needs a follow-up before release.

## What was checked

| Check | Result |
| --- | --- |
| Guard code on main vs `7a5ce09` | **Unchanged in behaviour.** I compared it function by function with an AST extraction. These are byte-identical: `ddr5_installed`, `boot_id`, `keep_openrgb_running`, `rescan_needs_ok`, `ram_missing_note` (rgb_engine.py), and `_ram_found`, `engine_rows`, `_note_hardware_search`, `_ask_on_main`, `_ram_guard_allows_restart`, `_full_rescan_locked`, `_check_ram` (central_rgb.py). The guard block in `_connect_flow` is now `_connect_flow_locked` behind main's existing connect lock, and its body is identical. `_full_rescan` keeps `why` as the first argument and adds main's existing `wait=` option. `on_close` keeps OpenRGB running with DDR5 exactly as before. `tests/test_ddr5_guard.py`, `tests/ddr5_scenario.py` and the installer's `StopOpenRGB` uninstall line are identical to 7a5ce09. The 7a5ce09 `build.yml` change (test-branch builds) was left out on purpose, as the PR says, and the guard doesn't need it. |
| Additions around the guard | `searched_before` passed to `diagnose_missing_ram` also counts a hidden OpenRGB kept from earlier this boot. Close them passes `why="conflicts"`, so it never restarts OpenRGB once DDR5 RAM is found. Both only add messages or route through the existing guard. |
| No SPD/SMBus writes by Central RGB | **Confirmed.** No SMBus, SPD, i2c, WinRing0 or DeviceIoControl access in `rgb_engine.py` or `central_rgb.py`. The only `ctypes` uses are `IsUserAnAdmin`, DPI awareness, dark title bar and the AppUserModelID. RAM lighting goes only through the OpenRGB SDK client (`openrgb-python`), using the same DRAM path as DDR4. |
| README limits vs code | **Match.** I checked these claims: OpenRGB 1.0+ with PawnIO (`openrgb_too_old` → title "DDR5 RAM not supported by this OpenRGB"); the kit list (`RGB_RAM_PARTS`: Kingston FURY RGB, Corsair Vengeance RGB DDR5, Dominator Platinum/Titanium, G.Skill Trident Z5 / Z5 Neo, T-Force Delta, XPG Lancer); once per boot (`keep_openrgb_running`, `rescan_needs_ok`, Close them guarded); the "if missing" causes (`diagnose_missing_ram` reasons plus `ddr5_unsupported_note`); and effects at the steady RAM rate, one stick at a time, in the sticks' own modes (covered by `test_ddr5_lighting.Effects`). |
| `tests/test_ddr5_guard.py` + `tests/test_ddr5_lighting.py` | **22 tests OK, 0 skipped**, once tkinter and Pillow's ImageTk are available. Without them, the 4 `OneSearchPerBoot` tests skip. |
| `xvfb-run -a python -m unittest discover tests` | **120 tests OK** (17 skipped are Windows-only or optional). |
| `tests/ddr5_scenario.py` / `--ddr4` | All 8 DDR5 and 4 DDR4 steps PASS. |
| Fan safety | `tests/test_fan_safety.py` passes (6 tests). The PR touches no fan, sensor or `hw_monitor.py` code. |
| DDR5 guard unchanged | Yes (see the first row). |
| GPL headers | Present on the new files `tests/ddr5_scenario.py`, `tests/test_ddr5_guard.py`, `tests/test_ddr5_lighting.py`. The changed files keep theirs. |
| Restyling outside the task | None. The `central_rgb.py` diff is logic and message text only, with no colour, font or layout changes. |
| Docs | `CHANGELOG.md` has an Unreleased line. `README.md` has a new "DDR5 RGB RAM" section and a Troubleshooting row. `tests/README.md` lists `test_ddr5_lighting.py`, `test_ddr5_guard.py`, `ddr5_scenario.py`, the `Z790_DDR5_PC` fake and `preview_user_pc.py --ddr5`. |
| Claude/Anthropic lines | None in commit `2707b1c` (authored as steven-t0764) or in the merge commit. None in the PR #26 title or body. |
| `windows` check on PR #26 | success. |

## Findings

1. **README.md, "DDR5 RGB RAM" section, first bullet (minor wording).** It says Central RGB "downloads the newest stable OpenRGB from openrgb.org". The code (`OpenRGBManager.latest_zip_url`) reads the release link from openrgb.org's releases page, then downloads the zip from wherever that link points (currently codeberg.org). If the page can't be read, it falls back to a pinned OpenRGB 1.1 zip. **Fix:** change it to "downloads the newest stable OpenRGB listed on openrgb.org (OpenRGB 1.1 if that page can't be reached)".
2. **rgb_engine.py `boot_id()` (robustness note, not a defect; carried unchanged from 7a5ce09).** The boot is identified by `psutil.boot_time()` rounded down to the minute. On Windows that value is derived from "now minus uptime" and can shift by a second after a clock or NTP adjustment, so a boot near a minute boundary could get a different id. The only effect is message wording: "searched earlier this boot" or the once-per-boot pop-up could be missed or repeated once. The guard itself (keep OpenRGB running, ask before Rescan) does not depend on it. **Fix (optional, later):** round to the nearest minute, or compare with a ±1 minute tolerance. The guard must stay exactly as it is, so this needs its own owner-approved task.
3. **README.md, "If the RAM isn't found" (minor completeness).** The README doesn't mention that RAM temperature reading (LibreHardwareMonitor, Settings) shares the same SMBus. When you turn it on, the app already warns that it can make RGB RAM blink (`central_rgb.py` `_toggle_ram_temps`, around line 3985). It is LibreHardwareMonitor reading, not Central RGB writing to the RAM. **Fix (optional):** add "leave RAM temperatures off in Settings" to the DDR5 tips.

## Limitations

- Not run on a real DDR5 PC. Real detection still depends on OpenRGB support for the kit and board (see the PR's notes on OpenRGB issues 4934 and 5106).
- In this Linux container, the default `python` (3.11) has no tkinter, so I ran the app-level tests with Python 3.12 in a venv with `requirements.txt` and a pip-installed Pillow. The CI `windows` check passed independently.
