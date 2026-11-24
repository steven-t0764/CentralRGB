# Tests

Everything here runs without RGB hardware, and without Windows. **Every new test, fake device or
preview script goes in this folder.**

| File | What it is |
| --- | --- |
| `fake_openrgb.py` | Simulated OpenRGB with 8 demo devices (motherboard, GPU, 2 RAM sticks, fan LEDs, AIO cooler, keyboard, mouse). `install()` points the lighting engine at it. `Z790_DDR5_PC` is a DDR5 PC (two Kingston FURY Beast RGB DDR5 sticks, `KINGSTON_FURY_DDR5_WMI`). `B550_PC` is the owner's PC (4x Corsair Vengeance RGB DDR4, a SteelSeries mouse) with what Windows reports for them; `ram_blocked` / `mouse_blocked` hide those, `ram_late` shows the RAM only after that many refreshes. `B550_PRO_PC` is the same PC with four Corsair Vengeance RGB PRO sticks (`CORSAIR_VENGEANCE_PRO_DDR4_WMI`). |
| `test_ram_detect.py` | RGB RAM that Windows reports but OpenRGB misses (4x Corsair Vengeance RGB DDR4 on an MSI B550 board, `fake_openrgb.B550_PC`): the app names the cause (admin, PawnIO, Mystic Light holding the SMBus), and checking never starts another scan. |
| `test_ram_vengeance_pro.py` | The owner's current RAM, 4x Corsair Vengeance RGB PRO DDR4 (CMW32GX4M2D3600C18, maker "Unknown" in Windows, `fake_openrgb.B550_PRO_PC`): maker and product line from part numbers and JEDEC codes, the Settings RAM line, only OpenRGB 1.0+ downloaded and its version known, switched-off RAM detectors turned back on before launch, the RAM diagnostics report (activity.log once, `ram-diagnostics.txt`), and RAM that OpenRGB finds late picked up without a restart (`ram_late`). |
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
| `preview.py` | Runs the whole app on the fake hardware and saves a screenshot of every page to `tests/preview_out/`. `--appearance light` (and `--theme <key>`) start it in Light mode or another theme. |
| `test_appearance.py` | Settings → Appearance (Dark / Light): a missing or unknown setting means Dark, every theme has a complete light palette with WCAG AA text contrast, Light then Dark gives back the exact dark colours, and under Xvfb a click on the toggle rebuilds the Settings page in place without errors and saves the choice. Light-mode polish: slider knobs stay visible on hover, white swatches are outlined, Breathing fades into the panel instead of to black, the sensor-tree selection shows, chart guides darken, and a theme switch changes the title bar and window colour before rebuilding; each check also proves Dark gets its old value. |
| `preview_user_pc.py` | Runs the preview on a simulated copy of the user's PC: MSI B550-A PRO, Razer Huntsman V2 TKL, four Corsair Vengeance RGB DDR4 sticks hidden as if MSI Center held the bus and a SteelSeries mouse hidden as if SteelSeries GG held it, with MSI Center and SteelSeries GG "running". `--ram-visible` / `--mouse-visible` show them; use `--pages Devices --warmup 45` to see the Devices-page note. `--ddr5` runs a DDR5 PC instead (Z790, Kingston FURY RGB DDR5, DDR5 guard on). `--vengeance-pro` runs the PC as of 2026-11-20: four Vengeance RGB PRO sticks and only SteelSeries GG / Engine running. |
| `restore_check.py` | Minimizes and restores the window and switches pages rapidly on the fake hardware, grabbing frames as it goes (`restore.gif`, `switch.gif`, before/after screenshots) and checking the last page clicked is the one shown, fully laid out, that no frame grabbed during the restore or the switching has near-black boxes (the black flashes), that every frame/canvas has its own background, that right after back-to-back page switches (Overlay → Monitor → Fans and every neighbour pair) the page area shows nothing of the previous page (`stale_*.png`), and that scrolling Settings up and down looks the same after every step as the page fully redrawn there, with no smeared rows (`scroll.gif`), and that the sidebar highlight isn't drawn before the new page is laid out. It also reports page-switch and scroll-step timings. Run it on Windows to record the real restore. `test_page_switch.py` runs it under Xvfb. |
| `test_repaint.py` | No black flashes and no stale pixels: checks the black-box, left-behind-page and smear detectors on made-up frames, that no theme uses near-black, that `thaw` erases to the panel colour, that the window isn't left layered (fade-ins end at exactly 100 % and draw once), that page switches don't freeze drawing, and under Xvfb runs `restore_check.py` and fails if any captured frame has black boxes, a switch leaves the previous page behind, Settings smears when scrolled, or any container is left at Tk's default background. |
| `test_owners_devices.py` | The owner's PC (`fake_openrgb.OWNERS_PC`): ARGB headers (JRAINBOW1/2) start at 0 LEDs and are reported until sized; resizing clamps to the header's range, redoes the device and is set again after an OpenRGB restart; a header set to 0 on purpose isn't reported; OpenRGB's log tells running vs finished detection and which USB brand it waits on; `_settle_devices` keeps reading while OpenRGB is still detecting and picks up a keyboard and mouse that appear minutes later, gives up after 10 minutes, and stops as before when there's no log. |
| `preview_headers.py` | Screenshots of the owner's PC on the fake hardware: the Devices page with the "Fan or strip lights not set up" note, the motherboard's Customize page with **Connected LEDs**, the same after setting JRAINBOW1 to 24, and the Devices page after. |
| `test_openrgb_version.py` | OpenRGB's blank exe version ("0.0.0.0") reads as unknown, never as "too old"; PawnIO modules next to OpenRGB.exe mean 1.0 or newer; an OpenRGB Central RGB didn't install, with no known version, is named with its folder in the missing-RAM message (never Central RGB's own copy). Uses the owner's 4x Corsair Vengeance RGB PRO sticks. |
| `test_auto_release.py` | When the nightly/after-build workflow publishes a release (`tools/auto_release.py`): small tweaks wait, 3+ changelog entries or one marked `<!-- big -->` cut a release, an `APP_VERSION` bump releases that version, and the next version number is picked (minor for `<!-- big -->`/`<!-- feature -->`, patch otherwise). |
| `test_settings_save.py` | Settings writes are coalesced: a burst of changes writes `settings.json` once, shortly after, on a background thread; `flush()` writes at once; the file format and old files still load. |
| `test_engine_idle.py` | The lighting loop is cheap when a still colour is showing (slow ticks, no per-frame colour work) yet a change reaches devices within a frame, and animations keep a steady frame rate. |
| `test_hw_monitor_ticks.py` | Slow Monitor extras (process count, CPU clock, disk usage) refresh on a slower cadence, live readings stay per tick and `snapshot()` keeps its shape. |
| `test_ui_timers.py` | Background UI timers do no unseen work: the Activity box keeps at most `LOG_LINES` lines, the overlay poll idles when off and hidden, the tray skips drawing the preview, and closing flushes pending settings. |
| `test_animation_cost.py` | Live previews (Lighting, Home, Devices) cost little per frame: staggered half-rate effect tiles, unchanged LEDs not redrawn, still effects drawn once, and per-frame reads done once. |
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
python tests/preview.py --appearance light    # every page in Light mode
```

On Linux with no screen, wrap it: `xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview.py`.
It uses a temporary settings folder, so your real Central RGB settings are never touched.
The CPU, memory, network and disk numbers are demo values; add `--real-stats` to show your own.

## Re-record the README demo

```
xvfb-run -a -s "-screen 0 1120x720x24" python3 tests/record_demo.py assets/demo.gif
```

It clicks fixed spots for the default 1120x720 window. If the layout changes, update `TOUR` at the top of the script.
