# Tests

Everything here runs without RGB hardware, and without Windows. **Every new test, fake device or
preview script goes in this folder.**

| File | What it is |
| --- | --- |
| `fake_openrgb.py` | Simulated OpenRGB with 8 demo devices (motherboard, GPU, 2 RAM sticks, fan LEDs, AIO cooler, keyboard, mouse). `install()` points the lighting engine at it. `Z790_DDR5_PC` is a DDR5 PC (two Kingston FURY Beast RGB DDR5 sticks, `KINGSTON_FURY_DDR5_WMI`). `B550_PC` is the owner's PC (4x Corsair Vengeance RGB DDR4, a SteelSeries mouse) with what Windows reports for them; `ram_blocked` / `mouse_blocked` hide those. |
| `test_ram_detect.py` | RGB RAM that Windows reports but OpenRGB misses (4x Corsair Vengeance RGB DDR4 on an MSI B550 board, `fake_openrgb.B550_PC`): the app names the cause (admin, PawnIO, Mystic Light holding the SMBus), and checking never starts another scan. |
| `test_device_detection.py` | The RAM and the mouse on the owner's PC (`fake_openrgb.B550_PC`, with a SteelSeries mouse): both are listed when OpenRGB reports them and nothing OpenRGB reports is dropped; when missing, the Devices page names MSI Center / Mystic Light or SteelSeries GG; Close them stops MSI's services and LEDKeeper2, reports failures and re-detects exactly once. |
| `fake_lhm.py` | Simulated LibreHardwareMonitor: CPU, GPU, motherboard and SSD sensors, plus 5 controllable fans (one is an AIO pump). |
| `fake_presentmon.py` | Fake PresentMon CSV output (1.x and 2.x column layouts) and error text, for the FPS overlay tests. |
| `test_fps_overlay.py` | FPS overlay: reading PresentMon output, picking the game (launchers, Discord/SteelSeries in front, recreated windows) and the status messages shown when it can't count. |
| `test_fan_safety.py` | Checks the fan-safety rules: fans never below 20 %, pumps never below 70 %, all fans to 100 % at 90 °C, and fans handed back to the BIOS on Auto and on close. |
| `test_ram_updates.py` | Checks the RGB RAM flicker fix: RAM gets a steady, lower update rate with the sticks taking turns, unchanged RAM frames are skipped, Breathing runs in the sticks' own hardware mode, and other devices keep the full rate. |
| `fake_github.py` | Fake GitHub Releases API (a real release plus a draft, a pre-release and the test build; can go offline, hit the rate limit or serve a tampered file) for the updater. |
| `test_updater.py` | One-click updater: version ordering, skipping pre-releases, picking the installer or portable exe, refusing a checksum mismatch, offline and rate-limit messages (including a connection that drops mid-read), the helper that waits for a normal close, and the once-a-day auto-check setting (older settings files still load). |
| `preview_updater.py` | Screenshots the Updates rows on the Settings page and the "new version" notice, using the fake GitHub. |
| `test_workflows.py` | Checks the GitHub workflows: auto-merge only merges passing, tested, non-draft PRs and then starts the main build, so every merge commit on main gets the `windows` check. |
| `test_ddr5_lighting.py` | DDR5 RGB RAM on a simulated Intel Z790 PC with two Kingston FURY Beast RGB DDR5 sticks (`fake_openrgb.Z790_DDR5_PC`): DDR5 part numbers recognised, sticks listed as RAM, effects applied (Direct, one stick per tick, their own Static / Breathing modes), the blocked / searched-this-boot / unsupported messages, and the guard still searching only once per boot. |
| `test_ddr5_guard.py` | Checks the DDR5 RAM rules: OpenRGB kept running with DDR5, Rescan asks before it would lose found RAM, and the "shut down fully" note. |
| `ddr5_scenario.py` | Walks the real app through the DDR5 rules on the fake hardware (`--ddr4` checks nothing changed for DDR4). Opens a window, so it isn't run by `unittest`. |
| `preview.py` | Runs the whole app on the fake hardware and saves a screenshot of every page to `tests/preview_out/`. |
| `restore_check.py` | Minimizes and restores the window and switches pages rapidly on the fake hardware, grabbing frames as it goes (`restore.gif`, `switch.gif`, before/after screenshots) and checking the last page clicked is the one shown, fully laid out. Run it on Windows to record the real restore. `test_page_switch.py` runs it under Xvfb. |
| `preview_user_pc.py` | Runs the preview on a simulated copy of the user's PC: MSI B550-A PRO, Razer Huntsman V2 TKL, four Corsair Vengeance RGB DDR4 sticks hidden as if MSI Center held the bus and a SteelSeries mouse hidden as if SteelSeries GG held it, with MSI Center and SteelSeries GG "running". `--ram-visible` / `--mouse-visible` show them; use `--pages Devices --warmup 45` to see the Devices-page note. `--ddr5` runs a DDR5 PC instead (Z790, Kingston FURY RGB DDR5, DDR5 guard on). |
| `preview_overlay_notes.py` | Screenshots the Overlay page preview showing each FPS-counter status note (PresentMon needs admin, no frames yet, exclusive fullscreen). |
| `record_demo.py` | Records the README's "See it in action" GIF: a scripted mouse tour of the real app on the fake hardware (Linux, needs Xvfb, xdotool and ffmpeg). Copy its output to `assets/demo.gif`. |

## Run the tests

From the repo root:

```
python -m unittest discover tests
```

## Preview the app

```
python tests/preview.py                       # every page
python tests/preview.py --pages Fans,Monitor  # just some pages
python tests/preview.py --keep-open           # leave the window open to click around
```

On Linux with no screen, wrap it: `xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview.py`.
It uses a temporary settings folder, so your real Central RGB settings are never touched.
The CPU, memory, network and disk numbers are demo values; add `--real-stats` to show your own.

## Re-record the README demo

```
xvfb-run -a -s "-screen 0 1120x720x24" python3 tests/record_demo.py assets/demo.gif
```

It clicks fixed spots for the default 1120x720 window. If the layout changes, update `TOUR` at the top of the script.
