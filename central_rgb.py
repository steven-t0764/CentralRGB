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
from tkinter import colorchooser, filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

import device_models as dm
import fps_overlay as fpo
import hw_monitor as hwm
import rgb_engine as eng
import updater as upd
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
# outline. Changing it rebuilds the window in place (App._switch_theme); nothing else restarts.
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
    "gunmetal": dict(name="Gunmetal", desc="Compact: neutral panels, only your lighting brings colour",
                     BG="#111214", SIDE="#0c0d0f", CARD="#17181b", CARD2="#1f2024", LINE="#2a2c31",
                     TEXT="#ececee", MUTED="#a0a2a8", FAINT="#6b6e75", TRACK="#2a2c31", HOVER="#16171a",
                     SEL="#1d1f23", BTN="#1e2023", BTN_HOVER="#26282c", BTN_LINE="#2f3237",
                     accent="#5cc8da", chrome="#e6e7ea", PURPLE="#7b7e86", TEAL="#5cc8da", BLUE="#5cc8da",
                     PINK="#5cc8da", VIOLET="#5cc8da"),
}
DEFAULT_THEME = "gunmetal"

# ----------------------------------------------------------------------------- appearance (dark / light)
# Settings > Appearance picks Dark (every theme exactly as above) or Light. Light mode keeps each theme's
# tint and accent hue on Windows 11-style light panels; LIGHT_THEMES (built below) has the full palette.
APPEARANCES = ("dark", "light")
DEFAULT_APPEARANCE = "dark"
# colours that are not part of a theme: status colours, the amber warning bars and the delete hover
_DARK_EXTRA = dict(OK=OK, WARN=WARN, BAD=BAD, INFO=INFO, WARN_BG="#2a2112", WARN_TEXT="#ffd166",
                   ON_STATUS="#1a1a1a", DEL_HOVER="#4a1f28")
_LIGHT_EXTRA = dict(OK="#0f7b0f", WARN="#9d5d00", BAD="#c42b1c", INFO="#005fb8", WARN_BG="#fff4ce",
                    WARN_TEXT="#6b4100", ON_STATUS="#ffffff", DEL_HOVER="#f6d6da")
WARN_BG, WARN_TEXT, ON_STATUS, DEL_HOVER = (_DARK_EXTRA[k] for k in ("WARN_BG", "WARN_TEXT", "ON_STATUS", "DEL_HOVER"))


def appearance_of(value) -> str:
    """'light' or 'dark'; anything missing or unknown (older settings files) means dark."""
    return value if value in APPEARANCES else DEFAULT_APPEARANCE


def _lum(hex_color) -> float:
    """WCAG relative luminance."""
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in hex2rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b) -> float:
    """WCAG contrast ratio between two colours (1 to 21)."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def darken_for(hex_color, bg, ratio=4.5) -> str:
    """The same hue, darkened only as far as needed to reach `ratio` contrast against `bg`."""
    r, g, b = (c / 255 for c in hex2rgb(hex_color))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    out = hex_color
    while contrast(out, bg) < ratio and l > 0:
        l = max(0.0, l - 0.01)
        out = hexcol([c * 255 for c in colorsys.hls_to_rgb(h, l, s)])
    return out


def _light_palette(t) -> dict:
    """Light variant of a theme: near-white panels with a trace of the theme's tint, near-black text and the
    accent colours darkened (same hue) until they read on white."""
    dark = {**_BASE_SOLID, **t} if "BG" in t else dict(_BASE_SOLID)
    acc = t.get("accent", _BASE_COLORS[0])
    tint = hex2rgb(dark["CARD2"])                   # the theme's own panel tint

    def tinted(base, amount):
        # the tint's hue at low strength: push the base colour toward the tint's direction from grey
        g = sum(tint) / 3
        return hexcol([min(255, max(0, c + (x - g) * amount)) for c, x in zip(hex2rgb(base), tint)])
    s = dict(BG=tinted("#f3f3f3", 0.9), SIDE=tinted("#eeeeee", 0.9), CARD=tinted("#fcfcfc", 0.5),
             CARD2=tinted("#f5f5f5", 0.7), LINE=tinted("#e0e0e0", 1.0), TEXT=tinted("#1b1b1b", 0.6),
             MUTED=tinted("#555555", 1.0), FAINT=tinted("#666666", 1.0), TRACK=tinted("#d6d6d6", 1.0),
             HOVER=tinted("#f9f9f9", 0.6), BTN=tinted("#fdfdfd", 0.4), BTN_HOVER=tinted("#f3f3f3", 0.6),
             BTN_LINE=tinted("#d9d9d9", 1.0))
    card = s["CARD"]
    s["accent"] = darken_for(acc, card, 4.5)
    s["SEL"] = hexcol(mix(hex2rgb(s["BG"]), hex2rgb(s["accent"]), 0.10))
    base = _BASE_COLORS
    for i, k in enumerate(("PURPLE", "TEAL", "BLUE", "PINK", "VIOLET"), start=1):
        s[k] = darken_for(t.get(k, base[i]), card, 3.0)
    if t.get("border"):
        s["border"] = darken_for(hexcol(mix(hex2rgb(t["border"]), hex2rgb(s["LINE"]), 0.4)), s["BG"], 1.6)
        s["border_w"] = t.get("border_w", 1)
    if t.get("chrome"):
        s["chrome"] = "#2b2d31"                     # Gunmetal: dark buttons and sliders instead of off-white
    return s


def _saved_theme() -> str:
    try:
        import json
        t = json.loads((eng.settings_dir() / "settings.json").read_text(encoding="utf-8")).get("theme")
        return t if t in THEMES else DEFAULT_THEME
    except Exception:
        return DEFAULT_THEME


def _saved_appearance() -> str:
    try:
        import json
        return appearance_of(json.loads((eng.settings_dir() / "settings.json").read_text(encoding="utf-8"))
                             .get("appearance"))
    except Exception:
        return DEFAULT_APPEARANCE


def _apply_extra(extra):
    global OK, WARN, BAD, INFO, WARN_BG, WARN_TEXT, ON_STATUS, DEL_HOVER
    OK, WARN, BAD, INFO = extra["OK"], extra["WARN"], extra["BAD"], extra["INFO"]
    WARN_BG, WARN_TEXT, ON_STATUS, DEL_HOVER = extra["WARN_BG"], extra["WARN_TEXT"], extra["ON_STATUS"], extra["DEL_HOVER"]


def _apply_theme(key: str, appearance: str = DEFAULT_APPEARANCE):
    """Swap the module colours for a theme in Dark or Light appearance (widgets made afterwards use them)."""
    global CYAN, PURPLE, TEAL, BLUE, PINK, VIOLET, GRAD, CARD_BORDER, CARD_BORDER_W, DEFAULT_ACCENT, APPEARANCE
    APPEARANCE = appearance_of(appearance)
    if APPEARANCE == "light":
        s = LIGHT_THEMES.get(key) or LIGHT_THEMES[DEFAULT_THEME]
        SOLID.update({k: s[k] for k in SOLID})
        P.update(SOLID)
        CYAN, PURPLE, TEAL, BLUE, PINK, VIOLET = s["accent"], s["PURPLE"], s["TEAL"], s["BLUE"], s["PINK"], s["VIOLET"]
        GRAD = (PINK, VIOLET, CYAN)
        CARD_BORDER, CARD_BORDER_W = s.get("border"), s.get("border_w", 0)
        DEFAULT_ACCENT = s.get("chrome", CYAN)
        _apply_extra(_LIGHT_EXTRA)
        return
    _apply_extra(_DARK_EXTRA)
    t = THEMES.get(key) or THEMES[DEFAULT_THEME]
    if "BG" not in t:                         # the default theme: the original values exactly
        SOLID.update(_BASE_SOLID)
        P.update(SOLID)
        CYAN, PURPLE, TEAL, BLUE, PINK, VIOLET, GRAD, CARD_BORDER, CARD_BORDER_W = _BASE_COLORS
        DEFAULT_ACCENT = CYAN
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
    DEFAULT_ACCENT = s.get("chrome", CYAN)      # buttons, sliders, selection (Gunmetal keeps them off-white)


def windows_accent(fallback="#60cdff") -> str:
    """The user's Windows accent colour, in the shade Windows 11 uses for controls: a lighter one in dark mode,
    a darker one in light mode."""
    if not eng.IS_WIN:
        return fallback
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as k:
            pal, _ = winreg.QueryValueEx(k, "AccentPalette")      # 8 RGBA shades, lightest first
        i = 16 if APPEARANCE == "light" else 4                       # shade 4 = "Dark 1", shade 1 = "Light 2"
        r, g, b = pal[i], pal[i + 1], pal[i + 2]
        return "#%02x%02x%02x" % (r, g, b)
    except Exception:
        return fallback


WIN11 = eng.IS_WIN and fx.win_build() >= 22000
FONT = "Segoe UI Variable Text" if WIN11 else ("Segoe UI" if eng.IS_WIN else "Selawik")   # Selawik: Segoe stand-in for previews
FONT_DISPLAY = "Segoe UI Variable Display" if WIN11 else FONT
FONT_SEMI = ("Segoe UI Variable Text Semibold" if WIN11 else
             ("Segoe UI Semibold" if eng.IS_WIN else "Selawik Semibold"))   # "bold" text uses semibold, not 700
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


# ----------------------------------------------------------------------------- light-mode helpers
# Each returns exactly what Dark has always used, so the dark look of every theme is unchanged.
def slider_hover(button_hex) -> str:
    """Slider knob colour while hovered or dragged: white in Dark; in Light a deeper shade of the knob, because a
    white knob vanishes on the near-white cards."""
    if APPEARANCE != "light":
        return "white"
    return hexcol(mix(hex2rgb(button_hex), hex2rgb(P["TEXT"]), 0.35))


def swatch_outline(rgb) -> str:
    """Outline for a colour swatch. Dark: the card colour (a gap, as before). Light: a thin line so a white or
    near-white swatch still shows; a stronger one when the swatch barely differs from the card."""
    if APPEARANCE != "light":
        return P["CARD"]
    if contrast(hexcol(rgb), P["CARD"]) < 1.5:
        return hexcol(mix(hex2rgb(P["BTN_LINE"]), hex2rgb(P["MUTED"]), 0.5))
    return P["BTN_LINE"]


def led_on(rgb, bg_rgb):
    """How a dimmed LED colour is drawn on a panel. Dark: as is (it blends into the dark panel). Light: brightness
    is treated as opacity over the panel, so a Breathing low point fades into the card instead of a black bar."""
    if APPEARANCE != "light":
        return tuple(rgb)
    v = max(rgb) / 255
    if v <= 0:
        return tuple(rgb)
    full = tuple(c / v for c in rgb)
    return mix(bg_rgb, full, v)


_BASE_SOLID = dict(SOLID)                 # the default theme, so it can be switched back to live
_BASE_COLORS = (CYAN, PURPLE, TEAL, BLUE, PINK, VIOLET, GRAD, CARD_BORDER, CARD_BORDER_W)
DEFAULT_ACCENT = CYAN
LIGHT_THEMES = {k: _light_palette(t) for k, t in THEMES.items()}
THEME = _saved_theme()
APPEARANCE = _saved_appearance()
_apply_theme(THEME, APPEARANCE)


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
        # The mouse wheel should scroll the page, not move a slider the pointer happens to pass over
        # (newer CustomTkinter moves sliders with the wheel). Dragging and clicking still work.
        for w in (self, getattr(self, "_canvas", None)):
            if w is not None:
                for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                    try:
                        w.unbind(seq)
                    except Exception:
                        pass


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
        self.bind("<Map>", lambda e=None: [tk.Misc.lift(c) for c in self._corners], add="+")
        for c in self._corners:
            tk.Misc.lift(c)


# CustomTkinter widgets call update_idletasks() on their canvas whenever they redraw. That forces a layout
# pass of the whole window, so while pages are being built every new dropdown or scrollbar stalled the app.
# Tk redraws them at the next idle moment anyway, so the forced pass is switched off.
ctk.CTkCanvas.update_idletasks = lambda self: None

# Invisible layout frames (fg_color="transparent") still get CustomTkinter's default rounded corners, drawn
# with its slow font-glyph shapes. Nobody can see them, but every repaint (e.g. bringing the window back from
# the taskbar) redrew 100+ of them, leaving black boxes for a second. Give them square corners instead.
_ctk_frame_init = ctk.CTkFrame.__init__


def _frame_init(self, master, *args, **kw):
    if kw.get("fg_color") == "transparent" and "corner_radius" not in kw:
        kw["corner_radius"] = 0
        kw.setdefault("border_width", 0)
    _ctk_frame_init(self, master, *args, **kw)


ctk.CTkFrame.__init__ = _frame_init


class SmoothButton(tk.Canvas):
    """Rounded button drawn with Pillow (anti-aliased fill and outline), in place of CustomTkinter buttons
    whose 1px outlines come out uneven on Windows. Takes the same options this app uses with CTkButton."""

    _cache: dict = {}

    def __init__(self, master, text="", command=None, width=140, height=28, corner_radius=6, font=None,
                 fg_color=None, hover_color=None, text_color=None, border_width=0, border_color=None, **_ignored):
        try:
            self._sc = ctk.ScalingTracker.get_widget_scaling(master)
        except Exception:
            self._sc = 1.0
        self._behind = SmoothFrame._color_behind(master)
        self._w0, self._h = int(width * self._sc), int(height * self._sc)
        super().__init__(master, width=self._w0, height=self._h, bg=self._behind, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._o = dict(text=text, command=command, corner_radius=corner_radius, font=font or F(13),
                       fg_color=fg_color or P["BTN"], hover_color=hover_color or fg_color or P["BTN_HOVER"],
                       text_color=text_color or P["TEXT"], border_width=border_width,
                       border_color=border_color or P["BTN_LINE"], state="normal")
        self._hover, self._img = False, None
        self._bg_item = self.create_image(0, 0, anchor="nw")
        self._txt = self.create_text(0, 0, text=text)
        self.bind("<Configure>", lambda e=None: self._draw())
        self.bind("<Enter>", lambda e=None: self._set_hover(True))
        self.bind("<Leave>", lambda e=None: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _font(self):
        f = self._o["font"]
        try:
            return (f.cget("family"), -max(8, round(abs(f.cget("size")) * self._sc)), f.cget("weight"))
        except Exception:
            return f

    @staticmethod
    def _col(c, fallback):
        return fallback if (not c or c == "transparent") else c

    def _draw(self):
        o = self._o
        w = max(self.winfo_width(), 2) if self.winfo_width() > 2 else self._w0
        h = self._h
        fill = self._col(o["hover_color"] if (self._hover and o["state"] == "normal") else o["fg_color"], self._behind)
        bw = o["border_width"]
        key = (w, h, round(o["corner_radius"] * self._sc), fill, self._behind, bw, o["border_color"] if bw else None)
        img = SmoothButton._cache.get(key)
        if img is None:
            r = min(h / 2, o["corner_radius"] * self._sc)
            img = ImageTk.PhotoImage(aa_round_rect(w, h, r, hex2rgb(fill), hex2rgb(self._behind),
                                                   outline=hex2rgb(self._col(o["border_color"], fill)) if bw else None,
                                                   width=max(1, bw * self._sc)))
            if len(SmoothButton._cache) > 400:
                SmoothButton._cache.clear()
            SmoothButton._cache[key] = img
        self._img = img
        self.itemconfigure(self._bg_item, image=img)
        col = o["text_color"] if o["state"] == "normal" else P["FAINT"]
        self.coords(self._txt, w / 2, h / 2)
        self.itemconfigure(self._txt, text=o["text"], fill=col, font=self._font())

    def _set_hover(self, on):
        if on != self._hover:
            self._hover = on
            self._draw()

    def _click(self, e):
        if self._o["state"] == "normal" and self._o["command"] and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._o["command"]()

    def configure(self, require_redraw=False, **kw):
        changed = False
        for k in list(kw):
            if k in self._o:
                self._o[k] = kw.pop(k)
                changed = True
        if "width" in kw:
            self._w0 = int(kw["width"] * self._sc)
            super().configure(width=self._w0)
            kw.pop("width")
        kw.pop("hover", None)
        if kw:
            super().configure(**kw)
        if changed:
            self._draw()

    config = configure

    def cget(self, key):
        if key in self._o:
            return self._o[key]
        return super().cget(key)


class CreateTile(tk.Canvas):
    """The "+ Create preset" tile at the end of the preset gallery."""

    def __init__(self, master, on_click, height=88):
        super().__init__(master, height=height, bg=P["CARD"], highlightthickness=0, cursor="hand2")
        self.h, self._img, self._key, self._hover = height, None, None, False
        self.bind("<Configure>", lambda e=None: self._render())
        self.bind("<Enter>", lambda e=None: self._set_hover(True))
        self.bind("<Leave>", lambda e=None: self._set_hover(False))
        self.bind("<Button-1>", lambda e=None: on_click())

    def _set_hover(self, on):
        self._hover = on
        self._render()

    def _render(self):
        w, h = max(self.winfo_width(), 40), self.h
        key = (w, h, self._hover, P["CARD"])
        if key == self._key:
            return
        self._key = key
        fill = P["HOVER"] if self._hover else P["CARD2"]
        self._img = ImageTk.PhotoImage(aa_round_rect(w - 6, h - 6, 9, fill, P["CARD"],
                                                     outline=P["MUTED"] if self._hover else P["LINE"], width=1))
        self.delete("all")
        self.create_image(3, 3, image=self._img, anchor="nw")
        self.create_text(w / 2, h / 2 - 8, text="+", fill=P["MUTED"], font=(FONT_DISPLAY, 18))
        self.create_text(w / 2, h / 2 + 14, text="Create preset", fill=P["MUTED"], font=(FONT, 10))


class PresetEditor(ctk.CTkToplevel):
    """Make or edit your own lighting preset: 2-5 colours, a motion, a speed and a name, with a live preview."""

    def __init__(self, app, name=None):
        super().__init__(app, fg_color=P["BG"])
        self.app, self.orig = app, name
        d = app.settings.data.get("custom_presets", {}).get(name) or {
            "motion": "Wave", "colors": [list(app.color), [160, 0, 255], [0, 220, 255]], "speed": 50}
        self.colors = [tuple(c) for c in d["colors"]]
        self.title("Edit preset" if name else "Create preset")
        self.geometry("620x560")
        self.resizable(False, False)
        self.transient(app)
        self.after(150, self.grab_set)
        pad = dict(padx=22)
        app.label(self, "Edit preset" if name else "Create preset", 22, "bold").pack(anchor="w", pady=(20, 2), **pad)
        app.label(self, "Pick your colours and how they move. Your presets appear in the Lighting gallery "
                        "(right-click one to edit or delete it).", 12, color=P["MUTED"], anchor="w", justify="left",
                  wraplength=570).pack(anchor="w", **pad)
        self.preview = LedStrip(self, n=36, height=44, bg=P["BG"], pill=True)
        self.preview.pack(fill="x", pady=(16, 10), **pad)

        app.label(self, "Name", 13, "bold").pack(anchor="w", pady=(8, 4), **pad)
        self.name_e = ctk.CTkEntry(self, height=34, font=F(13), fg_color=P["CARD2"], border_width=0, corner_radius=6,
                                   text_color=P["TEXT"], placeholder_text="My preset")
        self.name_e.pack(fill="x", **pad)
        if name:
            self.name_e.insert(0, name)

        app.label(self, "Motion", 13, "bold").pack(anchor="w", pady=(14, 4), **pad)
        self.motion = PillSwitcher(self, values=eng.CUSTOM_MOTIONS, height=32, font=F(12), selected_color=CYAN)
        self.motion.set(d.get("motion", "Wave"))
        self.motion.pack(anchor="w", **pad)

        app.label(self, "Colours", 13, "bold").pack(anchor="w", pady=(14, 4), **pad)
        self.col_row = ctk.CTkFrame(self, fg_color="transparent")
        self.col_row.pack(fill="x", **pad)

        app.label(self, "Speed", 13, "bold").pack(anchor="w", pady=(14, 0), **pad)
        self.speed = Slider(self, from_=0, to=100, number_of_steps=100, height=18, progress_color=CYAN,
                            button_color="#ffffff" if APPEARANCE != "light" else CYAN,
                            button_hover_color="#ffffff" if APPEARANCE != "light" else slider_hover(CYAN),
                            fg_color=P["TRACK"])
        self.speed.set(d.get("speed", 50))
        self.speed.pack(fill="x", pady=(6, 0), **pad)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", side="bottom", pady=20, **pad)
        app.primary(btns, "Save preset", self._save, height=38, width=150).pack(side="right")
        app.secondary(btns, "Cancel", self.destroy, height=38, width=100).pack(side="right", padx=8)
        if name:
            app.secondary(btns, "Delete", self._delete, height=38, width=100).pack(side="left")
        self._colours()
        self._tick()

    def _colours(self):
        for w in self.col_row.winfo_children():
            w.destroy()
        for i, c in enumerate(self.colors):
            hexc = hexcol(c)
            SmoothButton(self.col_row, text="", width=46, height=34, corner_radius=8, fg_color=hexc, hover_color=hexc,
                         border_width=1, border_color=P["LINE"],
                         command=lambda k=i: self._pick(k)).pack(side="left", padx=(0, 8))
        if len(self.colors) < 5:
            self.app.secondary(self.col_row, "+ Add", self._add, height=34, width=70).pack(side="left", padx=(4, 6))
        if len(self.colors) > 2:
            self.app.secondary(self.col_row, "− Remove", self._remove, height=34, width=90).pack(side="left")
        self.app.label(self.col_row, "click a colour to change it", 11, color=P["FAINT"]).pack(side="left", padx=10)

    def _pick(self, k):
        got = colorchooser.askcolor(color=hexcol(self.colors[k]), parent=self, title="Pick a colour")
        if got and got[0]:
            self.colors[k] = tuple(int(v) for v in got[0])
            self._colours()

    def _add(self):
        self.colors.append((255, 255, 255))
        self._colours()

    def _remove(self):
        self.colors.pop()
        self._colours()

    def _defn(self):
        return {"motion": self.motion.get(), "colors": [list(c) for c in self.colors], "speed": int(self.speed.get())}

    def _tick(self):
        if not self.winfo_exists():
            return
        d = self._defn()
        eng.CUSTOM_PRESETS["__preview__"] = d
        try:
            self.preview.show(eng.compute_colors("__preview__", (0, 0, 0), 100, d["speed"], self.preview.n, time.time()))
        finally:
            eng.CUSTOM_PRESETS.pop("__preview__", None)
        self.after(50, self._tick)

    def _save(self):
        name = self.name_e.get().strip()[:28]
        if not name:
            messagebox.showinfo(eng.APP_NAME, "Give your preset a name.", parent=self)
            return
        if name in eng.PRESET_EFFECTS or name in eng.BASIC_EFFECTS:
            messagebox.showinfo(eng.APP_NAME, f"\"{name}\" is a built-in effect. Pick another name.", parent=self)
            return
        presets = dict(self.app.settings.data.get("custom_presets", {}))
        if name != self.orig and name in presets and not messagebox.askyesno(
                eng.APP_NAME, f"Replace your preset \"{name}\"?", parent=self):
            return
        if self.orig and self.orig != name:
            presets.pop(self.orig, None)
        presets[name] = self._defn()
        self.app._store_custom_presets(presets)
        self.app._set_effect(name)
        self.app._set_speed_value(presets[name]["speed"])
        self.destroy()

    def _delete(self):
        if not messagebox.askyesno(eng.APP_NAME, f"Delete your preset \"{self.orig}\"?", parent=self):
            return
        presets = dict(self.app.settings.data.get("custom_presets", {}))
        presets.pop(self.orig, None)
        self.app._store_custom_presets(presets)
        if self.app.effect == self.orig:
            self.app._set_effect("Static")
        self.destroy()


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
        self.inner.bind("<Configure>", lambda e=None: self._sync())
        self.cv.bind("<Configure>", lambda e: self._fit(e.width))
        self.cv.bind("<Map>", lambda e=None: self.after_idle(lambda: self._fit(self.cv.winfo_width())), add="+")
        self.cv.configure(yscrollcommand=self._on_scroll)
        for w in (self, self.cv, self.inner, self.bar):
            w.bind("<Enter>", lambda e=None: self.bind_all("<MouseWheel>", self._wheel), add="+")
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



_TYPE = {9: 10, 10: 11, 11: 11, 12: 12, 13: 13, 14: 13}   # compact scale: body 13, caption 11-12


def spaced(text):
    """Uppercase with a little letter spacing, like the mockup's page titles."""
    return "\u2009".join(text.upper())


