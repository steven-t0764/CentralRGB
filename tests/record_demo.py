# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Record the README's "See it in action" demo (assets/demo.gif) on simulated hardware.

Linux only (needs Xvfb, xdotool and ffmpeg):

    xvfb-run -a -s "-screen 0 1120x720x24" python3 tests/record_demo.py [out.gif]

A scripted mouse tour clicks through the real app: the color wheel, swatches, effects and a preset,
the Devices page, a fan profile and curve, then Monitor and Advanced. The screen is recorded with
ffmpeg, a Windows-style title bar is added, and the result is written as a GIF (default
tests/preview_out/demo.gif; copy it to assets/demo.gif when updating the README).

The tour uses window coordinates for the default window size (1120x720). If the layout changes, take
screenshots with tests/preview.py and update TOUR below.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

W, H = 1120, 720            # app window = whole Xvfb screen
FPS = 20
TITLE_H = 32

# (action, args...) in window coordinates. "wait" is seconds.
TOUR = [
    ("wait", 3.8),                                   # splash animation + the window fading in
    ("click", 72, 113), ("wait", 1.2),               # Lighting
    ("wheel_drag", 356, 320, 62), ("wait", 0.8),     # drag the color wheel around
    ("click", 334, 431), ("wait", 0.9),              # swatches
    ("click", 400, 431), ("wait", 0.9),
    ("click", 660, 252), ("wait", 2.2),              # Breathing
    ("click", 910, 252), ("wait", 2.4),              # Rainbow Wave
    ("click", 571, 515), ("wait", 2.6),              # Aurora preset
    ("click", 73, 147), ("wait", 1.3),               # Devices
    ("click", 620, 504), ("wait", 1.0),              # keyboard off...
    ("click", 620, 504), ("wait", 1.0),              # ...and on again
    ("click", 63, 181), ("wait", 1.2),               # Fans
    ("click", 583, 104), ("wait", 1.6),              # Balanced
    ("click", 1029, 104), ("wait", 0.8),             # Custom
    ("drag", 633, 235, 633, 205), ("wait", 0.5),     # reshape the curve
    ("drag", 531, 274, 531, 300), ("wait", 1.4),
    ("click", 72, 215), ("wait", 3.0),               # Monitor
    ("click", 1053, 44), ("wait", 1.6),              # Advanced
    ("scroll", 520, 450, 6), ("wait", 1.4),
    ("click", 72, 113), ("wait", 1.5),               # back to Lighting
]

DEMO_SYSTEM = [
    ("Operating system", [("Windows", "Microsoft Windows 11 Pro"), ("Version", "10.0.26100 (build 26100)"),
                          ("Architecture", "64-bit"), ("Computer", "DEMO-PC")]),
    ("Processor", [("Model", "AMD Ryzen 7 7800X3D 8-Core Processor"), ("Cores / threads", "8 / 16"),
                   ("Max clock", "4201 MHz"), ("L2 / L3 cache", "8 MB / 96 MB"), ("Socket", "AM5")]),
    ("Motherboard", [("Board", "ASUSTeK COMPUTER INC. ROG STRIX B650-A GAMING WIFI"),
                     ("BIOS", "American Megatrends Inc. 3057 (2026-08-14)")]),
    ("Memory", [("Installed", "32 GB in 2 sticks"),
                ("DIMM 1", "16 GB  Corsair CMH32GX5M2B6000C30  @ 6000 MHz"),
                ("DIMM 2", "16 GB  Corsair CMH32GX5M2B6000C30  @ 6000 MHz")]),
    ("Graphics", [("GPU 1", "NVIDIA GeForce RTX 4070 SUPER  (driver 32.0.15.8157)"), ("Display", "2560x1440 @ 165Hz")]),
    ("Storage", [("NVMe", "Samsung SSD 990 PRO 2TB  (1863 GB)"), ("NVMe", "WD_BLACK SN850X 2TB  (1863 GB)")]),
    ("Network", [("Intel(R) Ethernet Controller I226-V", "2500 Mbps")]),
]


def xdo(*args):
    subprocess.run(["xdotool", *map(str, args)], check=False)


