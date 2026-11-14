# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Central RGB - RGB lighting, fan control and system monitoring in one sleek app.

Pages: Lighting · Devices · Fans · Monitor (Overview / Advanced) · Profiles · Settings
Layers: rgb_engine (OpenRGB lighting) · hw_monitor (sensors + fans via LibreHardwareMonitor)
        win_effects (dark, seamless title bar on Windows 10/11)

Run:  python central_rgb.py               (normal window)
      python central_rgb.py --background  (start minimized, re-apply last lighting)
"""
from __future__ import annotations

import colorsys
import math
import os
import queue
import sys
import subprocess
import threading
import time
import traceback
import webbrowser

if __name__ == "__main__" and "--sensor-worker" in sys.argv:
    # Sensor helper process (see hw_monitor.ProcBackend): start it before loading any UI code.
    import hw_monitor
    hw_monitor.sensor_worker()
    sys.exit(0)

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

import device_models as dm
import fps_overlay as fpo
import hw_monitor as hwm
import rgb_engine as eng
import win_effects as fx

APP_VERSION = eng.APP_VERSION
TASK_NAME = "CentralRGB"

# ----------------------------------------------------------------------------- palette
# "Neon" dark theme: deep navy panels, cyan and purple accents.
SOLID = dict(BG="#0b0f15", SIDE="#0b0f15", CARD="#121821", CARD2="#19202b", LINE="#262f47",
             TEXT="#e9eef6", MUTED="#9aa5b8", FAINT="#66718a", TRACK="#252d3b", HOVER="#141b25", SEL="#0f2129",
             BTN="#1a2230", BTN_HOVER="#232d3e", BTN_LINE="#2c3650")
P = dict(SOLID)
OK, WARN, BAD, INFO = "#4ade80", "#facc15", "#fb7185", "#38bdf8"
CYAN, PURPLE, TEAL, BLUE = "#2ee6ff", "#a46bff", "#2ee6c4", "#3b82f6"
PINK, VIOLET = "#ff2d95", "#8b5cff"
GRAD = (PINK, VIOLET, CYAN)
RADIUS = 8
CARD_BORDER, CARD_BORDER_W = None, 0      # outlined panels (set by some themes)

# ----------------------------------------------------------------------------- themes
# Each theme sets the panel colours, the accent (CYAN slot), the chart colours and an optional panel
# outline. A theme is applied once at startup, before any widget is made, so changing it needs a restart.
THEMES = {
    "cyber_cyan": dict(name="Cyber Cyan", desc="Default: navy panels, cyan accent"),
    "ultraviolet": dict(name="Ultraviolet Pulse", desc="Deep purple with magenta",
                        BG="#0e0a17", CARD="#161024", CARD2="#1f1731", LINE="#3a2a57", TEXT="#f1ebfb",
                        MUTED="#a99cbf", FAINT="#75688c", accent="#e14fe0", PURPLE="#9b5cff", TEAL="#c86bff",
                        BLUE="#7a5cff", PINK="#ff2d95", VIOLET="#a855f7"),
    "emerald": dict(name="Emerald Matrix", desc="Dark green with emerald",
                    BG="#08110e", CARD="#0f1a16", CARD2="#15231e", LINE="#22392f", TEXT="#e6f4ee",
                    MUTED="#93ab9f", FAINT="#61786d", accent="#2fe0a0", PURPLE="#20c4d8", TEAL="#7cf2c4",
                    BLUE="#18a6c8", PINK="#b7f36a", VIOLET="#2fd6a0"),
    "crimson": dict(name="Crimson Overclock", desc="Black-red with hot orange",
                    BG="#120a0a", CARD="#1b1011", CARD2="#251517", LINE="#44252a", TEXT="#f7eaea",
                    MUTED="#b79d9f", FAINT="#85696c", accent="#ff5a3c", PURPLE="#ff2d55", TEAL="#ff9a3c",
                    BLUE="#e8364f", PINK="#ffcc33", VIOLET="#ff3b3b"),
    "nebula_glass": dict(name="Nebula Glass", desc="Violet glass panels with soft outlines",
                         BG="#140f2a", SIDE="#120d26", CARD="#1f1840", CARD2="#2a2152", LINE="#4b3f8a",
                         TEXT="#f2efff", MUTED="#b2a9d8", FAINT="#7d74a8", accent="#45d4ff", PURPLE="#b06bff",
                         TEAL="#7fe3ff", BLUE="#6a7dff", PINK="#ff5ccf", VIOLET="#8b5cff",
                         border="#5d4fb0", border_w=1),
    "tactical_mech": dict(name="Tactical Mech", desc="Gunmetal plates with steel frames",
                          BG="#17191b", SIDE="#141618", CARD="#26292c", CARD2="#303438", LINE="#4a4f55",
                          TEXT="#e8eaec", MUTED="#a3a9b0", FAINT="#737a82", accent="#4fd1c5", PURPLE="#e0a33a",
                          TEAL="#7fe0d6", BLUE="#5b9bd5", PINK="#e0a33a", VIOLET="#8fa3b8",
                          BTN="#3a3f44", BTN_LINE="#5b6168", border="#6b7178", border_w=2),
    "bio_neural": dict(name="Bio-Neural", desc="Bioluminescent green glow",
                       BG="#07120f", SIDE="#06100d", CARD="#0c1c18", CARD2="#122722", LINE="#1f4a3e",
                       TEXT="#e4fbf3", MUTED="#8fbfae", FAINT="#5b8a7a", accent="#36f0b0", PURPLE="#29c4ff",
                       TEAL="#8af5d0", BLUE="#1fa8e0", PINK="#b4ff6a", VIOLET="#2fe6c0",
                       border="#1f6b55", border_w=1),
    "cyber_glitch": dict(name="Cyber Glitch", desc="Experimental: neon pink frames, cyan accent",
                         BG="#0c0a1d", SIDE="#0a0819", CARD="#141030", CARD2="#1c1740", LINE="#3a2d6e",
                         TEXT="#f0ecff", MUTED="#a69fd0", FAINT="#6f679c", accent="#36e2ff", PURPLE="#ff3fd2",
                         TEAL="#36e2ff", BLUE="#6a5cff", PINK="#ff3fd2", VIOLET="#8b5cff",
                         border="#c13fb8", border_w=1),
}
DEFAULT_THEME = "cyber_cyan"


def _saved_theme() -> str:
    try:
        import json
        t = json.loads((eng.settings_dir() / "settings.json").read_text(encoding="utf-8")).get("theme")
        return t if t in THEMES else DEFAULT_THEME
    except Exception:
        return DEFAULT_THEME


def _apply_theme(key: str):
    """Swap the module colours for a theme. Must run before any widget or default argument uses them."""
    global CYAN, PURPLE, TEAL, BLUE, PINK, VIOLET, GRAD, CARD_BORDER, CARD_BORDER_W
    t = THEMES.get(key) or THEMES[DEFAULT_THEME]
    if "BG" not in t:                         # the default theme keeps the original values exactly
        return
    s = dict(t)
    acc = s["accent"]
    s.setdefault("SIDE", s["BG"])
    s.setdefault("TRACK", hexcol(mix(hex2rgb(s["CARD2"]), hex2rgb(s["LINE"]), 0.5)))
    s.setdefault("HOVER", hexcol(mix(hex2rgb(s["BG"]), hex2rgb(s["CARD2"]), 0.5)))
    s.setdefault("SEL", hexcol(mix(hex2rgb(s["BG"]), hex2rgb(acc), 0.12)))
    s.setdefault("BTN", s["CARD2"])
    s.setdefault("BTN_HOVER", hexcol(mix(hex2rgb(s["BTN"]), hex2rgb(s["LINE"]), 0.5)))
    s.setdefault("BTN_LINE", s["LINE"])
    SOLID.update({k: s[k] for k in SOLID})
    P.update(SOLID)
    CYAN, PURPLE, TEAL, BLUE, PINK, VIOLET = acc, s["PURPLE"], s["TEAL"], s["BLUE"], s["PINK"], s["VIOLET"]
    GRAD = (PINK, VIOLET, CYAN)
    CARD_BORDER, CARD_BORDER_W = s.get("border"), s.get("border_w", 0)


def windows_accent(fallback="#60cdff") -> str:
    """The user's Windows accent colour, in the lighter shade Windows 11 uses for controls in dark mode."""
    if not eng.IS_WIN:
        return fallback
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as k:
            pal, _ = winreg.QueryValueEx(k, "AccentPalette")      # 8 RGBA shades, lightest first
        r, g, b = pal[4], pal[5], pal[6]                           # shade 1 = "Light 2"
        return "#%02x%02x%02x" % (r, g, b)
    except Exception:
        return fallback


WIN11 = eng.IS_WIN and fx.win_build() >= 22000
FONT = "Segoe UI Variable Text" if WIN11 else ("Segoe UI" if eng.IS_WIN else "DejaVu Sans")
FONT_DISPLAY = "Segoe UI Variable Display" if WIN11 else FONT
ICON_FONT = "Segoe Fluent Icons" if WIN11 else ("Segoe MDL2 Assets" if eng.IS_WIN else None)
MONO = "Cascadia Mono" if eng.IS_WIN else "DejaVu Sans Mono"

SWATCHES = [(255, 0, 0), (255, 90, 0), (255, 200, 0), (0, 255, 60), (0, 255, 255),
            (0, 70, 255), (150, 0, 255), (255, 0, 160), (255, 255, 255)]
EFFECT_INFO = {"Static": "Solid color", "Breathing": "Slow fade", "Color Cycle": "Shifting hue",
               "Rainbow Wave": "Flowing rainbow", "Off": "Lights off", "Tide": "Slow blue waves",
               "Drizzle": "Falling color drops", "Sweep": "Sweeping rainbow bar", "Ember": "Glowing red embers",
               "Pulse": "Bouncing equalizer", "Drift": "Drifting gradient", "Volt": "Lightning flashes",
               "Frost": "Cold glints", "Aurora": "Northern lights", "Supernova": "Bursting star",
               "Cascade": "Falling code", "Cyberpunk": "Neon glitch", "Magma": "Molten veins",
               "Stardust": "Twinkling stars", "Nebula": "Drifting clouds", "Eclipse": "Moving corona"}
TYPE_ICONS = {"Motherboard": "▦", "RAM": "▥", "GPU": "▣", "Cooler": "✺", "LED strip": "┅",
              "Keyboard": "⌨", "Mouse": "◖", "Mousepad": "▭", "Headset": "◠", "Headset stand": "⊥",
              "Case": "▢", "Light": "✦", "Speaker": "◉", "Other": "◆"}
# (page, Fluent icon glyph, fallback glyph)
NAV = [("Home", "\ue80f", "⌂"), ("Lighting", "\uea80", "✦"), ("Devices", "\ue772", "▣"), ("Fans", "\uec4a", "✺"),
       ("Monitor", "\ue9d9", "◔"), ("Overlay", "\ue7fc", "▤"), ("Profiles", "\ue734", "★"), ("Settings", "\ue713", "⚙")]


def resource(name: str) -> Path:
    """File bundled next to the script, or inside the PyInstaller .exe."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def hexcol(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def on_color(hex_color) -> str:
    """Readable text colour (dark or white) for text drawn on top of hex_color."""
    r, g, b = (c / 255 for c in hex2rgb(hex_color))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#0f1117" if lum > 0.6 else "#ffffff"


THEME = _saved_theme()
_apply_theme(THEME)
DEFAULT_ACCENT = CYAN


def lerp_grad(t, stops=GRAD):
    """Colour at position t (0..1) along the signature gradient."""
    t = max(0.0, min(1.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return hexcol(mix(hex2rgb(stops[i]), hex2rgb(stops[i + 1]), t - i))


_FONT_FILES = ("C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
               "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def grad_text(text, px=28):
    """Page title rendered with the signature gradient (returns a CTkImage, or None)."""
    from PIL import ImageFont
    for f in _FONT_FILES:
        try:
            font = ImageFont.truetype(f, px * 2)
            break
        except OSError:
            continue
    else:
        return None
    w, h = int(font.getlength(text)) + 6, int(px * 2 * 1.35)
    strip = Image.new("RGB", (len(GRAD), 1))
    strip.putdata([hex2rgb(c) for c in GRAD])
    img = strip.resize((max(w, 260), h), Image.BILINEAR).crop((0, 0, w, h)).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((0, 0), text, font=font, fill=255)
    img.putalpha(mask)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(w // 2, h // 2))


class Switch(ctk.CTkSwitch):
    def __init__(self, *a, **kw):
        kw.setdefault("corner_radius", 10)          # Fluent pill toggle with a round knob
        kw.setdefault("switch_width", 40)
        kw.setdefault("switch_height", 20)
        kw.setdefault("button_color", P["TEXT"])
        kw.setdefault("fg_color", P["TRACK"])
        kw.setdefault("progress_color", DEFAULT_ACCENT)
        super().__init__(*a, **kw)


class Slider(ctk.CTkSlider):
    def __init__(self, *a, **kw):
        kw.setdefault("corner_radius", 2)
        kw.setdefault("button_corner_radius", 9)    # round thumb
        kw.setdefault("button_length", 0)
        super().__init__(*a, **kw)


# ---------------------------------------------------------------- smooth (anti-aliased) drawing
# Tk's canvas draws curves and thick lines with no anti-aliasing on Windows, so they look jagged.
# Widgets with curves are drawn with Pillow at AA x size and scaled down, which gives smooth edges.
AA = 4


def imix(a, b, t):
    """mix() rounded to whole numbers, for Pillow colours."""
    return tuple(int(round(v)) for v in mix(a, b, t))


def aa_image(w, h, bg, draw_fn):
    """Draw at AA x size with draw_fn(draw, k), then scale down smoothly. Returns an RGB image."""
    w, h = max(1, int(w)), max(1, int(h))
    big = Image.new("RGB", (w * AA, h * AA), bg if isinstance(bg, tuple) else hex2rgb(bg))
    draw_fn(ImageDraw.Draw(big), AA, big)
    return big.resize((w, h), Image.LANCZOS)


def aa_round_rect(w, h, r, fill, bg, outline=None, width=1):
    def d(dr, k, _img):
        dr.rounded_rectangle((0, 0, w * k - 1, h * k - 1), r * k, fill=fill if isinstance(fill, tuple) else hex2rgb(fill),
                             outline=(outline if isinstance(outline, tuple) else hex2rgb(outline)) if outline else None,
                             width=int(width * k))
    return aa_image(w, h, bg, d)



class GradBar(tk.Canvas):
    """Thin pink → violet → cyan strip that sits on the top edge of a card."""

    def __init__(self, master, height=3, bg=None):
        super().__init__(master, height=height, bg=bg or P["CARD"], highlightthickness=0)
        self.h = height
        self.bind("<Configure>", self._draw)

    def _draw(self, _e=None):
        self.delete("all")
        w, n = max(self.winfo_width(), 10), 48
        for i in range(n):
            self.create_rectangle(i * w / n, 0, (i + 1) * w / n + 1, self.h, width=0, fill=lerp_grad(i / (n - 1)))


def accent_bar(frame):
    """Cards are plain in the simple theme (kept as a hook)."""
    return None


class SmoothFrame(ctk.CTkFrame):
    """A rounded card with smooth corners.

    CustomTkinter draws rounded corners from font glyphs, which come out uneven on Windows (especially
    with a 1px outline). This frame is square underneath, with four small corner pieces drawn by Pillow
    at 4x and scaled down, so the curve is properly anti-aliased against whatever is behind the card."""

    def __init__(self, master, fg_color=None, corner_radius=RADIUS, border_width=0, border_color=None, **kw):
        fg = fg_color or P["CARD"]
        if border_color is None and CARD_BORDER and fg == P["CARD"]:
            border_color, border_width = CARD_BORDER, CARD_BORDER_W     # outlined panels in some themes
        bw = int(border_width) if border_color else 0
        super().__init__(master, fg_color=fg, corner_radius=0, border_width=0, **kw)
        self._r = max(2, int(corner_radius))
        self._fill = fg
        self._line, self._bw = (border_color, bw) if bw else (None, 0)
        self._corners, self._imgs = [], []
        self._make_corners()

    @staticmethod
    def _color_behind(w):
        while w is not None:
            try:
                c = w.cget("fg_color")
            except Exception:
                try:
                    c = w.cget("bg")
                except Exception:
                    c = None
            if isinstance(c, (tuple, list)):
                c = c[1]
            if c and c != "transparent" and str(c).startswith("#"):
                return c
            w = w.master
        return P["BG"]

    _corner_cache: dict = {}

    def _make_corners(self):
        r = self._r
        bg = self._color_behind(self.master)
        sc = ctk.ScalingTracker.get_widget_scaling(self) if hasattr(ctk, "ScalingTracker") else 1.0
        px = max(2, int(round(r * sc)))
        bwp = max(1, int(round(self._bw * sc))) if self._bw else 0
        key = (px, bg, self._fill, self._line, bwp)
        if key not in SmoothFrame._corner_cache:             # 4 corner images per size/colour, made once
            big = Image.new("RGB", (2 * px * AA, 2 * px * AA), hex2rgb(bg))
            ImageDraw.Draw(big).ellipse((0, 0, 2 * px * AA - 1, 2 * px * AA - 1), fill=hex2rgb(self._fill),
                                        outline=hex2rgb(self._line) if bwp else None, width=bwp * AA)
            circle = big.resize((2 * px, 2 * px), Image.LANCZOS)
            SmoothFrame._corner_cache[key] = [ImageTk.PhotoImage(circle.crop((ox, oy, ox + px, oy + px)))
                                              for ox, oy in ((0, 0), (px, 0), (0, px), (px, px))]
        imgs = SmoothFrame._corner_cache[key]
        spots = (("nw", 0, 0), ("ne", 1, 0), ("sw", 0, 1), ("se", 1, 1))
        self._corners, self._imgs = [], imgs
        for img, (anchor, rx, ry) in zip(imgs, spots):
            cv = tk.Canvas(self, width=px, height=px, highlightthickness=0, bd=0, bg=self._fill)
            cv.create_image(0, 0, anchor="nw", image=img)
            cv.place(relx=rx, rely=ry, anchor=anchor)
            self._corners.append(cv)
        if bwp:                                              # straight edges of the outline, between the corners
            for kw in (dict(x=px, y=0, relwidth=1, width=-2 * px, height=bwp),
                       dict(x=px, rely=1, y=-bwp, relwidth=1, width=-2 * px, height=bwp),
                       dict(x=0, y=px, relheight=1, height=-2 * px, width=bwp),
                       dict(relx=1, x=-bwp, y=px, relheight=1, height=-2 * px, width=bwp)):
                edge = tk.Frame(self, bg=self._line, bd=0, highlightthickness=0)
                edge.place(**kw)
                self._corners.append(edge)
        self.bind("<Map>", lambda e: [tk.Misc.lift(c) for c in self._corners], add="+")
        for c in self._corners:
            tk.Misc.lift(c)


# CustomTkinter widgets call update_idletasks() on their canvas whenever they redraw. That forces a layout
# pass of the whole window, so while pages are being built every new dropdown or scrollbar stalled the app.
# Tk redraws them at the next idle moment anyway, so the forced pass is switched off.
ctk.CTkCanvas.update_idletasks = lambda self: None


class LightScroll(tk.Frame):
    """A light scrolling area (canvas + slim scrollbar + mouse wheel).

    CTkScrollableFrame is slow to create (the first one cost 0.7 s on a cold Windows start); this does the
    same job for a fraction of that. Put children in .inner."""

    def __init__(self, master, height=100, bg=None):
        bg = bg or P["CARD"]
        super().__init__(master, bg=bg, height=height)
        self.h = height
        self.cv = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, height=height)
        self.bar = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, width=8, height=1)   # stretches to fit
        self.bar.pack(side="right", fill="y", padx=(4, 2))
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.cv, bg=bg)
        self.win = self.cv.create_window(0, 0, anchor="nw", window=self.inner)
        self.thumb = self.bar.create_rectangle(2, 0, 6, 0, fill=P["TRACK"], width=0)
        self.inner.bind("<Configure>", lambda e: self._sync())
        self.cv.bind("<Configure>", lambda e: self._fit(e.width))
        self.cv.bind("<Map>", lambda e: self.after_idle(lambda: self._fit(self.cv.winfo_width())), add="+")
        self.cv.configure(yscrollcommand=self._on_scroll)
        for w in (self, self.cv, self.inner, self.bar):
            w.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._wheel), add="+")
            w.bind("<Leave>", self._leave, add="+")
        self.bar.bind("<B1-Motion>", self._drag)
        self.bar.bind("<Button-1>", self._drag)

    def _leave(self, _e):
        """Moving onto a child also sends <Leave>; only stop wheel scrolling when the pointer is really outside."""
        try:
            w = self.winfo_containing(*self.winfo_pointerxy())
        except Exception:
            w = None
        while w is not None:
            if w is self:
                return
            w = w.master
        self.unbind_all("<MouseWheel>")

    def _fit(self, width):
        """Make the inner frame exactly as wide as the visible area (re-applied when shown: Tk doesn't
        resize an embedded window while its page is hidden)."""
        if width > 1:
            self.cv.itemconfigure(self.win, width=width)
            self.inner.configure(width=width)
            self.cv.coords(self.win, 0, 0)
        self._sync()

    def _sync(self):
        self.cv.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))

    def _on_scroll(self, first, last):
        first, last = float(first), float(last)
        h = max(self.bar.winfo_height(), 10)
        if last - first >= 0.999:
            self.bar.coords(self.thumb, 2, 0, 6, 0)
        else:
            self.bar.coords(self.thumb, 2, first * h, 6, last * h)

    def _wheel(self, e):
        self.cv.yview_scroll(int(-e.delta / 120) * 2, "units")

    def _drag(self, e):
        self.cv.yview_moveto(max(0.0, e.y / max(1, self.bar.winfo_height()) - 0.1))


class Splash(tk.Frame):
    """Startup animation: the logo fades and zooms in over a soft glow, the name fades in beneath it,
    then everything keeps zooming as it fades away and the app fades in."""
    FPS = 60
    T_IN, T_HOLD, T_OUT, T_DIP, T_RISE = 1.0, 0.75, 0.5, 0.14, 0.32

    def __init__(self, root, icon_img, on_done=None, size=176):
        super().__init__(root, bg=P["BG"])
        self.root, self.on_done, self.icon = root, on_done, icon_img
        try:
            self.sc = ctk.ScalingTracker.get_window_scaling(root)
        except Exception:
            self.sc = max(1.0, root.winfo_fpixels("1i") / 96)
        self.cv = tk.Canvas(self, bg=P["BG"], highlightthickness=0)
        self.cv.pack(fill="both", expand=True)
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        tk.Misc.lift(self)
        bg = hex2rgb(P["BG"])
        self.size = int(size * self.sc)
        g = int(self.size * 3.2)
        glow = Image.new("RGB", (g, g), bg)
        d = ImageDraw.Draw(glow)
        for (fx_, fy_, col) in ((0.34, 0.40, PINK), (0.66, 0.42, CYAN), (0.5, 0.66, VIOLET)):
            r = g * 0.2
            d.ellipse((g * fx_ - r, g * fy_ - r, g * fx_ + r, g * fy_ + r), fill=hex2rgb(col))
        flat = Image.new("RGB", (g, g), bg)
        glow = Image.blend(glow.filter(ImageFilter.GaussianBlur(g * 0.11)), flat, 0.45)
        # fade to the background well before the edge of the image, so no square outline can show
        fade = Image.radial_gradient("L").resize((g, g), Image.BILINEAR).point(lambda v: max(0, 255 - int(v * 1.3)))
        glow = Image.composite(glow, flat, fade.filter(ImageFilter.GaussianBlur(g * 0.04)))
        self.glow_frames = [ImageTk.PhotoImage(Image.blend(flat, glow, k / 23)) for k in range(24)]
        self.glow_item = self.cv.create_image(-4000, -4000, image=self.glow_frames[0])   # off-screen until begin()
        self.logo_item = self.cv.create_image(-4000, -4000)
        self.line = self.cv.create_line(-10, -10, -10, -10, width=max(2, int(2 * self.sc)), fill=VIOLET)
        self.title = self.cv.create_text(-4000, 0, text="Central RGB", fill=P["BG"], font=(FONT, int(30 * self.sc), "bold"))
        self.sub = self.cv.create_text(-4000, 0, text="LIGHTING  ·  FANS  ·  MONITOR", fill=P["BG"], font=(FONT, int(10 * self.sc), "bold"))
        self._logo_img = None
        self.started, self.ready = False, False

    def keep_on_top(self):
        if self.winfo_exists():
            tk.Misc.lift(self)

    def begin(self):
        """Start the animation (called once the app behind it has finished building)."""
        self.keep_on_top()
        self.started, self.t0 = True, time.time()
        self.t_start = self.t0
        self._tick()

    @staticmethod
    def _smooth(k):
        k = max(0.0, min(1.0, k))
        return k * k * (3 - 2 * k)

    def _tick(self):
        if not self.winfo_exists():
            return
        t = time.time() - self.t0
        t_out = self.T_IN + self.T_HOLD
        if not self.ready and t > t_out:          # app still building: hold on the logo
            self.t0 += t - t_out
            t = t_out
        t_dip = t_out + self.T_OUT
        if t >= t_dip:                                   # logo has faded out
            if self.on_done:
                self.on_done()
            else:
                self.destroy()
            return
        w, h, sc = max(self.winfo_width(), 200), max(self.winfo_height(), 200), self.sc
        cx, cy = w / 2, h / 2 - 40 * sc
        cv, bg = self.cv, hex2rgb(P["BG"])
        k_in = 1 - (1 - min(1.0, t / self.T_IN)) ** 3     # ease-out
        k_out = self._smooth((t - t_out) / self.T_OUT)    # 0 until the exit starts
        drift = min(t, t_out) / t_out * 0.04              # slow continuous zoom so it never sits still
        real = time.time() - self.t_start                 # wall clock (t pauses while the app is loading)
        hold_w = self._smooth((real - t_out) / 0.6) * (1 - k_out)
        breathe = math.sin((real - t_out) * 2.6) * hold_w  # gentle pulse while waiting for the app
        scale = (0.62 + 0.38 * k_in + drift + 0.018 * breathe) * (1 + 0.55 * k_out * k_out)
        alpha = self._smooth(t / (self.T_IN * 0.8)) * (1 - k_out)
        px = max(8, int(self.size * scale))
        im = self.icon.resize((px, px), Image.BILINEAR)
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
        self._logo_img = ImageTk.PhotoImage(im)
        cv.coords(self.logo_item, cx, cy)
        cv.itemconfigure(self.logo_item, image=self._logo_img)
        cv.coords(self.glow_item, cx, cy)
        cv.itemconfigure(self.glow_item, image=self.glow_frames[max(0, min(23, int(alpha * (0.88 + 0.12 * breathe) * 23.99)))])
        kt = self._smooth((t - 0.35) / 0.6) * (1 - self._smooth((t - t_out) / (self.T_OUT * 0.7)))
        spread = (1 - self._smooth((t - 0.35) / 0.6)) * 8 * sc + k_out * 18 * sc
        cv.coords(self.title, cx, cy + 132 * sc + spread)
        cv.itemconfigure(self.title, fill=hexcol(mix(bg, hex2rgb(P["TEXT"]), kt)))
        cv.coords(self.sub, cx, cy + 164 * sc + spread)
        cv.itemconfigure(self.sub, fill=hexcol(mix(bg, hex2rgb(P["MUTED"]), kt)))
        kl = self._smooth((t - 0.5) / 0.9)                # thin line grows out from the centre
        half = 92 * sc * kl
        cv.coords(self.line, cx - half, cy + 188 * sc + spread, cx + half, cy + 188 * sc + spread)
        cv.itemconfigure(self.line, fill=hexcol(mix(bg, hex2rgb(lerp_grad((t * 0.5) % 1.0)), kt)))
        self.after(1000 // self.FPS, self._tick)



_TYPE = {9: 11, 10: 11, 11: 12, 12: 13, 13: 14}     # Fluent sizes: body 14, caption 12


def spaced(text):
    """Uppercase with a little letter spacing, like the mockup's page titles."""
    return "\u2009".join(text.upper())