def F(size, weight="normal", display=False):
    if weight == "bold":
        return ctk.CTkFont(family=FONT_SEMI, size=_TYPE.get(size, size))
    return ctk.CTkFont(family=FONT_DISPLAY if display else FONT, size=_TYPE.get(size, size), weight=weight)


def icon_label(parent, glyph, fallback, size=16, color=None, **kw):
    font = ctk.CTkFont(family=ICON_FONT, size=size) if ICON_FONT else ctk.CTkFont(family=FONT, size=size)
    return ctk.CTkLabel(parent, text=glyph if ICON_FONT else fallback, font=font,
                        text_color=color or P["TEXT"], **kw)


class NavItem(ctk.CTkFrame):
    """Windows 11 Settings-style navigation item: accent pill, icon, label."""

    def __init__(self, master, name, glyph, fallback, command):
        super().__init__(master, fg_color="transparent", corner_radius=6, height=32, border_width=0)
        self.pack_propagate(False)
        self.icon = icon_label(self, glyph, fallback, size=15, width=20, color=P["MUTED"])
        self.icon.pack(side="left", padx=(10, 0))
        self.text = ctk.CTkLabel(self, text=name, font=F(13), text_color=P["MUTED"], anchor="w")
        self.text.pack(side="left", padx=10, fill="x", expand=True)
        # signature: the open page is marked by one lit LED in your current lighting colour
        self.pill = tk.Canvas(self, width=14, height=14, bg=P["SIDE"], highlightthickness=0)
        self.pill.pack(side="right", padx=(0, 8))
        self._dot = None
        self.on = False
        for w in (self, self.icon, self.text, self.pill):
            # e=None: CustomTkinter 6 can call these without an event
            w.bind("<Button-1>", lambda e=None: command())
            w.bind("<Enter>", lambda e=None: self._hover(True))
            w.bind("<Leave>", lambda e=None: self._hover(False))

    def _hover(self, inside):
        if not self.on and self.winfo_exists():
            self.configure(fg_color=P["HOVER"] if inside else "transparent")
            self.pill.configure(bg=P["HOVER"] if inside else P["SIDE"])

    def set(self, on, led):
        if (on, led) == getattr(self, "_style", None):
            return                                   # unchanged: skip CustomTkinter's redraw
        self._style = (on, led)
        self.on = on
        self.configure(fg_color=P["SEL"] if on else "transparent")
        self.text.configure(text_color=P["TEXT"] if on else P["MUTED"])
        self.icon.configure(text_color=P["TEXT"] if on else P["MUTED"])
        bg = P["SEL"] if on else P["SIDE"]
        self.pill.configure(bg=bg)
        self.pill.delete("all")
        if on:                                       # soft halo + bright core, like an LED behind diffuser
            self.pill.create_oval(2, 2, 12, 12, fill=hexcol(mix(hex2rgb(bg), hex2rgb(led), 0.35)), width=0)
            self.pill.create_oval(4, 4, 10, 10, fill=led, width=0)


def fmt(v, unit="", nd=0, none="—"):
    return none if v is None else f"{v:.{nd}f}{unit}"


def temp_color(t):
    if t is None:
        return P["MUTED"]
    return P["TEXT"] if t < 70 else WARN if t < 85 else BAD      # colour only when it means something


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
    """Your LEDs as one smooth light line: a crisp rounded core in the real colours with a soft glow under it.
    Drawn with Pillow (anti-aliased), so the edges stay clean at any size."""

    def __init__(self, master, n=24, height=40, bg=None, pill=False):
        bg = bg or P["CARD"]
        super().__init__(master, height=height, bg=bg, highlightthickness=0)
        self.n, self.h, self.bgc = n, height, hex2rgb(bg)
        self._img = self._photo = None
        self._size = None
        self._last = None
        self._shown = None                                       # the colours in the picture now
        self.bind("<Configure>", lambda e=None: self._layout())

    def _layout(self):
        w, h = max(self.winfo_width(), 40), self.h
        if self._size == (w, h):
            return
        self._size = (w, h)
        SS = 4                                                   # draw masks 4x larger, then shrink: smooth edges
        core_t = max(3, round(h * 0.14))
        pad = max(4, round(h * 0.3))
        core = Image.new("L", (w * SS, h * SS), 0)
        y0, y1 = (h - core_t) / 2 * SS, (h + core_t) / 2 * SS
        ImageDraw.Draw(core).rounded_rectangle((pad * SS, y0, (w - pad) * SS, y1), radius=core_t * SS / 2, fill=255)
        self._core_mask = core.resize((w, h), Image.LANCZOS)
        glow = Image.new("L", (w, h), 0)
        gt = max(core_t + 2, round(h * 0.42))
        ImageDraw.Draw(glow).rounded_rectangle((pad, (h - gt) / 2, w - pad, (h + gt) / 2), radius=gt / 2, fill=150)
        self._glow_mask = glow.filter(ImageFilter.GaussianBlur(max(2, h * 0.16)))
        self._bg = Image.new("RGB", (w, h), self.bgc)
        self._white = Image.new("RGB", (w, h), (255, 255, 255))
        self.delete("all")
        self._photo = ImageTk.PhotoImage(self._bg)
        self.create_image(0, 0, image=self._photo, anchor="nw")
        self._shown = None
        if self._last is not None:                               # resized: redraw what was last shown
            self.show(self._last)

    def show(self, colors):
        self._last = colors
        if self._photo is None:
            return
        key = tuple(tuple(c) for c in colors or ())
        if key == self._shown:                                   # same colours as the picture: nothing to do
            return
        self._shown = key
        w, h = self._size
        dim = mix(self.bgc, (60, 64, 76), 0.5)
        if APPEARANCE == "light":                                # dimmed LEDs fade into the panel, not to black
            cols = [led_on(c, self.bgc) if max(c) > 0 else dim for c in (colors or [(0, 0, 0)])][:w]
        else:
            cols = [c if max(c) > 20 else dim for c in (colors or [(0, 0, 0)])][:w]
        row = Image.new("RGB", (len(cols), 1))
        row.putdata([tuple(int(v) for v in c) for c in cols])
        lit = row.resize((w, h), Image.BILINEAR)                 # colours blend smoothly from LED to LED
        frame = Image.composite(Image.blend(self._bg, lit, 0.55), self._bg, self._glow_mask)
        frame = Image.composite(Image.blend(lit, self._white, 0.22), frame, self._core_mask)
        self._photo.paste(frame)


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
        if getattr(self, "grid_lines", False):                # muted guides at 25 / 50 / 75 %
            for q in (0.25, 0.5, 0.75):
                y = (h - 3 - (h - 10) * q) * k
                d.line([(0, y), (W, y)], fill=imix(bgc, (255, 255, 255), 0.05) if APPEARANCE != "light"
                        else imix(bgc, (0, 0, 0), 0.07), width=k)
        for vals, color in series:
            rgb = hex2rgb(color)
            fkey = (W, H, color, bgc)
            if fkey not in Sparkline._fill_cache:            # fading fill colour + fade mask, made once
                grad = Image.linear_gradient("L").resize((W, H)).point(lambda v: int((255 - v) * 0.45))
                Sparkline._fill_cache[fkey] = (Image.new("RGB", (W, H), imix(bgc, rgb, 0.18)), grad)
            fill, grad = Sparkline._fill_cache[fkey]
            x0 = w - step * (len(vals) - 1)
            pts = [((x0 + i * step) * k, (h - 3 - (h - 10) * min(v, top) / top) * k) for i, v in enumerate(vals)]
            m = Image.new("L", (W, H), 0)
            ImageDraw.Draw(m).polygon([(pts[0][0], H)] + pts + [(pts[-1][0], H)], fill=255)
            img.paste(fill, (0, 0), ImageChops.multiply(m, grad))
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
        self.bind("<Configure>", lambda e=None: self.set(self.pct, *self.cols))

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
        self.bind("<Configure>", lambda e=None: self.redraw())
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
        self.bind("<Configure>", lambda e=None: self._masks())

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
        if APPEARANCE == "light":                                # dimmed colours fade into the card, not to black
            lit = [tuple(int(v) for v in led_on(c, self.bgc)) for c in colors]
        else:
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
    """Pill selector: the chosen option gets a smooth accent outline and accent text (replaces segmented buttons)."""

    def __init__(self, master, values, command=None, height=32, font=None, selected_color=None, **_ignored):
        super().__init__(master, fg_color="transparent", corner_radius=0, border_width=0)
        self.values, self.command, self.accent = list(values), command, selected_color or DEFAULT_ACCENT
        self.current = self.values[0] if self.values else None
        self.buttons = {}
        for v in self.values:
            b = SmoothButton(self, text=v, height=height - 6, width=max(40, 8 * len(v) + 26), corner_radius=(height - 6) // 2,
                             font=font or F(13), border_width=1, command=lambda x=v: self._click(x))
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
            b.configure(fg_color=P["SEL"] if on else "transparent", hover_color=P["HOVER"], border_width=1 if on else 0,
                        border_color=self.accent, text_color=self.accent if on else P["MUTED"])

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


def custom_preset_art(defn, w=480, h=300) -> Image.Image:
    """Tile picture for a user-made preset: its colours plotted over time (LEDs across, time down)."""
    name = "__art__"
    eng.CUSTOM_PRESETS[name] = defn
    try:
        frames = [eng.compute_colors(name, (0, 0, 0), 100, 60, 48, i * 0.09) for i in range(30)]
    finally:
        eng.CUSTOM_PRESETS.pop(name, None)
    im = Image.new("RGB", (48, 30))
    im.putdata([c for f in frames for c in f])
    im = im.resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(3))
    shade = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(v * 0.45))   # darker at the bottom
    return Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, shade)


