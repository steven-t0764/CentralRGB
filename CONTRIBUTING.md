# Contributing to Central RGB

Thanks for helping out! Central RGB is a small open-source project, so every bug report, device report and pull request makes a real difference.

## Reporting a problem or a device that isn't detected

Open an [issue](../../issues) and include:

- **What happened** and what you expected
- **Your hardware**: in the app, go to **Monitor → Advanced → Copy** and paste the result
- **The activity log**: **Settings → Activity**. Copy the lines around the problem.
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
| `win_effects.py` | Frosted-glass window, dark title bar, opacity |
| `central_rgb.iss` | Inno Setup installer (including the optional PawnIO driver install) |

## Sending a change

1. Fork the repo and create a branch (`fix-ram-detection`, `add-wave-effect`...).
2. Keep each pull request focused on one thing, and describe what you tested and on which hardware.
3. Push your branch. GitHub Actions builds the .exe and installer on Windows, so check that the build passes.
4. Anything that touches **fan control** must keep the safety limits: the minimum speeds, the 90 °C override, and handing fans back to the BIOS on exit.

By contributing, you agree that your contribution is licensed under the project's [GPL-3.0-or-later](LICENSE) license.