def F(size, weight="normal", display=False):
    return ctk.CTkFont(family=FONT_DISPLAY if display else FONT, size=_TYPE.get(size, size), weight=weight)


def icon_label(parent, glyph, fallback, size=16, color=None, **kw):
    font = ctk.CTkFont(family=ICON_FONT, size=size) if ICON_FONT else ctk.CTkFont(family=FONT, size=size)
    return ctk.CTkLabel(parent, text=glyph if ICON_FONT else fallback, font=font,
                        text_color=color or P["TEXT"], **kw)


class NavItem(ctk.CTkFrame):
    """Windows 11 Settings-style navigation item: accent pill, icon, label."""

    def __init__(self, master, name, glyph, fallback, command):
        super().__init__(master, fg_color="transparent", corner_radius=8, height=40, border_width=1, border_color=P["SIDE"])
        self.pack_propagate(False)
        self.pill = ctk.CTkFrame(self, width=3, height=16, corner_radius=2, fg_color="transparent")
        self.pill.pack(side="left", padx=(4, 10))
        self.icon = icon_label(self, glyph, fallback, size=16, width=22)
        self.icon.pack(side="left")
        self.text = ctk.CTkLabel(self, text=name, font=F(14), text_color=P["TEXT"], anchor="w")
        self.text.pack(side="left", padx=14, fill="x", expand=True)
        self.on = False
        for w in (self, self.icon, self.text, self.pill):
            w.bind("<Button-1>", lambda e: command())
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, inside):
        if not self.on:
            self.configure(fg_color=P["HOVER"] if inside else "transparent")

    def set(self, on, accent):
        if (on, accent) == getattr(self, "_style", None):
            return                                   # unchanged: skip CustomTkinter's redraw
        self._style = (on, accent)
        self.on = on
        self.configure(fg_color=P["SEL"] if on else "transparent", border_color=accent if on else P["SIDE"])
        self.pill.configure(fg_color=accent if on else "transparent")


def fmt(v, unit="", nd=0, none="—"):
    return none if v is None else f"{v:.{nd}f}{unit}"


def temp_color(t):
    if t is None:
        return P["MUTED"]
    return OK if t < 65 else WARN if t < 82 else BAD


# ----------------------------------------------------------------------------- canvas widgets
class ColorWheel(tk.Canvas):
    def __init__(self, master, size=232, command=None):
        super().__init__(master, width=size, height=size, bg=P["CARD"], highlightthickness=0)
        self.size, self.command, self.r = size, command, size / 2 - 4
        self.img = ImageTk.PhotoImage(self._render())
        self.create_image(size / 2, size / 2, image=self.img)
        self.ring = self.create_oval(0, 0, 0, 0, outline="white", width=3)
        self.dot = self.create_oval(0, 0, 0, 0, outline="", fill="white")
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)

    def _render(self):
        try:                                     # pre-rendered by tools/make_wheel.py
            disk = Image.open(resource("presets/wheel.png")).convert("RGBA")
            d = int(round(self.r * 2))
            disk = disk.resize((d, d), Image.LANCZOS)
            bg = Image.new("RGBA", (self.size, self.size), hex2rgb(P["CARD"]) + (255,))
            off = (self.size - d) // 2
            bg.alpha_composite(disk, (off, off))
            return bg.convert("RGB")
        except Exception:
            pass
        s = self.size * 2
        c, r = s / 2, self.r * 2
        hue = Image.new("RGB", (s, s))
        d = ImageDraw.Draw(hue)
        for k in range(720):                     # hue slices (0 deg = right, counter-clockwise)
            rr, gg, bb = colorsys.hsv_to_rgb(k / 720, 1, 1)
            d.pieslice((0, 0, s, s), -(k + 1) / 2 - 0.3, -k / 2 + 0.3, fill=(int(rr * 255), int(gg * 255), int(bb * 255)))
        hue = hue.filter(ImageFilter.GaussianBlur(0.8))
        # saturation: blend toward white near the centre (radial_gradient is 0 at centre, 255 at the edge)
        rad = Image.radial_gradient("L").resize((int(2 * r), int(2 * r)), Image.BILINEAR)
        sat = Image.new("L", (s, s), 255)
        sat.paste(rad, (int(c - r), int(c - r)))
        sat = sat.point(lambda v: int(255 * min(1.0, v * 1.41421 / 255) ** 0.9))   # gradient hits 255 at the corner
        img = Image.composite(hue, Image.new("RGB", (s, s), (255, 255, 255)), sat).convert("RGBA")
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).ellipse((c - r, c - r, c + r, c + r), fill=255)
        img.putalpha(mask)
        bg = Image.new("RGBA", (s, s), hex2rgb(P["CARD"]) + (255,))
        bg.alpha_composite(img)
        return bg.resize((self.size, self.size), Image.LANCZOS)

    def _drag(self, e):
        c = self.size / 2
        dx, dy = e.x - c, e.y - c
        h = (math.atan2(-dy, dx) / (2 * math.pi)) % 1
        s = min(math.hypot(dx, dy), self.r) / self.r
        self.set_hs(h, s)
        if self.command:
            self.command(tuple(int(v * 255) for v in colorsys.hsv_to_rgb(h, s ** 0.9, 1)))

    def set_hs(self, h, s):
        c = self.size / 2
        x, y = c + math.cos(h * 2 * math.pi) * s * self.r, c - math.sin(h * 2 * math.pi) * s * self.r
        self.coords(self.ring, x - 10, y - 10, x + 10, y + 10)
        self.coords(self.dot, x - 3, y - 3, x + 3, y + 3)

    def set_rgb(self, rgb):
        h, s, _ = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
        self.set_hs(h, s ** (1 / 0.9))


class LedStrip(tk.Canvas):
    def __init__(self, master, n=24, height=40, bg=None, pill=False):
        bg = bg or P["CARD"]
        super().__init__(master, height=height, bg=bg, highlightthickness=0)
        self.n, self.h, self.bgc, self.pill = n, height, hex2rgb(bg), pill
        self.items, self.glows = [], []
        self.bind("<Configure>", lambda e: self._layout())

    def _layout(self):
        self.delete("all")
        self.items, self.glows = [], []
        w = max(self.winfo_width(), 40)
        step = w / self.n
        cy = self.h / 2
        if self.pill:   # continuous light bar
            for i in range(self.n):
                x0, x1 = i * step, (i + 1) * step + 1
                self.glows.append(self.create_rectangle(x0, cy - 9, x1, cy + 9, width=0, fill=P["CARD"]))
                self.items.append(self.create_rectangle(x0, cy - 3, x1, cy + 3, width=0, fill=P["CARD"]))
            return
        r = min(step * 0.26, self.h * 0.16)
        for i in range(self.n):
            cx = step * (i + 0.5)
            self.glows.append(self.create_rectangle(cx - r * 2.1, cy - r * 2.1, cx + r * 2.1, cy + r * 2.1, width=0, fill=P["CARD"]))
            self.items.append(self.create_rectangle(cx - r, cy - r, cx + r, cy + r, width=0, fill=P["CARD"]))

    def show(self, colors):
        n = len(self.items)
        for i in range(n):
            c = colors[int(i * len(colors) / n)] if colors else (0, 0, 0)
            lit = max(c) > 20
            self.itemconfigure(self.items[i], fill=hexcol(mix(c, (255, 255, 255), 0.25) if lit else mix(self.bgc, (60, 64, 76), 0.5)))
            self.itemconfigure(self.glows[i], fill=hexcol(mix(self.bgc, c, 0.22 if lit else 0)))


class Sparkline(tk.Canvas):
    """Smooth line chart with a soft glow and a fading fill; can draw several series on one chart."""

    def __init__(self, master, height=54, color=DEFAULT_ACCENT, bg=None):
        super().__init__(master, height=height, bg=bg or P["CARD"], highlightthickness=0)
        self.h, self.color, self.bgc = height, color, hex2rgb(bg or P["CARD"])
        self._img = None
        self.img_item = self.create_image(0, 0, anchor="nw")

    def set(self, values, vmax=None, color=None):
        self.set_multi([(values, color or self.color)], vmax)

    _fill_cache: dict = {}

    def set_multi(self, series, vmax=None):
        h = self.winfo_height() if self.winfo_height() > 20 else self.h
        w = max(self.winfo_width(), 40)
        series = [(list(v)[-60:], c) for v, c in series if len(list(v)) >= 2]
        if not series:
            return
        top = vmax if vmax else max(max(max(v) for v, _ in series) * 1.2, 1e-6)
        k = 2
        W, H = w * k, h * k
        step = w / 59
        bgc = self.bgc
        img = Image.new("RGB", (W, H), bgc)
        d = ImageDraw.Draw(img)
        for vals, color in series:
            rgb = hex2rgb(color)
            fkey = (W, H, color, bgc)
            if fkey not in Sparkline._fill_cache:            # fading fill colour + fade mask, made once
                grad = Image.linear_gradient("L").resize((W, H)).point(lambda v: int((255 - v) * 0.55))
                Sparkline._fill_cache[fkey] = (Image.new("RGB", (W, H), imix(bgc, rgb, 0.30)), grad)
            fill, grad = Sparkline._fill_cache[fkey]
            x0 = w - step * (len(vals) - 1)
            pts = [((x0 + i * step) * k, (h - 3 - (h - 10) * min(v, top) / top) * k) for i, v in enumerate(vals)]
            m = Image.new("L", (W, H), 0)
            ImageDraw.Draw(m).polygon([(pts[0][0], H)] + pts + [(pts[-1][0], H)], fill=255)
            img.paste(fill, (0, 0), ImageChops.multiply(m, grad))
            d.line(pts, fill=imix(bgc, rgb, 0.30), width=6 * k, joint="curve")   # glow
            d.line(pts, fill=rgb, width=2 * k, joint="curve")
        out = img.resize((w, h), Image.BILINEAR)
        if self._img is None or (self._img.width(), self._img.height()) != (w, h):
            self._img = ImageTk.PhotoImage(out)
            self.itemconfigure(self.img_item, image=self._img)
        else:
            self._img.paste(out)

class Ring(tk.Canvas):
    """Circular gauge: a smooth 270-degree arc with a two-colour gradient and rounded ends."""

    def __init__(self, master, size=112, width=9):
        super().__init__(master, width=size, height=size, bg=P["CARD"], highlightthickness=0)
        self.s, self.w = size, width
        self._key, self._img = None, None
        self.img_item = self.create_image(0, 0, anchor="nw")
        self.val = self.create_text(size / 2, size / 2 - 7, text="—", fill=P["TEXT"], font=(FONT, 20))
        self.sub = self.create_text(size / 2, size / 2 + 17, text="", fill=P["MUTED"], font=(FONT, 9))
        self._draw(0, TEAL, CYAN)

    _conic_cache: dict = {}

    def _conic(self, c1, c2, n):
        """Gradient ring image (cached): c1 at the start of the gauge, c2 at the end."""
        key = (c1, c2, n)
        if key not in Ring._conic_cache:
            img = Image.new("RGB", (n, n), hex2rgb(c1))
            d = ImageDraw.Draw(img)
            a1, a2 = hex2rgb(c1), hex2rgb(c2)
            for i in range(270):
                d.pieslice((0, 0, n - 1, n - 1), 135 + i - 0.5, 135 + i + 1.5, fill=imix(a1, a2, i / 269))
            d.pieslice((0, 0, n - 1, n - 1), 404, 496, fill=a2)
            Ring._conic_cache[key] = img
        return Ring._conic_cache[key]

    def _draw(self, pct, c1, c2):
        key = (round(pct * 2) / 2, c1, c2)
        if key == self._key:
            return
        self._key = key
        k = 3
        s, wd = self.s, self.w
        n = s * k
        pad, lw = 3 * k, int(wd * k)
        box = (pad, pad, n - pad, n - pad)
        c = n / 2
        r = (n - 2 * pad) / 2 - lw / 2                     # Pillow strokes inward: caps go on the centre line

        def cap(d, ang, fill):
            x, y = c + r * math.cos(math.radians(ang)), c + r * math.sin(math.radians(ang))
            d.ellipse((x - lw / 2, y - lw / 2, x + lw / 2, y + lw / 2), fill=fill)

        tkey = (n, lw, P["CARD"], P["TRACK"])
        if tkey not in Ring._conic_cache:                   # empty track, drawn once
            base = Image.new("RGB", (n, n), hex2rgb(P["CARD"]))
            track = Image.new("L", (n, n), 0)
            td = ImageDraw.Draw(track)
            td.arc(box, 135, 405, fill=255, width=lw)
            cap(td, 135, 255)
            cap(td, 405, 255)
            base.paste(hex2rgb(P["TRACK"]), (0, 0, n, n), track)
            Ring._conic_cache[tkey] = base
        img = Ring._conic_cache[tkey].copy()
        if pct > 0:
            m = Image.new("L", (n, n), 0)
            md = ImageDraw.Draw(m)
            end = 135 + 270 * pct / 100
            md.arc(box, 135, end, fill=255, width=lw)
            cap(md, 135, 255)
            cap(md, end, 255)
            img.paste(self._conic(c1, c2, n), (0, 0), m)
        out = img.resize((s, s), Image.LANCZOS)
        if self._img is None:
            self._img = ImageTk.PhotoImage(out)
            self.itemconfigure(self.img_item, image=self._img)
        else:
            self._img.paste(out)                            # reuse the Tk image: much cheaper than a new one

    def set(self, pct, text, sub="", color=(TEAL, CYAN)):
        c1, c2 = color if isinstance(color, (tuple, list)) else (color, color)
        pct = 0 if pct is None else max(0, min(100, pct))
        self._draw(pct, c1, c2)
        self.itemconfigure(self.val, text=text)
        self.itemconfigure(self.sub, text=sub)


class GradientBar(tk.Canvas):
    """Thin rounded progress bar filled with a cyan to purple gradient."""

    def __init__(self, master, height=8):
        super().__init__(master, height=height, bg=P["CARD"], highlightthickness=0)
        self.h, self.pct, self.cols = height, 0, (CYAN, PURPLE)
        self._img, self._key = None, None
        self.img_item = self.create_image(0, 0, anchor="nw")
        self.bind("<Configure>", lambda e: self.set(self.pct, *self.cols))

    def set(self, pct, c1=CYAN, c2=PURPLE):
        self.pct, self.cols = pct, (c1, c2)
        w, h = max(self.winfo_width(), 20), self.h
        p = max(0.0, min(1.0, pct or 0))
        key = (w, round(p, 3), c1, c2)
        if key == self._key:
            return
        self._key = key

        def draw(d, k, img):
            d.rounded_rectangle((0, 0, w * k - 1, h * k - 1), h * k / 2, fill=hex2rgb(P["TRACK"]))
            fw = int(w * k * p)
            if fw >= h * k * 0.6:
                g = Image.linear_gradient("L").rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT).resize((fw, h * k))
                bar = Image.composite(Image.new("RGB", (fw, h * k), hex2rgb(c2)), Image.new("RGB", (fw, h * k), hex2rgb(c1)), g)
                m = Image.new("L", (fw, h * k), 0)
                ImageDraw.Draw(m).rounded_rectangle((0, 0, fw - 1, h * k - 1), h * k / 2, fill=255)
                img.paste(bar, (0, 0), m)

        self._img = ImageTk.PhotoImage(aa_image(w, h, P["CARD"], draw))
        self.itemconfigure(self.img_item, image=self._img)