class PresetTile(tk.Canvas):
    """Picture tile for a preset effect, with its name on top (like the effect gallery mockup)."""

    def __init__(self, master, name, on_click, height=104, image=None, on_edit=None):
        super().__init__(master, height=height, bg=P["CARD"], highlightthickness=0, cursor="hand2")
        self.name, self.h, self._img, self._size, self.selected = name, height, None, None, False
        self.accent = CYAN
        if image is not None:
            self.src = image
        else:
            try:
                self.src = Image.open(resource(PRESET_FILES[name])).convert("RGB")
            except Exception:
                self.src = None
        if on_edit is not None:                    # your own presets: right-click or double-click to edit
            self.bind("<Button-3>", lambda e=None: on_edit(name))
            self.bind("<Double-Button-1>", lambda e=None: on_edit(name))
        self.bind("<Configure>", lambda e=None: self._render())
        self.bind("<Button-1>", lambda e=None: on_click(name))

    _mask_cache: dict = {}

    @staticmethod
    def _masks(W, H):
        """Rounded-corner mask and selection-ring mask for a tile size (shared by all tiles)."""
        if (W, H) not in PresetTile._mask_cache:
            m = Image.new("L", (W * AA, H * AA), 0)
            ImageDraw.Draw(m).rounded_rectangle((2 * AA, 2 * AA, (W - 2) * AA - 1, (H - 2) * AA - 1), 6 * AA, fill=255)
            r = Image.new("L", (W * AA, H * AA), 0)
            ImageDraw.Draw(r).rounded_rectangle((AA, AA, W * AA - AA - 1, H * AA - AA - 1), 8 * AA, outline=255, width=2 * AA)
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
        fade = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(max(0, v - 110) * 1.6))
        im = Image.composite(Image.new("RGB", (w, h), (8, 9, 11)), im, fade)   # dark band under the name
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
        self.create_text(12, h - 8, text=self.name, fill="#f2f2f4", anchor="sw", font=(FONT_SEMI, 10))

    def select(self, on, accent):
        if (on, accent) != (self.selected, self.accent):
            self.selected, self.accent = on, accent
            self._render()


class EffectTile(tk.Canvas):
    """Effect tile: a live strip of the effect along the top edge, then its icon and name."""
    COLS = 24

    def __init__(self, master, name, on_click, big=False):
        self.h = 84 if big else 36
        super().__init__(master, height=self.h, bg=P["CARD"], highlightthickness=0, cursor="hand2")
        self.name, self.big, self.bars, self.selected = name, big, [], False
        self.accent, self._bg = CYAN, None
        self.n = self.COLS
        self._colors, self._fills = None, []          # last colours shown, and each bar's fill now
        self.bind("<Configure>", lambda e=None: self._layout())
        self.bind("<Button-1>", lambda e=None: on_click(name))

    def _layout(self):
        self.delete("all")
        w = max(self.winfo_width(), 40)
        on = self.selected
        self._bg = ImageTk.PhotoImage(aa_round_rect(w, self.h, 6, P["CARD2"], P["CARD"],
                                                    outline=self.accent if on else P["LINE"], width=1))
        self.create_image(0, 0, image=self._bg, anchor="nw")
        x0, x1 = 10, w - 10                                         # live strip, inset from the corners
        step = (x1 - x0) / self.COLS
        self.bars = [self.create_rectangle(x0 + i * step, 4, x0 + (i + 1) * step + 1, 7, width=0, fill=P["TRACK"])
                     for i in range(self.COLS)]
        self._fills = [P["TRACK"]] * self.COLS
        y = self.h - 30 if self.big else self.h / 2 + 2
        icon = EFFECT_ICONS.get(self.name, "•")
        if self.big:
            self.create_text(14, 24, text=icon, anchor="w", fill=P["FAINT"], font=(FONT, 12))
        self.create_text(14 if self.big else 10, y, text=self.name, anchor="w",
                         fill=P["TEXT"] if (on or self.big) else P["MUTED"],
                         font=(FONT_SEMI if on or self.big else FONT, 11 if self.big else 10))
        self.sub = self.create_text(14, y + 19, text="", anchor="w", fill=P["MUTED"], font=(FONT, 8))
        self._sub()
        if self._colors is not None:                                # laid out again: put the colours back
            self.show(self._colors)

    def _sub(self):
        if hasattr(self, "sub"):
            self.itemconfigure(self.sub, text=EFFECT_INFO.get(self.name, "") if (self.selected and self.big) else "")

    def show(self, colors):
        self._colors = colors
        if not colors:
            return
        light = APPEARANCE == "light"
        card2 = hex2rgb(P["CARD2"]) if light else None
        for i, it in enumerate(self.bars):
            c = colors[int(i * len(colors) / len(self.bars))]
            if light:                                         # dimmed colours fade into the tile, not to black
                fill = hexcol(led_on(c, card2)) if max(c) > 0 else P["TRACK"]
            else:
                fill = hexcol(c) if max(c) > 10 else P["TRACK"]
            if fill != self._fills[i]:                        # only bars whose colour changed are touched
                self._fills[i] = fill
                self.itemconfigure(it, fill=fill)

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
        super().__init__(master, fg_color=P["CARD"], corner_radius=8)
        accent_bar(self)
        self.key = key
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 4))
        # controls are packed before the text so a long device name can never squeeze them
        self.switch = Switch(top, text="", width=44, command=lambda: on_toggle(key, self.switch.get() == 1))
        self.switch.pack(side="right")
        self.edit_btn = SmoothButton(top, text="Customize", width=76, height=26, corner_radius=6, font=F(11),
                                      fg_color=P["BTN"], hover_color=P["BTN_HOVER"], text_color=P["TEXT"],
                                      border_width=1, border_color=P["BTN_LINE"], command=lambda: on_edit(key))
        self.edit_btn.pack(side="right", padx=8)
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=(4, 0))
        ctk.CTkLabel(info, text=name, font=F(13, "bold"), text_color=P["TEXT"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=f"{tname} · {leds} LEDs", font=F(11), text_color=P["FAINT"], anchor="w").pack(fill="x")
        if enabled:
            self.switch.select()
        self.strip = LedStrip(self, n=max(1, min(leds, 32)), height=20)
        self.strip.pack(fill="x", padx=8, pady=(0, 8))


class FanCard(SmoothFrame):
    def __init__(self, master, fan, on_manual, on_reset):
        super().__init__(master, fg_color=P["CARD"], corner_radius=8)
        accent_bar(self)
        self.fid, self.on_manual, self.touched = fan["id"], on_manual, 0
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 0))
        self.spin = tk.Canvas(top, width=28, height=28, bg=P["CARD"], highlightthickness=0)
        self.spin.pack(side="left")
        self.blades = [self.spin.create_arc(2, 2, 26, 26, start=a, extent=50, fill=P["FAINT"], outline="")
                       for a in (0, 120, 240)]
        self.spin.create_oval(10, 10, 18, 18, fill=P["CARD"], outline="")
        self.angle = 0
        self.badge = SmoothButton(top, text="", width=64, height=22, corner_radius=6, font=F(10),
                                   fg_color=P["CARD2"], hover_color=P["BTN_HOVER"], text_color=P["MUTED"],
                                   border_width=1, border_color=P["CARD2"],
                                   command=lambda: on_reset(self.fid))
        self.badge.pack(side="right")
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=10)
        ctk.CTkLabel(info, text=fan["name"], font=F(13, "bold"), text_color=P["TEXT"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=fan["hw"], font=F(11), text_color=P["FAINT"], anchor="w").pack(fill="x")
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=12, pady=(6, 0))
        self.rpm = ctk.CTkLabel(mid, text="—", font=F(20, display=True), text_color=P["TEXT"])
        self.rpm.pack(side="left")
        ctk.CTkLabel(mid, text=" RPM", font=F(11), text_color=P["FAINT"]).pack(side="left", pady=(6, 0))
        self.pct = ctk.CTkLabel(mid, text="", font=ctk.CTkFont(family=MONO, size=11), text_color=P["MUTED"])
        self.pct.pack(side="right")
        self.slider = Slider(self, from_=hwm.FAN_FLOOR, to=100, height=14, fg_color=P["TRACK"],
                                    button_color=P["TEXT"], button_hover_color=slider_hover(P["TEXT"]), command=self._slide)
        self.slider.pack(fill="x", padx=12, pady=(6, 12))

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
            self.badge.configure(text="Manual  ↺", text_color=P["TEXT"], border_color=P["BTN_LINE"])
        else:
            self.badge.configure(text="BIOS" if auto else "Curve", text_color=P["MUTED"], border_color=P["CARD2"])
        speed = (rpm or 0) / 2500
        self.angle = (self.angle + 40 * speed) % 360
        col = P["MUTED"] if rpm else P["FAINT"]
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


_instance_server = None


def _zone_sizes(app) -> dict:
    """The header sizes you set (device key -> {header: LEDs}); {} when there are none (or no settings)."""
    try:
        return dict(app.settings.data.get("zone_sizes") or {})
    except Exception:
        return {}


def plural(n, word, many=None) -> str:
    """plural(1, "fan") -> '1 fan', plural(3, "fan") -> '3 fans'."""
    return f"{n} {word if n == 1 else (many or word + 's')}"


def version_tuple(v) -> tuple:
    """'2.3.10' -> (2, 3, 10); anything unreadable counts as (0,)."""
    import re
    nums = re.findall(r"\d+", str(v))[:3]
    return tuple(int(n) for n in nums) if nums else (0,)


def _bind_instance_port(wait):
    import socket
    end = time.time() + wait
    while True:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.bind(("127.0.0.1", INSTANCE_PORT))
            srv.listen(4)
            return srv
        except OSError:
            srv.close()
            if time.time() >= end:
                return None
            time.sleep(0.25)


def claim_single_instance(app_q, wait=0.0, version=APP_VERSION) -> bool:
    """Become the running copy. Returns False if Central RGB is already running (it is asked to show itself).
    If the running copy is an older version (from 2.3.3 on), it quits properly (fans back to the BIOS) and
    this newer copy takes over, so opening a freshly downloaded update never shows the old window.
    wait: keep trying this many seconds first (used after a restart, while the old copy closes)."""
    import socket
    srv = _bind_instance_port(wait)
    if srv is None:
        try:
            with socket.create_connection(("127.0.0.1", INSTANCE_PORT), timeout=2) as c:
                c.sendall(f"show {version}".encode())
                try:
                    reply = c.recv(16)
                except OSError:
                    reply = b""
        except OSError:
            return True                     # port taken by something else: just run
        if not reply.startswith(b"bye"):
            return False                    # same or newer copy running: it shows itself
        srv = _bind_instance_port(20.0)     # older copy is shutting down: take its place
        if srv is None:
            return False

    global _instance_server
    _instance_server = srv                  # held for the life of the process; freed when it exits

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
                with conn:
                    conn.settimeout(2)
                    msg = conn.recv(64)
                    if not msg.startswith(b"show"):
                        continue
                    parts = msg.split()
                    newer = len(parts) > 1 and version_tuple(parts[1].decode(errors="ignore")) > version_tuple(version)
                    conn.sendall(b"bye" if newer else b"ok")
                    try:
                        conn.recv(1)         # let the caller hang up first, so our port is free right away
                    except OSError:
                        pass
                    if newer:                # a newer Central RGB was opened: hand over to it
                        app_q.put(("tray", "quit"))
                        return
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


