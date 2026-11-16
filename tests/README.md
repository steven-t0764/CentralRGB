# Tests

Everything here runs without RGB hardware, and without Windows. **Every new test, fake device or
preview script goes in this folder.**

| File | What it is |
| --- | --- |
| `fake_openrgb.py` | Simulated OpenRGB with 8 demo devices (motherboard, GPU, 2 RAM sticks, fan LEDs, AIO cooler, keyboard, mouse). `install()` points the lighting engine at it. |
| `fake_lhm.py` | Simulated LibreHardwareMonitor: CPU, GPU, motherboard and SSD sensors, plus 5 controllable fans (one is an AIO pump). |
| `test_fan_safety.py` | Checks the fan-safety rules: fans never below 20 %, pumps never below 70 %, all fans to 100 % at 90 °C, and fans handed back to the BIOS on Auto and on close. |
| `test_ddr5_guard.py` | Checks the DDR5 RAM rules: OpenRGB kept running with DDR5, Rescan asks before it would lose found RAM, and the "shut down fully" note. |
| `ddr5_scenario.py` | Walks the real app through the DDR5 rules on the fake hardware (`--ddr4` checks nothing changed for DDR4). Opens a window, so it isn't run by `unittest`. |
| `preview.py` | Runs the whole app on the fake hardware and saves a screenshot of every page to `tests/preview_out/`. |

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