class CurveEditor(tk.Canvas):
    """Drag-able temperature → fan-speed curve."""
    T0, T1 = 20, 100

    def __init__(self, master, on_change, height=250):
        super().__init__(master, height=height, bg=P["CARD"], highlightthickness=0)
        self.on_change, self.h = on_change, height
        self.points = [list(p) for p in hwm.DEFAULT_CURVE]
        self.editable, self.drag, self.temp, self.accent = True, None, None, DEFAULT_ACCENT
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def _xy(self, t, p):
        w = max(self.winfo_width(), 100)
        L, R, T, B = 42, 14, 12, 28
        return (L + (t - self.T0) / (self.T1 - self.T0) * (w - L - R), T + (1 - p / 100) * (self.h - T - B))

    def _tp(self, x, y):
        w = max(self.winfo_width(), 100)
        L, R, T, B = 42, 14, 12, 28
        t = self.T0 + (x - L) / (w - L - R) * (self.T1 - self.T0)
        p = 100 * (1 - (y - T) / (self.h - T - B))
        return max(self.T0, min(self.T1, t)), max(hwm.FAN_FLOOR, min(100, p))

    def set(self, points, editable=True, temp=None, accent=None):
        if self.drag is None:
            self.points = [list(p) for p in points]
        self.editable, self.temp = editable, temp
        self.accent = accent or self.accent
        self.redraw()

    def redraw(self):
        self.delete("all")
        for p in (0, 25, 50, 75, 100):
            x0, y = self._xy(self.T0, p)
            x1, _ = self._xy(self.T1, p)
            self.create_line(x0, y, x1, y, fill=P["LINE"])
            self.create_text(x0 - 8, y, text=f"{p}%", fill=P["FAINT"], anchor="e", font=(FONT, 8))
        for t in range(self.T0, self.T1 + 1, 10):
            x, y = self._xy(t, 0)
            self.create_text(x, y + 14, text=f"{t}°", fill=P["FAINT"], font=(FONT, 8))
        pts = sorted(self.points)
        line = [self._xy(self.T0, pts[0][1])] + [self._xy(*p) for p in pts] + [self._xy(self.T1, pts[-1][1])]
        base = self._xy(self.T0, 0)[1]
        bgc = hex2rgb(P["CARD"])
        for k in range(6):                                          # fill fades towards the bottom
            poly = [(x, y + (base - y) * k / 6) for x, y in line]
            self.create_polygon([(line[0][0], base)] + poly + [(line[-1][0], base)],
                                fill=hexcol(mix(bgc, hex2rgb(CYAN), 0.03 + 0.025 * (6 - k))), outline="")
        dense = []                                                  # split the line so it can change colour
        for (xa, ya), (xb, yb) in zip(line, line[1:]):
            for j in range(12):
                dense.append((xa + (xb - xa) * j / 12, ya + (yb - ya) * j / 12))
        dense.append(line[-1])
        x_min, x_max = dense[0][0], dense[-1][0]
        for (xa, ya), (xb, yb) in zip(dense, dense[1:]):
            k = (xa - x_min) / max(1, x_max - x_min)
            col = hexcol(mix(hex2rgb(CYAN), hex2rgb(PURPLE), k)) if self.editable else P["MUTED"]
            self.create_line(xa, ya, xb, yb, fill=hexcol(mix(bgc, hex2rgb(col), 0.3)), width=8, capstyle="round")
        for (xa, ya), (xb, yb) in zip(dense, dense[1:]):
            k = (xa - x_min) / max(1, x_max - x_min)
            col = hexcol(mix(hex2rgb(CYAN), hex2rgb(PURPLE), k)) if self.editable else P["MUTED"]
            self.create_line(xa, ya, xb, yb, fill=col, width=2.5, capstyle="round")
        if self.temp is not None:
            t = max(self.T0, min(self.T1, self.temp))
            x, _ = self._xy(t, 0)
            _, y = self._xy(t, hwm.interp_curve(pts, t))
            self.create_line(x, self._xy(0, 100)[1], x, base, fill=P["FAINT"], dash=(3, 4))
            self.create_oval(x - 6, y - 6, x + 6, y + 6, fill=P["TEXT"], outline=self.accent, width=3)
            self.create_text(x + 9, self._xy(0, 100)[1] + 8, text=f"{self.temp:.0f}°C now", fill=P["MUTED"],
                             anchor="w", font=(FONT, 9, "bold"))
        for i, (t, p) in enumerate(pts):
            x, y = self._xy(t, p)
            k = (x - x_min) / max(1, x_max - x_min)
            ring = hexcol(mix(hex2rgb(CYAN), hex2rgb(PURPLE), k)) if self.editable else P["MUTED"]
            self.create_oval(x - 7, y - 7, x + 7, y + 7, fill=P["CARD"], outline=ring, width=3, tags=("pt",))

    def _press(self, e):
        best, bd = None, 18
        for i, p in enumerate(sorted(self.points)):
            x, y = self._xy(*p)
            d = math.hypot(e.x - x, e.y - y)
            if d < bd:
                best, bd = i, d
        if best is not None:
            self.points = [list(p) for p in sorted(self.points)]
            self.drag = best

    def _move(self, e):
        if self.drag is None:
            return
        t, p = self._tp(e.x, e.y)
        lo = self.points[self.drag - 1][0] + 2 if self.drag > 0 else self.T0
        hi = self.points[self.drag + 1][0] - 2 if self.drag < len(self.points) - 1 else self.T1
        self.points[self.drag] = [round(max(lo, min(hi, t))), round(p)]
        self.editable = True
        self.redraw()

    def _release(self, _e):
        if self.drag is not None:
            self.drag = None
            self.on_change([tuple(p) for p in self.points])


# ----------------------------------------------------------------------------- composite widgets
EFFECT_ICONS = {"Static": "✧", "Breathing": "∿", "Color Cycle": "↻", "Rainbow Wave": "≋", "Tide": "≈",
                "Drizzle": "⁖", "Sweep": "⇆", "Ember": "◉", "Pulse": "▮", "Drift": "∿",
                "Volt": "ϟ", "Frost": "❄", "Aurora": "≋", "Supernova": "✺", "Cascade": "⋮",
                "Cyberpunk": "▚", "Magma": "◉", "Stardust": "✧", "Nebula": "☁", "Eclipse": "◐", "Off": "⏻"}


PRESET_FILES = {name: "presets/" + name.lower().replace(" ", "-") + ".jpg" for name in eng.PRESET_EFFECTS}


