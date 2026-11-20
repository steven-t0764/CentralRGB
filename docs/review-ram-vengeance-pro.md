# Review of the Vengeance RGB PRO RAM fix (PR #47)

Reviewed on 2026-11-20 against `main` at `30d11ec` (PR #47 merged as `c98121a`, change commit `3387715`; Version
2.4.0 and the sidebar fix landed after it). Issue #45, plan `bugfix-1`, phase `regressions-1`.

**Verdict: ready. No fix PR was needed.**

## What I checked

| Check | Result |
| --- | --- |
| `CMW32GX4M2D3600C18` is named Corsair Vengeance RGB PRO | **pass.** `ram_summary(["Unknown CMW32GX4M2D3600C18"] * 4)` gives `4x Corsair Vengeance RGB PRO (CMW32GX4M2D3600C18)`. The same name comes out when Windows reports the maker as `Unknown`, `Corsair`, the JEDEC code `029E` / `9E00000000000000`, or nothing. `rgb_ram_sticks()` counts it as RGB RAM (`Corsair Vengeance RGB PRO`), so a miss is reported. |
| Diagnostics entry has OpenRGB version, elevation, PawnIO, detectors run, part numbers | **pass.** `ram_diagnostics()` writes one line each for: OpenRGB version (and "too old" below 1.0) with its path; how OpenRGB was started and whether *it* runs as administrator; whether Central RGB runs as administrator; PawnIO driver plus the PawnIO SMBus modules next to OpenRGB.exe; CPU / SMBus type; OpenRGB's RAM detectors from `OpenRGB.json` (on/OFF); devices OpenRGB reported; apps holding the SMBus; RAM part numbers as Windows wrote them and what they are; OpenRGB's own log lines about the SMBus / RAM detection (that is what shows which detectors actually ran). It goes to `activity.log` (once, again only if it changes) and `%APPDATA%\CentralRGB\ram-diagnostics.txt`. |
| DDR5 once-per-boot RAM guard untouched | **pass.** The diff (`be8c9f0..c98121a`) only touches `rgb_engine.py` from `latest_zip_url` onward and the RAM helpers; `boot_id()`, `openrgb_boot`, `ram_note_boot` and `central_rgb.py` are not changed. `tests/test_ddr5_guard.py` and `tests/test_ddr5_lighting.py` pass. |
| Fan safety untouched | **pass.** `hw_monitor.py` and the fan code are not in the diff; `tests/test_fan_safety.py` passes. |
| Tests | **pass.** `python -m py_compile` on every `.py`, then `xvfb-run -a python3.12 -m unittest discover tests`: 171 tests, OK. The `windows` check on PR #47 passed (run 44836021747). `tests/test_ram_vengeance_pro.py` has 17 tests for part numbers, the OpenRGB version/zip choice, the detectors, the diagnostics and RAM found late. |
| Docs | **pass.** CHANGELOG `Unreleased` line, README (system check and troubleshooting row), CONTRIBUTING (attach `ram-diagnostics.txt`), tests/README (`B550_PRO_PC`, `ram_late`, `--vengeance-pro`, the new test file). New test file and fakes keep the GPL-3.0 header. |

## Things worth knowing (not bugs, no change made)

- If an OpenRGB older than 1.0 is already installed (saved path, Program Files, or next to Central RGB),
  Central RGB keeps using it and only logs that it is too old. It does not replace it by itself.
- OpenRGB's RAM detectors are switched back on only when Central RGB *starts* OpenRGB. Because the DDR5 guard
  keeps the hidden OpenRGB running for the whole boot, a detector you switched off is fixed on the next start
  (reboot, or the Rescan button on the Devices page, which restarts it).
- A Windows maker string that looks like hex but isn't a known JEDEC code is treated as "unknown" and the
  name falls back to the part number. Harmless for Corsair, G.Skill (F4-/F5-) and Kingston (KF).

## What Steven must check on his PC

Only a real PC can prove the RAM is found; the tests use a fake OpenRGB. Use Central RGB 2.4.0 or newer
(the build from `main`), with the four CMW32GX4M2D3600C18 sticks fitted.

1. **Before starting:** quit MSI Center / Mystic Light, iCUE and any OpenRGB you started yourself (check the
   tray and Task Manager). SteelSeries GG can stay, it doesn't hold the RAM's SMBus.
2. **Start Central RGB as administrator** (right-click > Run as administrator, or the installer's shortcut).
3. **Settings > system check:** the RAM line should read
   `RAM sticks: 4 (4x Corsair Vengeance RGB PRO (CMW32GX4M2D3600C18))`. Not `Unknown`.
   *If it still says Unknown:* send a screenshot of that line.
4. **OpenRGB version:** open `%APPDATA%\CentralRGB\activity.log` (Win+R, paste the path). Find
   `Starting OpenRGB <version> SDK server`. The version must be **1.0 or newer**. If it says 0.9 or
   "older than 1.0", close Central RGB, delete or rename that old OpenRGB folder (the path is in the same
   log line), start Central RGB again and let it download OpenRGB when it asks (or browse to a 1.0+
   OpenRGB.exe). Then check the log says `OpenRGB installed to ... (version 1.x)`.
5. **PawnIO:** the system check should say PawnIO is installed. If not, rerun the Central RGB installer
   (or install PawnIO from pawnio.eu), then reboot.
6. **Wait about 30 seconds** after the window opens, then open the **Devices** page.
   - **Pass:** the four Vengeance RGB PRO sticks are listed and change colour with the rest.
   - **Fail:** the "RGB RAM not detected" note shows. Go to step 7.
7. **If the RAM is missing:** open `%APPDATA%\CentralRGB\ram-diagnostics.txt` and check that it has all of
   these lines: `OpenRGB:` (version), `OpenRGB started:` with `running as administrator: yes`,
   `PawnIO driver installed: yes` and the modules (on the B550 / AMD board it must list `SmbusPIIX4.bin`),
   `CPU / SMBus: AMD (piix4 ...)`, `OpenRGB RAM detectors` (none should say OFF), `RAM part numbers` with
   `4x "... CMW32GX4M2D3600C18" = Corsair Vengeance RGB PRO`, and an `OpenRGB log` line.
   Attach the file to issue #45 or a new issue. If the file is missing or any of those lines is missing,
   say which.
8. **Rescan once:** press **Rescan** on the Devices page (it may ask first because of the once-per-boot guard), wait 30 s,
   and check the Devices page again. Note whether the result changed.
9. **Fans still safe:** on the Fans page, every fan stays at 20 % or above and the pump at 70 % or above; close
   Central RGB and check the fans go back to the BIOS curve (they should get audibly normal within seconds).

Report back: the RAM line from step 3, the OpenRGB version from step 4, pass/fail from step 6, and
`ram-diagnostics.txt` if it failed.