def glide(x, y, steps=14, delay=0.012):
    """Move the pointer smoothly to (x, y)."""
    out = subprocess.run(["xdotool", "getmouselocation", "--shell"], capture_output=True, text=True).stdout
    cur = dict(line.split("=") for line in out.split() if "=" in line)
    x0, y0 = int(cur.get("X", x)), int(cur.get("Y", y))
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)                       # ease in/out
        xdo("mousemove", round(x0 + (x - x0) * t), round(y0 + (y - y0) * t))
        time.sleep(delay)


def run_tour():
    import math
    for step in TOUR:
        kind, *a = step
        if kind == "wait":
            time.sleep(a[0])
        elif kind == "click":
            glide(a[0], a[1], steps=22)
            time.sleep(0.12)
            xdo("click", 1)
        elif kind == "drag":
            glide(a[0], a[1], steps=18)
            xdo("mousedown", 1)
            time.sleep(0.1)
            for i in range(1, 21):
                xdo("mousemove", round(a[0] + (a[2] - a[0]) * i / 20), round(a[1] + (a[3] - a[1]) * i / 20))
                time.sleep(0.02)
            xdo("mouseup", 1)
        elif kind == "wheel_drag":
            cx, cy, r = a
            glide(cx + r, cy, steps=20)
            xdo("mousedown", 1)
            for i in range(0, 80):
                ang = -i / 80 * 2 * math.pi * 0.85
                rr = r * (0.6 + 0.4 * math.cos(i / 80 * math.pi))
                xdo("mousemove", round(cx + rr * math.cos(ang)), round(cy + rr * math.sin(ang)))
                time.sleep(0.03)
            xdo("mouseup", 1)
        elif kind == "scroll":
            glide(a[0], a[1], steps=16)
            for _ in range(a[2]):
                xdo("click", 5)
                time.sleep(0.12)


ARROW = [                                            # Windows-style pointer, 1 = fill, 2 = outline
    "2",
    "22",
    "212",
    "2112",
    "21112",
    "211112",
    "2111112",
    "21111112",
    "211111112",
    "2111111112",
    "21111111112",
    "211111111112",
    "2111111222222",
    "2111211",
    "211221112",
    "21202112",
    "220021112",
    "2000211112",
    "00000211112",
    "000000211122",
    "0000000222",
]


def big_cursor(folder: Path, scale=1):
    """Write an X11 cursor (source + mask .xbm) shaped like the Windows arrow. Returns a Tk cursor spec."""
    from PIL import Image
    w = max(len(r) for r in ARROW) * scale + 2
    h = len(ARROW) * scale + 2
    src, mask = Image.new("1", (w, h), 0), Image.new("1", (w, h), 0)
    for y, row in enumerate(ARROW):
        for x, ch in enumerate(row):
            for dy in range(scale):
                for dx in range(scale):
                    if ch in "12":
                        mask.putpixel((x * scale + dx, y * scale + dy), 1)
                    if ch == "1":
                        src.putpixel((x * scale + dx, y * scale + dy), 1)
    sp, mp = folder / "arrow.xbm", folder / "arrow_mask.xbm"
    src.save(sp)
    mask.save(mp)
    txt = sp.read_text()                              # Tk needs the hot spot (the arrow tip) in the source file
    sp.write_text(txt.replace("#define im_height", "#define im_x_hot 1\n#define im_y_hot 1\n#define im_height", 1))
    return f"@{sp} {mp} white black"


def set_cursor_everywhere(widget, cursor):
    """Set the cursor straight on the Tk windows (CustomTkinter's own configure() would redraw them)."""
    try:
        if widget.tk.call(widget._w, "cget", "-cursor") != cursor:
            widget.tk.call(widget._w, "configure", "-cursor", cursor)
    except Exception:
        pass
    for child in widget.winfo_children():
        set_cursor_everywhere(child, cursor)