class GlowBar(tk.Canvas):
    """Smooth light bar drawn with Pillow: colours blend into each other, the ends are anti-aliased and
    rounded, and a soft blurred glow fades straight into the card - no hard edges or outlines."""

    def __init__(self, master, height=16, thickness=6, bg=None, glow=0.55):
        self.bgc_hex = bg or P["CARD"]
        super().__init__(master, height=height, bg=self.bgc_hex, highlightthickness=0, bd=0)
        self.h, self.t, self.glow_k, self.n = height, thickness, glow, 48
        self.bgc = hex2rgb(self.bgc_hex)
        self._size, self._last, self._photo = None, None, None
        self.item = self.create_image(0, 0, anchor="nw")
        self.bind("<Configure>", lambda e: self._masks())

    def _masks(self):
        w, h = max(self.winfo_width(), 20), self.h
        if (w, h) == self._size:
            return
        self._size = (w, h)
        ss = 4                                                      # draw 4x larger, then shrink = smooth edges
        big = Image.new("L", (w * ss, h * ss), 0)
        r = self.t * ss / 2
        pad = h * ss / 2
        ImageDraw.Draw(big).rounded_rectangle((pad - r, h * ss / 2 - r, w * ss - pad + r, h * ss / 2 + r), r, fill=255)
        self.core = big.resize((w, h), Image.LANCZOS)
        # the glow must fade to nothing before the canvas edge, or it shows as a faint box
        glow = self.core.filter(ImageFilter.GaussianBlur(max(1.5, (h - self.t) / 5)))
        glow = glow.point(lambda v: int(min(255, v * 2.0) * self.glow_k))
        fade = Image.new("L", (w, h), 0)
        e = max(2, int((h - self.t) / 4))
        ImageDraw.Draw(fade).rounded_rectangle((e, e, w - 1 - e, h - 1 - e), max(1, (h - 2 * e) // 2), fill=255)
        fade = fade.filter(ImageFilter.GaussianBlur(e))
        self.halo = ImageChops.multiply(glow, fade)
        self.bg_img = Image.new("RGB", (w, h), self.bgc)
        self._last = None
        if getattr(self, "_pending", None):
            self.show(self._pending)

    def show(self, colors):
        if not colors:
            return
        self._pending = colors
        if self._size is None:
            return
        key = tuple(colors)
        if key == self._last:
            return
        self._last = key
        w, h = self._size
        lit = [tuple(int(v) for v in (mix(c, (255, 255, 255), 0.08) if max(c) > 20 else mix(self.bgc, c, 0.5)))
               for c in colors]
        strip = Image.new("RGB", (len(lit), 1))
        strip.putdata(lit)
        colour = strip.resize((w, 1), Image.BILINEAR).resize((w, h), Image.NEAREST)
        out = Image.composite(colour, self.bg_img, self.halo)
        out = Image.composite(colour, out, self.core)
        ph = getattr(self, "_photo", None)
        if ph is None or (ph.width(), ph.height()) != out.size:
            self._photo = ImageTk.PhotoImage(out)
            self.itemconfigure(self.item, image=self._photo)
        else:
            ph.paste(out)                                   # reuse the Tk image every frame


class PillSwitcher(ctk.CTkFrame):
    """Outlined pill selector: the chosen option gets a cyan outline and cyan text (replaces segmented buttons)."""

    def __init__(self, master, values, command=None, height=32, font=None, selected_color=None, **_ignored):
        super().__init__(master, fg_color=P["CARD"], corner_radius=height // 2 + 3, border_width=1, border_color=P["LINE"])
        self.values, self.command, self.accent = list(values), command, selected_color or DEFAULT_ACCENT
        self.current = self.values[0] if self.values else None
        self.buttons = {}
        for v in self.values:
            b = ctk.CTkButton(self, text=v, height=height - 6, width=40, corner_radius=(height - 6) // 2, font=font or F(13),
                              border_width=1, command=lambda x=v: self._click(x))
            b.pack(side="left", padx=2, pady=3, fill="x", expand=True)
            self.buttons[v] = b
        self._style()

    def _click(self, v):
        self.set(v)
        if self.command:
            self.command(v)

    def _style(self):
        for v, b in self.buttons.items():
            on = v == self.current
            b.configure(fg_color=P["SEL"] if on else P["CARD"], hover_color=P["HOVER"],
                        border_color=self.accent if on else P["CARD"], text_color=self.accent if on else P["MUTED"])

    def get(self):
        return self.current

    def set(self, v):
        if v in self.buttons:
            self.current = v
            self._style()

    def configure(self, require_redraw=False, **kw):
        acc = kw.pop("selected_color", None)
        kw.pop("selected_hover_color", None)
        if "command" in kw:
            self.command = kw.pop("command")
        if acc:
            self.accent = acc
            self._style()
        if kw:
            super().configure(require_redraw=require_redraw, **kw)


class PresetTile(tk.Canvas):
    """Picture tile for a preset effect, with its name on top (like the effect gallery mockup)."""

    def __init__(self, master, name, on_click, height=104):
        super().__init__(master, height=height, bg=P["CARD"], highlightthickness=0, cursor="hand2")
        self.name, self.h, self._img, self._size, self.selected = name, height, None, None, False
        self.accent = CYAN
        try:
            self.src = Image.open(resource(PRESET_FILES[name])).convert("RGB")
        except Exception:
            self.src = None
        self.bind("<Configure>", lambda e: self._render())
        self.bind("<Button-1>", lambda e: on_click(name))

    _mask_cache: dict = {}

    @staticmethod
    def _masks(W, H):
        """Rounded-corner mask and selection-ring mask for a tile size (shared by all tiles)."""
        if (W, H) not in PresetTile._mask_cache:
            m = Image.new("L", (W * AA, H * AA), 0)
            ImageDraw.Draw(m).rounded_rectangle((2 * AA, 2 * AA, (W - 2) * AA - 1, (H - 2) * AA - 1), 9 * AA, fill=255)
            r = Image.new("L", (W * AA, H * AA), 0)
            ImageDraw.Draw(r).rounded_rectangle((AA, AA, W * AA - AA - 1, H * AA - AA - 1), 10 * AA, outline=255, width=2 * AA)
            PresetTile._mask_cache[(W, H)] = (m.resize((W, H), Image.LANCZOS), r.resize((W, H), Image.LANCZOS))
        return PresetTile._mask_cache[(W, H)]

    def _render(self):
        w, h = max(self.winfo_width() - 4, 40), self.h - 4
        if (w, h, self.selected, self.accent) == self._size:
            return
        self._size = (w, h, self.selected, self.accent)
        if self.src is not None:                               # cover-crop the artwork to the tile
            sw, sh = self.src.size
            k = max(w / sw, h / sh)
            im = self.src.resize((int(sw * k) + 1, int(sh * k) + 1), Image.LANCZOS, reducing_gap=2.0)
            l, t = (im.width - w) // 2, (im.height - h) // 2
            im = im.crop((l, t, l + w, t + h))
        else:
            cols = eng.compute_colors(self.name, (255, 255, 255), 100, 50, 32, 1.0)
            im = Image.new("RGB", (len(cols), 1))
            im.putdata(cols)
            im = im.resize((w, h), Image.BILINEAR)
        shade = Image.new("RGB", (w, h), (0, 0, 0))            # darken slightly so the title reads well
        im = Image.blend(im, shade, 0.22)
        W, H = w + 4, h + 4
        mask, ring = PresetTile._masks(W, H)
        bg = Image.new("RGB", (W, H), hex2rgb(P["CARD"]))
        full = Image.new("RGB", (W, H))
        full.paste(im, (2, 2))
        bg.paste(full, (0, 0), mask)
        if self.selected:                                             # smooth accent ring
            bg.paste(Image.new("RGB", (W, H), hex2rgb(self.accent)), (0, 0), ring)
        self._img = ImageTk.PhotoImage(bg)
        self.delete("all")
        self.create_image(0, 0, image=self._img, anchor="nw")
        words = self.name.upper().split(" ")
        text = "\n".join([" ".join(words[:len(words) // 2 or 1]), " ".join(words[len(words) // 2 or 1:])]) \
            if len(words) > 1 else words[0]
        for dx, dy, col in ((1, 2, "#000000"), (0, 0, "#ffffff")):
            self.create_text(w / 2 + 2 + dx, h / 2 + 2 + dy, text=text, fill=col, justify="center",
                             font=(FONT, 12, "bold"))

    def select(self, on, accent):
        if (on, accent) != (self.selected, self.accent):
            self.selected, self.accent = on, accent
            self._render()


class EffectTile(tk.Canvas):
    """Effect tile: a live strip of the effect along the top edge, then its icon and name."""
    COLS = 24

    def __init__(self, master, name, on_click, big=False):
        self.h = 84 if big else 44
        super().__init__(master, height=self.h, bg=P["CARD"], highlightthickness=0, cursor="hand2")
        self.name, self.big, self.bars, self.selected = name, big, [], False
        self.accent, self._bg = CYAN, None
        self.n = self.COLS
        self.bind("<Configure>", lambda e: self._layout())
        self.bind("<Button-1>", lambda e: on_click(name))

    def _layout(self):
        self.delete("all")
        w = max(self.winfo_width(), 40)
        on = self.selected
        self._bg = ImageTk.PhotoImage(aa_round_rect(w, self.h, 8, P["SEL"] if on else P["CARD2"], P["CARD"],
                                                    outline=self.accent if on else P["LINE"], width=2 if on else 1))
        self.create_image(0, 0, image=self._bg, anchor="nw")
        x0, x1 = 10, w - 10                                         # live strip, inset from the corners
        step = (x1 - x0) / self.COLS
        self.bars = [self.create_rectangle(x0 + i * step, 4, x0 + (i + 1) * step + 1, 7, width=0, fill=P["TRACK"])
                     for i in range(self.COLS)]
        y = self.h - 30 if self.big else self.h / 2 + 2
        icon = EFFECT_ICONS.get(self.name, "•")
        if self.big:
            self.create_text(14, 24, text=icon, anchor="w", fill=P["FAINT"], font=(FONT, 12))
        if not self.big:
            self.create_text(12, y, text=icon, anchor="w", fill=P["MUTED"], font=(FONT, 10))
        self.create_text(14 if self.big else 28, y, text=self.name, anchor="w", fill=P["TEXT"],
                         font=(FONT, 11 if self.big else 10, "bold" if self.big else "normal"))
        self.sub = self.create_text(14, y + 19, text="", anchor="w", fill=P["MUTED"], font=(FONT, 8))
        self._sub()

    def _sub(self):
        if hasattr(self, "sub"):
            self.itemconfigure(self.sub, text=EFFECT_INFO.get(self.name, "") if (self.selected and self.big) else "")

    def show(self, colors):
        for i, it in enumerate(self.bars):
            c = colors[int(i * len(colors) / len(self.bars))]
            self.itemconfigure(it, fill=hexcol(c) if max(c) > 10 else P["TRACK"])

    def select(self, on, accent):
        if (on, accent) != (self.selected, self.accent):
            self.selected, self.accent = on, accent
            self._layout()


class DeviceArt(tk.Canvas):
    """A model of the device (RAM stick, graphics card, fans...) lit live with its real LED colors."""

    def __init__(self, master, kind, leds):
        self.model = dm.model_for(kind, max(1, min(leds, 120)), hex2rgb(P["CARD"]))
        super().__init__(master, width=self.model.W, height=self.model.H, bg=P["CARD"], highlightthickness=0)
        self.leds = [None] * max(1, min(leds, 120))     # one slot per LED, so callers can ask how many to compute
        self._last = None
        self._img = ImageTk.PhotoImage(self.model.body)
        self._item = self.create_image(0, 0, anchor="nw", image=self._img)

    def show(self, colors):
        colors = [tuple(c) for c in colors]
        if colors == self._last:                         # nothing changed: skip the redraw
            return
        self._last = colors
        self._img.paste(self.model.render(colors))         # same size every frame: reuse the Tk image


class DeviceCard(SmoothFrame):
    def __init__(self, master, key, tname, name, leds, enabled, on_toggle, on_edit):
        super().__init__(master, fg_color=P["CARD"], corner_radius=6)
        accent_bar(self)
        self.key = key
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(top, text=TYPE_ICONS.get(tname, "◆"), width=40, height=40, corner_radius=10,
                     fg_color=P["SEL"], font=F(18), text_color=CYAN).pack(side="left")
        # controls are packed before the text so a long device name can never squeeze them
        self.switch = Switch(top, text="", width=44, command=lambda: on_toggle(key, self.switch.get() == 1))
        self.switch.pack(side="right")
        self.edit_btn = ctk.CTkButton(top, text="Customize", width=96, height=30, corner_radius=15, font=F(13),
                                      fg_color=P["BTN"], hover_color=P["BTN_HOVER"], text_color=P["TEXT"],
                                      border_width=1, border_color=P["BTN_LINE"], command=lambda: on_edit(key))
        self.edit_btn.pack(side="right", padx=10)
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkLabel(info, text=name, font=F(14, "bold"), text_color=P["TEXT"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=f"{tname} · {leds} LEDs", font=F(11), text_color=P["MUTED"], anchor="w").pack(fill="x")
        if enabled:
            self.switch.select()
        self.strip = GlowBar(self, height=20, thickness=6)
        self.strip.n = max(1, min(leds, 24))
        self.strip.pack(fill="x", padx=12, pady=(4, 14))


class FanCard(SmoothFrame):
    def __init__(self, master, fan, on_manual, on_reset):
        super().__init__(master, fg_color=P["CARD"], corner_radius=6)
        accent_bar(self)
        self.fid, self.on_manual, self.touched = fan["id"], on_manual, 0
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 0))
        self.spin = tk.Canvas(top, width=40, height=40, bg=P["CARD"], highlightthickness=0)
        self.spin.pack(side="left")
        self.blades = [self.spin.create_arc(4, 4, 36, 36, start=a, extent=50, fill=P["FAINT"], outline="")
                       for a in (0, 120, 240)]
        self.spin.create_oval(15, 15, 25, 25, fill=P["CARD"], outline="")
        self.angle = 0
        self.badge = ctk.CTkButton(top, text="", width=78, height=24, corner_radius=12, font=F(10, "bold"),
                                   fg_color=P["SEL"], hover_color=P["HOVER"], text_color=CYAN,
                                   border_width=1, border_color=P["BTN_LINE"],
                                   command=lambda: on_reset(self.fid))
        self.badge.pack(side="right")
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkLabel(info, text=fan["name"], font=F(14, "bold"), text_color=P["TEXT"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=fan["hw"], font=F(11), text_color=P["MUTED"], anchor="w").pack(fill="x")
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=16, pady=(10, 0))
        self.rpm = ctk.CTkLabel(mid, text="—", font=F(26, "bold"), text_color=P["TEXT"])
        self.rpm.pack(side="left")
        ctk.CTkLabel(mid, text=" RPM", font=F(12), text_color=P["MUTED"]).pack(side="left", pady=(8, 0))
        self.pct = ctk.CTkLabel(mid, text="", font=F(13, "bold"), text_color=P["MUTED"])
        self.pct.pack(side="right")
        self.slider = Slider(self, from_=hwm.FAN_FLOOR, to=100, height=16, fg_color=P["TRACK"],
                                    button_color=P["TEXT"], button_hover_color="white", command=self._slide)
        self.slider.pack(fill="x", padx=16, pady=(8, 16))

    def _slide(self, v):
        self.touched = time.time()
        self.pct.configure(text=f"{int(v)}%")
        self.on_manual(self.fid, int(v))

    def update_fan(self, f, accent, auto):
        rpm = f.get("rpm")
        self.rpm.configure(text=f"{rpm:,.0f}" if rpm is not None else "—")
        target = f.get("target")
        shown = target if target is not None else f.get("pct")
        if time.time() - self.touched > 1.5:
            self.pct.configure(text=fmt(shown, "%"))
            if shown is not None:
                self.slider.set(shown)
        self.slider.configure(progress_color=accent)
        if f.get("manual") is not None:
            self.badge.configure(text="MANUAL  ↺", fg_color=P["SEL"], text_color=accent, border_color=accent)
        else:
            self.badge.configure(text="BIOS" if auto else "CURVE", fg_color=P["SEL"], text_color=CYAN, border_color=P["BTN_LINE"])
        speed = (rpm or 0) / 2500
        self.angle = (self.angle + 40 * speed) % 360
        col = accent if rpm else P["FAINT"]
        for i, b in enumerate(self.blades):
            self.spin.itemconfigure(b, start=self.angle + i * 120, fill=col)


# ----------------------------------------------------------------------------- main window
# ---------------------------------------------------------------- system tray + single instance
INSTANCE_PORT = 47616          # localhost only: a second launch tells the running copy to show itself


class Tray:
    """Notification-area (system tray) icon. Clicks arrive on pystray's thread, so they're passed to the
    app through its queue and handled on the UI thread."""

    def __init__(self, app, image):
        import pystray                      # Windows backend; imported here so other platforms still start
        self.app = app
        menu = pystray.Menu(
            pystray.MenuItem("Open Central RGB", lambda *_: app.q.put(("tray", "show")), default=True),
            pystray.MenuItem("Turn lights off", lambda *_: app.q.put(("tray", "off"))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Central RGB", lambda *_: app.q.put(("tray", "quit"))))
        self.icon = pystray.Icon("CentralRGB", image.resize((64, 64), Image.LANCZOS), eng.APP_NAME, menu)
        self.icon.run_detached()

    def notify(self, text):
        try:
            self.icon.notify(text, eng.APP_NAME)
        except Exception:
            pass

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass


def claim_single_instance(app_q, wait=0.0) -> bool:
    """Become the running copy. Returns False if Central RGB is already running (it is asked to show itself).
    wait: keep trying this many seconds first (used after a restart, while the old copy closes)."""
    import socket
    end = time.time() + wait
    while True:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.bind(("127.0.0.1", INSTANCE_PORT))
            srv.listen(4)
            break
        except OSError:
            srv.close()
            if time.time() < end:
                time.sleep(0.25)
                continue
            srv = None
            break
    if srv is None:
        try:
            with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as c:
                c.sendall(b"show")
        except OSError:
            return True                     # port taken by something else: just run
        return False

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                with conn:
                    if conn.recv(16).startswith(b"show"):
                        app_q.put(("tray", "show"))
            except OSError:
                return
    threading.Thread(target=serve, daemon=True).start()
    return True


# ---------------------------------------------------------------- startup splash in its own process
class SplashProcess:
    """Runs the logo animation in a separate small process. The app builds its window at full speed
    while staying invisible, so nothing it does can make the animation stutter."""

    def __init__(self):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--splash"]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve()), "--splash"]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  creationflags=eng.NO_WINDOW, env=eng.child_env())
        self.t0 = time.perf_counter()

    def ready(self):
        """App is built: the logo plays its exit and the helper closes."""
        try:
            self.p.stdin.write(b"ready\n")
            self.p.stdin.flush()
            self.p.stdin.close()
        except Exception:
            pass

    def alive(self) -> bool:
        return self.p.poll() is None


def run_splash():
    """Entry point of the splash helper: a borderless, rounded card in the middle of the screen."""
    if eng.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    P.update(SOLID)
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.configure(bg=P["BG"])
    sc = max(1.0, root.winfo_fpixels("1i") / 96)
    w, h = int(560 * sc), int(420 * sc)
    x, y = (root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.attributes("-topmost", True)
    try:
        icon = Image.open(resource("central_rgb.png")).convert("RGBA")
    except Exception:
        return
    sp = Splash(root, icon, on_done=root.destroy, size=132)   # glow sized to fade out inside the card
    root.deiconify()
    root.update_idletasks()
    if eng.IS_WIN:
        try:                                     # Windows 11: rounded corners on the borderless card
            import ctypes
            from ctypes import wintypes
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            v = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(v), ctypes.sizeof(v))
        except Exception:
            pass

    def wait_for_app():
        try:
            sys.stdin.readline()                 # "ready", or EOF if the app went away
        except Exception:
            pass
        root.after(0, lambda: setattr(sp, "ready", True))
    if sys.stdin is not None:
        threading.Thread(target=wait_for_app, daemon=True).start()
    else:
        sp.ready = True
    root.after(30000, lambda: setattr(sp, "ready", True))   # never hang around
    sp.begin()
    root.mainloop()


class App(ctk.CTk):
    TEST_BACKEND = None   # tests can inject a simulated sensor backend

    def __init__(self, background=False, selftest=None):
        self._t_start = time.perf_counter()
        self.timings: dict[str, float] = {}
        self.slow_steps: list[str] = []
        self._gaps: list[tuple[float, float]] = []
        self.selftest = selftest          # path to write the result to, when run with --selftest
        self.selftest_errors: list[str] = []
        self.settings = eng.Settings()
        P.update(SOLID)
        ctk.set_appearance_mode("dark")
        self.splash_proc = None
        if not background and selftest is None and self.settings.data.get("animations", True) and not eng.is_onefile():
            try:
                self.splash_proc = SplashProcess()          # starts animating while we build
            except Exception:
                self.splash_proc = None
        super().__init__(fg_color=P["BG"])
        self.withdraw()                                     # stays hidden until fully built
        self.title(eng.APP_NAME)
        self.geometry("1300x840")
        self.minsize(1200, 790)
        self.background = background
        self._set_icon()

        self.q: queue.Queue = queue.Queue()
        self.manager = eng.OpenRGBManager(self.settings, self.log)
        self.engine = eng.LightingEngine(self.log, on_disconnect=lambda: self.q.put(("disconnected",)))
        self.engine.set_excluded(self.settings["excluded"])
        self.engine.set_overrides(self.settings.data.get("device_overrides", {}))
        self.editor, self.editor_key, self.sysinfo = None, None, []
        self.engine.state.update(self.settings["state"])
        self.engine.paused = True
        self.engine.start()
        self.monitor = hwm.HardwareMonitor(self.log, self.settings, backend=self.TEST_BACKEND)
        self.monitor.start()
        self.fps = fpo.FpsCounter(self.log)
        self.overlay_cfg = fpo.overlay_settings(self.settings)
        self.overlay_win = None

        st = self.settings["state"]
        self.color = tuple(st.get("color", (0, 120, 255)))
        self.effect = st.get("effect", "Static")
        self.accent = DEFAULT_ACCENT
        self.accent_widgets: list = []
        self.device_rows, self.device_cards = [], []
        self.fan_cards: dict[str, FanCard] = {}
        self.sensor_items: dict[str, str] = {}
        self.connected = False
        self.current_page = "Home"
        self.snap = self.monitor.snapshot()

        self.splash = None                       # the logo animation now runs in SplashProcess
        self._ttk_style()
        self._build()
        self.background = background
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._size_seen, self._resize_freeze, self._resize_job = None, 0, None
        self.bind("<Configure>", self._on_resize, add="+")
        self._was_minimized = False
        self.bind("<Unmap>", self._on_unmap, add="+")
        self.bind("<Map>", self._on_map, add="+")
        self._steps = self._page_steps()
        self._last_tick = time.perf_counter()
        self._hidden_flag = True
        self._stall_samples = []
        self.after(16, self._stall_tick)
        threading.Thread(target=self._watchdog, daemon=True).start()
        for _ in self._steps:                   # window is hidden, so build everything in one go
            pass
        self._finish_startup()

    def _finish_startup(self):
        background, selftest = self.background, self.selftest
        self.tray = None
        if eng.IS_WIN and self._icon_img is not None:
            try:
                self.tray = Tray(self, self._icon_img)
            except Exception as e:
                self.log(f"System tray icon unavailable: {e}", "warn")
        self._sync_ui_from_state()
        self.show_page("Home", animate=False)
        threading.Thread(target=self._check_autostart, daemon=True).start()
        self.after(100, self._poll_queue)
        self.after(40, self._animate)
        self.after(500, self._refresh_hw)
        self.after(900, self._overlay_tick)
        if self.overlay_cfg["enabled"]:
            self.fps.start()
        self.after(60, self._window_effects)
        if background:
            if self.tray is not None:
                self.withdraw()          # start-at-login: straight to the tray
            else:
                self.iconify()
        if not background:
            self._reveal()
        self.timings["window built"] = time.perf_counter() - self._t_start
        if selftest:
            self.after(9000, self._run_selftest)
            return
        self.after(300, lambda: self._bg(self._startup))
        self.after(800, lambda: self._bg(self._load_sysinfo))

    # ---------------------------------------------------------------- self-test (used by the CI build)
    def report_callback_exception(self, exc, val, tb):
        msg = "".join(traceback.format_exception(exc, val, tb))
        if self.selftest is not None:
            self.selftest_errors.append(msg)
        sys.stderr.write(msg)

    def _watchdog(self):
        """When the window stops responding for 150 ms, note what every thread was doing. The self-test
        prints these; normal runs write them to activity.log, so slowdowns on real hardware can be traced."""
        sampled = None
        while len(self._stall_samples) < 40:
            time.sleep(0.05)
            last = self._last_tick
            if time.perf_counter() - last > 0.15 and sampled != last and not self._hidden_flag:
                sampled = last
                names = {t.ident: t.name for t in threading.enumerate()}
                lines = []
                for tid, fr in sys._current_frames().items():
                    if tid == threading.get_ident():
                        continue
                    st = traceback.extract_stack(fr)[-4:]
                    lines.append(f"    {names.get(tid, tid)}: " + " <- ".join(
                        f"{os.path.basename(f.filename)}:{f.lineno} {f.name}" for f in reversed(st)))
                self._stall_samples.append((time.perf_counter() - self._t_start, lines))
                if self.selftest is None:
                    self._stall_pending = (time.perf_counter() - self._t_start, lines, last)

    def _stall_tick(self):
        now = time.perf_counter()
        pend = getattr(self, "_stall_pending", None)
        if pend is not None and pend[2] == self._last_tick:     # the stall just ended: log how long it was
            self._stall_pending = None
            self.log(f"UI paused {(now - pend[2]) * 1000:.0f} ms on {self.current_page} page "
                     f"({pend[0]:.1f} s after start). Threads were in:\n" + "\n".join(pend[1]))
        self._hidden_flag = self._hidden()
        if self.selftest is not None:
            self._gaps.append((now - self._t_start, now - self._last_tick))
        self._last_tick = now
        self.after(16 if self.selftest is not None else 50, self._stall_tick)

    def _run_selftest(self):
        """Open every page, draw the overlay preview, run the system check, then report and exit."""
        steps = []
        try:
            shots = os.environ.get("CENTRALRGB_SHOTS")
            for name, *_ in NAV:
                t0 = time.perf_counter()
                self.show_page(name)
                self.update()
                steps.append(f"page {name}: ok, switch took {(time.perf_counter() - t0) * 1000:.0f} ms")
            for name, *_ in NAV:                      # second pass: what switching feels like once warm
                t0 = time.perf_counter()
                self.show_page(name)
                self.update()
                steps.append(f"page {name} again: {(time.perf_counter() - t0) * 1000:.0f} ms  ("
                             + ", ".join(f"{k} {v:.0f}" for k, v in getattr(self, "_switch_phases", {}).items()) + ")")
                if shots and eng.IS_WIN:
                    try:
                        from PIL import ImageGrab
                        self.update()
                        x, y = self.winfo_rootx(), self.winfo_rooty()
                        from PIL import ImageStat
                        g = ImageGrab.grab((x, y, x + self.winfo_width(), y + self.winfo_height()))
                        g.save(os.path.join(shots, f"{name}.png"))
                        hx, hy = self._holder.winfo_rootx() - x, self._holder.winfo_rooty() - y
                        area = g.crop((hx, hy, hx + self._holder.winfo_width(), hy + self._holder.winfo_height())).convert("L")
                        sd = ImageStat.Stat(area).stddev[0]
                        prev = getattr(self, "_shot_prev", None)
                        diff = ImageStat.Stat(ImageChops.difference(area, prev)).mean[0] if prev is not None and prev.size == area.size else -1
                        self._shot_prev = area
                        steps.append(f"  screen check: content contrast {sd:.1f}, change from previous page {diff:.1f}")
                        if sd < 3:
                            self.selftest_errors.append(f"Page {name} looks blank after switching")
                    except Exception as e:
                        steps.append(f"  screenshot failed: {e}")
            missing = [f for f in PRESET_FILES.values() if not resource(f).exists()]
            if missing:
                raise RuntimeError(f"Preset pictures missing from the build: {missing}")
            steps.append(f"preset pictures: {len(PRESET_FILES)} found")
            for kind in ("RAM", "GPU", "Cooler", "Case", "Keyboard", "Mouse", "Motherboard", "LED strip", "Other"):
                dm.model_for(kind, 24, hex2rgb(P["CARD"])).render(dm.rainbow(24))
            steps.append("device models: ok")
            steps.append(f"windows accent read as: {windows_accent('(not found)')}")
            sp = SplashProcess()
            time.sleep(1.5)
            up = sp.alive()
            sp.ready()
            for _ in range(200):
                if not sp.alive():
                    break
                time.sleep(0.05)
            if not up or sp.alive():
                raise RuntimeError(f"Splash helper problem (started={up}, still running={sp.alive()})")
            steps.append(f"splash helper: started, closed {time.perf_counter() - sp.t0 - 1.5:.1f} s after ready")
            t0 = time.perf_counter()
            self.state("zoomed" if eng.IS_WIN else "normal")
            self.update()
            self.after(200)
            self.update()
            self.state("normal")
            self.update()
            self.after(200)
            self.update()
            steps.append(f"maximize + restore: {(time.perf_counter() - t0 - 0.4) * 1000:.0f} ms")
            self.iconify()
            self.update()
            self.after(300)
            self.update()
            self.deiconify()
            for _ in range(40):
                self.update()
                time.sleep(0.02)
            alpha = float(self.attributes("-alpha"))
            if alpha < 0.99:
                raise RuntimeError(f"Window not fully visible after restoring from minimized (alpha={alpha})")
            steps.append("minimize + restore: window comes back fully drawn")
            if eng.IS_WIN:                                   # tray: icon shows, X hides, Open brings it back
                if self.tray is None:
                    raise RuntimeError("System tray icon was not created")
                for _ in range(40):
                    if self.tray.icon.visible:
                        break
                    time.sleep(0.05)
                self.settings["tray_hint_shown"] = True
                self.on_close()
                self.update()
                hidden = self.state() == "withdrawn"
                self._tray_action("show")
                self.update()
                if not hidden or self.state() != "normal":
                    raise RuntimeError(f"Close-to-tray failed (hidden={hidden}, state={self.state()})")
                steps.append(f"tray: icon visible={self.tray.icon.visible}, X hides the window, Open restores it")
            self.overlay_preview.render(self.overlay_cfg, {"name": "test", "fps": 144, "low": 110, "ms": 6.9}, {})
            steps.append("overlay preview: ok")
            res = eng.system_check()
            steps.append(f"system check: {len(res)} results")
            for level, msg in res:
                steps.append(f"  [{level}] {msg}")
            steps.append(f"monitor: {self.monitor.snapshot()['status']}")
        except Exception:
            self.selftest_errors.append(traceback.format_exc())
        steps.append("timings:")
        for k, v in self.timings.items():
            steps.append(f"  {k}: {v * 1000:.0f} ms")
        try:
            import psutil
            me = psutil.Process()
            for label, eff, hide in (("idle on Home, Static", "Static", False), ("idle on Home, Rainbow Wave", "Rainbow Wave", False),
                                     ("hidden in tray, Rainbow Wave", "Rainbow Wave", True)):
                self._set_effect(eff)
                self.show_page("Home")
                if hide:
                    self.withdraw()
                self.update()
                me.cpu_percent(None)
                end = time.time() + 3
                while time.time() < end:
                    self.update()
                    time.sleep(0.01)
                cpu = me.cpu_percent(None) / max(1, psutil.cpu_count())
                steps.append(f"CPU {label}: {cpu:.1f}% of the whole machine")
                if hide:
                    self.deiconify()
        except Exception as e:
            steps.append(f"CPU measure failed: {e}")
        steps.append("slow build steps: " + (", ".join(self.slow_steps) or "none"))
        for at, lines in getattr(self, "_stall_samples", []):
            steps.append(f"  stall at {at:.1f} s, threads were in:")
            steps.extend(lines)
        worst = sorted(self._gaps, key=lambda g: -g[1])[:5]
        steps.append("longest UI freezes after the window appeared (at time: length):")
        for at, g in worst:
            steps.append(f"  {at:.1f} s: {g * 1000:.0f} ms")
        ok = not self.selftest_errors
        report = [f"Central RGB {eng.APP_VERSION} self-test: {'PASSED' if ok else 'FAILED'}"] + steps + self.selftest_errors
        try:
            Path(self.selftest).write_text("\n".join(report), encoding="utf-8")
        except Exception:
            pass
        self.engine.stop()
        os._exit(0 if ok else 1)

    def _on_unmap(self, e):
        """Minimized: make the window transparent, so when it comes back nothing half-drawn can show."""
        if e.widget is self and self.state() == "iconic":
            self._was_minimized = True
            try:
                self.attributes("-alpha", 0.0)
            except tk.TclError:
                pass

    def _on_map(self, e):
        """Restored from the taskbar: repaint while still transparent, then fade in (no black flash)."""
        if e.widget is self and self._was_minimized:
            self._was_minimized = False
            self.after(1, self._repaint_and_show)

    def _repaint_and_show(self):
        try:
            self.update_idletasks()
            self.update()
        except tk.TclError:
            return
        self._fade_in(0.25)

    def _on_resize(self, e):
        """Maximize / restore / drag-resize: pause drawing while the layout changes, then repaint once.
        Pages you aren't looking at leave the layout and are laid out again when next opened."""
        if e.widget is not self:
            return
        size = (e.width, e.height)
        if self._size_seen is None or size == self._size_seen:
            self._size_seen = size
            return
        self._size_seen = size
        if not self._resize_freeze:
            self._resize_freeze = fx.freeze(self) or -1
            for n, pg in self.pages.items():
                if n != self.current_page and pg.winfo_manager():
                    pg.place_forget()
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(90, self._resize_done)

    def _resize_done(self):
        self._resize_job = None
        self.update_idletasks()
        h, self._resize_freeze = self._resize_freeze, 0
        if h and h != -1:
            fx.thaw(h)
            self.update_idletasks()

    def _reveal(self):
        """Show the finished window: drawn while fully transparent, then faded in as the logo leaves."""
        def show():
            try:
                self.attributes("-alpha", 0.0)
            except tk.TclError:
                pass
            self.deiconify()
            self.update_idletasks()
            self.update()                        # everything painted while still invisible
            self._fade_in(0.0)
        if self.splash_proc is not None and self.splash_proc.alive():
            self.splash_proc.ready()             # logo plays its exit (about half a second)
            self.after(320, show)
        else:
            show()

    def _fade_in(self, a):
        a = min(1.0, a + 0.12)
        try:
            self.attributes("-alpha", a)
        except tk.TclError:
            return
        if a < 1.0:
            self.after(16, lambda: self._fade_in(a))

    def _window_effects(self):
        fx.dark_titlebar(self)
        fx.titlebar_colors(self, P["BG"], P["LINE"], P["TEXT"])   # seamless title bar on Windows 11

    def _set_icon(self):
        try:
            self._icon_img = Image.open(resource("central_rgb.png")).convert("RGBA")
            self._icon = ImageTk.PhotoImage(self._icon_img.resize((64, 64), Image.LANCZOS))
            self.iconphoto(True, self._icon)
            if eng.IS_WIN:
                self.iconbitmap(default=str(resource("central_rgb.ico")))   # title bar + taskbar
        except Exception:
            self._icon_img = None

    def _ttk_style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("Dark.Treeview", background=P["CARD"], fieldbackground=P["CARD"], foreground=P["TEXT"],
                    rowheight=28, borderwidth=0, font=(FONT, 10))
        s.configure("Dark.Treeview.Heading", background=P["CARD2"], foreground=P["MUTED"], borderwidth=0,
                    relief="flat", font=(FONT, 10, "bold"), padding=(8, 6))
        s.map("Dark.Treeview.Heading", background=[("active", P["LINE"])])
        s.map("Dark.Treeview", background=[("selected", P["CARD2"])], foreground=[("selected", P["TEXT"])])
        s.layout("Dark.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Dark.Vertical.TScrollbar", background=P["CARD2"], troughcolor=P["CARD"], borderwidth=0,
                    arrowcolor=P["MUTED"], relief="flat")

    # ---------------------------------------------------------------- layout helpers
    def card(self, parent, **kw):
        c = SmoothFrame(parent, fg_color=P["CARD"], corner_radius=RADIUS, **kw)
        accent_bar(c)
        return c

    def label(self, parent, text, size=12, weight="normal", color=None, **kw):
        return ctk.CTkLabel(parent, text=text, font=F(size, weight), text_color=color or P["TEXT"], **kw)

    def caption(self, parent, text):
        """Fluent group heading: sentence case, semibold."""
        return ctk.CTkLabel(parent, text=text, font=F(14, "bold"), text_color=P["TEXT"], anchor="w")

    def setting_row(self, parent, glyph, fallback, title, desc, make_control):
        """Windows 11 Settings row: icon, title and description on the left, a control on the right."""
        row = SmoothFrame(parent, fg_color=P["CARD"], corner_radius=6, height=68)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)
        icon_label(row, glyph, fallback, size=18, width=24, color=P["TEXT"]).pack(side="left", padx=(18, 14))
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        self.label(txt, title, 14, anchor="w").pack(fill="x")
        if desc:
            self.label(txt, desc, 12, color=P["MUTED"], anchor="w", justify="left", wraplength=560).pack(fill="x")
        ctl = make_control(row)
        ctl.pack(side="right", padx=18)
        return row, ctl

    def primary(self, parent, text, cmd, **kw):
        b = ctk.CTkButton(parent, text=text, command=cmd, fg_color=self.accent, hover_color=self.accent,
                          text_color=on_color(self.accent), font=F(14), corner_radius=kw.pop("corner_radius", 6), **kw)
        self.accent_widgets.append(("button", b))
        return b

    def secondary(self, parent, text, cmd, **kw):
        return ctk.CTkButton(parent, text=text, command=cmd, fg_color=P["BTN"], hover_color=P["BTN_HOVER"],
                             text_color=P["TEXT"], font=F(14), corner_radius=kw.pop("corner_radius", 6),
                             border_width=1, border_color=P["BTN_LINE"], **kw)

    def slider_row(self, parent, label, value, cmd, lo=0, hi=100, unit="%"):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        self.label(top, label, 12, "bold").pack(side="left")
        val = self.label(top, f"{value}{unit}", 12, color=P["MUTED"])
        val.pack(side="right")
        s = Slider(row, from_=lo, to=hi, number_of_steps=hi - lo, height=20, progress_color=self.accent,
                          button_color=self.accent, button_hover_color="white", fg_color=P["TRACK"])
        s.set(value)
        s.configure(command=lambda v: (val.configure(text=f"{int(v)}{unit}"), cmd(int(v))))
        s.pack(fill="x", pady=(6, 0))
        s.value_label = val
        self.accent_widgets.append(("slider", s))
        return row, s

    def header(self, parent, title, subtitle, right=None):
        h = ctk.CTkFrame(parent, fg_color="transparent")
        h.pack(fill="x", pady=(4, 20))
        txt = ctk.CTkFrame(h, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        img = None
        if img is not None:
            ctk.CTkLabel(txt, text="", image=img, anchor="w").pack(fill="x")
        else:
            ctk.CTkLabel(txt, text=spaced(title), font=F(28, display=True), text_color=P["TEXT"], anchor="w").pack(fill="x")
        if subtitle:
            self.label(txt, subtitle, 13, color=P["MUTED"], anchor="w").pack(fill="x", pady=(2, 0))
        return h

    # ---------------------------------------------------------------- build
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color=P["SIDE"], corner_radius=0, width=268)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.pack_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 14))
        self.logo = tk.Canvas(brand, width=32, height=32, bg=P["SIDE"], highlightthickness=0)
        self.logo.pack(side="left")
        if self._icon_img is not None:
            self._logo_img = ImageTk.PhotoImage(self._icon_img.resize((32, 32), Image.LANCZOS))
            self.logo.create_image(16, 16, image=self._logo_img)
        bt = ctk.CTkFrame(brand, fg_color="transparent")
        bt.pack(side="left", padx=12)
        self.label(bt, "Central RGB", 14, "bold", anchor="w").pack(fill="x")
        self.label(bt, f"Version {APP_VERSION}", 11, color=P["FAINT"], anchor="w").pack(fill="x")

        self.nav = {}
        for name, glyph, fallback in NAV:
            item = NavItem(side, name, glyph, fallback, lambda n=name: self.show_page(n))
            item.pack(fill="x", padx=8, pady=1)
            self.nav[name] = item

        st = ctk.CTkFrame(side, fg_color="transparent")
        st.pack(side="bottom", fill="x", padx=20, pady=18)
        self.status_rows = {}
        for key, label in (("rgb", "Lighting"), ("hw", "Sensors")):
            r = ctk.CTkFrame(st, fg_color="transparent")
            r.pack(fill="x", pady=3)
            dot = tk.Canvas(r, width=8, height=8, bg=P["SIDE"], highlightthickness=0)
            dot.pack(side="left", pady=(6, 0), anchor="n")
            oval = dot.create_oval(0, 0, 8, 8, fill=WARN, width=0)
            col = ctk.CTkFrame(r, fg_color="transparent")
            col.pack(side="left", padx=10, fill="x", expand=True)
            self.label(col, label, 12, anchor="w").pack(fill="x")
            sub = self.label(col, "Starting…", 11, color=P["FAINT"], anchor="w", justify="left", wraplength=200)
            sub.pack(fill="x")
            self.status_rows[key] = (dot, oval, sub)

        if self.splash is not None:
            self.splash.keep_on_top()
        holder = ctk.CTkFrame(self, fg_color=P["BG"], corner_radius=0)
        holder.grid(row=0, column=1, sticky="nsew", padx=(20, 36), pady=(18, 24))
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        self.pages = {}
        self._holder = holder

    def _page_steps(self):
        """Build every page, pausing between pieces (each page builder is a generator)."""
        for name, *_ in NAV:
            f = ctk.CTkFrame(self._holder, fg_color=P["BG"], corner_radius=0)
            f.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[name] = f
            _t = time.perf_counter()
            step = 0
            for _ in getattr(self, f"_page_{name.lower()}")(f):
                took = time.perf_counter() - _t
                self.timings[f"page {name}"] = self.timings.get(f"page {name}", 0) + took
                if took > 0.15:
                    self.slow_steps.append(f"{name} step {step}: {took * 1000:.0f} ms")
                step += 1
                yield
                _t = time.perf_counter()
            self.timings[f"page {name}"] = self.timings.get(f"page {name}", 0) + time.perf_counter() - _t
            if name != "Home":
                f.place_forget()        # only the visible page takes part in layout; others join when opened
            if self.splash is not None:
                self.splash.keep_on_top()

    def _build_slice(self):
        """Run page building for ~12 ms, then let the splash draw a frame."""
        end = time.perf_counter() + 0.012
        try:
            while time.perf_counter() < end:
                next(self._steps)
        except StopIteration:
            self._finish_startup()
            return
        self.after(1, self._build_slice)

    # ---------------------------------------------------------------- Home
    def _page_home(self, p):
        self.header(p, "Home", "")
        # hero: logo, name, live status and the current lighting
        yield
        hero = self.card(p)
        yield
        hero.pack(fill="x")
        yield
        top = ctk.CTkFrame(hero, fg_color="transparent")
        yield
        top.pack(fill="x", padx=22, pady=(20, 6))
        yield
        logo = tk.Canvas(top, width=64, height=64, bg=P["CARD"], highlightthickness=0)
        yield
        logo.pack(side="left")
        yield
        if self._icon_img is not None:
            self._home_logo = ImageTk.PhotoImage(self._icon_img.resize((64, 64), Image.LANCZOS))
            logo.create_image(32, 32, image=self._home_logo)
        yield
        txt = ctk.CTkFrame(top, fg_color="transparent")
        yield
        txt.pack(side="left", padx=18, fill="x", expand=True)
        yield
        ctk.CTkLabel(txt, text="Central RGB", font=F(22, "bold", display=True), text_color=P["TEXT"], anchor="w").pack(fill="x")
        yield
        self.home_status = self.label(txt, "Starting…", 13, color=P["MUTED"], anchor="w")
        yield
        self.home_status.pack(fill="x")
        yield
        self.primary(top, "Apply lighting", self._apply_all, height=34, width=140).pack(side="right")
        yield
        self.home_strip = GlowBar(hero, height=22, thickness=8)
        yield
        self.home_strip.pack(fill="x", padx=22, pady=(6, 18))

        # tiles
        yield
        grid = ctk.CTkFrame(p, fg_color="transparent")
        yield
        grid.pack(fill="x", pady=(14, 0))
        yield
        self.home_tiles = {}
        yield
        specs = [("Lighting", "\uea80", "✦", "Lighting"), ("Fans", "\uec4a", "✺", "Fans"),
                 ("Processor", "\ue950", "◔", "Monitor"), ("Graphics", "\ue7f4", "▣", "Monitor")]
        yield
        for i, (title, glyph, fb, page) in enumerate(specs):
            c = self.card(grid, height=132)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            c.pack_propagate(False)
            grid.grid_columnconfigure(i, weight=1, uniform="ht")
            hdr = ctk.CTkFrame(c, fg_color="transparent")
            hdr.pack(fill="x", padx=18, pady=(16, 0))
            icon_label(hdr, glyph, fb, size=16, color=P["MUTED"]).pack(side="left")
            self.label(hdr, title, 13, color=P["MUTED"]).pack(side="left", padx=10)
            big = ctk.CTkLabel(c, text="—", font=F(26, "bold", display=True), text_color=P["TEXT"], anchor="w")
            big.pack(fill="x", padx=18, pady=(8, 0))
            sub = self.label(c, "", 12, color=P["FAINT"], anchor="w")
            sub.pack(fill="x", padx=18)
            self.home_tiles[title] = (big, sub)
            for w in (c, hdr, big, sub):
                w.bind("<Button-1>", lambda e, pg=page: self.show_page(pg))
                w.configure(cursor="hand2")
        yield
        self.home_light_strip = GlowBar(self.home_tiles["Lighting"][1].master, height=12, thickness=4)
        yield
        self.home_light_strip.pack(fill="x", padx=18, pady=(6, 0))

        # quick actions
        yield
        self.caption(p, "Quick actions").pack(fill="x", pady=(22, 8))
        yield
        self.home_switches = []

        yield
        def lights(row):
            f = ctk.CTkFrame(row, fg_color="transparent")
            self.secondary(f, "All lights off", lambda: self._set_effect("Off"), height=32, width=120).pack(side="right", padx=(8, 0))
            self.secondary(f, "Rainbow", lambda: self._set_effect("Rainbow Wave"), height=32, width=100).pack(side="right")
            return f
        yield
        self.setting_row(p, "\uea80", "✦", "Lighting", "Quick effects for every RGB device", lights)

        yield
        def fans(row):
            self.home_fan_seg = PillSwitcher(row, values=hwm.PROFILES[:5], height=32, font=F(13), corner_radius=6,
                                                       fg_color=P["CARD2"], unselected_color=P["CARD2"],
                                                       unselected_hover_color=P["BTN_HOVER"], selected_color=self.accent,
                                                       selected_hover_color=self.accent, text_color=P["TEXT"],
                                                       command=lambda v: (self._set_fan_profile(v), self.fan_seg.set(v)))
            self.home_fan_seg.set(self.monitor.profile if self.monitor.profile in hwm.PROFILES[:5] else "Auto")
            self.accent_widgets.append(("seg", self.home_fan_seg))
            return self.home_fan_seg
        yield
        self.setting_row(p, "\uec4a", "✺", "Fan profile", "How your fans respond to temperature", fans)

        yield
        def overlay(row):
            self.home_overlay_sw = Switch(row, text="", width=46, command=self._home_overlay)
            if self.overlay_cfg["enabled"]:
                self.home_overlay_sw.select()
            self.home_switches.append(self.home_overlay_sw)
            return self.home_overlay_sw
        yield
        self.setting_row(p, "\ue7fc", "▤", "Game overlay", "Show your frame rate on top of games", overlay)

    def _home_overlay(self):
        on = self.home_overlay_sw.get() == 1
        self.overlay_sw.select() if on else self.overlay_sw.deselect()
        self._overlay_toggle()

    def _refresh_home(self, s):
        m, fans = s.get("metrics", {}), s.get("fans", {})
        rows = self.device_rows
        self.home_status.configure(text=(f"{len(rows)} RGB devices · {sum(r[3] for r in rows)} LEDs · {len(fans)} fans"
                                         if self.connected else "Connecting to your RGB hardware…"))
        big, sub = self.home_tiles["Lighting"]
        big.configure(text=self.effect, font=F(26 if len(self.effect) <= 10 else 20, "bold", display=True))
        sub.configure(text=f"{hexcol(self.color).upper()} · {int(self.bright.get())}% brightness")
        big, sub = self.home_tiles["Fans"]
        big.configure(text=s.get("profile", "Auto"))
        rpms = [f["rpm"] for f in fans.values() if f.get("rpm")]
        sub.configure(text=f"{len(fans)} fans · avg {sum(rpms) / len(rpms):,.0f} RPM" if rpms else "No controllable fans yet")
        for title, tk_, lk in (("Processor", "cpu_temp", "cpu_load"), ("Graphics", "gpu_temp", "gpu_load")):
            big, sub = self.home_tiles[title]
            big.configure(text=fmt(m.get(tk_), "°C"), text_color=temp_color(m.get(tk_)) if m.get(tk_) else P["TEXT"])
            sub.configure(text=f"{fmt(m.get(lk), '%')} load")
        if self.home_fan_seg.get() != s.get("profile") and s.get("profile") in hwm.PROFILES[:5]:
            self.home_fan_seg.set(s["profile"])

    # ---------------------------------------------------------------- Lighting
    def _page_lighting(self, p):
        self.header(p, "Lighting", "Pick a color and an effect. Changes go live on every selected device.")
        yield
        self.light_scope = "All"
        yield
        self.chip_row = ctk.CTkFrame(p, fg_color="transparent")
        yield
        self.chip_row.pack(fill="x", pady=(0, 12))
        yield
        self.chips = {}
        yield
        self._build_chips()

        yield
        prev = self.card(p, height=58)
        yield
        prev.pack(fill="x", pady=(0, 14))
        yield
        prev.pack_propagate(False)
        yield
        self.preview_label = self.label(prev, "", 14, anchor="w", width=250)
        yield
        self.preview_label.pack(side="left", padx=(18, 10))
        yield
        pv = ctk.CTkFrame(prev, fg_color="transparent")
        yield
        pv.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=8)
        yield
        self.preview = LedStrip(pv, n=36, height=28)
        yield
        self.preview.pack(fill="x")
        yield
        self.preview_track = tk.Canvas(pv, height=4, bg=P["CARD"], highlightthickness=0)
        yield
        self.preview_track.pack(fill="x", pady=(2, 0))

        yield
        body = ctk.CTkFrame(p, fg_color="transparent")
        yield
        body.pack(fill="both", expand=True)
        yield
        body.grid_columnconfigure(1, weight=1)
        yield
        body.grid_rowconfigure(0, weight=1)

        yield
        cc = self.card(body)
        yield
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        yield
        self.caption(cc, "Color").pack(fill="x", padx=18, pady=(14, 8))
        yield
        self.wheel = ColorWheel(cc, size=196, command=lambda rgb: self._set_color(rgb, from_wheel=True))
        yield
        self.wheel.pack(padx=18)
        yield
        hexrow = ctk.CTkFrame(cc, fg_color="transparent")
        yield
        hexrow.pack(fill="x", padx=18, pady=(12, 6))
        yield
        self.swatch = tk.Canvas(hexrow, width=28, height=28, bg=P["CARD"], highlightthickness=0)
        yield
        self.swatch.pack(side="left")
        yield
        self.swatch_item = self.swatch.create_rectangle(1, 1, 27, 27, fill="#000", width=0)
        yield
        self.hex_entry = ctk.CTkEntry(hexrow, width=104, height=30, corner_radius=6, font=F(13),
                                      fg_color=P["CARD2"], border_width=1, border_color=P["LINE"], text_color=P["TEXT"],
                                      justify="center")
        yield
        self.hex_entry.pack(side="left", padx=10)
        yield
        self.hex_entry.bind("<Return>", self._hex_entered)
        yield
        self.hex_entry.bind("<FocusOut>", self._hex_entered)
        yield
        sw = tk.Canvas(cc, height=48, width=200, bg=P["CARD"], highlightthickness=0)
        yield
        sw.pack(padx=18, pady=(4, 4), anchor="w")
        yield
        step = 200 / len(SWATCHES)
        yield
        for row, k in ((0, 0.0), (1, 0.42)):                       # vivid row, then a softer row
            for i, c in enumerate(SWATCHES):
                col = tuple(int(v) for v in mix(c, (230, 230, 240), k)) if k else c
                x = step * i + step / 2
                it = sw.create_rectangle(x - 9, 3 + row * 24, x + 9, 21 + row * 24, fill=hexcol(col), outline=P["CARD"], width=2)
                sw.tag_bind(it, "<Button-1>", lambda e, cl=col: self._set_color(cl))
                sw.tag_bind(it, "<Enter>", lambda e, i2=it: sw.itemconfigure(i2, outline="white"))
                sw.tag_bind(it, "<Leave>", lambda e, i2=it: sw.itemconfigure(i2, outline=P["CARD"]))
        yield
        rgbrow = ctk.CTkFrame(cc, fg_color="transparent")
        yield
        rgbrow.pack(fill="x", padx=18, pady=(6, 14))
        yield
        self.rgb_entries = []
        yield
        for ch in "RGB":
            self.label(rgbrow, ch, 12, color=P["MUTED"]).pack(side="left", padx=(0, 5))
            e = ctk.CTkEntry(rgbrow, width=46, height=28, corner_radius=6, font=F(12), fg_color=P["CARD2"],
                             border_width=1, border_color=P["LINE"], text_color=P["TEXT"], justify="center")
            e.pack(side="left", padx=(0, 10))
            e.bind("<Return>", self._rgb_entered)
            e.bind("<FocusOut>", self._rgb_entered)
            self.rgb_entries.append(e)

        yield
        right = ctk.CTkFrame(body, fg_color="transparent")
        yield
        right.grid(row=0, column=1, sticky="nsew")
        yield
        ec = self.card(right)
        yield
        ec.pack(fill="x")
        yield
        self.caption(ec, "Effect").pack(fill="x", padx=18, pady=(14, 6))
        yield
        grid = ctk.CTkFrame(ec, fg_color="transparent")
        yield
        grid.pack(fill="x", padx=12, pady=(0, 12))
        yield
        self.tiles = {}
        yield
        for i, name in enumerate(eng.BASIC_EFFECTS):
            t = EffectTile(grid, name, self._set_effect)
            t.grid(row=0, column=i, sticky="nsew", padx=3, pady=2)
            grid.grid_columnconfigure(i, weight=1, uniform="e")
            self.tiles[name] = t
        yield
        self.caption(ec, "Presets").pack(fill="x", padx=18, pady=(4, 6))
        yield
        # 16 presets: about two and a half rows show, the rest scroll into view
        scroll = LightScroll(ec, height=218)
        pg = scroll.inner
        yield
        scroll.pack(fill="x", padx=(12, 4), pady=(0, 12))
        yield
        for i, name in enumerate(eng.PRESET_EFFECTS):
            t = PresetTile(pg, name, self._set_effect, height=88)
            t.grid(row=i // 4, column=i % 4, sticky="nsew", padx=3, pady=3)
            pg.grid_columnconfigure(i % 4, weight=1, uniform="p")
            self.tiles[name] = t
            yield                                  # one tile per build step

        yield
        ctl = self.card(right)
        yield
        ctl.pack(fill="x", pady=(14, 0))
        yield
        st = self.settings["state"]
        yield
        r1, self.bright = self.slider_row(ctl, "Brightness", st.get("brightness", 100), lambda v: self._state_changed())
        yield
        r1.pack(fill="x", padx=18, pady=(14, 4))
        yield
        r2, self.speed = self.slider_row(ctl, "Speed", st.get("speed", 50), lambda v: self._state_changed())
        yield
        r2.pack(fill="x", padx=18, pady=4)
        yield
        btns = ctk.CTkFrame(ctl, fg_color="transparent")
        yield
        btns.pack(fill="x", padx=18, pady=(10, 16))
        yield
        self.apply_btn = self.primary(btns, "Apply to all devices", self._apply_all, height=40)
        yield
        self.apply_btn.pack(side="left", fill="x", expand=True)
        yield
        self.secondary(btns, "Save to hardware", lambda: self._bg(self._save_hw), height=40, width=140).pack(side="right", padx=(10, 0))
        yield
        self.secondary(btns, "⏻  Off", lambda: self._set_effect("Off"), height=40, width=80).pack(side="right", padx=(10, 0))

    # ---- device chips: edit all devices at once, or one kind of device
    def _build_chips(self):
        for w in self.chip_row.winfo_children():
            w.destroy()
        self.chips = {}
        counts = {}
        for _, t, _, _ in self.device_rows:
            counts[t] = counts.get(t, 0) + 1
        items = [("All", f"[ All Devices ({len(self.device_rows)}) ]")] + \
                [(t, f"[ {t} ({n}) ]" if n > 1 else f"[ {t} ]") for t, n in counts.items()]
        if self.light_scope not in dict(items):
            self.light_scope = "All"
        for key, text in items:
            b = ctk.CTkButton(self.chip_row, text=text, height=32, width=60, corner_radius=16, font=F(13), border_width=1,
                              command=lambda k=key: self._set_scope(k))
            b.pack(side="left", padx=(0, 8))
            self.chips[key] = b
        self._style_chips()

    def _style_chips(self):
        for k, b in self.chips.items():
            on = k == self.light_scope
            b.configure(fg_color=P["SEL"] if on else "transparent", hover_color=P["HOVER"],
                        border_color=self.accent if on else P["BTN_LINE"], text_color=self.accent if on else P["MUTED"])

    def _scope_keys(self):
        return [r[0] for r in self.device_rows if r[1] == self.light_scope]

    def _set_scope(self, key):
        self.light_scope = key
        self._style_chips()
        if key == "All":
            st = self.settings["state"]
        else:
            ov = self.settings.data.get("device_overrides", {})
            st = next((ov[k] for k in self._scope_keys() if k in ov), None) or self.settings["state"]
        self.color, self.effect = tuple(st["color"]), st["effect"]
        for sl, v in ((self.bright, st["brightness"]), (self.speed, st["speed"])):
            sl.set(v)
            sl.value_label.configure(text=f"{int(v)}%")
        self.apply_btn.configure(text="Apply to all devices" if key == "All" else f"Apply to {key}")
        self._sync_ui_from_state()

    def _rgb_entered(self, _e=None):
        try:
            rgb = tuple(max(0, min(255, int(e.get()))) for e in self.rgb_entries)
        except ValueError:
            return
        if rgb != self.color:
            self._set_color(rgb)

    def _sync_color_fields(self):
        self.hex_entry.delete(0, "end")
        self.hex_entry.insert(0, hexcol(self.color).upper())
        for e, v in zip(self.rgb_entries, self.color):
            e.delete(0, "end")
            e.insert(0, str(int(v)))

    # ---------------------------------------------------------------- Devices
    def _page_devices(self, p):
        h = self.header(p, "Devices", "Every RGB device OpenRGB found. Switch one off to leave it out.")
        yield
        bar = ctk.CTkFrame(p, fg_color="transparent")
        yield
        bar.pack(fill="x", pady=(0, 14))
        yield
        self.primary(bar, "⟳  Rescan", lambda: self._bg(self._full_rescan), height=38, width=120).pack(side="left")
        yield
        self.secondary(bar, "All on", lambda: self._set_all_devices(True), height=38, width=90).pack(side="left", padx=8)
        yield
        self.secondary(bar, "All off", lambda: self._set_all_devices(False), height=38, width=90).pack(side="left")
        yield
        self.dev_summary = self.label(bar, "", 12, color=P["MUTED"])
        yield
        self.dev_summary.pack(side="right")
        yield
        _sc_dev_area = LightScroll(p, bg=P["BG"])
        self.dev_area = _sc_dev_area.inner
        yield
        _sc_dev_area.pack(fill="both", expand=True)
        yield
        self.dev_area.grid_columnconfigure((0, 1), weight=1, uniform="d")
        yield
        self.dev_empty = self.label(self.dev_area, "Scanning for devices…", 14, color=P["MUTED"])
        yield
        self.dev_empty.grid(row=0, column=0, columnspan=2, pady=50)

    def _fill_devices(self, rows):
        self.device_rows = rows
        for c in self.device_cards:
            c.destroy()
        self.device_cards = []
        excluded = set(self.settings["excluded"])
        if rows:
            self.dev_empty.grid_remove()
        else:
            self.dev_empty.configure(text="No RGB devices found yet. Settings → System check shows what's needed.")
            self.dev_empty.grid()
        for i, (key, t, name, leds) in enumerate(rows):
            c = DeviceCard(self.dev_area, key, t, name, leds, key not in excluded, self._toggle_device, self._open_device)
            if key in self.settings.data.get("device_overrides", {}):
                c.edit_btn.configure(text="Custom ✓")
            c.switch.configure(progress_color=self.accent)
            c.grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6)
            self.device_cards.append(c)
        self._update_dev_summary()
        if hasattr(self, "chip_row"):
            self._build_chips()

    # ---------------------------------------------------------------- device editor
    def _state_for(self, key, base):
        return self.settings.data.get("device_overrides", {}).get(key) or base

    def _save_override(self, key, state):
        ov = dict(self.settings.data.get("device_overrides", {}))
        if state is None:
            ov.pop(key, None)
        else:
            ov[key] = state
        self.settings["device_overrides"] = ov
        self.engine.set_overrides(ov)
        if self.connected:
            self.engine.paused = False
        for c in self.device_cards:
            if c.key == key:
                c.edit_btn.configure(text="Custom ✓" if state else "Customize")

    def _close_device(self):
        if self.editor is not None:
            self.editor.destroy()
            self.editor = None

    def _open_device(self, key):
        """Pop up one device: a drawing of it with live LEDs, its exact model details, and its own lighting."""
        self._close_device()
        info = self.engine.device_info(key)
        row = next((r for r in self.device_rows if r[0] == key), None)
        if info is None and row is None:
            return
        info = info or {"name": row[2], "type": row[1], "leds": row[3], "vendor": "", "description": "", "version": "",
                        "serial": "", "location": "", "zones": [], "modes": []}
        self.editor_key = key
        ed = ctk.CTkFrame(self.pages["Devices"], fg_color=P["BG"], corner_radius=0)
        ed.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.editor = ed
        head = ctk.CTkFrame(ed, fg_color="transparent")
        head.pack(fill="x", pady=(4, 14))
        self.secondary(head, "←  Devices", self._close_device, height=32, width=110).pack(side="left")
        tt = ctk.CTkFrame(head, fg_color="transparent")
        tt.pack(side="left", padx=16)
        ctk.CTkLabel(tt, text=info["name"], font=F(22, "bold", display=True), text_color=P["TEXT"], anchor="w").pack(fill="x")
        self.label(tt, f"{info['type']} · {info['leds']} LEDs", 13, color=P["MUTED"], anchor="w").pack(fill="x")

        body = ctk.CTkFrame(ed, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=3, uniform="de")
        body.grid_columnconfigure(1, weight=2, uniform="de")
        body.grid_rowconfigure(0, weight=1)
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))

        art_card = self.card(left)
        art_card.pack(fill="x")
        self.editor_art = DeviceArt(art_card, info["type"], info["leds"])
        self.editor_art.pack(pady=14)

        det = self.card(left)
        det.pack(fill="both", expand=True, pady=(14, 0))
        self.caption(det, "About this device").pack(fill="x", padx=20, pady=(14, 6))
        rows = [("Model", info["name"]), ("Vendor", info["vendor"]), ("Description", info["description"]),
                ("Firmware / version", info["version"]), ("Serial", info["serial"]), ("Connection", info["location"]),
                ("Zones", ", ".join(f"{z} ({n})" for z, n in info["zones"]))]
        # exact hardware details from Windows for this kind of device
        section = {"RAM": "Memory", "GPU": "Graphics", "Motherboard": "Motherboard"}.get(info["type"])
        for sec, items in self.sysinfo:
            if sec == section:
                rows += [(k, v) for k, v in items]
        _sc_box = LightScroll(det, bg=P["CARD"])
        box = _sc_box.inner
        _sc_box.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        for k, v in rows:
            if not str(v).strip():
                continue
            r = ctk.CTkFrame(box, fg_color="transparent")
            r.pack(fill="x", padx=10, pady=2)
            self.label(r, k, 12, color=P["MUTED"], anchor="w", width=130).pack(side="left", anchor="n")
            self.label(r, str(v), 13, anchor="w", justify="left", wraplength=360).pack(side="left", fill="x", expand=True)

        right = self.card(body)
        right.grid(row=0, column=1, sticky="nsew")
        cur = self.settings.data.get("device_overrides", {}).get(key)
        state = dict(cur or self._current_state())
        self.caption(right, "Lighting for this device").pack(fill="x", padx=20, pady=(14, 8))
        mode = PillSwitcher(right, values=["Follow all devices", "Custom"], height=32, font=F(13), corner_radius=6,
                                      fg_color=P["CARD2"], unselected_color=P["CARD2"], unselected_hover_color=P["BTN_HOVER"],
                                      selected_color=self.accent, selected_hover_color=self.accent, text_color=P["TEXT"])
        mode.pack(fill="x", padx=20)
        mode.set("Custom" if cur else "Follow all devices")
        controls = ctk.CTkFrame(right, fg_color="transparent")
        controls.pack(fill="both", expand=True, padx=20, pady=(14, 14))

        def commit():
            self._save_override(key, dict(state) if mode.get() == "Custom" else None)

        def choose(**kw):
            state.update(kw)
            mode.set("Custom")
            swatch.configure(fg_color=hexcol(state["color"]))
            commit()

        self.label(controls, "Effect", 13, color=P["MUTED"], anchor="w").pack(fill="x")
        fxm = ctk.CTkOptionMenu(controls, values=eng.EFFECTS, height=32, corner_radius=6, font=F(13), fg_color=P["CARD2"],
                                button_color=P["CARD2"], button_hover_color=P["BTN_HOVER"], dropdown_fg_color=P["CARD2"],
                                text_color=P["TEXT"], command=lambda v: choose(effect=v))
        fxm.set(state["effect"])
        fxm.pack(fill="x", pady=(4, 12))
        crow = ctk.CTkFrame(controls, fg_color="transparent")
        crow.pack(fill="x")
        self.label(crow, "Color", 13, color=P["MUTED"], anchor="w").pack(side="left")
        swatch = ctk.CTkFrame(crow, width=26, height=26, corner_radius=6, fg_color=hexcol(state["color"]))
        swatch.pack(side="right")
        sw = tk.Canvas(controls, height=30, bg=P["CARD"], highlightthickness=0)
        sw.pack(fill="x", pady=(6, 4))
        for i, c in enumerate(SWATCHES):
            it = sw.create_rectangle(i * 34, 3, i * 34 + 26, 27, fill=hexcol(c), outline=P["CARD"], width=2)
            sw.tag_bind(it, "<Button-1>", lambda e, col=c: (choose(color=list(col)) if state["effect"] in eng.USES_COLOR
                                                            else (fxm.set("Static"), choose(color=list(col), effect="Static"))))
        self.label(controls, "Colors apply to the Static and Breathing effects.", 12, color=P["FAINT"], anchor="w").pack(fill="x", pady=(0, 10))
        r1, _b = self.slider_row(controls, "Brightness", int(state["brightness"]), lambda v: choose(brightness=v))
        r1.pack(fill="x", pady=4)
        r2, _s = self.slider_row(controls, "Speed", int(state["speed"]), lambda v: choose(speed=v))
        r2.pack(fill="x", pady=4)
        mode.configure(command=lambda v: commit())

    def _update_dev_summary(self):
        ex = set(self.settings["excluded"])
        on = sum(1 for r in self.device_rows if r[0] not in ex)
        self.dev_summary.configure(text=f"{on} of {len(self.device_rows)} active · {sum(r[3] for r in self.device_rows)} LEDs")

    # ---------------------------------------------------------------- Fans
    def _page_fans(self, p):
        h = self.header(p, "Fans", "Pick a profile or draw your own curve. Fans always speed up if things get too hot.")
        yield
        self.fan_seg = PillSwitcher(p, values=hwm.PROFILES, command=self._set_fan_profile, height=36,
                                              font=F(12, "bold"), corner_radius=6, fg_color=P["CARD"],
                                              unselected_color=P["CARD"], unselected_hover_color=P["CARD2"],
                                              selected_color=self.accent, selected_hover_color=self.accent,
                                              text_color=P["TEXT"])
        yield
        self.fan_seg.pack(fill="x", pady=(0, 14))
        yield
        self.accent_widgets.append(("seg", self.fan_seg))

        yield
        top = ctk.CTkFrame(p, fg_color="transparent")
        yield
        top.pack(fill="x")
        yield
        top.grid_columnconfigure(0, weight=1)
        yield
        cc = self.card(top)
        yield
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        yield
        row = ctk.CTkFrame(cc, fg_color="transparent")
        yield
        row.pack(fill="x", padx=20, pady=(16, 0))
        yield
        self.caption(row, "Fan curve · CPU temperature").pack(side="left")
        yield
        self.curve_hint = self.label(row, "", 10, color=P["MUTED"])
        yield
        self.curve_hint.pack(side="right")
        yield
        self.curve = CurveEditor(cc, self._curve_changed, height=232)
        yield
        self.curve.pack(fill="x", padx=12, pady=(6, 12))

        yield
        tc = self.card(top, width=270)
        yield
        tc.grid(row=0, column=1, sticky="nsew")
        yield
        self.caption(tc, "Temperatures").pack(fill="x", padx=20, pady=(16, 6))
        yield
        self.fan_temp_labels = {}
        yield
        for key, name in (("cpu_temp", "CPU"), ("gpu_temp", "GPU")):
            r = ctk.CTkFrame(tc, fg_color="transparent")
            r.pack(fill="x", padx=20, pady=6)
            self.label(r, name, 12, "bold", color=P["MUTED"]).pack(side="left")
            v = self.label(r, "—", 30, "bold")
            v.pack(side="right")
            self.fan_temp_labels[key] = v
        yield
        self.fan_note = self.label(tc, "", 11, color=P["MUTED"], wraplength=230, justify="left", anchor="w")
        yield
        self.fan_note.pack(fill="x", padx=20, pady=(10, 16))

        yield
        _sc_fan_area = LightScroll(p, bg=P["BG"])
        self.fan_area = _sc_fan_area.inner
        yield
        _sc_fan_area.pack(fill="both", expand=True, pady=(14, 0))
        yield
        self.fan_area.grid_columnconfigure((0, 1, 2), weight=1, uniform="f")
        yield
        self.fan_empty = ctk.CTkFrame(self.fan_area, fg_color="transparent")
        yield
        self.fan_empty.grid(row=0, column=0, columnspan=3, pady=30)
        yield
        self.fan_empty_lbl = self.label(self.fan_empty, "Loading fan controllers…", 13, color=P["MUTED"], wraplength=640)
        yield
        self.fan_empty_lbl.pack()

    def _set_fan_profile(self, name):
        self.monitor.set_profile(name)
        for c in self.fan_cards.values():
            c.touched = 0

    def _curve_changed(self, pts):
        self.monitor.set_curve(pts)
        if self.fan_seg.get() != "Custom":
            self.fan_seg.set("Custom")
            self.monitor.set_profile("Custom")

    def _fan_manual(self, fid, pct):
        self.monitor.set_manual(fid, pct)

    def _fan_reset(self, fid):
        self.monitor.set_manual(fid, None)
        if fid in self.fan_cards:
            self.fan_cards[fid].touched = 0

    def _refresh_fans(self, s):
        m = s["metrics"]
        for k, lbl in self.fan_temp_labels.items():
            lbl.configure(text=fmt(m.get(k), "°"), text_color=temp_color(m.get(k)))
        if self.fan_seg.get() != s["profile"]:
            self.fan_seg.set(s["profile"])
        prof = s["profile"]
        curve = s["curve"] if prof == "Custom" else hwm.PRESETS.get(prof, s["curve"])
        self.curve.set(curve, editable=prof not in ("Auto",), temp=m.get("cpu_temp"), accent=self.accent)
        self.curve_hint.configure(text={"Auto": "BIOS is in control - drag a point to take over",
                                        "Custom": "Drag the points to shape your curve"}.get(prof, "Drag a point to customise"))
        if m.get("fan_emergency"):
            self.fan_note.configure(text=f"⚠ Above {hwm.EMERGENCY_TEMP}°C - all fans forced to 100%.", text_color=BAD)
        else:
            self.fan_note.configure(text=f"Fans never go below {hwm.FAN_FLOOR}%, and jump to 100% if the CPU or GPU "
                                         f"reaches {hwm.EMERGENCY_TEMP}°C. Closing the app hands control back to the BIOS.",
                                    text_color=P["MUTED"])
        fans = s["fans"]
        if not fans:
            if s["status"] == "starting":
                msg = "Loading fan controllers…"
            elif s["status"] == "ok":
                msg = ("No controllable fans were reported. Your motherboard's fan chip may not be supported yet, "
                       "or fans are set to a fixed mode in the BIOS.")
            else:
                msg = ("Fan control needs the PawnIO driver and administrator rights.\n" + s["msg"])
            self.fan_empty_lbl.configure(text=msg)
            self.fan_empty.grid()
            return
        self.fan_empty.grid_remove()
        if set(fans) != set(self.fan_cards):
            for c in self.fan_cards.values():
                c.destroy()
            self.fan_cards = {}
            for i, (fid, f) in enumerate(sorted(fans.items(), key=lambda kv: (kv[1]["src"], kv[1]["name"]))):
                c = FanCard(self.fan_area, f, self._fan_manual, self._fan_reset)
                c.grid(row=i // 3, column=i % 3, sticky="ew", padx=6, pady=6)
                self.fan_cards[fid] = c
        for fid, f in fans.items():
            self.fan_cards[fid].update_fan(f, self.accent, prof == "Auto")

    # ---------------------------------------------------------------- Monitor
    def _page_monitor(self, p):
        h = self.header(p, "Monitor", "Live view of your system. Advanced shows every sensor and full hardware details.")
        yield
        self.mon_seg = PillSwitcher(h, values=["Overview", "Advanced"], command=self._mon_tab, height=34,
                                              width=220, font=F(12, "bold"), corner_radius=6, fg_color=P["CARD"],
                                              unselected_color=P["CARD"], unselected_hover_color=P["CARD2"],
                                              selected_color=self.accent, selected_hover_color=self.accent,
                                              text_color=P["TEXT"])
        yield
        self.mon_seg.pack(side="right")
        yield
        self.mon_seg.set("Overview")
        yield
        self.accent_widgets.append(("seg", self.mon_seg))
        yield
        stack = ctk.CTkFrame(p, fg_color="transparent")
        yield
        stack.pack(fill="both", expand=True)
        yield
        stack.grid_rowconfigure(0, weight=1)
        yield
        stack.grid_columnconfigure(0, weight=1)
        yield
        self.mon_over = ctk.CTkFrame(stack, fg_color="transparent")
        yield
        self.mon_adv = ctk.CTkFrame(stack, fg_color="transparent")
        yield
        for f in (self.mon_over, self.mon_adv):
            f.grid(row=0, column=0, sticky="nsew")
        yield
        yield from self._build_overview(self.mon_over)
        yield
        yield from self._build_advanced(self.mon_adv)
        yield
        self.mon_over.tkraise()

    def _mon_tab(self, name):
        (self.mon_over if name == "Overview" else self.mon_adv).tkraise()

    def _gauge_card(self, parent, title):
        c = self.card(parent)
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 4))
        self.caption(top, title).pack(side="left")
        name = self.label(top, "", 10, color=P["MUTED"])
        name.pack(side="right")
        mid = ctk.CTkFrame(c, fg_color="transparent")
        mid.pack(fill="x", padx=14)
        ring = Ring(mid, size=108)
        ring.pack(side="left")
        stats = ctk.CTkFrame(mid, fg_color="transparent")
        stats.pack(side="left", fill="both", expand=True, padx=(14, 4))
        rows = {}
        for k in ("a", "b", "c"):
            r = ctk.CTkFrame(stats, fg_color="transparent")
            r.pack(fill="x", pady=3)
            l = self.label(r, "", 11, color=P["MUTED"])
            l.pack(side="left")
            v = self.label(r, "—", 14, "bold")
            v.pack(side="right")
            rows[k] = (l, v)
        spark = Sparkline(c, height=48)
        spark.pack(fill="x", padx=14, pady=(8, 14))
        return {"card": c, "ring": ring, "rows": rows, "spark": spark, "name": name}

    def _build_overview(self, p):
        g = ctk.CTkFrame(p, fg_color="transparent")
        yield
        g.pack(fill="both", expand=True)
        yield
        for i in range(3):
            g.grid_columnconfigure(i, weight=1, uniform="o")
        yield
        self.g_cpu = self._gauge_card(g, "Processor")
        yield
        self.g_gpu = self._gauge_card(g, "Graphics")
        yield
        self.g_ram = self._gauge_card(g, "Memory")
        yield
        for i, gc in enumerate((self.g_cpu, self.g_gpu, self.g_ram)):
            gc["card"].grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == 2 else 8))

        yield
        net = self.card(g)
        yield
        net.grid(row=1, column=0, sticky="nsew", pady=(16, 0), padx=(0, 8))
        yield
        self.caption(net, "Network").pack(fill="x", padx=18, pady=(16, 4))
        yield
        nr = ctk.CTkFrame(net, fg_color="transparent")
        yield
        nr.pack(fill="x", padx=18)
        yield
        self.net_down = self.label(nr, "—", 20, color=CYAN)
        yield
        self.net_down.pack(side="left")
        yield
        self.net_up = self.label(nr, "—", 20, color=PURPLE)
        yield
        self.net_up.pack(side="right")
        yield
        self.net_spark = Sparkline(net, height=150, color=CYAN)
        yield
        self.net_spark.pack(fill="both", expand=True, padx=12, pady=(8, 14))

        yield
        dk = self.card(g)
        yield
        dk.grid(row=1, column=1, sticky="nsew", pady=(16, 0), padx=8)
        yield
        top = ctk.CTkFrame(dk, fg_color="transparent")
        yield
        top.pack(fill="x", padx=18, pady=(16, 4))
        yield
        self.caption(top, "Storage").pack(side="left")
        yield
        self.disk_box = ctk.CTkFrame(dk, fg_color="transparent")
        yield
        self.disk_box.pack(fill="x", padx=18, pady=(4, 4))
        yield
        self.disk_rows = {}
        yield
        self.disk_chart = Sparkline(dk, height=80, color=CYAN)
        yield
        self.disk_chart.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        yield
        io = ctk.CTkFrame(dk, fg_color="transparent")
        yield
        io.pack(pady=(2, 12))
        yield
        self.disk_r = self.label(io, "R —", 13, color=CYAN)
        yield
        self.disk_r.pack(side="left")
        yield
        self.label(io, "  ·  ", 13, color=P["FAINT"]).pack(side="left")
        yield
        self.disk_w = self.label(io, "W —", 13, color=PURPLE)
        yield
        self.disk_w.pack(side="left")

        yield
        sy = self.card(g)
        yield
        sy.grid(row=1, column=2, sticky="nsew", pady=(16, 0), padx=(8, 0))
        yield
        self.caption(sy, "System").pack(fill="x", padx=18, pady=(16, 4))
        yield
        self.sys_rows = {}
        yield
        for k, lab in (("uptime", "Uptime"), ("procs", "Processes"), ("cpu_power", "CPU power"),
                       ("gpu_power", "GPU power"), ("fans", "Fans"), ("os", "OS")):
            r = ctk.CTkFrame(sy, fg_color="transparent")
            r.pack(fill="x", padx=18, pady=4)
            self.label(r, lab, 11, color=P["MUTED"]).pack(side="left")
            if k == "fans":
                v = ctk.CTkLabel(r, text="—", font=F(13), text_color=CYAN, fg_color=P["SEL"], corner_radius=8, height=26)
            else:
                v = self.label(r, "—", 13)
            v.pack(side="right")
            self.sys_rows[k] = v
        yield
        g.grid_rowconfigure(1, weight=1)

    def _build_advanced(self, p):
        p.grid_columnconfigure(0, weight=2, uniform="a")
        yield
        p.grid_columnconfigure(1, weight=3, uniform="a")
        yield
        p.grid_rowconfigure(0, weight=1)
        yield
        left = self.card(p)
        yield
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        yield
        top = ctk.CTkFrame(left, fg_color="transparent")
        yield
        top.pack(fill="x", padx=18, pady=(16, 6))
        yield
        self.caption(top, "System details").pack(side="left")
        yield
        self.secondary(top, "Copy", self._copy_sysinfo, height=26, width=64, corner_radius=6).pack(side="right")
        yield
        _sc_info_box = LightScroll(left, bg=P["CARD"])
        self.info_box = _sc_info_box.inner
        yield
        _sc_info_box.pack(fill="both", expand=True, padx=6, pady=(0, 10))
        yield
        self.label(self.info_box, "Gathering hardware details…", 12, color=P["MUTED"]).pack(pady=20)
        yield
        self.sysinfo_text = ""

        yield
        right = self.card(p)
        yield
        right.grid(row=0, column=1, sticky="nsew")
        yield
        top = ctk.CTkFrame(right, fg_color="transparent")
        yield
        top.pack(fill="x", padx=18, pady=(14, 8))
        yield
        self.caption(top, "All sensors").pack(side="left")
        yield
        self.sensor_count = self.label(top, "", 10, color=P["MUTED"])
        yield
        self.sensor_count.pack(side="left", padx=10)
        yield
        self.sensor_filter = ctk.CTkOptionMenu(top, values=["All types", "Temperature", "Load", "Clock", "Power", "Fan",
                                                            "Control", "Voltage", "Data", "SmallData", "Throughput"],
                                               width=130, height=28, corner_radius=6, fg_color=P["CARD2"],
                                               button_color=P["CARD2"], button_hover_color=P["LINE"],
                                               dropdown_fg_color=P["CARD2"], text_color=P["TEXT"], font=F(11),
                                               command=lambda _v: self._rebuild_sensors())
        yield
        self.sensor_filter.pack(side="right")
        yield
        self.sensor_search = ctk.CTkEntry(top, placeholder_text="Search sensors…", width=180, height=28,
                                          corner_radius=6, fg_color=P["CARD2"], border_width=0, text_color=P["TEXT"], font=F(11))
        yield
        self.sensor_search.pack(side="right", padx=8)
        yield
        self.sensor_search.bind("<KeyRelease>", lambda e: self._rebuild_sensors())
        yield
        wrap = ctk.CTkFrame(right, fg_color=P["CARD"])
        yield
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        yield
        cols = ("value", "min", "max")
        yield
        self.tree = ttk.Treeview(wrap, columns=cols, style="Dark.Treeview", show="tree headings")
        yield
        self.tree.heading("#0", text="Sensor", anchor="w")
        yield
        self.tree.column("#0", width=260, stretch=True)
        yield
        for c, t in zip(cols, ("Value", "Min", "Max")):
            self.tree.heading(c, text=t, anchor="e")
            self.tree.column(c, width=90, anchor="e", stretch=False)
        yield
        self.tree.tag_configure("group", foreground=P["MUTED"], font=(FONT, 10, "bold"))
        yield
        self.tree.tag_configure("hw", foreground=P["TEXT"], font=(FONT, 11, "bold"))
        yield
        sb = ctk.CTkScrollbar(wrap, command=self.tree.yview, button_color=P["CARD2"], button_hover_color=P["LINE"])
        yield
        self.tree.configure(yscrollcommand=sb.set)
        yield
        self.tree.pack(side="left", fill="both", expand=True)
        yield
        sb.pack(side="right", fill="y")
        yield
        self.sensor_sig = None

    UNITS = {"Temperature": "°C", "Load": "%", "Clock": " MHz", "Power": " W", "Fan": " RPM", "Control": "%",
             "Voltage": " V", "Current": " A", "Data": " GB", "SmallData": " MB", "Throughput": " MB/s",
             "Level": "%", "Frequency": " Hz", "Flow": " L/h", "Energy": " mWh", "Factor": ""}

    def _sval(self, s, key):
        v = s[key]
        if v is None:
            return "—"
        if s["type"] == "Throughput":
            v = v / 2**20
        nd = 3 if s["type"] == "Voltage" else 0 if s["type"] in ("Clock", "Fan", "SmallData") else 1
        return f"{v:,.{nd}f}{self.UNITS.get(s['type'], '')}"

    def _filtered_sensors(self, sensors):
        q = self.sensor_search.get().strip().lower()
        flt = self.sensor_filter.get()
        out = []
        for s in sensors:
            if flt != "All types" and s["type"] != flt:
                continue
            if q and q not in f"{s['hw']} {s['sub']} {s['name']} {s['type']}".lower():
                continue
            out.append(s)
        return out

    def _rebuild_sensors(self):
        self.sensor_sig = None
        self._refresh_sensors(self.snap)

    def _refresh_sensors(self, s):
        sensors = self._filtered_sensors(s["sensors"])
        sig = tuple(x["id"] for x in sensors)
        if sig != self.sensor_sig:
            self.sensor_sig = sig
            self.tree.delete(*self.tree.get_children())
            self.sensor_items = {}
            groups = {}
            for x in sensors:
                hw_key = x["hw"]
                if hw_key not in groups:
                    groups[hw_key] = self.tree.insert("", "end", text=f"  {x['hw']}", open=True, tags=("hw",))
                gk = (hw_key, x["type"])
                if gk not in groups:
                    groups[gk] = self.tree.insert(groups[hw_key], "end", text=x["type"].upper(), open=True, tags=("group",))
                name = f"{x['sub']} · {x['name']}" if x["sub"] else x["name"]
                self.sensor_items[x["id"]] = self.tree.insert(groups[gk], "end", text=name)
            if not s["sensors"]:
                msg = s["msg"] if s["status"] != "starting" else "Loading sensors…"
                self.tree.insert("", "end", text=f"  {msg}")
        for x in sensors:
            iid = self.sensor_items.get(x["id"])
            if iid:
                self.tree.item(iid, values=(self._sval(x, "value"), self._sval(x, "min"), self._sval(x, "max")))
        self.sensor_count.configure(text=f"{len(s['sensors'])} sensors" if s["sensors"] else "")

    def _load_sysinfo(self):
        info = hwm.system_info()
        self.q.put(("call", lambda: self._show_sysinfo(info)))

    def _show_sysinfo(self, info):
        self.sysinfo = info
        for w in self.info_box.winfo_children():
            w.destroy()
        lines = []
        for section, rows in info:
            self.label(self.info_box, section.upper(), 10, "bold", color=self.accent, anchor="w").pack(fill="x", padx=12, pady=(12, 2))
            lines.append(f"[{section}]")
            for k, v in rows:
                r = ctk.CTkFrame(self.info_box, fg_color="transparent")
                r.pack(fill="x", padx=12, pady=1)
                self.label(r, k, 11, color=P["MUTED"], anchor="w", width=110).pack(side="left", anchor="n")
                self.label(r, str(v), 11, anchor="w", justify="left", wraplength=240).pack(side="left", fill="x", expand=True)
                lines.append(f"  {k}: {v}")
        self.sysinfo_text = "\n".join(lines)
        osrow = next((rows for sec, rows in info if sec == "Operating system"), [])
        if osrow:
            self.sys_rows["os"].configure(text=str(osrow[0][1])[:28])

    def _copy_sysinfo(self):
        self.clipboard_clear()
        self.clipboard_append(self.sysinfo_text)
        self.log("System details copied to clipboard.", "ok")

    def _refresh_monitor(self, s):
        m, hist = s["metrics"], s["hist"]
        acc = self.accent
        # CPU
        g = self.g_cpu
        g["ring"].set(m.get("cpu_load"), fmt(m.get("cpu_load"), "%"), "load", (TEAL, CYAN))
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Temperature"); v1.configure(text=fmt(m.get("cpu_temp"), "°C"), text_color=temp_color(m.get("cpu_temp")))
        l2.configure(text="Clock"); v2.configure(text=fmt((m.get("cpu_clock") or 0) / 1000 if m.get("cpu_clock") else None, " GHz", 2))
        l3.configure(text="Power"); v3.configure(text=fmt(m.get("cpu_power"), " W"))
        g["spark"].set(hist.get("cpu_load", []), 100, TEAL)
        # GPU
        g = self.g_gpu
        g["name"].configure(text=(m.get("gpu_name") or "")[:26])
        g["ring"].set(m.get("gpu_load"), fmt(m.get("gpu_load"), "%"), "load", (CYAN, BLUE))
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Temperature"); v1.configure(text=fmt(m.get("gpu_temp"), "°C"), text_color=temp_color(m.get("gpu_temp")))
        l2.configure(text="Clock"); v2.configure(text=fmt(m.get("gpu_clock"), " MHz"))
        vu, vt = m.get("vram_used"), m.get("vram_total")
        l3.configure(text="VRAM"); v3.configure(text=f"{vu/1024:.1f} / {vt/1024:.0f} GB" if vu and vt else fmt(vu, " MB"))
        g["spark"].set(hist.get("gpu_load", []) or [0, 0], 100, CYAN)
        # RAM
        g = self.g_ram
        g["ring"].set(m.get("ram_pct"), fmt(m.get("ram_pct"), "%"), "used", ("#60a5fa", BLUE))
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Used"); v1.configure(text=fmt(m.get("ram_used"), " GB", 1))
        l2.configure(text="Total"); v2.configure(text=fmt(m.get("ram_total"), " GB", 1))
        l3.configure(text="Free"); v3.configure(text=fmt((m.get("ram_total") or 0) - (m.get("ram_used") or 0), " GB", 1) if m.get("ram_total") else "—")
        g["spark"].set(hist.get("ram_pct", []), 100, BLUE)
        # network
        def rate(v):
            return "—" if v is None else (f"{v:.1f} Mb/s" if v < 1000 else f"{v/1000:.2f} Gb/s")
        self.net_down.configure(text=rate(m.get("net_down")) + " ↓")
        self.net_up.configure(text=rate(m.get("net_up")) + " ↑")
        self.net_spark.set_multi([(hist.get("net_down", []), CYAN), (hist.get("net_up", []), PURPLE)])
        # disks
        self.disk_r.configure(text=f"R {fmt(m.get('disk_read'), ' MB/s', 1)}")
        self.disk_w.configure(text=f"W {fmt(m.get('disk_write'), ' MB/s', 1)}")
        self.disk_chart.set_multi([(hist.get("disk_read", []), CYAN), (hist.get("disk_write", []), PURPLE)])
        for mount, used, total, pct in m.get("disks", []):
            if mount not in self.disk_rows:
                r = ctk.CTkFrame(self.disk_box, fg_color="transparent")
                r.pack(fill="x", pady=5)
                top = ctk.CTkFrame(r, fg_color="transparent")
                top.pack(fill="x")
                self.label(top, mount, 12, "bold").pack(side="left")
                v = self.label(top, "", 11, color=P["MUTED"])
                v.pack(side="right")
                bar = GradientBar(r, height=6)
                bar.pack(fill="x", pady=(5, 0))
                self.disk_rows[mount] = (v, bar)
            v, bar = self.disk_rows[mount]
            v.configure(text=f"{used:,.0f} / {total:,.0f} GB")
            bar.set(pct / 100, *((BAD, BAD) if pct > 90 else (CYAN, PURPLE)))
        # system
        up = int(m.get("uptime") or 0)
        self.sys_rows["uptime"].configure(text=f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m")
        self.sys_rows["procs"].configure(text=str(m.get("procs", "—")))
        self.sys_rows["cpu_power"].configure(text=fmt(m.get("cpu_power"), " W"))
        self.sys_rows["gpu_power"].configure(text=fmt(m.get("gpu_power"), " W"))
        fans = s["fans"]
        self.sys_rows["fans"].configure(text=f"  {len(fans)} • {s['profile']}  " if fans else "—")

    def _refresh_hw(self):
        try:
            s = self.monitor.snapshot()
            self.snap = s
            dot, oval, sub = self.status_rows["hw"]
            dot.itemconfigure(oval, fill={"ok": OK, "basic": WARN}.get(s["status"], WARN))
            sub.configure(text={"ok": f"{len(s['sensors'])} sensors · {len(s['fans'])} fans",
                                "basic": "Basic stats only", "starting": "Loading…"}.get(s["status"], ""))
            if self._hidden():
                pass                              # in the tray: keep the data, skip drawing
            elif self.current_page == "Home":
                self._refresh_home(s)
            elif self.current_page == "Monitor":
                self._refresh_monitor(s)
                if self.mon_seg.get() == "Advanced":
                    self._refresh_sensors(s)
            elif self.current_page == "Fans":
                self._refresh_fans(s)
        except tk.TclError:
            pass
        except Exception:
            traceback.print_exc()
        self.after(1000, self._refresh_hw)

    # ---------------------------------------------------------------- Overlay (in-game FPS counter)
    def _overlay_colors(self):
        return dict(bg=P["BG"], line=P["LINE"], text=P["TEXT"], muted=P["MUTED"], grad=GRAD, ok=OK, warn=WARN, bad=BAD)

    def _page_overlay(self, p):
        self.header(p, "Overlay", "A small FPS and temperature readout that sits on top of your games.")
        yield
        body = ctk.CTkFrame(p, fg_color="transparent")
        yield
        body.pack(fill="both", expand=True)
        yield
        body.grid_columnconfigure(0, weight=3, uniform="ov")
        yield
        body.grid_columnconfigure(1, weight=2, uniform="ov")
        yield
        body.grid_rowconfigure(0, weight=1)
        yield
        cfg = self.overlay_cfg

        yield
        left = self.card(body)
        yield
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        yield
        self.caption(left, "FPS overlay").pack(fill="x", padx=20, pady=(18, 6))
        yield
        self.overlay_sw = Switch(left, text="Show the overlay in games", font=F(13, "bold"), text_color=P["TEXT"],
                                 command=self._overlay_toggle)
        yield
        self.overlay_sw.pack(anchor="w", padx=20, pady=4)
        yield
        if cfg["enabled"]:
            self.overlay_sw.select()
        yield
        self.overlay_status = self.label(left, "Off", 11, color=P["MUTED"], anchor="w", justify="left", wraplength=560)
        yield
        self.overlay_status.pack(fill="x", padx=20, pady=(2, 10))

        yield
        def seg(parent, values, current, cmd):
            sb = PillSwitcher(parent, values=values, command=cmd, height=34, font=F(12, "bold"),
                                        corner_radius=RADIUS, fg_color=P["CARD2"], unselected_color=P["CARD2"],
                                        unselected_hover_color=P["LINE"], selected_color=self.accent,
                                        selected_hover_color=self.accent, text_color=P["TEXT"])
            sb.set(current)
            self.accent_widgets.append(("seg", sb))
            return sb

        yield
        self.caption(left, "Position").pack(fill="x", padx=20, pady=(10, 6))
        yield
        seg(left, fpo.CORNERS, cfg["corner"], lambda v: self._overlay_set("corner", v)).pack(fill="x", padx=20)
        yield
        self.caption(left, "Size").pack(fill="x", padx=20, pady=(16, 6))
        yield
        seg(left, list(fpo.SIZES), cfg["size"], lambda v: self._overlay_set("size", v)).pack(fill="x", padx=20)
        yield
        self.caption(left, "Show").pack(fill="x", padx=20, pady=(16, 6))
        yield
        self.overlay_item_sw = {}
        yield
        for key, label in fpo.ITEMS:
            sw = Switch(left, text=label, font=F(12), text_color=P["TEXT"], command=lambda k=key: self._overlay_item(k))
            sw.pack(anchor="w", padx=20, pady=4)
            if cfg["items"].get(key):
                sw.select()
            self.overlay_item_sw[key] = sw

        yield
        right = self.card(body)
        yield
        right.grid(row=0, column=1, sticky="nsew")
        yield
        self.caption(right, "Preview").pack(fill="x", padx=20, pady=(18, 10))
        yield
        stage = tk.Frame(right, bg=P["SIDE"], highlightthickness=1, highlightbackground=P["LINE"])
        yield
        stage.pack(fill="x", padx=20)
        yield
        self.overlay_preview = fpo.OverlayPanel(stage, self._overlay_colors(), FONT, outer=P["SIDE"])
        yield
        self.overlay_preview.pack(padx=24, pady=24, anchor="w")
        yield
        self.overlay_preview_note = self.label(right, "", 11, color=P["MUTED"], anchor="w", justify="left", wraplength=360)
        yield
        self.overlay_preview_note.pack(fill="x", padx=20, pady=(10, 4))
        yield
        self.label(right, "How it works\n"
                          "• FPS is measured with Intel PresentMon, which reads Windows' own graphics events. "
                          "Nothing is injected into the game.\n"
                          "• It sticks to the game you're playing, even when you tab out, and hides when the game is minimised or closed.\n"
                          "• It shows over windowed and borderless-fullscreen games. Games in exclusive "
                          "fullscreen can cover it, so switch them to borderless.\n"
                          "• Clicks pass straight through it.",
                   11, color=P["MUTED"], anchor="w", justify="left", wraplength=360).pack(fill="x", padx=20, pady=(8, 18))

    def _overlay_save(self):
        self.settings["overlay"] = self.overlay_cfg

    def _overlay_set(self, key, value):
        self.overlay_cfg[key] = value
        self._overlay_save()

    def _overlay_item(self, key):
        self.overlay_cfg["items"][key] = self.overlay_item_sw[key].get() == 1
        self._overlay_save()

    def _overlay_toggle(self):
        on = self.overlay_sw.get() == 1
        if hasattr(self, "home_overlay_sw"):
            self.home_overlay_sw.select() if on else self.home_overlay_sw.deselect()
        self.overlay_cfg["enabled"] = on
        self._overlay_save()
        if on:
            self.fps.start()
        else:
            self._bg(self.fps.stop)
            if self.overlay_win is not None:
                self.overlay_win.destroy()
                self.overlay_win = None

    def _overlay_tick(self):
        """Follow the game: pick the app you're playing, then keep the overlay on it even after you tab out."""
        try:
            cfg, metrics = self.overlay_cfg, self.snap.get("metrics", {})
            running = cfg["enabled"] and self.fps.status == "running"
            fps, stale = None, False
            if running:
                fg_hwnd, fg_pid = fpo.foreground_window()
                if fg_pid and fg_pid != getattr(self, "_game_pid", None) and self.fps.current(fg_pid):
                    self._game_pid, self._game_hwnd, self._game_last = fg_pid, fg_hwnd, None   # a new game is in front
                pid = getattr(self, "_game_pid", None)
                if pid and (not self.fps.alive(pid) or fpo.game_window_state(self._game_hwnd) is None and eng.IS_WIN):
                    self._game_pid = pid = None                                              # game closed
                if pid:
                    fps = self.fps.current(pid)
                    if fps:
                        self._game_last = fps
                    else:                         # backgrounded games often pause drawing: keep the last number, dimmed
                        fps, stale = self._game_last, True
            if cfg["enabled"] and running and getattr(self, "_game_pid", None):
                if self.overlay_win is None:
                    self.overlay_win = fpo.OverlayWindow(self, self._overlay_colors(), FONT)
                in_front = fpo.foreground_window()[1] == self._game_pid
                self.overlay_win.update_overlay(cfg, fps, metrics, self._game_hwnd, in_front, stale)
            elif self.overlay_win is not None:
                self.overlay_win.hide()
            if self.current_page == "Overlay":
                sample = fps or {"name": "", "fps": 144, "low": 112, "ms": 6.9}
                self.overlay_preview.render(cfg, sample, metrics)
                self.overlay_preview_note.configure(
                    text=f"Live: {fps['name']}" if fps else "Sample numbers. Live numbers show here while a game is running.")
                st = self.fps.status
                self.overlay_status.configure(
                    text={"off": "Off", "starting": "Starting the FPS counter (first time downloads PresentMon)…",
                          "running": (f"Tracking {fps['name']}: {fps['fps']:.0f} FPS" if fps else
                                      "Running. Open a game and it will appear on it."),
                          "error": self.fps.message}.get(st, ""),
                    text_color=BAD if st == "error" else OK if st == "running" else P["MUTED"])
        except tk.TclError:
            pass
        except Exception:
            traceback.print_exc()
        self.after(250, self._overlay_tick)

    # ---------------------------------------------------------------- Profiles
    def _page_profiles(self, p):
        self.header(p, "Profiles", "Save looks you like and switch between them in one click.")
        yield
        save = self.card(p)
        yield
        save.pack(fill="x", pady=(0, 14))
        yield
        row = ctk.CTkFrame(save, fg_color="transparent")
        yield
        row.pack(fill="x", padx=16, pady=14)
        yield
        self.profile_name = ctk.CTkEntry(row, placeholder_text="Name this look…", height=40, corner_radius=6,
                                         font=F(13), fg_color=P["CARD2"], border_width=0, text_color=P["TEXT"])
        yield
        self.profile_name.pack(side="left", fill="x", expand=True)
        yield
        self.profile_name.bind("<Return>", lambda e: self._save_profile())
        yield
        self.primary(row, "Save current", self._save_profile, height=40, width=140).pack(side="left", padx=(10, 0))
        yield
        _sc_prof_area = LightScroll(p, bg=P["BG"])
        self.prof_area = _sc_prof_area.inner
        yield
        _sc_prof_area.pack(fill="both", expand=True)
        yield
        self.prof_area.grid_columnconfigure((0, 1, 2), weight=1, uniform="p")
        yield
        self._refresh_profiles()

    def _refresh_profiles(self):
        for w in self.prof_area.winfo_children():
            w.destroy()
        for i, (name, st) in enumerate(sorted(self.settings["profiles"].items())):
            c = self.card(self.prof_area)
            c.grid(row=i // 3, column=i % 3, sticky="ew", padx=6, pady=6)
            strip = GlowBar(c, height=24, thickness=7)
            strip.pack(fill="x", padx=12, pady=(14, 4))
            cols = eng.compute_colors("Rainbow Wave" if st["effect"] == "Color Cycle" else st["effect"],
                                      st["color"], max(st["brightness"], 40), 50, 16, 0)
            strip.after(60, lambda s=strip, c2=cols: s.show(c2))
            self.label(c, name, 15, "bold", anchor="w").pack(fill="x", padx=18)
            self.label(c, f"{st['effect']} · {hexcol(st['color']).upper()} · {st['brightness']}%", 11,
                       color=P["MUTED"], anchor="w").pack(fill="x", padx=18)
            r = ctk.CTkFrame(c, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=(10, 14))
            self.secondary(r, "Load", lambda n=name: self._load_profile(n), height=32).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(r, text="✕", width=34, height=32, corner_radius=16, fg_color=P["BTN"], hover_color="#4a1f28",
                          text_color=P["MUTED"], command=lambda n=name: self._delete_profile(n)).pack(side="left", padx=(6, 0))

    # ---------------------------------------------------------------- Settings
    def _page_settings(self, p):
        self.header(p, "Settings", "")
        yield
        _sc_body = LightScroll(p, bg=P["BG"])
        body = _sc_body.inner
        yield
        _sc_body.pack(fill="both", expand=True)

        yield
        hr = ctk.CTkFrame(body, fg_color="transparent")
        yield
        hr.pack(fill="x", pady=(0, 8))
        yield
        self.caption(hr, "System check").pack(side="left")
        yield
        self.secondary(hr, "Run again", lambda: self._bg(self._run_check), height=30, width=100).pack(side="right")
        yield
        self.check_list = ctk.CTkFrame(body, fg_color="transparent")
        yield
        self.check_list.pack(fill="x")

        yield
        def switch(attr, on, cmd):
            def make(row):
                sw = Switch(row, text="", width=46, command=cmd)
                if on:
                    sw.select()
                setattr(self, attr, sw)
                return sw
            return make

        yield
        self.caption(body, "Appearance").pack(fill="x", pady=(22, 8))

        yield
        def theme(row):
            names = [t["name"] for t in THEMES.values()]
            self.theme_menu = ctk.CTkOptionMenu(row, values=names, width=230, height=32, corner_radius=6, font=F(13),
                                                dropdown_font=F(13), fg_color=P["CARD2"], button_color=P["CARD2"],
                                                button_hover_color=P["BTN_HOVER"], dropdown_fg_color=P["CARD2"],
                                                dropdown_hover_color=P["BTN_HOVER"], dropdown_text_color=P["TEXT"],
                                                text_color=P["TEXT"], dynamic_resizing=False, command=self._set_theme)
            saved = self.settings.data.get("theme")
            self.theme_menu.set(THEMES[saved if saved in THEMES else THEME]["name"])
            return self.theme_menu
        yield
        self.setting_row(body, "\ue771", "◑", "Theme", "The look of the whole app. Changing it restarts Central RGB", theme)
        yield
        def accent(row):
            self.accent_seg = PillSwitcher(row, values=["Theme", "Windows", "Match lighting"], command=self._set_accent_mode,
                                                     height=32, font=F(13), corner_radius=6, fg_color=P["CARD2"],
                                                     unselected_color=P["CARD2"], unselected_hover_color=P["BTN_HOVER"],
                                                     selected_color=self.accent, selected_hover_color=self.accent,
                                                     text_color=P["TEXT"])
            self.accent_seg.set({"match": "Match lighting", "windows": "Windows"}.get(self.settings.data.get("accent_mode"), "Theme"))
            self.accent_widgets.append(("seg", self.accent_seg))
            return self.accent_seg
        yield
        self.setting_row(body, "\ue790", "◐", "Accent color", "The theme's accent, your Windows accent color, or follow your lighting color", accent)
        yield
        def closing(row):
            self.close_seg = PillSwitcher(row, values=["Keep running in tray", "Quit"], command=self._set_close_mode,
                                          height=32, font=F(13), corner_radius=6, fg_color=P["CARD2"],
                                          unselected_color=P["CARD2"], unselected_hover_color=P["BTN_HOVER"],
                                          selected_color=self.accent, selected_hover_color=self.accent,
                                          text_color=P["TEXT"])
            self.close_seg.set("Keep running in tray" if self.settings.data.get("close_to_tray", True) else "Quit")
            self.accent_widgets.append(("seg", self.close_seg))
            return self.close_seg
        self.setting_row(body, "\ue8bb", "✕", "Close button", "What the X does: hide to the system tray, or quit", closing)
        yield
        self.setting_row(body, "\ue768", "▶", "Startup animation", "Show the logo animation when the app opens",
                         switch("anim_sw", self.settings.data.get("animations", True),
                                lambda: self.settings.__setitem__("animations", self.anim_sw.get() == 1)))

        yield
        self.caption(body, "Sensors").pack(fill="x", pady=(22, 8))
        yield
        self.setting_row(body, "\ue9d9", "◔", "Read RAM temperatures",
                         "Off by default: reading them can make RGB RAM flicker", 
                         switch("ramtemp_sw", self.settings.data.get("ram_temps", False), self._toggle_ram_temps))

        yield
        self.caption(body, "Startup").pack(fill="x", pady=(22, 8))
        yield
        self.setting_row(body, "\ue7e8", "⏻", "Start with Windows", "Open minimized at sign-in and apply your lighting",
                         switch("autostart_sw", False, self._toggle_autostart))
        yield
        self.setting_row(body, "\ue72c", "↻", "Re-apply lighting on launch", "Restore your last lighting when the app opens",
                         switch("restore_sw", self.settings["restore_on_start"],
                                lambda: self.settings.__setitem__("restore_on_start", self.restore_sw.get() == 1)))

        yield
        self.caption(body, "Help").pack(fill="x", pady=(22, 8))
        yield
        for glyph, fb, title, desc, btn, cmd in (
                ("\ue7ef", "⚑", "PawnIO driver", "Needed for RGB RAM, fan control and most sensors", "Get driver",
                 lambda: webbrowser.open(eng.PAWNIO_PAGE)),
                ("\ue8b7", "▤", "OpenRGB", "Point Central RGB at your own copy of OpenRGB.exe", "Browse", self._browse_openrgb),
                ("\ue774", "◎", "Supported devices", "See which RGB hardware OpenRGB supports", "Open",
                 lambda: webbrowser.open(eng.RELEASES_PAGE))):
            self.setting_row(body, glyph, fb, title, desc,
                             lambda row, b=btn, c=cmd: self.secondary(row, b, c, height=32, width=110))

        yield
        self.caption(body, "Activity").pack(fill="x", pady=(22, 8))
        yield
        logc = self.card(body)
        yield
        logc.pack(fill="x", pady=(0, 10))
        yield
        self.logbox = ctk.CTkTextbox(logc, height=220, fg_color=P["CARD"], text_color=P["MUTED"],
                                     font=ctk.CTkFont(family=MONO, size=12), corner_radius=0, border_width=0, wrap="word")
        yield
        self.logbox.pack(fill="both", expand=True, padx=14, pady=12)
        yield
        for tag, col in (("ok", OK), ("warn", WARN), ("bad", BAD), ("info", INFO)):
            self.logbox.tag_config(tag, foreground=col)
        yield
        self.logbox.configure(state="disabled")

    def _show_checks(self, results):
        for w in self.check_list.winfo_children():
            w.destroy()
        icons = {"ok": ("✓", OK), "warn": ("!", WARN), "bad": ("✕", BAD), "info": ("i", INFO)}
        for level, msg in results:
            g, col = icons.get(level, ("•", P["MUTED"]))
            r = SmoothFrame(self.check_list, fg_color=P["CARD"], corner_radius=6)
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=g, width=22, height=22, corner_radius=11, fg_color=col, text_color="#1a1a1a",
                         font=F(12, "bold")).pack(side="left", padx=(18, 14), pady=12)
            self.label(r, msg, 13, anchor="w", justify="left", wraplength=820).pack(side="left", fill="x", expand=True, padx=(0, 16), pady=10)

    def _toggle_ram_temps(self):
        on = self.ramtemp_sw.get() == 1
        self.settings["ram_temps"] = on
        messagebox.showinfo(eng.APP_NAME, "Restart Central RGB for this to take effect." + (
            "\n\nReading RAM temperatures shares the RAM's SMBus with the RGB controller, which can make "
            "RGB RAM blink. Leave this off if you have RGB RAM." if on else ""))

    def _set_theme(self, name):
        key = next((k for k, t in THEMES.items() if t["name"] == name), DEFAULT_THEME)
        if key == THEME:
            self.settings["theme"] = key
            return
        self.settings["theme"] = key
        if messagebox.askyesno(eng.APP_NAME, f"Restart Central RGB now to switch to {name}?\n\n"
                               "Your lighting comes back right away. Fans go back to BIOS control for a moment "
                               "while it restarts."):
            self._restart()
        else:
            self.status(f"{name} will be used next time Central RGB opens")

    def _restart(self):
        """Start a fresh copy (it waits for this one to close), then quit."""
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--restarted"]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve()), "--restarted"]
        try:
            subprocess.Popen(cmd, creationflags=eng.NO_WINDOW if not getattr(sys, "frozen", False) else 0)
        except Exception as e:
            messagebox.showerror(eng.APP_NAME, f"Couldn't restart automatically ({e}). Please reopen Central RGB.")
        self._quit()

    def _set_accent_mode(self, choice):
        self.settings["accent_mode"] = {"Match lighting": "match", "Windows": "windows"}.get(choice, "cyan")
        self._update_accent()

    def show_page(self, name, animate=True):
        if name not in self.pages:
            return
        self.current_page = name
        page = self.pages[name]
        ph, t = {}, time.perf_counter()

        def mark(k):
            nonlocal t
            now = time.perf_counter()
            ph[k] = (now - t) * 1000
            t = now
        for n, item in self.nav.items():
            item.set(n == name, self.accent)
        mark("nav")
        # Swap pages with drawing frozen, so the old page stays on screen until the new one is fully laid
        # out and filled in, then it appears in a single repaint (no half-drawn frames).
        h = fx.freeze(self._holder)
        try:
            if not page.winfo_manager():          # first visit: lay it out once, then keep it ready
                page.place(relx=0, rely=0, relwidth=1, relheight=1)
            page.tkraise()
            mark("raise")
            if name == "Home":
                self._refresh_home(self.snap)
            elif name == "Monitor":
                self._refresh_monitor(self.snap)
            elif name == "Fans":
                self._refresh_fans(self.snap)
            mark("refresh")
            self.update_idletasks()
            mark("layout")
        finally:
            fx.thaw(h)
            mark("paint")
        if h:
            self.update_idletasks()
            mark("after")
        self._switch_phases = ph

    def _update_accent(self):
        h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in self.color))
        mode = self.settings.data.get("accent_mode", "cyan")
        match = mode == "match"
        if match and self.effect not in eng.USES_COLOR and self.effect != "Off":
            # animated effects: their main colour = average hue of the LEDs over time, weighted by how vivid
            # they are. Effects that use every colour (rainbows) average out to nothing and keep cyan.
            sx = sy = wt = 0.0
            for tt in (0.0, 0.7, 1.4, 2.1, 2.8):
                for col in eng.compute_colors(self.effect, self.color, 100, 50, 24, tt):
                    hh, ss, vv = colorsys.rgb_to_hsv(*(x / 255 for x in col))
                    k = ss * vv
                    sx, sy, wt = sx + k * math.cos(hh * 2 * math.pi), sy + k * math.sin(hh * 2 * math.pi), wt + k
            spread_ok = wt > 0 and math.hypot(sx, sy) / wt > 0.45
            h, s = (math.atan2(sy, sx) / (2 * math.pi)) % 1.0, (1.0 if spread_ok else 0.0)
        if mode == "windows":
            acc = windows_accent(CYAN)
        elif not match or s < 0.25:
            acc = DEFAULT_ACCENT
        else:
            # a light, softened shade like Windows' own dark-mode accents
            acc = hexcol([c * 255 for c in colorsys.hsv_to_rgb(h, min(s, 0.55), 1.0)])
        self.accent = acc
        hov = hexcol(mix(hex2rgb(acc), (255, 255, 255), 0.12))
        for kind, w in self.accent_widgets:
            try:
                if kind == "button":
                    w.configure(fg_color=acc, hover_color=hov, text_color=on_color(acc))
                elif kind == "slider":
                    w.configure(progress_color=acc, button_color=acc)
                elif kind == "seg":
                    w.configure(selected_color=acc, selected_hover_color=hov)
            except tk.TclError:
                pass
        for n, t in self.tiles.items():
            t.select(n == self.effect, acc)
        if hasattr(self, "chips"):
            self._style_chips()
        for sw in (self.autostart_sw, self.restore_sw, self.ramtemp_sw, self.anim_sw):
            sw.configure(progress_color=acc)
        for card in self.device_cards:
            card.switch.configure(progress_color=acc)
        if hasattr(self, "nav"):
            self.nav[self.current_page].set(True, acc)
        for sw in getattr(self, "home_switches", []):
            sw.configure(progress_color=acc)

    def _hidden(self) -> bool:
        try:
            return self.state() in ("withdrawn", "iconic")
        except tk.TclError:
            return True

    def _animate(self):
        if self._hidden():                       # in the tray or minimized: draw nothing
            self.after(250, self._animate)
            return
        t = time.time()
        st = self._current_state()
        try:
            if self.current_page == "Lighting":
                self.preview.show(eng.compute_colors(st["effect"], st["color"], max(st["brightness"], 8), st["speed"], self.preview.n, t))
                tw = max(self.preview_track.winfo_width(), 20)
                self.preview_track.delete("all")
                self.preview_track.create_rectangle(0, 1, tw, 3, fill=P["TRACK"], width=0)
                pos = (t * (0.05 + st["speed"] / 400)) % 1.0
                self.preview_track.create_rectangle(0, 1, tw * pos, 3, fill=self.accent, width=0)
            if self.current_page == "Home":
                self.home_strip.show(eng.compute_colors(st["effect"], st["color"], max(st["brightness"], 8), st["speed"], 48, t))
                self.home_light_strip.show(eng.compute_colors(st["effect"], st["color"], max(st["brightness"], 8), st["speed"], 24, t))
            elif self.current_page == "Lighting":
                for name, tile in self.tiles.items():
                    if isinstance(tile, EffectTile):
                        tile.show(eng.compute_colors(name, self.color, 100, 50, tile.n, t))
            elif self.current_page == "Devices":
                ex = set(self.settings["excluded"])
                for i, card in enumerate(self.device_cards):
                    ds = self._state_for(card.key, self.settings["state"])
                    card.strip.show([(0, 0, 0)] if card.key in ex else eng.compute_colors(
                        ds["effect"], ds["color"], max(ds["brightness"], 8), ds["speed"], card.strip.n, t, offset=i * 0.07))
                if self.editor is not None:
                    ds = self._state_for(self.editor_key, self.settings["state"])
                    self.editor_art.show(eng.compute_colors(ds["effect"], ds["color"], max(ds["brightness"], 8),
                                                            ds["speed"], max(1, len(self.editor_art.leds)), t))
        except tk.TclError:
            pass
        self.after(40, self._animate)

    # ---------------------------------------------------------------- threads / queue
    def _bg(self, fn, *a):
        def wrapper():
            try:
                fn(*a)
            except Exception as e:
                self.log(f"Error: {e}", "bad")
                traceback.print_exc()
        threading.Thread(target=wrapper, daemon=True).start()

    def log(self, msg, level=""):
        self.q.put(("log", msg, level))
        try:                                     # also kept in %APPDATA%\CentralRGB\activity.log
            if not hasattr(self, "_logfile"):
                path = Path(eng.settings_dir()) / "activity.log"
                if path.exists() and path.stat().st_size > 512_000:
                    path.replace(path.with_suffix(".old.log"))
                self._logfile = open(path, "a", encoding="utf-8", buffering=1)
                self._logfile.write(f"\n===== Central RGB {APP_VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
            self._logfile.write(time.strftime("%H:%M:%S  ") + str(msg) + "\n")
        except Exception:
            pass

    def status(self, sub, level="warn"):
        self.q.put(("status", sub, level))

    def _poll_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.logbox.configure(state="normal")
                    prefix = {"ok": "✓ ", "warn": "! ", "bad": "✕ ", "info": "  "}.get(item[2], "")
                    self.logbox.insert("end", time.strftime("%H:%M:%S  ") + prefix + item[1] + "\n", item[2] or None)
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "tray":
                    self._tray_action(item[1])
                elif kind == "status":
                    dot, oval, sub = self.status_rows["rgb"]
                    sub.configure(text=item[1])
                    dot.itemconfigure(oval, fill={"ok": OK, "bad": BAD}.get(item[2], WARN))
                elif kind == "devices":
                    self._fill_devices(item[1])
                elif kind == "checks":
                    self._show_checks(item[1])
                elif kind == "need_openrgb":
                    self._ask_for_openrgb()
                elif kind == "disconnected":
                    self.connected = False
                    self.status("Disconnected - press Rescan", "bad")
                elif kind == "call":
                    item[1]()
        except queue.Empty:
            pass
        except tk.TclError:
            pass
        self.after(100, self._poll_queue)

    # ---------------------------------------------------------------- startup / OpenRGB
    def _startup(self):
        self.status("Checking your system…")
        self._run_check()
        self._connect_flow()

    def _run_check(self):
        res = eng.system_check()
        self.q.put(("checks", res))
        for level, msg in res:
            self.log(msg, level)

    def _wait_for_sensors(self, limit=25.0):
        """RAM and graphics-card lighting are found over the SMBus, which the sensor library also uses
        while it loads. Scanning at the same time makes OpenRGB miss those devices, so wait for it."""
        end = time.time() + limit
        while time.time() < end and self.monitor.snapshot()["status"] == "starting":
            time.sleep(0.2)

    def _connect_flow(self):
        if self.manager.replace_visible_copy():
            time.sleep(1.0)                  # let its server port close
        if not self.manager.started_by_us() and self.manager.own_copies():
            # a hidden OpenRGB of ours left over from an earlier session (e.g. ended in Task Manager):
            # its device list may be incomplete, so restart it for a fresh hardware scan
            self.log("Restarting a hidden OpenRGB left from an earlier session, for a fresh hardware scan.")
            self.manager.stop_own_copies()
            for _ in range(25):
                if not self.manager.server_running():
                    break
                time.sleep(0.2)
        if not self.manager.server_running():
            self.status("Waiting for sensors…")
            self._wait_for_sensors()
            exe = self.manager.find_exe()
            if not exe:
                self.status("OpenRGB needed")
                self.log("OpenRGB (the lighting layer) was not found.", "warn")
                self.q.put(("need_openrgb",))
                return
            self.status("Starting OpenRGB (≈30 s)…")
            if not self.manager.launch(exe):
                self.status("OpenRGB problem - see Settings", "bad")
                return
        else:
            self.log("OpenRGB SDK server already running - connecting.", "ok")
        if not self.engine.connect():
            self.status("Can't connect - see Settings", "bad")
            return
        self.connected = True
        self._rescan(initial=True)
        self._bg(self._settle_devices)
        if self.settings["restore_on_start"] or self.background:
            self.engine.paused = False
            self.engine.force_reapply()

    def _full_rescan(self):
        """Rescan button: make OpenRGB look for hardware again. The hidden OpenRGB this app runs is
        restarted (it only detects devices when it starts); an OpenRGB you run yourself is just refreshed."""
        if not self.manager.started_by_us() and not self.manager.own_copies():
            self._rescan()                   # an OpenRGB you run yourself: just refresh its list
            return
        self.status("Re-detecting hardware…")
        self.log("Re-detecting hardware (restarting the hidden OpenRGB)…")
        exe = self.manager.find_exe()
        self.engine.disconnect()
        self.manager.stop_own_copies()
        for _ in range(25):
            if not self.manager.server_running():
                break
            time.sleep(0.2)
        self._wait_for_sensors()
        if not self.manager.launch(exe):
            self.status("OpenRGB problem - see Settings", "bad")
            return
        if self.engine.connect():
            self._rescan(initial=True)
            self._bg(self._settle_devices)

    def _settle_devices(self, max_wait=90.0, quiet_for=12.0, min_wait=25.0):
        """OpenRGB keeps detecting hardware after its server opens: USB devices appear at once, but RAM and
        graphics-card lighting are found by probing the SMBus and can take much longer. Keep reading the
        device list until it has stopped changing for a while (runs on a background thread)."""
        t0 = last_change = time.time()
        count = len(self.engine.devices())
        while time.time() - t0 < max_wait:
            time.sleep(1.5)
            try:
                self._rescan(quiet=True)
            except Exception:
                pass
            rows = len(self.engine.devices())
            if rows != count:
                self.log(f"OpenRGB found more hardware: {rows} device(s) now.", "ok")
                count, last_change = rows, time.time()
            elif time.time() - t0 > min_wait and time.time() - last_change > quiet_for:
                break
        self.log(f"Hardware detection finished: {count} device(s) after {time.time() - t0:.0f} s.", "info")

    def _rescan(self, initial=False, quiet=False):
        if not self.engine.client:
            self._connect_flow()
            return
        if not quiet:
            self.status("Scanning…")
        try:
            self.engine.rescan()
        except Exception as e:
            self.log(f"Rescan failed: {e}", "bad")
            return
        rows = [(eng.device_key(d), eng.type_name(d), d.name, len(d.leds)) for d in self.engine.devices()]
        if rows != self.device_rows:
            self.q.put(("devices", rows))
        self.status(f"{len(rows)} devices · {sum(r[3] for r in rows)} LEDs", "ok" if rows else "warn")
        if not quiet or initial:
            self.log(f"Found {len(rows)} RGB device(s).", "ok" if rows else "warn")
            for _, t, name, leds in rows:
                self.log(f"  {t}: {name} ({leds} LEDs)", "info")

    def _toggle_device(self, key, on):
        ex = set(self.settings["excluded"])
        (ex.discard if on else ex.add)(key)
        self._apply_exclusions(ex)

    def _set_all_devices(self, on):
        ex = set(self.settings["excluded"])
        keys = {r[0] for r in self.device_rows}
        self._apply_exclusions(ex - keys if on else ex | keys)
        for c in self.device_cards:
            c.switch.select() if on else c.switch.deselect()

    def _apply_exclusions(self, ex):
        self.settings["excluded"] = sorted(ex)
        self.engine.set_excluded(ex)
        self._update_dev_summary()

    def _ask_for_openrgb(self):
        ans = messagebox.askyesnocancel(
            "OpenRGB needed",
            "Central RGB uses the free, open-source OpenRGB engine to talk to your RGB hardware, "
            "and it isn't installed yet.\n\nYes  = download it automatically (≈15 MB)\n"
            "No   = I already have it - let me pick OpenRGB.exe\nCancel = open the OpenRGB website")
        if ans is True:
            self.status("Downloading OpenRGB…")
            self._bg(self._download_then_connect)
        elif ans is False:
            self._browse_openrgb()
        else:
            webbrowser.open(eng.RELEASES_PAGE)

    def _browse_openrgb(self):
        path = filedialog.askopenfilename(title="Find OpenRGB.exe", filetypes=[("OpenRGB", "OpenRGB.exe"), ("Programs", "*.exe")])
        if path:
            self.settings["openrgb_path"] = path
            self._bg(self._connect_flow)

    def _download_then_connect(self):
        last = [-1]

        def prog(p):
            if p // 5 != last[0]:
                last[0] = p // 5
                self.status(f"Downloading OpenRGB {p}%")
        try:
            self.manager.download(prog)
        except Exception as e:
            self.log(f"Download failed: {e}. Opening the OpenRGB website instead.", "bad")
            webbrowser.open(eng.RELEASES_PAGE)
            self.status("Download failed", "bad")
            return
        self._connect_flow()

    # ---------------------------------------------------------------- lighting state
    def _current_state(self):
        return {"color": list(self.color), "effect": self.effect,
                "brightness": int(self.bright.get()), "speed": int(self.speed.get())}

    def _sync_ui_from_state(self):
        self.wheel.set_rgb(self.color)
        self.swatch.itemconfigure(self.swatch_item, fill=hexcol(self.color))
        self._sync_color_fields()
        self.preview_label.configure(text=f"Live Preview - {self.effect}")
        self._update_accent()

    def _state_changed(self):
        st = self._current_state()
        self.preview_label.configure(text=f"Live Preview - {self.effect}")
        if getattr(self, "light_scope", "All") != "All":
            ov = dict(self.settings.data.get("device_overrides", {}))
            for k in self._scope_keys():
                ov[k] = dict(st)
            self.settings["device_overrides"] = ov
            self.engine.set_overrides(ov)
            for c in self.device_cards:
                if c.key in ov:
                    c.edit_btn.configure(text="Custom ✓")
            if self.connected:
                self.engine.paused = False
            return
        self.engine.set_state(**st)
        if self.connected:
            self.engine.paused = False
        self.settings["state"] = st

    def _set_color(self, rgb, from_wheel=False):
        self.color = tuple(int(c) for c in rgb)
        if self.effect not in eng.USES_COLOR:
            self.effect = "Static"
        if not from_wheel:
            self.wheel.set_rgb(self.color)
        self.swatch.itemconfigure(self.swatch_item, fill=hexcol(self.color))
        self._sync_color_fields()
        self._update_accent()
        self._state_changed()

    def _hex_entered(self, _e=None):
        txt = self.hex_entry.get().strip().lstrip("#")
        if len(txt) == 6:
            try:
                rgb = hex2rgb(txt)
                if rgb != self.color:
                    self._set_color(rgb)
            except ValueError:
                pass

    def _set_effect(self, name):
        self.effect = name
        self._update_accent()
        self._state_changed()

    def _apply_all(self):
        if not self.engine.client:
            messagebox.showinfo(eng.APP_NAME, "Not connected to OpenRGB yet - check Settings.")
            return
        self.engine.force_reapply()
        self._state_changed()
        self.log(f"Applied {self.effect} to all selected devices.", "ok")

    def _save_hw(self):
        if self.effect in eng.ANIMATED:
            self.q.put(("call", lambda: messagebox.showinfo(eng.APP_NAME, "Save to hardware stores one solid color - pick Static first.")))
            return
        for r in self.engine.save_to_hardware():
            self.log(r, "ok" if r.startswith("Saved") else "warn")

    # ---------------------------------------------------------------- profiles
    def _load_profile(self, name):
        st = self.settings["profiles"].get(name)
        if not st:
            return
        self.color, self.effect = tuple(st["color"]), st["effect"]
        for s, v in ((self.bright, st["brightness"]), (self.speed, st["speed"])):
            s.set(v)
            s.value_label.configure(text=f"{v}%")
        self._sync_ui_from_state()
        self._state_changed()
        self.show_page("Lighting")

    def _save_profile(self):
        name = self.profile_name.get().strip()
        if not name:
            self.profile_name.focus_set()
            return
        profs = dict(self.settings["profiles"])
        profs[name] = self._current_state()
        self.settings["profiles"] = profs
        self.profile_name.delete(0, "end")
        self._refresh_profiles()

    def _delete_profile(self, name):
        if messagebox.askyesno("Delete profile", f"Delete '{name}'?"):
            profs = dict(self.settings["profiles"])
            profs.pop(name, None)
            self.settings["profiles"] = profs
            self._refresh_profiles()

    # ---------------------------------------------------------------- autostart (Task Scheduler: admin apps
    # are blocked from the normal Startup / Run key)
    def _launch_command(self) -> str:
        if getattr(sys, "frozen", False):
            return f'"{sys.executable}" --background'
        pyw = Path(sys.executable).with_name("pythonw.exe")
        return f'"{pyw if pyw.exists() else sys.executable}" "{Path(__file__).resolve()}" --background'

    def _autostart_enabled(self) -> bool:
        if not eng.IS_WIN:
            return False
        r = eng.run_quiet(["schtasks", "/Query", "/TN", TASK_NAME])
        return bool(r and r.returncode == 0)

    def _check_autostart(self):
        on = self._autostart_enabled()
        if on:
            self.after(0, lambda: self.autostart_sw.select() if self.autostart_sw.winfo_exists() else None)

    def _toggle_autostart(self):
        if not eng.IS_WIN:
            messagebox.showinfo(eng.APP_NAME, "Start with Windows is only available on Windows.")
            self.autostart_sw.deselect()
            return
        if self.autostart_sw.get() == 1:
            r = eng.run_quiet(["schtasks", "/Create", "/TN", TASK_NAME, "/TR", self._launch_command(),
                               "/SC", "ONLOGON", "/RL", "HIGHEST", "/DELAY", "0000:20", "/F"])
            ok = bool(r and r.returncode == 0)
            self.log("Central RGB will start at login." if ok else
                     f"Couldn't create startup task: {r.stderr.strip() if r else 'unknown error'}", "ok" if ok else "bad")
            if not ok:
                self.autostart_sw.deselect()
        else:
            eng.run_quiet(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
            self.log("Removed from Windows startup.", "ok")

    # ---------------------------------------------------------------- closing
    def on_close(self):
        """The X button: hide to the system tray (keeps lighting and fan control running), or quit."""
        if self.tray is not None and self.settings.data.get("close_to_tray", True):
            self.settings["state"] = self._current_state()
            self.withdraw()                                  # off the taskbar, still running
            if not self.settings.data.get("tray_hint_shown"):
                self.settings["tray_hint_shown"] = True
                self.tray.notify("Still running in the system tray. Right-click the icon to open or quit.")
            return
        self._confirm_quit()

    def _set_close_mode(self, value):
        self.settings["close_to_tray"] = value != "Quit"

    def _tray_action(self, what):
        if what == "show":
            try:
                self.attributes("-alpha", 0.0)
            except tk.TclError:
                pass
            self.deiconify()
            self.state("normal")
            self.update()                        # repaint everything while invisible (no white flash)
            self._fade_in(0.4)
            self.lift()
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
            self.focus_force()
        elif what == "off":
            self._set_effect("Off")
        elif what == "quit":
            self._quit()

    def _confirm_quit(self):
        s = self.monitor.snapshot()
        fan_custom = s["profile"] != "Auto" or s["manual"]
        if self.effect in eng.ANIMATED or fan_custom:
            why = []
            if self.effect in eng.ANIMATED:
                why.append(f"the '{self.effect}' lighting effect")
            if fan_custom:
                why.append("your fan profile (fans go back to BIOS control)")
            ans = messagebox.askyesnocancel(
                eng.APP_NAME, "Closing stops " + " and ".join(why) + ".\n\n"
                "Yes = minimize and keep running\nNo = quit")
            if ans is None:
                return
            if ans:
                self.iconify()
                return
        self._quit()

    def _quit(self):
        self.settings["state"] = self._current_state()
        if self.tray is not None:
            self.tray.stop()
        self.engine.stop()
        self.fps.stop()
        self.monitor.stop()       # hands fans back to the BIOS
        self.manager.stop()       # the hidden OpenRGB this app started
        self.destroy()


def main():
    if "--sensor-worker" in sys.argv:          # helper process that runs the hardware sensors
        hwm.sensor_worker()
        return
    if "--splash" in sys.argv:                 # helper process that plays the startup animation
        run_splash()
        return
    if eng.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            # own taskbar identity, so Windows shows the Central RGB icon (not Python's)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CentralRGB.App")
        except Exception:
            pass
    selftest = None
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        selftest = sys.argv[i + 1] if i + 1 < len(sys.argv) else str(Path(eng.settings_dir()) / "selftest.txt")
        try:
            App(selftest=selftest).mainloop()
        except Exception:
            Path(selftest).write_text("Central RGB self-test: FAILED\n" + traceback.format_exc(), encoding="utf-8")
            os._exit(1)
        return
    q: queue.Queue = queue.Queue()
    if not claim_single_instance(q, wait=15.0 if "--restarted" in sys.argv else 0.0):
        return                                   # already running: it has been asked to show its window
    app = App(background="--background" in sys.argv)
    while not q.empty():                         # a "show" that arrived while starting
        app.q.put(q.get())
    _forward = threading.Thread(target=lambda: [app.q.put(q.get()) for _ in iter(int, 1)], daemon=True)
    _forward.start()
    app.mainloop()


if __name__ == "__main__":
    main()