LOG_LINES = 500           # the Activity box keeps this many lines (activity.log keeps everything)
QUEUE_BATCH = 200         # queue items handled per _poll_queue tick, so a burst can't hold up the window
LOG_PREFIX = {"ok": "✓ ", "warn": "! ", "bad": "✕ ", "info": "  "}
OVERLAY_FAST_MS = 250     # overlay on, or its page open: follow the game this often
OVERLAY_IDLE_MS = 1000    # overlay off and its page not showing: only check whether that changed
ANIM_MS = 40              # the live previews' frame time (25 fps)
TILE_EVERY = 2            # effect tiles redraw every 2nd frame (12.5 fps), not all of them on the same frame


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
        eng.CUSTOM_PRESETS.clear()
        eng.CUSTOM_PRESETS.update(self.settings.data.get("custom_presets", {}))
        P.update(SOLID)
        ctk.set_appearance_mode(APPEARANCE)
        self.splash_proc = None
        if not background and selftest is None and self.settings.data.get("animations", True) and not eng.is_onefile():
            try:
                self.splash_proc = SplashProcess()          # starts animating while we build
            except Exception:
                self.splash_proc = None
        super().__init__(fg_color=P["BG"])
        self.withdraw()                                     # stays hidden until fully built
        self.title(eng.APP_NAME)
        self.geometry("1120x720")
        self.minsize(1040, 680)
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
        self._switching, self._pending_page = False, None   # page switch in progress / the latest one asked for
        self._pinned, self._restoring = None, False
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
        self.after(20000, self._auto_check_updates)
        self.after(4000, self._report_last_update)

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
            for key in list(THEMES)[1:] + [list(THEMES)[0]]:
                t_sw = time.perf_counter()
                self._switch_theme(key)
                for _ in range(20):
                    self.update()
                    time.sleep(0.01)
                if not all(pg.winfo_exists() for pg in self.pages.values()):
                    raise RuntimeError(f"Pages missing after switching to theme {key}")
                steps.append(f"theme {THEMES[key]['name']}: applied live in {(time.perf_counter() - t_sw - 0.2) * 1000:.0f} ms")
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
            if eng.IS_WIN:                     # the overlay really sits above a game window (in front and behind)
                game = tk.Toplevel(self)
                game.geometry("900x600+80+80")
                game.update()
                ghwnd = int(fpo._u32().GetParent(game.winfo_id()) or game.winfo_id())
                ow = fpo.OverlayWindow(self, self._overlay_colors(), FONT)
                sample = {"name": "test", "fps": 144, "low": 110, "ms": 6.9}
                ow.update_overlay(self.overlay_cfg, sample, {}, ghwnd, True)
                self.update()
                top_in_front = ow.is_topmost()
                ow.update_overlay(self.overlay_cfg, sample, {}, ghwnd, False)
                self.update()
                u, above, h = fpo._u32(), False, ow.hwnd
                for _ in range(400):                         # walk down the z-order from the overlay to the game
                    h = u.GetWindow(h, 2)                    # GW_HWNDNEXT
                    if not h:
                        break
                    if int(h) == ghwnd:
                        above = True
                        break
                ow.destroy()
                game.destroy()
                if not top_in_front or not above:
                    raise RuntimeError(f"Overlay placement failed (topmost while game in front={top_in_front}, "
                                       f"above the game when it's behind={above})")
                steps.append("overlay: on top of the game when it's in front, and just above it when it isn't")
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
        """Minimized: remember it, so the size changes Windows reports on the way back aren't treated as a
        resize (pausing drawing then is what caused the black flash). Windows' own animations play as usual."""
        if e.widget is self and self.state() == "iconic":
            self._was_minimized = True

    def _on_map(self, e):
        if e.widget is self and self._was_minimized:
            self._was_minimized = False
            self._ignore_resize_until = time.time() + 0.6
            self._restore_drawn()

    def _restore_drawn(self):
        """Back from the taskbar. Minimizing shrinks the window to nothing, so Windows throws its picture away and
        puts up an empty (black) one when it comes back, while Tk only draws a moment later, widget by widget; on a
        240 Hz screen every one of those half-drawn moments gets its own frame. So the window is hidden from the
        screen for that moment (Windows 8+), drawn completely in one go, and only then shown."""
        if self._restoring:
            return
        self._restoring = True
        cloaked = fx.cloak(self, True)
        if cloaked:
            self.after(1000, lambda: fx.cloak(self, False))     # never left hidden, whatever happens below
        try:
            self._refresh_page(self.current_page, self.snap)   # pages skip drawing while minimized: catch up first
            self._paint_now()
        except Exception:
            pass
        finally:
            if cloaked:
                fx.dwm_flush()
                fx.cloak(self, False)
            self._restoring = False

    def _paint_now(self):
        """Do all the drawing that is waiting, right now. Tk answers Windows' requests to repaint at once but draws
        later, widget by widget, spread over several screen frames; this does it all in one go."""
        if self._hidden():
            return
        try:
            self.update()
        except tk.TclError:
            pass

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
        if self._was_minimized or time.time() < getattr(self, "_ignore_resize_until", 0) or self.state() == "iconic":
            self._size_seen = (e.width, e.height)
            return
        size = (e.width, e.height)
        if self._size_seen is None or size == self._size_seen:
            self._size_seen = size
            return
        self._size_seen = size
        if not self._resize_job:
            # resize starting: pin the visible page at its current size so it isn't laid out again for every
            # pixel of the drag (the window frame follows the mouse freely); other pages leave the layout
            page = self.pages.get(self.current_page)
            if page is not None and page.winfo_manager() == "place":
                page.place_configure(relwidth=0, relheight=0, width=page.winfo_width(), height=page.winfo_height())
                self._pinned = page
            for n, pg in self.pages.items():
                if n != self.current_page and pg.winfo_manager():
                    pg.place_forget()
        else:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(140, self._resize_done)

    def _resize_done(self):
        """Resize finished: lay the page out once at the new size, shown in a single repaint."""
        self._resize_job = None
        page = self.pages.get(self.current_page)
        pinned, self._pinned = self._pinned, None
        h = fx.freeze(self._holder)
        try:
            if page is not None:
                page.place_configure(relwidth=1, relheight=1, width=0, height=0)
            # the page pinned when the resize began, if another page was opened meanwhile: back to full size,
            # or it would reappear later at the old window size
            if pinned is not None and pinned is not page and pinned.winfo_manager() == "place":
                pinned.place_configure(relwidth=1, relheight=1, width=0, height=0)
            self.update_idletasks()
        finally:
            fx.thaw(h)
        self._paint_now()

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
        # ends at exactly 100 % (fx.OPAQUE): a window left see-through at 254/255 stays "layered", which smears
        # when scrolling and redraws slowly. Reaching 100 % makes Tk redraw the whole window once (cleared to the
        # panel colour), so that redraw is done at once instead of widget by widget.
        a = min(fx.OPAQUE, a + 0.12)
        try:
            self.attributes("-alpha", a)
        except tk.TclError:
            return
        if a < fx.OPAQUE:
            self.after(16, lambda: self._fade_in(a))
        else:
            self._paint_now()

    def _window_effects(self):
        fx.dark_titlebar(self, APPEARANCE != "light")      # light mode: light title bar
        fx.titlebar_colors(self, P["BG"], P["LINE"], P["TEXT"])   # seamless title bar on Windows 11
        fx.panel_background(self, P["BG"])     # anything Windows clears before Tk draws shows the panel colour

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
        sel = P["SEL"] if APPEARANCE == "light" else P["CARD2"]   # light: CARD2 is too close to CARD to see
        s.map("Dark.Treeview", background=[("selected", sel)], foreground=[("selected", P["TEXT"])])
        s.layout("Dark.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        s.configure("Dark.Vertical.TScrollbar", background=P["CARD2"], troughcolor=P["CARD"], borderwidth=0,
                    arrowcolor=P["MUTED"], relief="flat")

    # ---------------------------------------------------------------- layout helpers
    def card(self, parent, **kw):
        c = SmoothFrame(parent, fg_color=P["CARD"], corner_radius=RADIUS, **kw)
        accent_bar(c)
        return c

    def label(self, parent, text, size=12, weight="normal", color=None, **kw):
        kw.setdefault("font", F(size, weight))
        return ctk.CTkLabel(parent, text=text, text_color=color or P["TEXT"], **kw)

    def caption(self, parent, text):
        """Group heading: sentence case, small, secondary colour."""
        return ctk.CTkLabel(parent, text=text, font=F(12, "bold"), text_color=P["MUTED"], anchor="w")

    def setting_row(self, parent, glyph, fallback, title, desc, make_control):
        """Windows 11 Settings row: icon, title and description on the left, a control on the right."""
        row = SmoothFrame(parent, fg_color=P["CARD"], corner_radius=8, height=52)
        row.pack(fill="x", pady=(0, 4))
        row.pack_propagate(False)
        icon_label(row, glyph, fallback, size=15, width=20, color=P["MUTED"]).pack(side="left", padx=(16, 12))
        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        self.label(txt, title, 13, anchor="w").pack(fill="x")
        if desc:
            self.label(txt, desc, 11, color=P["FAINT"], anchor="w", justify="left", wraplength=520).pack(fill="x")
        ctl = make_control(row)
        ctl.pack(side="right", padx=16)
        return row, ctl

    def primary(self, parent, text, cmd, **kw):
        b = ctk.CTkButton(parent, text=text, command=cmd, fg_color=self.accent, hover_color=self.accent,
                          text_color=on_color(self.accent), font=F(13, "bold"), corner_radius=kw.pop("corner_radius", 6), **kw)
        self.accent_widgets.append(("button", b))
        return b

    def secondary(self, parent, text, cmd, **kw):
        return SmoothButton(parent, text=text, command=cmd, fg_color=P["BTN"], hover_color=P["BTN_HOVER"],
                            text_color=P["TEXT"], font=kw.pop("font", F(13)), corner_radius=kw.pop("corner_radius", 6),
                            border_width=1, border_color=P["BTN_LINE"], **kw)

    def slider_row(self, parent, label, value, cmd, lo=0, hi=100, unit="%"):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        self.label(top, label, 12, color=P["MUTED"]).pack(side="left")
        val = self.label(top, f"{value}{unit}", 12, color=P["TEXT"], font=ctk.CTkFont(family=MONO, size=11))
        val.pack(side="right")
        s = Slider(row, from_=lo, to=hi, number_of_steps=hi - lo, height=16, progress_color=self.accent,
                          button_color=self.accent, button_hover_color=slider_hover(self.accent), fg_color=P["TRACK"])
        s.set(value)
        s.configure(command=lambda v: (val.configure(text=f"{int(v)}{unit}"), cmd(int(v))))
        s.pack(fill="x", pady=(4, 0))
        s.value_label = val
        self.accent_widgets.append(("slider", s))
        return row, s

    def header(self, parent, title, subtitle, right=None):
        h = ctk.CTkFrame(parent, fg_color="transparent")
        h.pack(fill="x", pady=(0, 16))
        txt = ctk.CTkFrame(h, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        img = None
        if img is not None:
            ctk.CTkLabel(txt, text="", image=img, anchor="w").pack(fill="x")
        else:
            ctk.CTkLabel(txt, text=title, font=F(20, display=True), text_color=P["TEXT"], anchor="w").pack(fill="x")
        if subtitle:
            self.label(txt, subtitle.rstrip("."), 12, color=P["MUTED"], anchor="w").pack(fill="x")
        return h

    # ---------------------------------------------------------------- build
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color=P["SIDE"], corner_radius=0, width=220)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.pack_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(16, 20))
        self.logo = tk.Canvas(brand, width=24, height=24, bg=P["SIDE"], highlightthickness=0)
        self.logo.pack(side="left")
        if self._icon_img is not None:
            self._logo_img = ImageTk.PhotoImage(self._icon_img.resize((24, 24), Image.LANCZOS))
            self.logo.create_image(12, 12, image=self._logo_img)
        self.label(brand, "Central RGB", 13, "bold", anchor="w").pack(side="left", padx=(10, 0))
        self.label(brand, APP_VERSION, 11, color=P["FAINT"], anchor="e",
                   font=ctk.CTkFont(family=MONO, size=10)).pack(side="right")

        self.nav = {}
        for name, glyph, fallback in NAV:
            item = NavItem(side, name, glyph, fallback, lambda n=name: self.show_page(n))
            item.pack(fill="x", padx=8, pady=(0, 2))
            self.nav[name] = item

        st = ctk.CTkFrame(side, fg_color="transparent")
        st.pack(side="bottom", fill="x", padx=16, pady=16)
        self.status_rows = {}
        for key, label in (("rgb", "Lighting"), ("hw", "Sensors")):
            r = ctk.CTkFrame(st, fg_color="transparent")
            r.pack(fill="x", pady=3)
            dot = tk.Canvas(r, width=6, height=6, bg=P["SIDE"], highlightthickness=0)
            dot.pack(side="left", pady=(6, 0), anchor="n")
            oval = dot.create_oval(0, 0, 6, 6, fill=WARN, width=0)
            col = ctk.CTkFrame(r, fg_color="transparent")
            col.pack(side="left", padx=8, fill="x", expand=True)
            self.label(col, label, 11, color=P["MUTED"], anchor="w").pack(fill="x")
            sub = self.label(col, "Starting…", 10, color=P["FAINT"], anchor="w", justify="left", wraplength=170)
            sub.pack(fill="x")
            self.status_rows[key] = (dot, oval, sub)

        if self.splash is not None:
            self.splash.keep_on_top()
        holder = ctk.CTkFrame(self, fg_color=P["BG"], corner_radius=0)
        holder.grid(row=0, column=1, sticky="nsew", padx=(20, 20), pady=(16, 16))
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
        top.pack(fill="x", padx=16, pady=(16, 4))
        yield
        txt = ctk.CTkFrame(top, fg_color="transparent")
        yield
        txt.pack(side="left", fill="x", expand=True)
        yield
        self.label(txt, "Your lighting", 11, color=P["FAINT"], anchor="w").pack(fill="x")
        self.home_effect = ctk.CTkLabel(txt, text=self.effect, font=F(16, "bold"), text_color=P["TEXT"], anchor="w")
        self.home_effect.pack(fill="x")
        yield
        hero_sub = self.label(txt, "", 12, color=P["MUTED"], anchor="w")
        hero_sub.pack(fill="x")
        yield
        yield
        self.primary(top, "Apply lighting", self._apply_all, height=32, width=128).pack(side="right", anchor="n")
        yield
        # the one bright thing on the page: your LEDs, live
        self.home_strip = LedStrip(hero, n=40, height=48)
        yield
        self.home_strip.pack(fill="x", padx=12, pady=(4, 4))
        self.home_status = self.label(hero, "Starting…", 11, color=P["FAINT"], anchor="w")
        self.home_status.pack(fill="x", padx=16, pady=(0, 12))

        # tiles
        yield
        grid = ctk.CTkFrame(p, fg_color="transparent")
        yield
        grid.pack(fill="x", pady=(12, 0))
        yield
        self.home_tiles = {"Lighting": (self.home_effect, hero_sub)}
        yield
        specs = [("Fans", "\uec4a", "✺", "Fans"),
                 ("Processor", "\ue950", "◔", "Monitor"), ("Graphics", "\ue7f4", "▣", "Monitor")]
        yield
        for i, (title, glyph, fb, page) in enumerate(specs):
            c = self.card(grid, height=104)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            c.pack_propagate(False)
            grid.grid_columnconfigure(i, weight=1, uniform="ht")
            hdr = ctk.CTkFrame(c, fg_color="transparent")
            hdr.pack(fill="x", padx=16, pady=(12, 0))
            icon_label(hdr, glyph, fb, size=13, color=P["FAINT"]).pack(side="left")
            self.label(hdr, title, 12, color=P["MUTED"]).pack(side="left", padx=8)
            big = ctk.CTkLabel(c, text="—", font=F(22, display=True), text_color=P["TEXT"], anchor="w")
            big.pack(fill="x", padx=16, pady=(4, 0))
            sub = self.label(c, "", 11, color=P["FAINT"], anchor="w")
            sub.pack(fill="x", padx=16)
            self.home_tiles[title] = (big, sub)
            for w in (c, hdr, big, sub):
                w.bind("<Button-1>", lambda e, pg=page: self.show_page(pg))
                w.configure(cursor="hand2")
        yield
        self.home_light_strip = LedStrip(grid, n=24, height=8)     # kept for the animator, not shown

        # quick actions
        yield
        self.caption(p, "Quick actions").pack(fill="x", pady=(20, 8))
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
        self.home_status.configure(text=(f"{plural(len(rows), 'RGB device')} · {plural(sum(r[3] for r in rows), 'LED')} · {plural(len(fans), 'fan')}"
                                         if self.connected else "Connecting to your RGB hardware…"))
        big, sub = self.home_tiles["Lighting"]
        big.configure(text=self.effect)
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
        h = self.header(p, "Lighting", "Pick a color and an effect. Changes go live on every selected device")
        yield
        self.light_scope = "All"
        yield
        self.apply_btn = self.primary(h, "Apply to all devices", self._apply_all, height=32, width=164)
        self.apply_btn.pack(side="right", anchor="n", pady=(4, 0))
        self.secondary(h, "Save to hardware", lambda: self._bg(self._save_hw), height=32, width=132).pack(
            side="right", anchor="n", pady=(4, 0), padx=(0, 8))
        yield
        # device scope + live strip share one row: what you edit, and what it looks like right now
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x", pady=(0, 12))
        self.chip_row = ctk.CTkFrame(top, fg_color="transparent")
        self.chip_row.pack(fill="x")
        yield
        self.chips = {}
        yield
        self._build_chips()

        yield
        prev = self.card(p, height=44)
        yield
        prev.pack(fill="x", pady=(0, 12))
        prev.pack_propagate(False)
        yield
        self.label(prev, "Live", 11, color=P["FAINT"], anchor="w").pack(side="left", padx=(16, 8))
        self.preview_label = self.label(prev, "", 12, "bold", anchor="w", width=96)
        self.preview_label.pack(side="left")
        yield
        self.preview = LedStrip(prev, n=48, height=28)
        self.preview.pack(side="left", fill="x", expand=True, padx=(8, 12))
        self.preview_track = tk.Canvas(prev, height=1, bg=P["CARD"], highlightthickness=0)   # kept, not shown

        yield
        body = ctk.CTkFrame(p, fg_color="transparent")
        yield
        body.pack(fill="both", expand=True)
        yield
        body.grid_columnconfigure(1, weight=1)
        yield
        body.grid_rowconfigure(0, weight=1)

        yield
        cc = self.card(body, width=232)
        yield
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        yield
        self.caption(cc, "Color").pack(fill="x", padx=16, pady=(12, 8))
        yield
        self.wheel = ColorWheel(cc, size=176, command=lambda rgb: self._set_color(rgb, from_wheel=True))
        yield
        self.wheel.pack(padx=16)
        yield
        sw = tk.Canvas(cc, height=44, width=200, bg=P["CARD"], highlightthickness=0)
        yield
        sw.pack(padx=16, pady=(12, 0), anchor="w")
        yield
        step = 200 / len(SWATCHES)
        yield
        for row, k in ((0, 0.0), (1, 0.42)):                       # vivid row, then a softer row
            for i, c in enumerate(SWATCHES):
                col = tuple(int(v) for v in mix(c, (230, 230, 240), k)) if k else c
                x = step * i + step / 2
                it = sw.create_oval(x - 8, 3 + row * 22, x + 8, 19 + row * 22, fill=hexcol(col), outline=swatch_outline(col), width=2)
                sw.tag_bind(it, "<Button-1>", lambda e=None, cl=col: self._set_color(cl))
                sw.tag_bind(it, "<Enter>", lambda e=None, i2=it: sw.itemconfigure(i2, outline=P["TEXT"]))
                sw.tag_bind(it, "<Leave>", lambda e=None, i2=it, cl=col: sw.itemconfigure(i2, outline=swatch_outline(cl)))
        yield
        hexrow = ctk.CTkFrame(cc, fg_color="transparent")
        yield
        hexrow.pack(fill="x", padx=16, pady=(12, 0))
        yield
        self.swatch = tk.Canvas(hexrow, width=24, height=24, bg=P["CARD"], highlightthickness=0)
        yield
        self.swatch.pack(side="left")
        yield
        self.swatch_item = self.swatch.create_oval(1, 1, 23, 23, fill="#000", width=0)
        yield
        mono = ctk.CTkFont(family=MONO, size=11)
        self.hex_entry = ctk.CTkEntry(hexrow, width=100, height=28, corner_radius=6, font=mono,
                                      fg_color=P["CARD2"], border_width=1, border_color=P["LINE"], text_color=P["TEXT"],
                                      justify="center")
        yield
        self.hex_entry.pack(side="left", padx=(8, 0), fill="x", expand=True)
        yield
        self.hex_entry.bind("<Return>", self._hex_entered)
        yield
        self.hex_entry.bind("<FocusOut>", self._hex_entered)
        yield
        rgbrow = ctk.CTkFrame(cc, fg_color="transparent")
        yield
        rgbrow.pack(fill="x", padx=16, pady=(8, 16))
        yield
        self.rgb_entries = []
        yield
        for i, ch in enumerate("RGB"):
            rgbrow.grid_columnconfigure(i, weight=1, uniform="rgb")
            cell = ctk.CTkFrame(rgbrow, fg_color="transparent")
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            self.label(cell, ch, 11, color=P["FAINT"], width=12).pack(side="left", padx=(0, 4))
            e = ctk.CTkEntry(cell, width=40, height=28, corner_radius=6, font=mono, fg_color=P["CARD2"],
                             border_width=1, border_color=P["LINE"], text_color=P["TEXT"], justify="center")
            e.pack(side="left", fill="x", expand=True)
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
        ec.pack(fill="both", expand=True)
        yield
        self.caption(ec, "Effect").pack(fill="x", padx=16, pady=(12, 8))
        yield
        grid = ctk.CTkFrame(ec, fg_color="transparent")
        yield
        grid.pack(fill="x", padx=14, pady=(0, 12))
        yield
        self.tiles = {}
        yield
        for i, name in enumerate(eng.BASIC_EFFECTS):
            t = EffectTile(grid, name, self._set_effect)
            t.grid(row=0, column=i, sticky="nsew", padx=2)
            grid.grid_columnconfigure(i, weight=1, uniform="e")
            self.tiles[name] = t
        yield
        self.caption(ec, "Presets").pack(fill="x", padx=16, pady=(0, 8))
        yield
        # 16 presets: about two and a half rows show, the rest scroll into view
        scroll = LightScroll(ec, height=260)
        pg = scroll.inner
        yield
        scroll.pack(fill="both", expand=True, padx=(14, 4), pady=(0, 12))
        yield
        for i, name in enumerate(eng.PRESET_EFFECTS):
            t = PresetTile(pg, name, self._set_effect, height=76)
            t.grid(row=i // 4, column=i % 4, sticky="nsew", padx=2, pady=2)
            pg.grid_columnconfigure(i % 4, weight=1, uniform="p")
            self.tiles[name] = t
            yield                                  # one tile per build step
        self.preset_grid = pg
        self._custom_tiles = []
        self._fill_custom_tiles()

        yield
        st = self.settings["state"]
        yield
        # brightness and speed live with the colour: everything that changes how the light looks, in one column
        sl = ctk.CTkFrame(cc, fg_color="transparent")
        sl.pack(side="bottom", fill="x", padx=16, pady=(0, 16))
        r1, self.bright = self.slider_row(sl, "Brightness", st.get("brightness", 100), lambda v: self._state_changed())
        yield
        r1.pack(fill="x", pady=(0, 12))
        yield
        r2, self.speed = self.slider_row(sl, "Speed", st.get("speed", 50), lambda v: self._state_changed())
        yield
        r2.pack(fill="x")
        ctk.CTkFrame(cc, height=1, fg_color=P["LINE"]).pack(side="bottom", fill="x", padx=16, pady=(0, 16))

    # ---- device chips: edit all devices at once, or one kind of device
    def _build_chips(self):
        for w in self.chip_row.winfo_children():
            w.destroy()
        self.chips = {}
        counts = {}
        for _, t, _, _ in self.device_rows:
            counts[t] = counts.get(t, 0) + 1
        items = [("All", f"All devices  {len(self.device_rows)}")] + \
                [(t, f"{t}  {n}" if n > 1 else t) for t, n in counts.items()]
        if self.light_scope not in dict(items):
            self.light_scope = "All"
        for key, text in items:
            b = SmoothButton(self.chip_row, text=text, height=28, width=max(52, 7 * len(text) + 24), corner_radius=6,
                             font=F(12), border_width=1,
                              command=lambda k=key: self._set_scope(k))
            b.pack(side="left", padx=(0, 4))
            self.chips[key] = b
        self._style_chips()

    def _style_chips(self):
        for k, b in self.chips.items():
            on = k == self.light_scope
            b.configure(fg_color=P["CARD2"] if on else P["BG"], hover_color=P["CARD"],
                        border_color=P["BTN_LINE"] if on else P["BG"], text_color=P["TEXT"] if on else P["MUTED"])

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
        bar.pack(fill="x", pady=(0, 12))
        yield
        self.secondary(bar, "Rescan", lambda: self._bg(self._full_rescan), height=28, width=76, font=F(12)).pack(side="left")
        yield
        self.secondary(bar, "All on", lambda: self._set_all_devices(True), height=28, width=64, font=F(12)).pack(side="left", padx=4)
        yield
        self.secondary(bar, "All off", lambda: self._set_all_devices(False), height=28, width=64, font=F(12)).pack(side="left")
        yield
        self.dev_summary = self.label(bar, "", 11, color=P["FAINT"])
        yield
        self.dev_summary.pack(side="right")
        yield
        # warning when vendor RGB apps are holding the hardware, with a button to close them
        self.conflict_bar = SmoothFrame(p, fg_color=WARN_BG, corner_radius=8)
        cb_txt = ctk.CTkFrame(self.conflict_bar, fg_color="transparent")
        self.conflict_btn = ctk.CTkButton(self.conflict_bar, text="Close them", width=110, height=32, corner_radius=16,
                                          font=F(13, "bold"), fg_color=WARN, hover_color=WARN_TEXT if APPEARANCE == "light" else "#ffd166",
                                          text_color=ON_STATUS,
                                          command=self._close_conflicts)
        self.conflict_btn.pack(side="right", padx=14, pady=12)
        cb_txt.pack(side="left", fill="x", expand=True, padx=16, pady=10)
        self.conflict_title = self.label(cb_txt, "", 13, "bold", anchor="w", color=WARN_TEXT)
        self.conflict_title.pack(fill="x")
        self.label(cb_txt, "They can hide devices from Central RGB (on MSI boards, Mystic Light holds the motherboard "
                           "and RAM lighting).", 12, color=P["MUTED"], anchor="w", justify="left",
                   wraplength=760).pack(fill="x")
        yield
        # warning when RGB RAM or an RGB mouse is installed but OpenRGB didn't report it, with the exact reason(s)
        self.missing_bar = SmoothFrame(p, fg_color=WARN_BG, corner_radius=8)
        self.missing_title = self.label(self.missing_bar, "", 13, "bold", anchor="w", color=WARN_TEXT)
        self.missing_title.pack(fill="x", padx=16, pady=(10, 0))
        self.missing_text = self.label(self.missing_bar, "", 12, color=P["MUTED"], anchor="w", justify="left",
                                       wraplength=780)
        self.missing_text.pack(fill="x", padx=16, pady=(2, 10))
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
        self._update_missing_bar(getattr(self, "_missing", None))

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
            c.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0 if i % 2 == 0 else 6, 6 if i % 2 == 0 else 0), pady=(0, 12))
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
        fxm = ctk.CTkOptionMenu(controls, values=eng.EFFECTS + list(eng.CUSTOM_PRESETS), height=32, corner_radius=6, font=F(13), fg_color=P["CARD2"],
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
            it = sw.create_rectangle(i * 34, 3, i * 34 + 26, 27, fill=hexcol(c), outline=swatch_outline(c), width=2)
            sw.tag_bind(it, "<Button-1>", lambda e, col=c: (choose(color=list(col)) if state["effect"] in eng.USES_COLOR
                                                            else (fxm.set("Static"), choose(color=list(col), effect="Static"))))
        self.label(controls, "Colors apply to the Static and Breathing effects.", 12, color=P["FAINT"], anchor="w").pack(fill="x", pady=(0, 10))
        r1, _b = self.slider_row(controls, "Brightness", int(state["brightness"]), lambda v: choose(brightness=v))
        r1.pack(fill="x", pady=4)
        r2, _s = self.slider_row(controls, "Speed", int(state["speed"]), lambda v: choose(speed=v))
        r2.pack(fill="x", pady=4)
        mode.configure(command=lambda v: commit())
        self._header_controls(controls, key)

    def _header_controls(self, parent, key):
        """Connected LEDs: for each ARGB header / LED strip port of this device, how many LEDs are plugged in.
        OpenRGB can't count them, and a header left at 0 keeps fans and strips on it dark."""
        zones = self.engine.zones(key)
        if not zones:
            return
        self.label(parent, "Connected LEDs", 13, color=P["MUTED"], anchor="w").pack(fill="x", pady=(14, 0))
        self.label(parent, "How many LEDs are plugged into each header. Most RGB fans have 8 to 18 each; "
                           "add them up if they're chained.", 12, color=P["FAINT"], anchor="w", justify="left",
                   wraplength=300).pack(fill="x", pady=(0, 6))
        saved = self.settings.data.get("zone_sizes", {}).get(key, {})
        for z in zones:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=2)
            self.label(row, z["name"], 13, anchor="w").pack(side="left")
            val = tk.IntVar(value=int(saved.get(z["name"], z["leds"])))
            job = {"id": None}

            def push(z=z, val=val, job=job):
                job["id"] = None
                try:
                    n = max(z["min"], min(z["max"], int(val.get())))
                except (tk.TclError, ValueError):
                    return
                val.set(n)
                self._bg(lambda: self._set_header(key, z, n))

            def later(z=z, val=val, job=job, push=push):
                if job["id"]:
                    self.after_cancel(job["id"])
                job["id"] = self.after(500, push)            # one write after you stop clicking or typing

            def step(d, z=z, val=val, later=later):
                try:
                    val.set(max(z["min"], min(z["max"], int(val.get()) + d)))
                except (tk.TclError, ValueError):
                    val.set(z["leds"])
                later()

            self.secondary(row, "+", lambda st=step: st(1), height=28, width=28).pack(side="right")
            ent = ctk.CTkEntry(row, textvariable=val, width=52, height=28, corner_radius=6, justify="center",
                               fg_color=P["CARD2"], border_color=P["LINE"], text_color=P["TEXT"], font=F(13))
            ent.pack(side="right", padx=4)
            ent.bind("<Return>", lambda e=None, pu=push: pu())
            ent.bind("<FocusOut>", lambda e=None, pu=push: pu())
            self.secondary(row, "−", lambda st=step: st(-1), height=28, width=28).pack(side="right")
            self.label(row, f"up to {z['max']}", 11, color=P["FAINT"]).pack(side="right", padx=(0, 8))

    def _set_header(self, key, zone, n):
        """Background thread: resize one header in OpenRGB, remember it, refresh the device list."""
        try:
            got = self.engine.resize_zone(key, zone["index"], n)
        except Exception as e:
            self.log(f"Couldn't set {zone['name']} to {n} LEDs: {e}", "bad")
            return
        if got is None:
            return
        sizes = dict(self.settings.data.get("zone_sizes") or {})
        sizes[key] = dict(sizes.get(key) or {}, **{zone["name"]: got})
        self.settings["zone_sizes"] = sizes
        self.log(f"{zone['name']} set to {got} LEDs.", "ok")
        self._rescan(quiet=True)
        self._check_missing()

    def _update_dev_summary(self):
        ex = set(self.settings["excluded"])
        on = sum(1 for r in self.device_rows if r[0] not in ex)
        self.dev_summary.configure(text=f"{on} of {len(self.device_rows)} active · {sum(r[3] for r in self.device_rows)} LEDs")

    # ---------------------------------------------------------------- Fans
    def _page_fans(self, p):
        h = self.header(p, "Fans", "Pick a profile or draw your own curve. Fans always speed up if things get too hot.")
        yield
        self.fan_seg = PillSwitcher(p, values=hwm.PROFILES, command=self._set_fan_profile, height=32,
                                              font=F(12), corner_radius=6, fg_color=P["CARD"],
                                              unselected_color=P["CARD"], unselected_hover_color=P["CARD2"],
                                              selected_color=self.accent, selected_hover_color=self.accent,
                                              text_color=P["TEXT"])
        yield
        self.fan_seg.pack(fill="x", pady=(0, 12))
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
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        yield
        row = ctk.CTkFrame(cc, fg_color="transparent")
        yield
        row.pack(fill="x", padx=16, pady=(12, 0))
        yield
        self.label(row, "Fan curve · CPU temperature", 12, color=P["MUTED"]).pack(side="left")
        yield
        self.curve_hint = self.label(row, "", 10, color=P["FAINT"])
        yield
        self.curve_hint.pack(side="right")
        yield
        self.curve = CurveEditor(cc, self._curve_changed, height=196)
        yield
        self.curve.pack(fill="x", padx=12, pady=(4, 12))

        yield
        tc = self.card(top, width=232)
        yield
        tc.grid(row=0, column=1, sticky="nsew")
        yield
        self.label(tc, "Temperatures", 12, color=P["MUTED"], anchor="w").pack(fill="x", padx=16, pady=(12, 4))
        yield
        self.fan_temp_labels = {}
        yield
        for key, name in (("cpu_temp", "CPU"), ("gpu_temp", "GPU")):
            r = ctk.CTkFrame(tc, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=2)
            self.label(r, name, 11, color=P["FAINT"]).pack(side="left", anchor="s", pady=(0, 6))
            v = ctk.CTkLabel(r, text="—", font=F(26, display=True), text_color=P["TEXT"])
            v.pack(side="right")
            self.fan_temp_labels[key] = v
        yield
        self.fan_note = self.label(tc, "", 11, color=P["FAINT"], wraplength=200, justify="left", anchor="w")
        yield
        self.fan_note.pack(fill="x", padx=16, pady=(8, 12))

        yield
        _sc_fan_area = LightScroll(p, bg=P["BG"])
        self.fan_area = _sc_fan_area.inner
        yield
        _sc_fan_area.pack(fill="both", expand=True, pady=(12, 0))
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
                c.grid(row=i // 3, column=i % 3, sticky="ew", pady=(0, 12),
                       padx=(0 if i % 3 == 0 else 6, 0 if i % 3 == 2 else 6))
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
        self.pawn_bar = SmoothFrame(p, fg_color=WARN_BG, corner_radius=8)
        self.primary(self.pawn_bar, "Install PawnIO", self._install_pawnio, height=32, width=140).pack(side="right", padx=14, pady=12)
        self.label(self.pawn_bar, "CPU temperatures (and fan control) need the free PawnIO driver, which isn't installed.",
                   13, color=WARN_TEXT, anchor="w").pack(side="left", fill="x", expand=True, padx=16, pady=12)
        if eng.IS_WIN and not eng.pawnio_installed():
            self.pawn_bar.pack(fill="x", pady=(0, 12))
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
        """Compact stat card: label, the one big number, three small readings. No mini chart."""
        c = self.card(parent, height=112)
        c.pack_propagate(False)
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.label(top, title, 12, color=P["MUTED"]).pack(side="left")
        name = self.label(top, "", 10, color=P["FAINT"])
        name.pack(side="right")
        mid = ctk.CTkFrame(c, fg_color="transparent")
        mid.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        big = ctk.CTkLabel(mid, text="—", font=F(26, display=True), text_color=P["TEXT"], anchor="sw", width=84)
        big.pack(side="left", anchor="s")
        ring = Ring(mid, size=8)                          # kept for the refresher; not shown
        stats = ctk.CTkFrame(mid, fg_color="transparent")
        stats.pack(side="right", fill="x", expand=True, padx=(16, 0), anchor="s")
        rows = {}
        mono = ctk.CTkFont(family=MONO, size=11)
        for k in ("a", "b", "c"):
            r = ctk.CTkFrame(stats, fg_color="transparent")
            r.pack(fill="x")
            l = self.label(r, "", 11, color=P["FAINT"], height=18)
            l.pack(side="left")
            v = self.label(r, "—", 11, font=mono, height=18)
            v.pack(side="right")
            rows[k] = (l, v)
        spark = Sparkline(c, height=4)                    # kept for the refresher; not shown
        return {"card": c, "ring": ring, "rows": rows, "spark": spark, "name": name, "big": big}

    def _build_overview(self, p):
        g = ctk.CTkFrame(p, fg_color="transparent")
        g.pack(fill="both", expand=True)
        for i in range(3):
            g.grid_columnconfigure(i, weight=1, uniform="o")
        self.g_cpu = self._gauge_card(g, "Processor")
        self.g_gpu = self._gauge_card(g, "Graphics")
        self.g_ram = self._gauge_card(g, "Memory")
        for i, gc in enumerate((self.g_cpu, self.g_gpu, self.g_ram)):
            gc["card"].grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))

        # the main chart: processor load leads in the accent, graphics follows in grey
        lc = self.card(g)
        lc.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0), padx=(0, 6))
        lt = ctk.CTkFrame(lc, fg_color="transparent")
        lt.pack(fill="x", padx=16, pady=(12, 0))
        self.label(lt, "Load · last minute", 12, color=P["MUTED"]).pack(side="left")
        for name, col in (("Graphics", PURPLE), ("Processor", CYAN)):
            self.label(lt, name, 11, color=P["MUTED"]).pack(side="right", padx=(4, 12 if name == "Graphics" else 12))
            dot = tk.Canvas(lt, width=8, height=8, bg=P["CARD"], highlightthickness=0)
            dot.create_oval(0, 0, 8, 8, fill=col, width=0)
            dot.pack(side="right", pady=(2, 0))
        self.load_chart = Sparkline(lc, height=260, color=CYAN)
        self.load_chart.grid_lines = True
        self.load_chart.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        side = ctk.CTkFrame(g, fg_color="transparent")
        side.grid(row=1, column=2, sticky="nsew", pady=(12, 0), padx=(6, 0))
        mono = ctk.CTkFont(family=MONO, size=11)

        net = self.card(side)
        net.pack(fill="x")
        nt = ctk.CTkFrame(net, fg_color="transparent")
        nt.pack(fill="x", padx=16, pady=(12, 0))
        self.label(nt, "Network", 12, color=P["MUTED"]).pack(side="left")
        nr = ctk.CTkFrame(net, fg_color="transparent")
        nr.pack(fill="x", padx=16, pady=(4, 0))
        self.net_down = self.label(nr, "—", 12, font=mono)
        self.net_down.pack(side="left")
        self.net_up = self.label(nr, "—", 12, color=P["MUTED"], font=mono)
        self.net_up.pack(side="right")
        self.net_spark = Sparkline(net, height=40, color=CYAN)
        self.net_spark.pack(fill="x", padx=12, pady=(4, 12))

        dk = self.card(side)
        dk.pack(fill="x", pady=(12, 0))
        top = ctk.CTkFrame(dk, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 0))
        self.label(top, "Storage", 12, color=P["MUTED"]).pack(side="left")
        io = ctk.CTkFrame(top, fg_color="transparent")
        io.pack(side="right")
        self.disk_r = self.label(io, "R —", 11, color=P["MUTED"], font=mono)
        self.disk_r.pack(side="left")
        self.disk_w = self.label(io, "W —", 11, color=P["MUTED"], font=mono)
        self.disk_w.pack(side="left", padx=(8, 0))
        self.disk_box = ctk.CTkFrame(dk, fg_color="transparent")
        self.disk_box.pack(fill="x", padx=16, pady=(4, 12))
        self.disk_rows = {}
        self.disk_chart = Sparkline(dk, height=4, color=CYAN)          # kept for the refresher; not shown

        sy = self.card(side)
        sy.pack(fill="both", expand=True, pady=(12, 0))
        self.label(sy, "System", 12, color=P["MUTED"], anchor="w").pack(fill="x", padx=16, pady=(12, 4))
        self.sys_rows = {}
        for k, lab in (("uptime", "Uptime"), ("procs", "Processes"), ("cpu_power", "CPU power"),
                       ("gpu_power", "GPU power"), ("fans", "Fans"), ("os", "OS")):
            r = ctk.CTkFrame(sy, fg_color="transparent")
            r.pack(fill="x", padx=16)
            self.label(r, lab, 11, color=P["FAINT"], height=22).pack(side="left")
            v = self.label(r, "—", 11, font=mono, height=22)
            v.pack(side="right")
            self.sys_rows[k] = v
        g.grid_rowconfigure(1, weight=1)
        yield

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
        self.sensor_search.bind("<KeyRelease>", lambda e=None: self._rebuild_sensors())
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
        g["big"].configure(text=fmt(m.get("cpu_load"), "%"))
        self.load_chart.set_multi([(hist.get("gpu_load", []) or [0, 0], PURPLE), (hist.get("cpu_load", []), CYAN)], 100)
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
        g["big"].configure(text=fmt(m.get("gpu_load"), "%"))
        # RAM
        g = self.g_ram
        g["ring"].set(m.get("ram_pct"), fmt(m.get("ram_pct"), "%"), "used", ("#60a5fa", BLUE))
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Used"); v1.configure(text=fmt(m.get("ram_used"), " GB", 1))
        l2.configure(text="Total"); v2.configure(text=fmt(m.get("ram_total"), " GB", 1))
        l3.configure(text="Free"); v3.configure(text=fmt((m.get("ram_total") or 0) - (m.get("ram_used") or 0), " GB", 1) if m.get("ram_total") else "—")
        g["spark"].set(hist.get("ram_pct", []), 100, BLUE)
        g["big"].configure(text=fmt(m.get("ram_pct"), "%"))
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
                r.pack(fill="x", pady=(4, 0))
                top = ctk.CTkFrame(r, fg_color="transparent")
                top.pack(fill="x")
                self.label(top, mount, 11).pack(side="left")
                v = self.label(top, "", 11, color=P["FAINT"], font=ctk.CTkFont(family=MONO, size=10))
                v.pack(side="right")
                bar = GradientBar(r, height=4)
                bar.pack(fill="x", pady=(4, 0))
                self.disk_rows[mount] = (v, bar)
            v, bar = self.disk_rows[mount]
            v.configure(text=f"{used:,.0f} / {total:,.0f} GB")
            bar.set(pct / 100, *((BAD, BAD) if pct > 90 else (P["MUTED"], P["MUTED"])))
        # system
        up = int(m.get("uptime") or 0)
        self.sys_rows["uptime"].configure(text=f"{up // 86400}d {up % 86400 // 3600}h {up % 3600 // 60}m")
        self.sys_rows["procs"].configure(text=str(m.get("procs", "—")))
        self.sys_rows["cpu_power"].configure(text=fmt(m.get("cpu_power"), " W"))
        self.sys_rows["gpu_power"].configure(text=fmt(m.get("gpu_power"), " W"))
        fans = s["fans"]
        self.sys_rows["fans"].configure(text=f"{len(fans)} · {s['profile']}" if fans else "—")

    def _refresh_hw(self):
        try:
            s = self.monitor.snapshot()
            self.snap = s
            dot, oval, sub = self.status_rows["hw"]
            dot.itemconfigure(oval, fill={"ok": OK, "basic": WARN}.get(s["status"], WARN))
            sub.configure(text={"ok": f"{plural(len(s['sensors']), 'sensor')} · {plural(len(s['fans']), 'fan')}",
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
        body.pack(fill="x")
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
        self.caption(left, "FPS overlay").pack(fill="x", padx=16, pady=(12, 6))
        yield
        self.overlay_sw = Switch(left, text="Show the overlay in games", font=F(13, "bold"), text_color=P["TEXT"],
                                 command=self._overlay_toggle)
        yield
        self.overlay_sw.pack(anchor="w", padx=16, pady=4)
        yield
        if cfg["enabled"]:
            self.overlay_sw.select()
        yield
        self.overlay_status = self.label(left, "Off", 11, color=P["MUTED"], anchor="w", justify="left", wraplength=560)
        yield
        self.overlay_status.pack(fill="x", padx=16, pady=(2, 10))

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
        self.caption(left, "Position").pack(fill="x", padx=16, pady=(10, 6))
        yield
        seg(left, fpo.CORNERS, cfg["corner"], lambda v: self._overlay_set("corner", v)).pack(fill="x", padx=16)
        yield
        self.caption(left, "Size").pack(fill="x", padx=16, pady=(16, 6))
        yield
        seg(left, list(fpo.SIZES), cfg["size"], lambda v: self._overlay_set("size", v)).pack(fill="x", padx=16)
        yield
        self.caption(left, "Show").pack(fill="x", padx=16, pady=(16, 6))
        yield
        self.overlay_item_sw = {}
        yield
        for key, label in fpo.ITEMS:
            sw = Switch(left, text=label, font=F(12), text_color=P["TEXT"], command=lambda k=key: self._overlay_item(k))
            sw.pack(anchor="w", padx=16, pady=4)
            if cfg["items"].get(key):
                sw.select()
            self.overlay_item_sw[key] = sw

        yield
        right = self.card(body)
        yield
        right.grid(row=0, column=1, sticky="nsew")
        yield
        self.caption(right, "Preview").pack(fill="x", padx=16, pady=(12, 8))
        yield
        stage = tk.Frame(right, bg=P["SIDE"], highlightthickness=1, highlightbackground=P["LINE"])
        yield
        stage.pack(fill="x", padx=16)
        yield
        self.overlay_preview = fpo.OverlayPanel(stage, self._overlay_colors(), FONT, outer=P["SIDE"])
        yield
        self.overlay_preview.pack(padx=24, pady=24, anchor="w")
        yield
        self.overlay_preview_note = self.label(right, "", 11, color=P["FAINT"], anchor="w", justify="left", wraplength=280)
        yield
        self.overlay_preview_note.pack(fill="x", padx=16, pady=(10, 4))
        yield
        self.label(right, "How it works\n"
                          "• FPS is measured with Intel PresentMon, which reads Windows' own graphics events. "
                          "Nothing is injected into the game.\n"
                          "• It sticks to the game you're playing, even when you tab out, and hides when the game is minimised or closed.\n"
                          "• It shows over windowed and borderless-fullscreen games. Games in exclusive "
                          "fullscreen can cover it, so switch them to borderless.\n"
                          "• Clicks pass straight through it.",
                   11, color=P["MUTED"], anchor="w", justify="left", wraplength=280).pack(fill="x", padx=16, pady=(8, 16))

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
            self._overlay_wake()
        else:
            self.fps.stop_async()       # flag set now, so switching back on right away can't be undone by it
            if self.overlay_win is not None:
                self.overlay_win.destroy()
                self.overlay_win = None

    def _overlay_tick(self):
        """Follow the game: pick the app you're playing, then keep the overlay on it even after you tab out.
        Anything that stops the counter (PresentMon refused, crashed, no frames...) is shown on this page and in
        the overlay itself instead of the overlay just vanishing.
        With the overlay off and its page not on screen there is nothing to follow or draw, so no Win32 calls are
        made and it only checks again every OVERLAY_IDLE_MS (_overlay_wake brings it back at once)."""
        cfg = self.overlay_cfg
        page_showing = self.current_page == "Overlay" and not self._hidden()
        if not cfg["enabled"] and not page_showing:
            if self.overlay_win is not None:
                try:
                    self.overlay_win.hide()
                except tk.TclError:
                    pass
            self._overlay_idle = True
            self._overlay_job = self.after(OVERLAY_IDLE_MS, self._overlay_tick)
            return
        self._overlay_idle = False
        try:
            metrics = self.snap.get("metrics", {})
            if not hasattr(self, "game_tracker"):
                self.game_tracker = fpo.GameTracker(self.fps)
            fg_hwnd, fg_pid = fpo.foreground_window()
            fg_rect = fpo.game_window_state(fg_hwnd) if fg_hwnd and fg_pid != os.getpid() else None
            gamelike = fpo.covers_monitor(fg_rect, fpo.monitor_rect(fg_hwnd)) if fg_rect else False
            st = self.game_tracker.update(fg_hwnd, fg_pid, gamelike) if cfg["enabled"] else None
            fps = st["fps"] if st else None
            target = None
            if st and st["pid"]:
                target, in_front = st["hwnd"], st["in_front"]
            elif st and st["note"] and gamelike:      # nothing to measure, but say why on the fullscreen app in front
                target, in_front = fg_hwnd, True
            if target:
                if self.overlay_win is None:
                    self.overlay_win = fpo.OverlayWindow(self, self._overlay_colors(), FONT)
                gp = st["pid"]
                mode = self.fps.mode(gp) if gp else ""
                key = (gp, st["exclusive"], st["note"])
                if key != getattr(self, "_overlay_logged", None):
                    self._overlay_logged = key
                    name = (fps or {}).get("name") or "the game"
                    if gp:
                        self.log(f"Overlay attached to {name} (pid {gp}, display mode: {mode or 'unknown'}, "
                                 f"window {fpo.game_window_state(target)}).")
                    if st["note"]:
                        self.log(f"Overlay: {st['text']}", "warn")
                self.overlay_win.update_overlay(cfg, fps, metrics, target, in_front, st["stale"], st["note"])
            elif self.overlay_win is not None:
                self.overlay_win.hide()
            if page_showing:                          # in the tray: keep following the game, skip the preview
                sample = fps or {"name": "", "fps": 144, "low": 112, "ms": 6.9}
                self.overlay_preview.render(cfg, sample, metrics, note=st["note"] if st else "")
                self.overlay_preview_note.configure(
                    text=f"Live: {fps['name']}" if fps else "Sample numbers. Live numbers show here while a game is running.")
                level, text = (st["level"], st["text"]) if st else ("off", "Off")
                self.overlay_status.configure(
                    text=text, text_color={"bad": BAD, "warn": WARN, "ok": OK}.get(level, P["MUTED"]))
        except tk.TclError:
            pass
        except Exception:
            traceback.print_exc()
        self._overlay_job = self.after(OVERLAY_FAST_MS, self._overlay_tick)

    def _overlay_wake(self):
        """The overlay was switched on or its page opened: if the tick is waiting out its slow idle delay,
        run it now instead of up to OVERLAY_IDLE_MS later."""
        job = getattr(self, "_overlay_job", None)
        if job is None or not getattr(self, "_overlay_idle", False):
            return                               # not started yet, or already on the fast schedule
        try:
            self.after_cancel(job)
        except (tk.TclError, ValueError):
            pass
        self._overlay_idle = False
        self._overlay_job = self.after(0, self._overlay_tick)

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
        self.profile_name.bind("<Return>", lambda e=None: self._save_profile())
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
            c.grid(row=i // 3, column=i % 3, sticky="ew", pady=(0, 12),
                   padx=(0 if i % 3 == 0 else 6, 0 if i % 3 == 2 else 6))
            strip = LedStrip(c, n=20, height=28)
            strip.pack(fill="x", padx=8, pady=(8, 0))
            cols = eng.compute_colors("Rainbow Wave" if st["effect"] == "Color Cycle" else st["effect"],
                                      st["color"], max(st["brightness"], 40), 50, 16, 0)
            strip.after(60, lambda s=strip, c2=cols: s.show(c2))
            self.label(c, name, 13, "bold", anchor="w").pack(fill="x", padx=16)
            self.label(c, f"{st['effect']} · {hexcol(st['color']).upper()} · {st['brightness']}%", 11,
                       color=P["FAINT"], anchor="w").pack(fill="x", padx=16)
            r = ctk.CTkFrame(c, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=(8, 12))
            self.secondary(r, "Load", lambda n=name: self._load_profile(n), height=28, font=F(12)).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(r, text="✕", width=28, height=28, corner_radius=6, fg_color=P["BTN"], hover_color=DEL_HOVER,
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
        self.setting_row(body, "\ue771", "◑", "Theme", "The look of the whole app, applied straight away", theme)
        yield
        def appearance(row):
            self.appearance_seg = PillSwitcher(row, values=["Dark", "Light"], command=self._set_appearance,
                                               height=32, font=F(13), corner_radius=6, fg_color=P["CARD2"],
                                               unselected_color=P["CARD2"], unselected_hover_color=P["BTN_HOVER"],
                                               selected_color=self.accent, selected_hover_color=self.accent,
                                               text_color=P["TEXT"])
            self.appearance_seg.set(appearance_of(self.settings.data.get("appearance")).capitalize())
            self.accent_widgets.append(("seg", self.appearance_seg))
            return self.appearance_seg
        yield
        self.setting_row(body, "\ue706", "☼", "Appearance", "Dark or light panels for the theme, applied straight away",
                         appearance)
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
        self.caption(body, "Updates").pack(fill="x", pady=(22, 8))
        yield
        def check_btn(row):
            box = ctk.CTkFrame(row, fg_color="transparent")
            self.update_status = self.label(box, getattr(self, "_update_status_text", ""), 11, color=P["FAINT"], anchor="e")
            self.update_status.pack(side="left", padx=(0, 12))
            self.secondary(box, "Check now", lambda: self._check_updates(manual=True), height=32, width=110).pack(side="left")
            return box
        self.setting_row(body, "\ue895", "↻", "Check for updates", f"You have Central RGB {APP_VERSION}", check_btn)
        yield
        self.setting_row(body, "\ue896", "↓", "Automatically check for updates",
                         "Look for a new version at most once a day and offer to install it",
                         switch("autoupd_sw", upd.auto_check_enabled(self.settings.data),
                                lambda: self.settings.__setitem__(upd.AUTO_KEY, self.autoupd_sw.get() == 1)))

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
            ctk.CTkLabel(r, text=g, width=22, height=22, corner_radius=11, fg_color=col, text_color=ON_STATUS,
                         font=F(12, "bold")).pack(side="left", padx=(18, 14), pady=12)
            if "PawnIO driver not found" in msg and eng.IS_WIN:
                self.primary(r, "Install PawnIO", self._install_pawnio, height=32, width=140).pack(side="right", padx=14)
            self.label(r, msg, 13, anchor="w", justify="left", wraplength=820).pack(side="left", fill="x", expand=True, padx=(0, 16), pady=10)

    def _install_pawnio(self):
        if not messagebox.askyesno(eng.APP_NAME, "Install the PawnIO driver?\n\nIt's the free, signed driver Central RGB "
                                   "uses (through LibreHardwareMonitor and OpenRGB) to read CPU temperatures, control fans "
                                   "and reach RGB RAM. The official installer is downloaded from pawnio.eu's GitHub."):
            return

        def work():
            res = eng.install_pawnio(self.log)
            if res in ("ok", "reboot"):
                self.log("PawnIO installed." + (" Windows wants a restart to finish." if res == "reboot" else ""), "ok")
                msg = ("PawnIO is installed. " + ("Restart Windows, then open Central RGB." if res == "reboot"
                                                  else "Close Central RGB from the tray and open it again to load CPU temperatures."))
                self.q.put(("call", lambda: (messagebox.showinfo(eng.APP_NAME, msg),
                                             self.pawn_bar.pack_forget() if hasattr(self, "pawn_bar") else None)))
                self._bg(self._run_check)
            else:
                self.log(res, "bad")
                self.q.put(("call", lambda: messagebox.showerror(eng.APP_NAME, res)))
        self._bg(work)

    def _toggle_ram_temps(self):
        on = self.ramtemp_sw.get() == 1
        self.settings["ram_temps"] = on
        messagebox.showinfo(eng.APP_NAME, "Restart Central RGB for this to take effect." + (
            "\n\nReading RAM temperatures shares the RAM's SMBus with the RGB controller, which can make "
            "RGB RAM blink. Leave this off if you have RGB RAM." if on else ""))

    def _set_theme(self, name):
        key = next((k for k, t in THEMES.items() if t["name"] == name), DEFAULT_THEME)
        self.settings["theme"] = key
        if key != THEME:
            self.after(60, lambda: self._switch_theme(key))   # after the dropdown has closed

    def _set_appearance(self, choice):
        mode = appearance_of(str(choice).lower())
        self.settings["appearance"] = mode
        if mode != APPEARANCE:
            self.after(60, lambda: self._switch_theme(THEME, mode))

    def _switch_theme(self, key, appearance=None):
        """Apply a theme (and Dark / Light appearance) live: the window fades out, is rebuilt in the new colours
        and fades back in. Lighting, fan control, sensors and OpenRGB keep running untouched (no restart, no
        re-detection)."""
        global THEME
        appearance = appearance_of(appearance or APPEARANCE)
        t0 = time.perf_counter()
        for a in (0.7, 0.4, 0.15, 0.0):                         # quick fade out
            try:
                self.attributes("-alpha", a)
                self.update()
            except tk.TclError:
                break
            time.sleep(0.012)
        _apply_theme(key, appearance)
        THEME = key
        ctk.set_appearance_mode(appearance)
        # title bar and the colour Windows clears to switch now, before anything is rebuilt, so nothing is
        # cleared to the old (dark) panel colour while the new widgets draw
        self._window_effects()
        page = self.current_page
        rows = list(self.device_rows)
        if self.overlay_win is not None:
            try:
                self.overlay_win.destroy()
            except Exception:
                pass
            self.overlay_win = None
        for w in self.winfo_children():
            w.destroy()
        self.configure(fg_color=P["BG"])
        self.accent = DEFAULT_ACCENT
        self.accent_widgets = []
        self.device_rows, self.device_cards = [], []
        self.fan_cards, self.sensor_items = {}, {}
        self.editor, self.editor_key = None, None
        self.current_page = "Home"
        self._ttk_style()
        self._build()
        for _ in self._page_steps():
            pass
        self._sync_ui_from_state()
        if rows:
            self._fill_devices(rows)
        if getattr(self, "_last_checks", None):
            self._show_checks(self._last_checks)
        if getattr(self, "_conflicts", None) is not None:
            self._update_conflict_bar(self._conflicts)
        self._update_missing_bar(getattr(self, "_missing", None))
        if self.sysinfo:
            self._show_sysinfo(self.sysinfo)
        try:                                                     # activity log comes back too
            self.logbox.configure(state="normal")
            for stamp, msg, level in getattr(self, "_log_hist", []):
                prefix = {"ok": "✓ ", "warn": "! ", "bad": "✕ ", "info": "  "}.get(level, "")
                self.logbox.insert("end", stamp + "  " + prefix + msg + "\n", level or None)
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        except Exception:
            pass
        self.show_page(page)
        if getattr(self, "update_notice", None) is not None and getattr(self, "_update_result", None) is not None:
            self.update_notice = None
            self._show_update_notice(self._update_result)
        self._update_accent()
        self._window_effects()
        self.update()
        self._fade_in(0.0)
        self.log(f"Theme changed to {THEMES[key]['name']} ({(time.perf_counter() - t0) * 1000:.0f} ms).", "ok")

    def _restart(self):
        """Start a fresh copy (it waits for this one to close), then quit."""
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--restarted"]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve()), "--restarted"]
        try:
            # env: the portable exe must give the new copy a clean start, or PyInstaller refuses it
            # ("Security validation failure ... PID not found") once this copy has closed
            subprocess.Popen(cmd, creationflags=eng.NO_WINDOW if not getattr(sys, "frozen", False) else 0,
                             env=eng.child_env())
        except Exception as e:
            messagebox.showerror(eng.APP_NAME, f"Couldn't restart automatically ({e}). Please reopen Central RGB.")
        self._quit()

    def _set_accent_mode(self, choice):
        self.settings["accent_mode"] = {"Match lighting": "match", "Windows": "windows"}.get(choice, "cyan")
        self._update_accent()

    def show_page(self, name, animate=True):
        if name not in self.pages:
            return
        if self._switching:
            # a switch is still being drawn and a click arrived meanwhile: never start a second switch on top of
            # it (that left pages half-built); open the latest page asked for as soon as this one is done
            self._pending_page = name
            return
        self._switching = True
        try:
            self._swap_page(name)
        finally:
            self._switching = False
        if self.current_page == "Overlay":
            self._overlay_wake()
        nxt, self._pending_page = self._pending_page, None
        if nxt is not None and nxt != self.current_page:
            self.show_page(nxt)

    def _refresh_page(self, name, s):
        if name == "Home":
            self._refresh_home(s)
        elif name == "Monitor":
            self._refresh_monitor(s)
        elif name == "Fans":
            self._refresh_fans(s)

    def _swap_page(self, name):
        self.current_page = name
        page = self.pages[name]
        ph, t = {}, time.perf_counter()

        def mark(k):
            nonlocal t
            now = time.perf_counter()
            ph[k] = (now - t) * 1000
            t = now
        # The new page is filled in and laid out while still underneath, then raised and drawn in one go. No
        # freezing of drawing (WM_SETREDRAW): with drawing frozen Windows never cleared what the raised page
        # uncovered, so wherever Tk didn't repaint, the previous page's pixels stayed on screen.
        if not page.winfo_manager():              # first visit: lay it out once, then keep it ready
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
        try:
            self._refresh_page(name, self.snap)
        except tk.TclError:
            pass
        except Exception as e:                    # a bad reading must never stop the page from opening
            self.log(f"Couldn't refresh the {name} page: {e}", "warn")
        mark("refresh")
        self.update_idletasks()
        mark("layout")
        # The sidebar highlight moves only now, after the layout pass: update_idletasks() above would otherwise
        # draw it straight away, showing the new page lit while the old page stays up (for over 100 ms on a
        # page's first visit). Set here, it is drawn in the same go as the page.
        for n, item in self.nav.items():
            item.set(n == name, self._led_color())
        mark("nav")
        page.tkraise()
        mark("raise")
        # Tk draws later, widget by widget, spread over several screen frames; do it now, all in one go (the
        # sidebar highlight included), so the page appears complete.
        self._paint_now()
        mark("paint")
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
        elif APPEARANCE == "light":
            # light mode: the same hue, dark enough to read on the light panels
            acc = darken_for(hexcol([c * 255 for c in colorsys.hsv_to_rgb(h, min(s, 0.85), 0.75)]), P["CARD"], 4.5)
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
                    w.configure(progress_color=acc, button_color=acc, button_hover_color=slider_hover(acc))
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
            self.nav[self.current_page].set(True, self._led_color())
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
        try:
            self._draw_frame(time.time())
        except tk.TclError:
            pass
        self.after(ANIM_MS, self._animate)

    def _draw_frame(self, t):
        """One frame of the live previews on the page showing. A preview is only redrawn when its effect moves
        (effect tiles at half the frame rate, staggered), or when what it shows changed. Still effects, and
        every effect while animations are off in Settings, are drawn once and then left alone."""
        frame = self._anim_frame = getattr(self, "_anim_frame", 0) + 1
        live = self.settings.data.get("animations", True)
        page = self.current_page
        memo = {}                                     # one compute_colors per set of arguments per frame

        def draw(widget, effect, color, bright, speed, n, offset=0.0, every=1, phase=0):
            custom = eng.CUSTOM_PRESETS.get(effect)
            sig = (effect, tuple(color), bright, speed, n, offset, repr(custom) if custom else None)
            if sig == getattr(widget, "_anim_sig", None):
                if not (live and eng.is_animated(eng.RENAMED.get(effect, effect))) or (frame + phase) % every:
                    return False
            widget._anim_sig = sig
            key = sig[:6]
            if key not in memo:
                memo[key] = eng.compute_colors(effect, color, bright, speed, n, t, offset=offset)
            widget.show(memo[key])
            return True

        if page in ("Home", "Lighting"):
            st = self._current_state()
            eff, col, bright, speed = st["effect"], st["color"], max(st["brightness"], 8), st["speed"]
            if page == "Home":
                draw(self.home_strip, eff, col, bright, speed, 48)
                if self.home_light_strip.winfo_ismapped():        # not on screen: nothing to draw
                    draw(self.home_light_strip, eff, col, bright, speed, 24)
            else:
                if draw(self.preview, eff, col, bright, speed, self.preview.n):
                    self._move_track(t, speed)
                for i, (name, tile) in enumerate(self.tiles.items()):
                    if isinstance(tile, EffectTile):
                        draw(tile, name, self.color, 100, 50, tile.n, every=TILE_EVERY, phase=i)
        elif page == "Devices":
            ex = set(self.settings["excluded"])           # read once per frame, not once per card
            overrides = self.settings.data.get("device_overrides", {})
            base = self.settings["state"]
            for i, card in enumerate(self.device_cards):
                if card.key in ex:
                    if getattr(card.strip, "_anim_sig", None) != "excluded":
                        card.strip._anim_sig = "excluded"
                        card.strip.show([(0, 0, 0)])
                    continue
                ds = overrides.get(card.key) or base
                draw(card.strip, ds["effect"], ds["color"], max(ds["brightness"], 8), ds["speed"], card.strip.n,
                     offset=i * 0.07)
            if self.editor is not None:
                ds = overrides.get(self.editor_key) or base
                draw(self.editor_art, ds["effect"], ds["color"], max(ds["brightness"], 8), ds["speed"],
                     max(1, len(self.editor_art.leds)))

    def _move_track(self, t, speed):
        """The preview's progress line: two bars made once, then only moved."""
        trk = self.preview_track
        items = getattr(trk, "_track_bars", None)
        if items is None:
            items = trk._track_bars = (trk.create_rectangle(0, 1, 20, 3, fill=P["TRACK"], width=0),
                                       trk.create_rectangle(0, 1, 0, 3, fill=self.accent, width=0))
            trk._track_fill = self.accent
        tw = max(trk.winfo_width(), 20)
        trk.coords(items[0], 0, 1, tw, 3)
        trk.coords(items[1], 0, 1, tw * ((t * (0.05 + speed / 400)) % 1.0), 3)
        if trk._track_fill != self.accent:
            trk._track_fill = self.accent
            trk.itemconfigure(items[1], fill=self.accent)

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
        hist = self.__dict__.setdefault("_log_hist", [])
        hist.append((time.strftime("%H:%M:%S"), str(msg), level))
        if len(hist) > 300:
            del hist[:100]
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

    def _add_log_lines(self, items):
        """Put queued log lines into the Activity box in one go, then trim it to the last LOG_LINES lines (an
        ever-growing Text widget made every insert slower the longer the app ran)."""
        if not items:
            return
        box = self.logbox
        box.configure(state="normal")
        for _, msg, level in items:
            box.insert("end", time.strftime("%H:%M:%S  ") + LOG_PREFIX.get(level, "") + msg + "\n", level or None)
        lines = int(str(box.index("end-1c")).split(".")[0]) - 1     # every line ends in "\n"
        if lines > LOG_LINES:
            box.delete("1.0", f"{lines - LOG_LINES + 1}.0")
        box.see("end")
        box.configure(state="disabled")

    def _poll_queue(self):
        logs = []                                # log lines go in together, before the next non-log item
        handled = 0
        try:
            while handled < QUEUE_BATCH:
                item = self.q.get_nowait()
                handled += 1
                kind = item[0]
                if kind == "log":
                    logs.append(item)
                    continue
                if logs:
                    batch, logs = logs, []
                    try:
                        self._add_log_lines(batch)
                    except tk.TclError:          # the log box is being rebuilt: still handle this item
                        pass
                if kind == "tray":
                    self._tray_action(item[1])
                elif kind == "status":
                    dot, oval, sub = self.status_rows["rgb"]
                    sub.configure(text=item[1])
                    dot.itemconfigure(oval, fill={"ok": OK, "bad": BAD}.get(item[2], WARN))
                elif kind == "devices":
                    self._fill_devices(item[1])
                elif kind == "checks":
                    self._last_checks = item[1]
                    self._show_checks(item[1])
                elif kind == "conflicts":
                    self._update_conflict_bar(item[1])
                elif kind == "missing":
                    self._update_missing_bar(item[1])
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
        try:
            self._add_log_lines(logs)
        except tk.TclError:
            pass
        # more waiting: come back almost at once, but still let Tk draw and handle input in between
        self.after(15 if handled >= QUEUE_BATCH else 100, self._poll_queue)

    # ---------------------------------------------------------------- startup / OpenRGB
    def _startup(self):
        self.status("Checking your system…")
        self._run_check()
        self._connect_flow()

    def _run_check(self):
        res = eng.system_check()
        self.q.put(("checks", res))
        self.q.put(("conflicts", eng.find_conflicts()))
        for level, msg in res:
            self.log(msg, level)

    def _wait_for_sensors(self, limit=25.0):
        """RAM and graphics-card lighting are found over the SMBus, which the sensor library also uses
        while it loads. Scanning at the same time makes OpenRGB miss those devices, so wait for it."""
        end = time.time() + limit
        while time.time() < end and self.monitor.snapshot()["status"] == "starting":
            time.sleep(0.2)

    def _connect_flow(self):
        """Find/start OpenRGB and connect. Only one of these runs at a time (the device-checking loop and the
        startup could otherwise both start one, launching or connecting twice)."""
        if not hasattr(self, "_connect_lock"):
            self._connect_lock = threading.Lock()
        if not self._connect_lock.acquire(blocking=False):
            return
        try:
            self._connect_flow_locked()
        finally:
            self._connect_lock.release()

    def _connect_flow_locked(self):
        self.ddr5 = eng.ddr5_installed()
        self._searched_before = False
        if self.manager.replace_visible_copy():
            time.sleep(1.0)                  # let its server port close
        if not self.manager.started_by_us() and self.manager.own_copies():
            if eng.keep_openrgb_running(self.ddr5) and self.manager.server_running():
                # DDR5 RAM is only found the first time OpenRGB searches after the PC starts, so the hidden
                # OpenRGB kept from the last session is reused instead of restarted
                self.log("Reconnecting to the hidden OpenRGB that's already running (with DDR5 RAM it isn't "
                         "restarted, so your RAM lighting stays found).", "ok")
            else:
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
            self._note_hardware_search()
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

    def _update_conflict_bar(self, found):
        self._conflicts = found
        if not hasattr(self, "conflict_bar"):
            return
        if found:
            self.conflict_title.configure(text="Other RGB software is running: " + ", ".join(sorted(found)))
            if not self.conflict_bar.winfo_manager():
                self.conflict_bar.pack(fill="x", pady=(0, 12), before=self.dev_area.master.master)
        elif self.conflict_bar.winfo_manager():
            self.conflict_bar.pack_forget()

    @staticmethod
    def _missing_texts(diags):
        """(title, body) for the Devices-page warning about RGB devices OpenRGB didn't report."""
        if len(diags) == 1:
            d = diags[0]
            return d["title"] + ": " + d["summary"], "\n".join("• " + r for r in d["reasons"])
        title = "Not detected: " + ", ".join(d["title"].replace(" not detected", "") for d in diags)
        body = "\n".join(d["summary"] + "\n" + "\n".join("• " + r for r in d["reasons"]) for d in diags)
        return title, body

    def _update_missing_bar(self, diags):
        self._missing = diags
        if not hasattr(self, "missing_bar"):
            return
        if diags:
            title, body = self._missing_texts(diags)
            self.missing_title.configure(text=title)
            self.missing_text.configure(text=body)
            if not self.missing_bar.winfo_manager():
                self.missing_bar.pack(fill="x", pady=(0, 12), before=self.dev_area.master.master)
        elif self.missing_bar.winfo_manager():
            self.missing_bar.pack_forget()

    def _check_missing(self):
        """After hardware detection: if Windows reports RGB RAM or an RGB mouse that OpenRGB didn't report,
        say exactly why and what to change (Devices page and activity log). Never starts another scan."""
        found = [eng.type_name(d) for d in self.engine.devices()]
        try:
            ours_now, ours_kept = self.manager.started_by_us(), bool(self.manager.own_copies())
            external = not (ours_now or ours_kept) and bool(self.engine.client)
            # DDR5: a hidden OpenRGB kept from earlier this boot has already done its one RAM search
            searched = getattr(self, "_searched_before", False) or (not ours_now and ours_kept)
            orgb = eng.running_openrgb_exe()
            headers = eng.diagnose_unset_headers(self.engine.devices(), _zone_sizes(self))
            diags = eng.diagnose_missing_devices(found, external_openrgb=external,
                                                 openrgb_ver=eng.openrgb_version(orgb), openrgb_path=orgb,
                                                 ddr5=getattr(self, "ddr5", False),
                                                 searched_before=searched)
            if headers:
                diags.append(headers)
        except Exception as e:
            self.log(f"Couldn't check for missing RGB devices: {e}", "warn")
            return None
        before = {d["kind"]: d for d in (getattr(self, "_missing", None) or [])}
        now = {d["kind"]: d for d in diags}
        for kind, d in now.items():
            if before.get(kind) != d:
                self.log(d["title"] + ": " + d["summary"], "warn")
                for r in d["reasons"]:
                    self.log("  " + r, "warn")
        for kind, d in before.items():
            if kind not in now:
                self.log(d["title"].replace(" not detected", "") + " detected.", "ok")
        self._missing = diags
        self.q.put(("missing", diags))
        return diags

    def _close_conflicts(self):
        names = sorted(getattr(self, "_conflicts", {}) or eng.find_conflicts())
        if not names:
            self._update_conflict_bar({})
            return
        if not messagebox.askyesno(eng.APP_NAME, "Close these so Central RGB can reach your hardware?\n\n  "
                                   + "\n  ".join(names) + "\n\nTheir background services are stopped and set to start "
                                   "manually, so they don't take the hardware back at the next sign-in. You can still "
                                   "open those apps yourself any time. Central RGB then re-detects your devices."):
            return
        self.conflict_btn.configure(state="disabled", text="Closing…")
        self._bg(self._after_close_conflicts)

    def _after_close_conflicts(self, settle=3.0):
        """Close them, on a background thread: close the apps, wait until they are really gone (so the SMBus
        and the mouse's HID interface are free), then re-detect the hardware exactly once - never in a loop."""
        for line in eng.close_conflicts(self.log):
            self.log(line, "ok")
        left = eng.wait_for_conflicts_gone()
        if left:
            self.log("Still running: " + ", ".join(sorted(left)) + ". Close it yourself (or run Central RGB as "
                     "administrator and press Close them again).", "warn")
        self.q.put(("call", lambda: (self.conflict_btn.configure(state="normal", text="Close them"),
                                     self._update_conflict_bar(left))))
        time.sleep(settle)                       # let the vendor driver hand the bus back
        self.log("Re-detecting hardware now that the other RGB software is closed.", "info")
        self._full_rescan(wait=True, why="conflicts")

    def _ram_found(self) -> bool:
        return any(r[1] == "RAM" for r in self.engine_rows())

    def engine_rows(self):
        try:
            return [(eng.device_key(d), eng.type_name(d)) for d in self.engine.devices()]
        except Exception:
            return []

    def _note_hardware_search(self):
        """Called just before the hidden OpenRGB starts (and searches for hardware)."""
        boot = eng.boot_id()
        self._searched_before = bool(boot) and self.settings["openrgb_boot"] == boot
        self.settings["openrgb_boot"] = boot

    def _ask_on_main(self, title, text) -> bool:
        """Yes/No question from a background thread (the answer waits for the user)."""
        done, ans = threading.Event(), [False]

        def ask():
            try:
                ans[0] = messagebox.askyesno(title, text, icon="warning", default="no")
            finally:
                done.set()
        self.q.put(("call", ask))
        done.wait()
        return ans[0]

    def _ram_guard_allows_restart(self, why: str) -> bool:
        """With DDR5 RAM already found, restarting the hidden OpenRGB would lose it until a full shutdown."""
        ours = self.manager.started_by_us() or bool(self.manager.own_copies())
        if not eng.rescan_needs_ok(getattr(self, "ddr5", False), ours, self._ram_found()):
            return True
        if why == "conflicts":
            self.log("Kept OpenRGB running instead of re-detecting: your DDR5 RAM lighting is already found, and "
                     "searching again would lose it until the PC is shut down.", "info")
            return False
        return self._ask_on_main(
            eng.APP_NAME,
            "Your RAM is DDR5. On many PCs, DDR5 RAM lighting is only found the first time OpenRGB searches "
            "after the PC starts.\n\nRe-detecting now restarts OpenRGB, and your RAM lighting will probably "
            "disappear until you shut the PC down fully.\n\nRe-detect anyway?")

    def _full_rescan(self, why: str = "button", wait=False):
        """Rescan button: make OpenRGB look for hardware again. The hidden OpenRGB this app runs is
        restarted (it only detects devices when it starts); an OpenRGB you run yourself is just refreshed.
        wait=True (after Close them) waits for a rescan already running instead of skipping this one."""
        if not hasattr(self, "_rescan_lock"):
            self._rescan_lock = threading.Lock()
        if not self._rescan_lock.acquire(blocking=wait, timeout=120 if wait else -1):
            return                           # a rescan is already running
        try:
            self._full_rescan_locked(why)
        finally:
            self._rescan_lock.release()

    def _full_rescan_locked(self, why: str = "button"):
        if not self.manager.started_by_us() and not self.manager.own_copies():
            self._rescan()                   # an OpenRGB you run yourself: just refresh its list
            return
        if not self._ram_guard_allows_restart(why):
            self._rescan()                   # refresh the list without restarting OpenRGB
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
        self._note_hardware_search()
        if not self.manager.launch(exe):
            self.status("OpenRGB problem - see Settings", "bad")
            return
        if self.engine.connect():
            self._rescan(initial=True)
            self._bg(self._settle_devices)

    def _settle_devices(self, max_wait=90.0, quiet_for=12.0, min_wait=25.0, long_wait=600.0):
        """OpenRGB keeps detecting hardware after its server opens: USB devices appear at once, but RAM and
        graphics-card lighting are found by probing the SMBus and can take much longer, and a USB device held
        by its vendor app (SteelSeries GG, for example) can hold detection up for minutes. Keep reading the
        device list until it has stopped changing, and for as long as OpenRGB's own log says it is still
        detecting (up to long_wait). Runs on a background thread; never restarts or rescans OpenRGB."""
        t0 = last_change = time.time()
        since = t0 - 120                       # OpenRGB was started (or reconnected) just before this
        count = len(self.engine.devices())
        told = False
        while True:
            elapsed = time.time() - t0
            state, waiting = eng.openrgb_detection_state(since=since)
            if elapsed > long_wait or (elapsed > max_wait and state != "running"):
                break
            time.sleep(1.5 if elapsed < max_wait else 5.0)
            try:
                self._rescan(quiet=True)
            except Exception:
                pass
            rows = len(self.engine.devices())
            if rows != count:
                self.log(f"OpenRGB found more hardware: {rows} device(s) now.", "ok")
                count, last_change = rows, time.time()
            elif elapsed > min_wait and time.time() - last_change > quiet_for and state != "running":
                break
            if state == "running" and elapsed > min_wait and not told:
                told = True
                self.log(eng.still_detecting_note(waiting, eng.find_conflicts()), "warn")
                self.status("Still detecting devices…", "warn")
        self.log(f"Hardware detection finished: {count} device(s) after {time.time() - t0:.0f} s.", "info")
        self._rescan(quiet=True)
        self._check_missing()
        self._check_ram()

    def _check_ram(self):
        found = self._ram_found()
        if found and not self.settings["ram_seen"]:
            self.settings["ram_seen"] = True
        note = eng.ram_missing_note(getattr(self, "ddr5", False), found, getattr(self, "_searched_before", False),
                                    self.settings["ram_seen"])
        if not note:
            return
        self.log(note, "warn")
        boot = eng.boot_id()
        # a pop-up only when RAM lighting is expected (found on this PC before) and at most once per boot
        if self.settings["ram_seen"] and self.settings["ram_note_boot"] != boot and not self.background:
            self.settings["ram_note_boot"] = boot
            self.q.put(("call", lambda: messagebox.showwarning(eng.APP_NAME, note)))

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
        sizes = _zone_sizes(self)
        if sizes:                              # OpenRGB forgets header sizes when it restarts: set them again
            for line in self.engine.apply_zone_sizes(sizes):
                self.log(f"Header set to your LED count: {line}", "info")
        rows = [(eng.device_key(d), eng.type_name(d), d.name, len(d.leds)) for d in self.engine.devices()]
        if rows != self.device_rows:
            self.q.put(("devices", rows))
        self.status(f"{plural(len(rows), 'device')} · {plural(sum(r[3] for r in rows), 'LED')}", "ok" if rows else "warn")
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
        self.preview_label.configure(text=self.effect)
        self._update_accent()

    def _state_changed(self):
        st = self._current_state()
        self.preview_label.configure(text=self.effect)
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

    def _fill_custom_tiles(self):
        """Your own presets (after the built-in ones), then the + Create preset tile."""
        pg = getattr(self, "preset_grid", None)
        if pg is None:
            return
        for t in self._custom_tiles:
            self.tiles.pop(getattr(t, "name", None), None)
            t.destroy()
        self._custom_tiles = []
        i = len(eng.PRESET_EFFECTS)
        for name, defn in self.settings.data.get("custom_presets", {}).items():
            t = PresetTile(pg, name, self._set_effect, height=88, image=custom_preset_art(defn),
                           on_edit=self._edit_preset)
            t.grid(row=i // 4, column=i % 4, sticky="nsew", padx=3, pady=3)
            self.tiles[name] = t
            self._custom_tiles.append(t)
            i += 1
        c = CreateTile(pg, lambda: PresetEditor(self), height=88)
        c.grid(row=i // 4, column=i % 4, sticky="nsew", padx=3, pady=3)
        self._custom_tiles.append(c)
        for name, t in self.tiles.items():
            t.select(name == self.effect, self.accent)

    def _edit_preset(self, name):
        PresetEditor(self, name)

    def _store_custom_presets(self, presets):
        self.settings["custom_presets"] = presets
        eng.CUSTOM_PRESETS.clear()
        eng.CUSTOM_PRESETS.update(presets)
        self._fill_custom_tiles()
        self.log(f"Saved your presets ({len(presets)}).", "ok")

    def _set_speed_value(self, v):
        try:
            self.speed.set(v)
            self.speed.value_label.configure(text=f"{int(v)}%")
            self._state_changed()
        except Exception:
            pass

    def _led_color(self):
        """The colour your lights are showing now (for the sidebar's LED dot)."""
        if self.effect == "Off":
            return P["FAINT"]
        if self.effect in eng.USES_COLOR:
            return hexcol(self.color)
        try:
            cols = eng.compute_colors(self.effect, self.color, 100, 50, 12, 0.0)
            return hexcol(max(cols, key=lambda c: max(c) - min(c)))
        except Exception:
            return hexcol(self.color)

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
        if eng.is_animated(self.effect):
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

    # ---------------------------------------------------------------- updates (see updater.py)
    def _report_last_update(self):
        """After an in-app update: say whether it installed (the helper leaves the installer's exit code)."""
        code = upd.last_update_result()
        if code is None:
            return
        logs = upd.update_dir()
        if code == 0:
            self.log(f"Update installed: you're on Central RGB {APP_VERSION}.", "ok")
            return
        msg = (f"The last update didn't finish installing (installer code {code}), so you're still on "
               f"{APP_VERSION}. Try Settings > Updates > Check now again, or download CentralRGB-Setup.exe from "
               f"the Releases page. Details are in update.log and setup.log in {logs}.")
        self.log(msg, "bad")
        if not self.background:
            messagebox.showwarning(eng.APP_NAME, msg)

    def _auto_check_updates(self):
        """At most once a day, if 'Automatically check for updates' is on (the default)."""
        if upd.should_auto_check(self.settings.data):
            self.settings[upd.LAST_KEY] = time.time()
            self._check_updates(manual=False)
        self.after(3600 * 1000, self._auto_check_updates)      # the app often runs for days in the tray

    def _set_update_status(self, text):
        self._update_status_text = text
        lab = getattr(self, "update_status", None)
        try:
            if lab is not None and lab.winfo_exists():
                lab.configure(text=text)
        except tk.TclError:
            pass

    def _check_updates(self, manual=True):
        if getattr(self, "_update_busy", False):
            return
        self._update_busy = True
        if manual:
            self._set_update_status("Checking...")

        def work():
            try:
                res = upd.check(APP_VERSION)
            except upd.UpdateError as e:
                self.log(str(e), "warn" if manual else "info")
                self.q.put(("call", lambda: self._set_update_status("Couldn't check")))
                return
            finally:
                self._update_busy = False
            self.log(res.message, "ok" if not res.newer else "info")
            self.q.put(("call", lambda: (self._set_update_status(
                f"{res.latest.tag.lstrip('vV')} available" if res.newer else "Up to date"),
                self._show_update_notice(res, manual) if res.newer else None)))
        threading.Thread(target=work, daemon=True).start()

    def _show_update_notice(self, res, manual=True):
        """Small card in the bottom-right corner: it doesn't block anything and goes away with Later."""
        self._update_result = res
        if not manual and getattr(self, "_update_later", None) == res.latest.tag:
            return                                        # 'Later' was pressed for this version already
        self._hide_update_notice()
        card = SmoothFrame(self, fg_color=P["CARD"], corner_radius=10, border_width=1, border_color=P["BTN_LINE"])
        self.update_notice = card
        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 2))
        self.label(top, f"Central RGB {res.latest.tag.lstrip('vV')} is available", 13, "bold", anchor="w").pack(side="left")
        self.update_notice_text = self.label(card, f"You have {APP_VERSION}. Updating closes the app, installs the new "
                                             "version and opens it again.", 11, color=P["MUTED"], anchor="w",
                                             justify="left", wraplength=300)
        self.update_notice_text.pack(fill="x", padx=16)
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(10, 14))
        self.update_now_btn = self.primary(btns, "Update now", self._update_now, height=30, width=110)
        self.update_now_btn.pack(side="right")
        self.secondary(btns, "Later", self._update_later_clicked, height=30, width=80).pack(side="right", padx=(0, 8))
        card.place(relx=1.0, rely=1.0, x=-24, y=-24, anchor="se")
        card.lift()

    def _hide_update_notice(self):
        card = getattr(self, "update_notice", None)
        self.update_notice = None
        if card is not None:
            try:
                card.destroy()
            except tk.TclError:
                pass

    def _update_later_clicked(self):
        res = getattr(self, "_update_result", None)
        if res is not None and res.latest is not None:
            self._update_later = res.latest.tag
        self._hide_update_notice()

    def _update_now(self):
        res = getattr(self, "_update_result", None)
        if res is None or res.latest is None or getattr(self, "_update_busy", False):
            return
        kind = upd.install_kind()
        if kind == "source" or not eng.IS_WIN:
            self.log("This copy runs from source: opening the release page instead.", "info")
            webbrowser.open(res.latest.page)
            self._hide_update_notice()
            return
        self._update_busy = True
        try:
            self.update_now_btn.configure(state="disabled", text="Downloading...")
        except Exception:
            pass

        def progress(done, total):
            txt = (f"Downloading... {done * 100 // total} %" if total else f"Downloading... {done // 1048576} MB")
            self.q.put(("call", lambda: self._notice_text(txt)))

        def work():
            try:
                path = upd.download(res.latest, kind, upd.download_dir(kind), progress)
                self.log(f"Downloaded and verified {path.name} ({res.latest.tag}).", "ok")
                self.q.put(("call", lambda: self._apply_update(kind, path)))
            except upd.UpdateError as e:
                msg = str(e)
                self.log(msg, "bad")
                self.q.put(("call", lambda: self._update_failed(msg)))
            finally:
                self._update_busy = False
        threading.Thread(target=work, daemon=True).start()

    def _notice_text(self, txt):
        try:
            if getattr(self, "update_notice", None) is not None:
                self.update_notice_text.configure(text=txt)
        except tk.TclError:
            pass

    def _update_failed(self, msg):
        self._notice_text(msg)
        try:
            self.update_now_btn.configure(state="normal", text="Try again")
        except Exception:
            pass

    def _apply_update(self, kind, path):
        try:
            upd.start_apply(kind, path)
        except upd.UpdateError as e:
            self.log(str(e), "bad")
            self._update_failed(str(e))
            return
        self.log("Closing to install the update; Central RGB opens again on the new version.", "ok")
        self._quit()                  # the normal exit path: fans go back to the BIOS as on any close

    # ---------------------------------------------------------------- closing
    def on_close(self):
        """The X button: hide to the system tray (keeps lighting and fan control running), or quit."""
        if self.tray is not None and self.settings.data.get("close_to_tray", True):
            self.settings["state"] = self._current_state()
            self.withdraw()                                  # off the taskbar, still running
            if not self.settings.data.get("tray_hint_shown"):
                self.settings["tray_hint_shown"] = True
                self.tray.notify("Still running in the system tray. Right-click the icon to open or quit.")
            self.settings.flush()                            # on disk now, not after the save delay
            return
        self.settings.flush()
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
            if self.current_page == "Overlay":
                self._overlay_wake()
        elif what == "off":
            self._set_effect("Off")
        elif what == "quit":
            self._quit()

    def _confirm_quit(self):
        s = self.monitor.snapshot()
        fan_custom = s["profile"] != "Auto" or s["manual"]
        if eng.is_animated(self.effect) or fan_custom:
            why = []
            if eng.is_animated(self.effect):
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
        try:
            self.withdraw()                      # disappear immediately; shutting things down takes a moment
            self.update_idletasks()
        except tk.TclError:
            pass
        self.settings["state"] = self._current_state()
        self.settings.flush()     # the last change is written even if shutting down below is cut short
        if self.tray is not None:
            self.tray.stop()
        self.engine.stop()
        self.fps.stop()
        self.monitor.stop()       # hands fans back to the BIOS
        if eng.keep_openrgb_running(getattr(self, "ddr5", False)):
            pass                  # DDR5: keep the hidden OpenRGB so the RAM isn't searched for again this boot
        else:
            self.manager.stop()   # the hidden OpenRGB this app started
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
    # Everything was shut down in _quit (fans handed back, settings written). End the process now, so no
    # leftover thread keeps it alive invisibly: that would lock the exe during an update and make the
    # reopened copy think Central RGB is still running.
    try:
        app.settings.flush()
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