def title_bar(icon_path):
    from PIL import Image, ImageDraw, ImageFont
    bar = Image.new("RGB", (W, TITLE_H), (24, 25, 28))
    d = ImageDraw.Draw(bar)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 12)
    except Exception:
        font = ImageFont.load_default()
    try:
        ic = Image.open(icon_path).convert("RGBA").resize((16, 16), Image.LANCZOS)
        bar.paste(ic, (10, 8), ic)
    except Exception:
        pass
    d.text((34, 9), "Central RGB", fill=(214, 216, 220), font=font)
    g = (200, 202, 206)
    x = W - 138                                       # minimize, maximize, close
    d.line((x + 18, 16, x + 28, 16), fill=g)
    d.rectangle((x + 64, 11, x + 73, 20), outline=g)
    d.line((x + 110, 11, x + 119, 20), fill=g)
    d.line((x + 110, 20, x + 119, 11), fill=g)
    return bar


def make_gif(video, out_gif, width=860, gif_fps=12):
    from PIL import Image
    frames = Path(tempfile.mkdtemp(prefix="demo-frames-"))
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", f"fps={gif_fps}",
                    str(frames / "f%04d.png")], check=True)
    bar = title_bar(ROOT / "assets" / "icon.png")
    composed = frames / "c"
    composed.mkdir()
    for f in sorted(frames.glob("f*.png")):
        im = Image.open(f).convert("RGB")
        canvas = Image.new("RGB", (W, H + TITLE_H))
        canvas.paste(bar, (0, 0))
        canvas.paste(im, (0, TITLE_H))
        canvas.save(composed / f.name)
    h = round((H + TITLE_H) * width / W / 2) * 2
    pal = frames / "palette.png"
    scale = f"scale={width}:{h}:flags=lanczos"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-framerate", str(gif_fps), "-i", str(composed / "f%04d.png"),
                    "-vf", f"{scale},palettegen=max_colors=192:stats_mode=diff", "-y", str(pal)], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-framerate", str(gif_fps), "-i", str(composed / "f%04d.png"),
                    "-i", str(pal), "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                    "-loop", "0", "-y", str(out_gif)], check=True)
    shutil.rmtree(frames, ignore_errors=True)


def main():
    out_gif = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "preview_out" / "demo.gif"
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="centralrgb-demo-"))
    os.environ["APPDATA"], os.environ["LOCALAPPDATA"] = str(tmp / "r"), str(tmp / "l")

    import fake_openrgb
    import rgb_engine as eng
    fake_openrgb.install(eng)
    import central_rgb as app_mod
    import hw_monitor as hwm
    from fake_lhm import FakeLHM
    from preview import _demo_stats
    _demo_stats(hwm)
    hwm.system_info = lambda: DEMO_SYSTEM
    app_mod.App.TEST_BACKEND = FakeLHM()

    video = tmp / "demo.mp4"
    display = os.environ.get("DISPLAY", ":99")
    rec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "1", "-framerate", str(FPS),
                            "-video_size", f"{W}x{H}", "-i", f"{display}+0,0", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "12", "-pix_fmt", "yuv444p", "-y", str(video)], stdin=subprocess.PIPE)
    def park_pointer():                               # the pointer only moves once a window exists, so keep
        end = time.time() + 3.0                       # nudging it into the corner while the splash opens
        while time.time() < end:
            xdo("mousemove", W - 2, H - 2)
            time.sleep(0.05)
    threading.Thread(target=park_pointer, daemon=True).start()
    app = app_mod.App()
    app.geometry(f"{W}x{H}+0+0")
    cursor = big_cursor(tmp, scale=2)

    def keep_cursor():                                # pages build widgets lazily, so re-apply now and then
        set_cursor_everywhere(app, cursor)
        app.after(500, keep_cursor)
    keep_cursor()
    app.monitor.INTERVAL = 0.25                       # fill the graphs before the Monitor page is shown
    app.after(15000, lambda: setattr(app.monitor, "INTERVAL", 1.0))

    def tour_then_quit():
        try:
            run_tour()
        finally:
            app.after(0, finish)

    def finish():
        try:
            app.engine.stop()
            app.monitor.stop()
        finally:
            app.destroy()

    threading.Thread(target=tour_then_quit, daemon=True).start()
    app.mainloop()
    rec.communicate(b"q", timeout=30)
    make_gif(video, out_gif)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Saved {out_gif} ({out_gif.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
