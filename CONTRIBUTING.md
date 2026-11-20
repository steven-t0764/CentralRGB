# Contributing to Central RGB

Thanks for helping out! Central RGB is a small open-source project, so every bug report, device report and pull request makes a real difference.

## Reporting a problem or a device that isn't detected

Open an [issue](../../issues) and include:

- **What happened** and what you expected
- **Your hardware**: in the app, go to **Monitor → Advanced → Copy** and paste the result
- **The activity log**: **Settings → Activity**, or attach `%APPDATA%\CentralRGB\activity.log`. It also records any moment the window paused, with what the app was doing.
- Your **Windows version**, and whether you used the **installer** or the **portable** .exe
- For lighting problems: does the device work in [OpenRGB](https://openrgb.org) on its own? If not, it needs support in OpenRGB first.
- For fan or sensor problems: does it show up in [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) on its own?

## Running from source

1. Install Python 3.12 (tick "Add python.exe to PATH").
2. From an **administrator** terminal in the project folder:

   ```powershell
   py -m pip install -r requirements.txt
   py central_rgb.py
   ```

3. To build the .exe and installer, run `build.bat` (the installer also needs [Inno Setup](https://jrsoftware.org/isdl.php)).

## Where things live

| File | Responsibility |
|---|---|
| `central_rgb.py` | Window, pages and custom-drawn widgets |
| `rgb_engine.py` | Finding, downloading and starting OpenRGB, lighting effects, system check, settings |
| `hw_monitor.py` | LibreHardwareMonitor sensors, fan-curve logic and safety limits, system details |
| `win_effects.py` | Dark title bar, title bar colors, flicker-free redraws (no black flashes on restore or page switch) |
| `updater.py` | In-app updates: finds the newest real release, downloads and SHA-256-checks it, installs or swaps it after a normal close |
| `central_rgb.iss` | Inno Setup installer (including the optional PawnIO driver install) |
| `tests/` | Simulated hardware, the fan-safety tests and a page-by-page preview (see [tests/README.md](tests/README.md)) |

## Sending a change

1. Create a branch (`fix-ram-detection`, `add-wave-effect`...). Collaborators can branch in this repo; everyone else, fork it first. Don't push straight to `main`.
2. Keep each pull request focused on one thing, and describe what you tested and on which hardware.
3. Push your branch and open a pull request into `main`. GitHub Actions runs the tests, builds the .exe and installer on Windows and runs the app's self-test.
   - **If it all passes, the pull request merges itself** (for branches in this repo) and the branch is deleted; the auto-merge then starts the Windows build on `main` so the merge commit gets its own `windows` check. If something fails, it stays open: fix it and push again.
   - Want someone to look first? Open it as a **draft**, or add the label `do-not-merge`; then it's merged by hand.
   - To try a build on a real PC before merging, push it to the `test` branch: it publishes a **Test build (not a release)** pre-release with the .exe and installer.
4. Anything that touches **fan control** must keep the safety limits: the minimum speeds, the 90 °C override, and handing fans back to the BIOS on exit. `python -m unittest discover tests` checks them.
5. Put any new test, fake device or preview script in the `tests/` folder.
6. Add a plain-English line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md) and update the README if anything you changed is visible to users. AI agents working in this repo follow [CLAUDE.md](CLAUDE.md).

By contributing, you agree that your contribution is licensed under the project's [GPL-3.0-or-later](LICENSE) license.
