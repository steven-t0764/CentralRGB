# Tests

Everything here runs without RGB hardware, and without Windows. **Every new test, fake device or
preview script goes in this folder.**

| File | What it is |
| --- | --- |
| `fake_openrgb.py` | Simulated OpenRGB with 8 demo devices (motherboard, GPU, 2 RAM sticks, fan LEDs, AIO cooler, keyboard, mouse). `install()` points the lighting engine at it. |
| `fake_lhm.py` | Simulated LibreHardwareMonitor: CPU, GPU, motherboard and SSD sensors, plus 5 controllable fans (one is an AIO pump). |
| `fake_presentmon.py` | Fake PresentMon CSV output (1.x and 2.x column layouts) and error text, for the FPS overlay tests. |
| `test_fps_overlay.py` | FPS overlay: reading PresentMon output, picking the game (launchers, Discord/SteelSeries in front, recreated windows) and the status messages shown when it can't count. |
| `test_fan_safety.py` | Checks the fan-safety rules: fans never below 20 %, pumps never below 70 %, all fans to 100 % at 90 °C, and fans handed back to the BIOS on Auto and on close. |
| `preview.py` | Runs the whole app on the fake hardware and saves a screenshot of every page to `tests/preview_out/`. |
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
