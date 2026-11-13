"""
Central RGB - RGB lighting, fan control and system monitoring in one sleek app.

Pages: Lighting · Devices · Fans · Monitor (Overview / Advanced) · Profiles · Settings
Layers: rgb_engine (OpenRGB lighting) · hw_monitor (sensors + fans via LibreHardwareMonitor)
        win_effects (frosted-glass window on Windows 10/11)

Run:  python central_rgb.py               (normal window)
      python central_rgb.py --background  (start minimized, re-apply last lighting)
"""
from __future__ import annotations

import colorsys
import math
import os
import queue
import sys
import threading
import time
import traceback
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

import hw_monitor as hwm
import rgb_engine as eng
import win_effects as fx

APP_VERSION = "2.0.1"
TASK_NAME = "CentralRGB"

# ----------------------------------------------------------------------------- palette
# In glass mode the window background is pure black, which Windows turns into the
# blurred desktop; dark panel colours then read as tinted, frosted glass.
GLASS = dict(BG="#000000", SIDE="#000000", CARD="#14161c", CARD2="#1c1f27", LINE="#262a35",
             TEXT="#f2f4f8", MUTED="#8c94a6", FAINT="#4a5061", TRACK="#22252e")
SOLID = dict(BG="#0a0b0f", SIDE="#0d0e13", CARD="#13151b", CARD2="#1a1d25", LINE="#232631",
             TEXT="#f2f4f8", MUTED="#8c94a6", FAINT="#4a5061", TRACK="#20232b")
P = dict(SOLID)
OK, WARN, BAD, INFO = "#34d399", "#fbbf24", "#f87171", "#60a5fa"
DEFAULT_ACCENT = "#6d7cff"
FONT = "Segoe UI Variable Display" if (eng.IS_WIN and fx.win_build() >= 22000) else ("Segoe UI" if eng.IS_WIN else "DejaVu Sans")
MONO = "Cascadia Mono" if eng.IS_WIN else "DejaVu Sans Mono"

SWATCHES = [(255, 0, 0), (255, 90, 0), (255, 200, 0), (0, 255, 60), (0, 255, 255),
            (0, 70, 255), (150, 0, 255), (255, 0, 160), (255, 255, 255)]
EFFECT_INFO = {"Static": "Solid color", "Breathing": "Slow fade", "Color Cycle": "Shifting hue",
               "Rainbow Wave": "Flowing rainbow", "Off": "Lights off"}
TYPE_ICONS = {"Motherboard": "▦", "RAM": "▥", "GPU": "▣", "Cooler": "✺", "LED strip": "┅",
              "Keyboard": "⌨", "Mouse": "◖", "Mousepad": "▭", "Headset": "◠", "Headset stand": "⊥",
              "Case": "▢", "Light": "✦", "Speaker": "◉", "Other": "◆"}
NAV = [("Lighting", "✦"), ("Devices", "▣"), ("Fans", "✺"), ("Monitor", "◔"), ("Profiles", "★"), ("Settings", "⚙")]


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


def F(size, weight="normal"):
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


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
        s = self.size * 2
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        px = img.load()
        c, r = s / 2, self.r * 2
        for y in range(s):
            dy = y - c
            for x in range(s):
                dx = x - c
                d = math.hypot(dx, dy)
                if d <= r:
                    rr, gg, bb = colorsys.hsv_to_rgb((math.atan2(-dy, dx) / (2 * math.pi)) % 1, min(1, d / r) ** 0.9, 1)
                    px[x, y] = (int(rr * 255), int(gg * 255), int(bb * 255), 255)
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
            self.glows.append(self.create_oval(cx - r * 2.3, cy - r * 2.3, cx + r * 2.3, cy + r * 2.3, width=0, fill=P["CARD"]))
            self.items.append(self.create_oval(cx - r, cy - r, cx + r, cy + r, width=0, fill=P["CARD"]))

    def show(self, colors):
        n = len(self.items)
        for i in range(n):
            c = colors[int(i * len(colors) / n)] if colors else (0, 0, 0)
            lit = max(c) > 20
            self.itemconfigure(self.items[i], fill=hexcol(mix(c, (255, 255, 255), 0.25) if lit else mix(self.bgc, (60, 64, 76), 0.5)))
            self.itemconfigure(self.glows[i], fill=hexcol(mix(self.bgc, c, 0.22 if lit else 0)))


class Sparkline(tk.Canvas):
    def __init__(self, master, height=54, color=DEFAULT_ACCENT, bg=None):
        super().__init__(master, height=height, bg=bg or P["CARD"], highlightthickness=0)
        self.h, self.color, self.bgc = height, color, hex2rgb(bg or P["CARD"])

    def set(self, values, vmax=None, color=None):
        self.delete("all")
        color = color or self.color
        w = max(self.winfo_width(), 40)
        vals = list(values)[-60:]
        if len(vals) < 2:
            return
        top = vmax if vmax else max(max(vals) * 1.2, 1e-6)
        step = w / 59
        x0 = w - step * (len(vals) - 1)
        pts = [(x0 + i * step, self.h - 3 - (self.h - 8) * min(v, top) / top) for i, v in enumerate(vals)]
        fill = hexcol(mix(self.bgc, hex2rgb(color), 0.16))
        self.create_polygon([(pts[0][0], self.h)] + pts + [(pts[-1][0], self.h)], fill=fill, outline="")
        self.create_line(pts, fill=color, width=2, smooth=True)
        self.create_oval(pts[-1][0] - 3, pts[-1][1] - 3, pts[-1][0] + 3, pts[-1][1] + 3, fill=color, outline="")


class Ring(tk.Canvas):
    """Circular gauge."""

    def __init__(self, master, size=112, width=9):
        super().__init__(master, width=size, height=size, bg=P["CARD"], highlightthickness=0)
        self.s, self.w = size, width
        pad = width / 2 + 2
        self.create_arc(pad, pad, size - pad, size - pad, start=-225, extent=-270, style="arc",
                        outline=P["TRACK"], width=width)
        self.arc = self.create_arc(pad, pad, size - pad, size - pad, start=225, extent=0, style="arc",
                                   outline=DEFAULT_ACCENT, width=width)
        self.val = self.create_text(size / 2, size / 2 - 6, text="—", fill=P["TEXT"], font=(FONT, 20, "bold"))
        self.sub = self.create_text(size / 2, size / 2 + 18, text="", fill=P["MUTED"], font=(FONT, 9))

    def set(self, pct, text, sub="", color=DEFAULT_ACCENT):
        pct = 0 if pct is None else max(0, min(100, pct))
        self.itemconfigure(self.arc, extent=-270 * pct / 100, outline=color)
        self.itemconfigure(self.val, text=text)
        self.itemconfigure(self.sub, text=sub)


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
        fill = hexcol(mix(hex2rgb(P["CARD"]), hex2rgb(self.accent), 0.13))
        self.create_polygon([(line[0][0], base)] + line + [(line[-1][0], base)], fill=fill, outline="")
        self.create_line(line, fill=self.accent if self.editable else P["MUTED"], width=2.5)
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
            self.create_oval(x - 7, y - 7, x + 7, y + 7, fill=P["CARD"], outline=self.accent if self.editable else P["MUTED"],
                             width=3, tags=("pt",))

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
class EffectTile(ctk.CTkFrame):
    def __init__(self, master, name, on_click):
        super().__init__(master, fg_color=P["CARD2"], corner_radius=14, border_width=1, border_color=P["CARD2"])
        self.strip = LedStrip(self, n=12, height=22, bg=P["CARD2"], pill=True)
        self.strip.pack(fill="x", padx=14, pady=(14, 6))
        self.t = ctk.CTkLabel(self, text=name, font=F(14, "bold"), text_color=P["TEXT"], anchor="w")
        self.t.pack(fill="x", padx=14)
        self.s = ctk.CTkLabel(self, text=EFFECT_INFO[name], font=F(11), text_color=P["MUTED"], anchor="w")
        self.s.pack(fill="x", padx=14, pady=(0, 12))
        for w in (self, self.strip, self.t, self.s):
            w.bind("<Button-1>", lambda e: on_click(name))
            w.configure(cursor="hand2")

    def select(self, on, accent):
        self.configure(border_color=accent if on else P["CARD2"], border_width=2 if on else 1)


class DeviceCard(ctk.CTkFrame):
    def __init__(self, master, key, tname, name, leds, enabled, on_toggle):
        super().__init__(master, fg_color=P["CARD"], corner_radius=18, border_width=1, border_color=P["LINE"])
        self.key = key
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(top, text=TYPE_ICONS.get(tname, "◆"), width=40, height=40, corner_radius=12,
                     fg_color=P["CARD2"], font=F(18), text_color=P["TEXT"]).pack(side="left")
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkLabel(info, text=name, font=F(14, "bold"), text_color=P["TEXT"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=f"{tname} · {leds} LEDs", font=F(11), text_color=P["MUTED"], anchor="w").pack(fill="x")
        self.switch = ctk.CTkSwitch(top, text="", width=44, command=lambda: on_toggle(key, self.switch.get() == 1))
        self.switch.pack(side="right")
        if enabled:
            self.switch.select()
        self.strip = LedStrip(self, n=max(1, min(leds, 20)), height=26, pill=True)
        self.strip.pack(fill="x", padx=16, pady=(4, 16))


class FanCard(ctk.CTkFrame):
    def __init__(self, master, fan, on_manual, on_reset):
        super().__init__(master, fg_color=P["CARD"], corner_radius=18, border_width=1, border_color=P["LINE"])
        self.fid, self.on_manual, self.touched = fan["id"], on_manual, 0
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 0))
        self.spin = tk.Canvas(top, width=40, height=40, bg=P["CARD"], highlightthickness=0)
        self.spin.pack(side="left")
        self.blades = [self.spin.create_arc(4, 4, 36, 36, start=a, extent=50, fill=P["FAINT"], outline="")
                       for a in (0, 120, 240)]
        self.spin.create_oval(15, 15, 25, 25, fill=P["CARD"], outline="")
        self.angle = 0
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkLabel(info, text=fan["name"], font=F(14, "bold"), text_color=P["TEXT"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=fan["hw"], font=F(11), text_color=P["MUTED"], anchor="w").pack(fill="x")
        self.badge = ctk.CTkButton(top, text="", width=72, height=24, corner_radius=12, font=F(10, "bold"),
                                   fg_color=P["CARD2"], hover_color=P["LINE"], text_color=P["MUTED"],
                                   command=lambda: on_reset(self.fid))
        self.badge.pack(side="right")
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.pack(fill="x", padx=16, pady=(10, 0))
        self.rpm = ctk.CTkLabel(mid, text="—", font=F(26, "bold"), text_color=P["TEXT"])
        self.rpm.pack(side="left")
        ctk.CTkLabel(mid, text=" RPM", font=F(12), text_color=P["MUTED"]).pack(side="left", pady=(8, 0))
        self.pct = ctk.CTkLabel(mid, text="", font=F(13, "bold"), text_color=P["MUTED"])
        self.pct.pack(side="right")
        self.slider = ctk.CTkSlider(self, from_=hwm.FAN_FLOOR, to=100, height=16, fg_color=P["TRACK"],
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
            self.badge.configure(text="MANUAL  ↺", fg_color=hexcol(mix(hex2rgb(P["CARD"]), hex2rgb(accent), 0.3)), text_color=P["TEXT"])
        else:
            self.badge.configure(text="BIOS" if auto else "CURVE", fg_color=P["CARD2"], text_color=P["MUTED"])
        speed = (rpm or 0) / 2500
        self.angle = (self.angle + 40 * speed) % 360
        col = accent if rpm else P["FAINT"]
        for i, b in enumerate(self.blades):
            self.spin.itemconfigure(b, start=self.angle + i * 120, fill=col)


# ----------------------------------------------------------------------------- main window
class App(ctk.CTk):
    TEST_BACKEND = None   # tests can inject a simulated sensor backend

    def __init__(self, background=False):
        self.settings = eng.Settings()
        self.glass = bool(self.settings.data.get("glass", True)) and (fx.glass_supported() or os.environ.get("RGBC_GLASS_PALETTE"))
        P.update(GLASS if self.glass else SOLID)
        ctk.set_appearance_mode("dark")
        super().__init__(fg_color=P["BG"])
        self.title(eng.APP_NAME)
        self.geometry("1300x840")
        self.minsize(1200, 790)
        self.background = background
        self._set_icon()

        self.q: queue.Queue = queue.Queue()
        self.manager = eng.OpenRGBManager(self.settings, self.log)
        self.engine = eng.LightingEngine(self.log, on_disconnect=lambda: self.q.put(("disconnected",)))
        self.engine.set_excluded(self.settings["excluded"])
        self.engine.state.update(self.settings["state"])
        self.engine.paused = True
        self.engine.start()
        self.monitor = hwm.HardwareMonitor(self.log, self.settings, backend=self.TEST_BACKEND)
        self.monitor.start()

        st = self.settings["state"]
        self.color = tuple(st.get("color", (0, 120, 255)))
        self.effect = st.get("effect", "Static")
        self.accent = DEFAULT_ACCENT
        self.accent_widgets: list = []
        self.device_rows, self.device_cards = [], []
        self.fan_cards: dict[str, FanCard] = {}
        self.sensor_items: dict[str, str] = {}
        self.connected = False
        self.current_page = "Lighting"
        self.snap = self.monitor.snapshot()

        self._ttk_style()
        self._build()
        self._sync_ui_from_state()
        self.show_page("Lighting")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll_queue)
        self.after(40, self._animate)
        self.after(500, self._refresh_hw)
        self.after(60, self._window_effects)
        if background:
            self.iconify()
        self.after(300, lambda: self._bg(self._startup))
        self.after(800, lambda: self._bg(self._load_sysinfo))

    def _window_effects(self):
        fx.dark_titlebar(self)
        if self.glass and fx.glass_supported():
            fx.apply_glass(self)
        op = int(self.settings.data.get("opacity", 100))
        if op < 100:
            fx.set_opacity(self, op)

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
        return ctk.CTkFrame(parent, fg_color=P["CARD"], corner_radius=18, border_width=1, border_color=P["LINE"], **kw)

    def label(self, parent, text, size=12, weight="normal", color=None, **kw):
        return ctk.CTkLabel(parent, text=text, font=F(size, weight), text_color=color or P["TEXT"], **kw)

    def caption(self, parent, text):
        return ctk.CTkLabel(parent, text=text.upper(), font=F(10, "bold"), text_color=P["FAINT"], anchor="w")

    def primary(self, parent, text, cmd, **kw):
        b = ctk.CTkButton(parent, text=text, command=cmd, fg_color=self.accent, hover_color=self.accent,
                          text_color="white", font=F(13, "bold"), corner_radius=kw.pop("corner_radius", 22), **kw)
        self.accent_widgets.append(("button", b))
        return b

    def secondary(self, parent, text, cmd, **kw):
        return ctk.CTkButton(parent, text=text, command=cmd, fg_color=P["CARD2"], hover_color=P["LINE"],
                             text_color=P["TEXT"], font=F(12, "bold"), corner_radius=kw.pop("corner_radius", 22),
                             border_width=0, **kw)

    def slider_row(self, parent, label, value, cmd, lo=0, hi=100, unit="%"):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x")
        self.label(top, label, 12, "bold").pack(side="left")
        val = self.label(top, f"{value}{unit}", 12, color=P["MUTED"])
        val.pack(side="right")
        s = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=hi - lo, height=16, progress_color=self.accent,
                          button_color=P["TEXT"], button_hover_color="white", fg_color=P["TRACK"])
        s.set(value)
        s.configure(command=lambda v: (val.configure(text=f"{int(v)}{unit}"), cmd(int(v))))
        s.pack(fill="x", pady=(6, 0))
        s.value_label = val
        self.accent_widgets.append(("slider", s))
        return row, s

    def header(self, parent, title, subtitle, right=None):
        h = ctk.CTkFrame(parent, fg_color="transparent")
        h.pack(fill="x", pady=(0, 18))
        txt = ctk.CTkFrame(h, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        self.label(txt, title, 26, "bold", anchor="w").pack(fill="x")
        self.label(txt, subtitle, 12, color=P["MUTED"], anchor="w").pack(fill="x")
        return h

    # ---------------------------------------------------------------- build
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        side = ctk.CTkFrame(self, fg_color=P["SIDE"], corner_radius=0, width=232)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.pack_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=18, pady=(28, 6))
        self.logo = tk.Canvas(brand, width=36, height=36, bg=P["SIDE"], highlightthickness=0)
        self.logo.pack(side="left")
        if self._icon_img is not None:
            self._logo_img = ImageTk.PhotoImage(self._icon_img.resize((36, 36), Image.LANCZOS))
            self.logo.create_image(18, 18, image=self._logo_img)
        bt = ctk.CTkFrame(brand, fg_color="transparent")
        bt.pack(side="left", padx=10)
        self.label(bt, "Central RGB", 14, "bold", anchor="w").pack(fill="x")
        self.label(bt, f"v{APP_VERSION}", 10, color=P["FAINT"], anchor="w").pack(fill="x")
        ctk.CTkFrame(side, fg_color="transparent", height=18).pack()

        self.nav, self.nav_bars = {}, {}
        for name, glyph in NAV:
            row = ctk.CTkFrame(side, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            bar = ctk.CTkFrame(row, width=3, height=22, corner_radius=2, fg_color=P["SIDE"])
            bar.pack(side="left", padx=(0, 6))
            b = ctk.CTkButton(row, text=f"{glyph}    {name}", anchor="w", height=40, corner_radius=12,
                              font=F(13, "bold"), fg_color="transparent", hover_color=P["CARD"],
                              text_color=P["MUTED"], command=lambda n=name: self.show_page(n))
            b.pack(side="left", fill="x", expand=True)
            self.nav[name], self.nav_bars[name] = b, bar

        st = self.card(side)
        st.pack(side="bottom", fill="x", padx=14, pady=16)
        self.status_rows = {}
        for key, label in (("rgb", "Lighting"), ("hw", "Sensors")):
            r = ctk.CTkFrame(st, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=(12 if key == "rgb" else 2, 2 if key == "rgb" else 12))
            dot = tk.Canvas(r, width=10, height=10, bg=P["CARD"], highlightthickness=0)
            dot.pack(side="left")
            oval = dot.create_oval(1, 1, 9, 9, fill=WARN, width=0)
            col = ctk.CTkFrame(r, fg_color="transparent")
            col.pack(side="left", padx=10, fill="x", expand=True)
            t = self.label(col, label, 12, "bold", anchor="w")
            t.pack(fill="x")
            sub = self.label(col, "Starting…", 10, color=P["MUTED"], anchor="w", justify="left", wraplength=150)
            sub.pack(fill="x")
            self.status_rows[key] = (dot, oval, sub)

        holder = ctk.CTkFrame(self, fg_color=P["BG"], corner_radius=0)
        holder.grid(row=0, column=1, sticky="nsew", padx=(8, 28), pady=24)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        self.pages = {}
        for name, _ in NAV:
            f = ctk.CTkFrame(holder, fg_color=P["BG"], corner_radius=0)
            f.grid(row=0, column=0, sticky="nsew")
            getattr(self, f"_page_{name.lower()}")(f)
            self.pages[name] = f

    # ---------------------------------------------------------------- Lighting
    def _page_lighting(self, p):
        self.header(p, "Lighting", "Pick a color and an effect. Changes go live on every selected device.")
        prev = self.card(p)
        prev.pack(fill="x", pady=(0, 16))
        top = ctk.CTkFrame(prev, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 0))
        self.caption(top, "Live preview").pack(side="left")
        self.preview_label = self.label(top, "", 10, "bold", color=P["MUTED"])
        self.preview_label.pack(side="right")
        self.preview = LedStrip(prev, n=40, height=44)
        self.preview.pack(fill="x", padx=14, pady=(2, 14))

        body = ctk.CTkFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        cc = self.card(body)
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self.caption(cc, "Color").pack(fill="x", padx=20, pady=(16, 10))
        self.wheel = ColorWheel(cc, size=232, command=lambda rgb: self._set_color(rgb, from_wheel=True))
        self.wheel.pack(padx=22)
        hexrow = ctk.CTkFrame(cc, fg_color="transparent")
        hexrow.pack(fill="x", padx=20, pady=(16, 8))
        self.swatch = tk.Canvas(hexrow, width=34, height=34, bg=P["CARD"], highlightthickness=0)
        self.swatch.pack(side="left")
        self.swatch_item = self.swatch.create_oval(2, 2, 32, 32, fill="#000", width=0)
        self.hex_entry = ctk.CTkEntry(hexrow, width=118, height=34, corner_radius=17, font=F(13, "bold"),
                                      fg_color=P["CARD2"], border_width=0, text_color=P["TEXT"], justify="center")
        self.hex_entry.pack(side="left", padx=10)
        self.hex_entry.bind("<Return>", self._hex_entered)
        self.hex_entry.bind("<FocusOut>", self._hex_entered)
        sw = tk.Canvas(cc, height=30, width=236, bg=P["CARD"], highlightthickness=0)
        sw.pack(padx=20, pady=(6, 18))
        step = 236 / len(SWATCHES)
        for i, c in enumerate(SWATCHES):
            x = step * i + step / 2
            it = sw.create_oval(x - 11, 4, x + 11, 26, fill=hexcol(c), outline=P["CARD"], width=2)
            sw.tag_bind(it, "<Button-1>", lambda e, col=c: self._set_color(col))
            sw.tag_bind(it, "<Enter>", lambda e, i2=it: sw.itemconfigure(i2, outline="white"))
            sw.tag_bind(it, "<Leave>", lambda e, i2=it: sw.itemconfigure(i2, outline=P["CARD"]))

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        ec = self.card(right)
        ec.pack(fill="x")
        self.caption(ec, "Effect").pack(fill="x", padx=20, pady=(16, 6))
        grid = ctk.CTkFrame(ec, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(0, 14))
        self.tiles = {}
        for i, name in enumerate(eng.EFFECTS):
            t = EffectTile(grid, name, self._set_effect)
            t.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
            grid.grid_columnconfigure(i % 3, weight=1, uniform="e")
            self.tiles[name] = t

        ctl = self.card(right)
        ctl.pack(fill="x", pady=(16, 0))
        st = self.settings["state"]
        r1, self.bright = self.slider_row(ctl, "Brightness", st.get("brightness", 100), lambda v: self._state_changed())
        r1.pack(fill="x", padx=20, pady=(18, 8))
        r2, self.speed = self.slider_row(ctl, "Speed", st.get("speed", 50), lambda v: self._state_changed())
        r2.pack(fill="x", padx=20, pady=8)
        btns = ctk.CTkFrame(ctl, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(14, 20))
        self.primary(btns, "Apply to all devices", self._apply_all, height=44).pack(side="left", fill="x", expand=True)
        self.secondary(btns, "Save to hardware", lambda: self._bg(self._save_hw), height=44, width=150).pack(side="right", padx=(10, 0))
        self.secondary(btns, "⏻  Off", lambda: self._set_effect("Off"), height=44, width=86).pack(side="right", padx=(10, 0))

    # ---------------------------------------------------------------- Devices
    def _page_devices(self, p):
        h = self.header(p, "Devices", "Every RGB device OpenRGB found. Switch one off to leave it out.")
        bar = ctk.CTkFrame(p, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 14))
        self.primary(bar, "⟳  Rescan", lambda: self._bg(self._rescan), height=38, width=120).pack(side="left")
        self.secondary(bar, "All on", lambda: self._set_all_devices(True), height=38, width=90).pack(side="left", padx=8)
        self.secondary(bar, "All off", lambda: self._set_all_devices(False), height=38, width=90).pack(side="left")
        self.dev_summary = self.label(bar, "", 12, color=P["MUTED"])
        self.dev_summary.pack(side="right")
        self.dev_area = ctk.CTkScrollableFrame(p, fg_color=P["BG"], corner_radius=0)
        self.dev_area.pack(fill="both", expand=True)
        self.dev_area.grid_columnconfigure((0, 1), weight=1, uniform="d")
        self.dev_empty = self.label(self.dev_area, "Scanning for devices…", 14, color=P["MUTED"])
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
            c = DeviceCard(self.dev_area, key, t, name, leds, key not in excluded, self._toggle_device)
            c.switch.configure(progress_color=self.accent)
            c.grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6)
            self.device_cards.append(c)
        self._update_dev_summary()

    def _update_dev_summary(self):
        ex = set(self.settings["excluded"])
        on = sum(1 for r in self.device_rows if r[0] not in ex)
        self.dev_summary.configure(text=f"{on} of {len(self.device_rows)} active · {sum(r[3] for r in self.device_rows)} LEDs")

    # ---------------------------------------------------------------- Fans
    def _page_fans(self, p):
        h = self.header(p, "Fans", "Pick a profile or draw your own curve. Fans always speed up if things get too hot.")
        self.fan_seg = ctk.CTkSegmentedButton(p, values=hwm.PROFILES, command=self._set_fan_profile, height=36,
                                              font=F(12, "bold"), corner_radius=18, fg_color=P["CARD"],
                                              unselected_color=P["CARD"], unselected_hover_color=P["CARD2"],
                                              selected_color=self.accent, selected_hover_color=self.accent,
                                              text_color=P["TEXT"])
        self.fan_seg.pack(fill="x", pady=(0, 14))
        self.accent_widgets.append(("seg", self.fan_seg))

        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x")
        top.grid_columnconfigure(0, weight=1)
        cc = self.card(top)
        cc.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        row = ctk.CTkFrame(cc, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(16, 0))
        self.caption(row, "Fan curve · CPU temperature").pack(side="left")
        self.curve_hint = self.label(row, "", 10, color=P["MUTED"])
        self.curve_hint.pack(side="right")
        self.curve = CurveEditor(cc, self._curve_changed, height=232)
        self.curve.pack(fill="x", padx=12, pady=(6, 12))

        tc = self.card(top, width=270)
        tc.grid(row=0, column=1, sticky="nsew")
        self.caption(tc, "Temperatures").pack(fill="x", padx=20, pady=(16, 6))
        self.fan_temp_labels = {}
        for key, name in (("cpu_temp", "CPU"), ("gpu_temp", "GPU")):
            r = ctk.CTkFrame(tc, fg_color="transparent")
            r.pack(fill="x", padx=20, pady=6)
            self.label(r, name, 12, "bold", color=P["MUTED"]).pack(side="left")
            v = self.label(r, "—", 30, "bold")
            v.pack(side="right")
            self.fan_temp_labels[key] = v
        self.fan_note = self.label(tc, "", 11, color=P["MUTED"], wraplength=230, justify="left", anchor="w")
        self.fan_note.pack(fill="x", padx=20, pady=(10, 16))

        self.fan_area = ctk.CTkScrollableFrame(p, fg_color=P["BG"], corner_radius=0)
        self.fan_area.pack(fill="both", expand=True, pady=(14, 0))
        self.fan_area.grid_columnconfigure((0, 1, 2), weight=1, uniform="f")
        self.fan_empty = ctk.CTkFrame(self.fan_area, fg_color="transparent")
        self.fan_empty.grid(row=0, column=0, columnspan=3, pady=30)
        self.fan_empty_lbl = self.label(self.fan_empty, "Loading fan controllers…", 13, color=P["MUTED"], wraplength=640)
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
        self.mon_seg = ctk.CTkSegmentedButton(h, values=["Overview", "Advanced"], command=self._mon_tab, height=34,
                                              width=220, font=F(12, "bold"), corner_radius=17, fg_color=P["CARD"],
                                              unselected_color=P["CARD"], unselected_hover_color=P["CARD2"],
                                              selected_color=self.accent, selected_hover_color=self.accent,
                                              text_color=P["TEXT"])
        self.mon_seg.pack(side="right")
        self.mon_seg.set("Overview")
        self.accent_widgets.append(("seg", self.mon_seg))
        stack = ctk.CTkFrame(p, fg_color="transparent")
        stack.pack(fill="both", expand=True)
        stack.grid_rowconfigure(0, weight=1)
        stack.grid_columnconfigure(0, weight=1)
        self.mon_over = ctk.CTkFrame(stack, fg_color="transparent")
        self.mon_adv = ctk.CTkFrame(stack, fg_color="transparent")
        for f in (self.mon_over, self.mon_adv):
            f.grid(row=0, column=0, sticky="nsew")
        self._build_overview(self.mon_over)
        self._build_advanced(self.mon_adv)
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
        g.pack(fill="both", expand=True)
        for i in range(3):
            g.grid_columnconfigure(i, weight=1, uniform="o")
        self.g_cpu = self._gauge_card(g, "Processor")
        self.g_gpu = self._gauge_card(g, "Graphics")
        self.g_ram = self._gauge_card(g, "Memory")
        for i, gc in enumerate((self.g_cpu, self.g_gpu, self.g_ram)):
            gc["card"].grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == 2 else 8))

        net = self.card(g)
        net.grid(row=1, column=0, sticky="nsew", pady=(16, 0), padx=(0, 8))
        self.caption(net, "Network").pack(fill="x", padx=18, pady=(16, 4))
        nr = ctk.CTkFrame(net, fg_color="transparent")
        nr.pack(fill="x", padx=18)
        self.net_down = self.label(nr, "—", 20, "bold")
        self.net_down.pack(side="left")
        self.label(nr, " ↓", 12, color=OK).pack(side="left")
        self.net_up = self.label(nr, "—", 20, "bold")
        self.net_up.pack(side="right")
        self.label(nr, "↑ ", 12, color=INFO).pack(side="right")
        self.net_spark = Sparkline(net, height=90, color=OK)
        self.net_spark.pack(fill="x", padx=14, pady=(8, 2))
        self.net_spark2 = Sparkline(net, height=60, color=INFO)
        self.net_spark2.pack(fill="x", padx=14, pady=(0, 14))

        dk = self.card(g)
        dk.grid(row=1, column=1, sticky="nsew", pady=(16, 0), padx=8)
        top = ctk.CTkFrame(dk, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 4))
        self.caption(top, "Storage").pack(side="left")
        self.disk_io = self.label(top, "", 10, color=P["MUTED"])
        self.disk_io.pack(side="right")
        self.disk_box = ctk.CTkFrame(dk, fg_color="transparent")
        self.disk_box.pack(fill="both", expand=True, padx=18, pady=(4, 14))
        self.disk_rows = {}

        sy = self.card(g)
        sy.grid(row=1, column=2, sticky="nsew", pady=(16, 0), padx=(8, 0))
        self.caption(sy, "System").pack(fill="x", padx=18, pady=(16, 4))
        self.sys_rows = {}
        for k, lab in (("uptime", "Uptime"), ("procs", "Processes"), ("cpu_power", "CPU power"),
                       ("gpu_power", "GPU power"), ("fans", "Fans"), ("os", "OS")):
            r = ctk.CTkFrame(sy, fg_color="transparent")
            r.pack(fill="x", padx=18, pady=4)
            self.label(r, lab, 11, color=P["MUTED"]).pack(side="left")
            v = self.label(r, "—", 12, "bold")
            v.pack(side="right")
            self.sys_rows[k] = v
        g.grid_rowconfigure(1, weight=1)

    def _build_advanced(self, p):
        p.grid_columnconfigure(0, weight=2, uniform="a")
        p.grid_columnconfigure(1, weight=3, uniform="a")
        p.grid_rowconfigure(0, weight=1)
        left = self.card(p)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(16, 6))
        self.caption(top, "System details").pack(side="left")
        self.secondary(top, "Copy", self._copy_sysinfo, height=26, width=64, corner_radius=13).pack(side="right")
        self.info_box = ctk.CTkScrollableFrame(left, fg_color=P["CARD"], corner_radius=0)
        self.info_box.pack(fill="both", expand=True, padx=6, pady=(0, 10))
        self.label(self.info_box, "Gathering hardware details…", 12, color=P["MUTED"]).pack(pady=20)
        self.sysinfo_text = ""

        right = self.card(p)
        right.grid(row=0, column=1, sticky="nsew")
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=(14, 8))
        self.caption(top, "All sensors").pack(side="left")
        self.sensor_count = self.label(top, "", 10, color=P["MUTED"])
        self.sensor_count.pack(side="left", padx=10)
        self.sensor_filter = ctk.CTkOptionMenu(top, values=["All types", "Temperature", "Load", "Clock", "Power", "Fan",
                                                            "Control", "Voltage", "Data", "SmallData", "Throughput"],
                                               width=130, height=28, corner_radius=14, fg_color=P["CARD2"],
                                               button_color=P["CARD2"], button_hover_color=P["LINE"],
                                               dropdown_fg_color=P["CARD2"], text_color=P["TEXT"], font=F(11),
                                               command=lambda _v: self._rebuild_sensors())
        self.sensor_filter.pack(side="right")
        self.sensor_search = ctk.CTkEntry(top, placeholder_text="Search sensors…", width=180, height=28,
                                          corner_radius=14, fg_color=P["CARD2"], border_width=0, text_color=P["TEXT"], font=F(11))
        self.sensor_search.pack(side="right", padx=8)
        self.sensor_search.bind("<KeyRelease>", lambda e: self._rebuild_sensors())
        wrap = ctk.CTkFrame(right, fg_color=P["CARD"])
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        cols = ("value", "min", "max")
        self.tree = ttk.Treeview(wrap, columns=cols, style="Dark.Treeview", show="tree headings")
        self.tree.heading("#0", text="Sensor", anchor="w")
        self.tree.column("#0", width=260, stretch=True)
        for c, t in zip(cols, ("Value", "Min", "Max")):
            self.tree.heading(c, text=t, anchor="e")
            self.tree.column(c, width=90, anchor="e", stretch=False)
        self.tree.tag_configure("group", foreground=P["MUTED"], font=(FONT, 10, "bold"))
        self.tree.tag_configure("hw", foreground=P["TEXT"], font=(FONT, 11, "bold"))
        sb = ctk.CTkScrollbar(wrap, command=self.tree.yview, button_color=P["CARD2"], button_hover_color=P["LINE"])
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
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
        g["ring"].set(m.get("cpu_load"), fmt(m.get("cpu_load"), "%"), "load", acc)
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Temperature"); v1.configure(text=fmt(m.get("cpu_temp"), "°C"), text_color=temp_color(m.get("cpu_temp")))
        l2.configure(text="Clock"); v2.configure(text=fmt((m.get("cpu_clock") or 0) / 1000 if m.get("cpu_clock") else None, " GHz", 2))
        l3.configure(text="Power"); v3.configure(text=fmt(m.get("cpu_power"), " W"))
        g["spark"].set(hist.get("cpu_load", []), 100, acc)
        # GPU
        g = self.g_gpu
        g["name"].configure(text=(m.get("gpu_name") or "")[:26])
        g["ring"].set(m.get("gpu_load"), fmt(m.get("gpu_load"), "%"), "load", acc)
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Temperature"); v1.configure(text=fmt(m.get("gpu_temp"), "°C"), text_color=temp_color(m.get("gpu_temp")))
        l2.configure(text="Clock"); v2.configure(text=fmt(m.get("gpu_clock"), " MHz"))
        vu, vt = m.get("vram_used"), m.get("vram_total")
        l3.configure(text="VRAM"); v3.configure(text=f"{vu/1024:.1f} / {vt/1024:.0f} GB" if vu and vt else fmt(vu, " MB"))
        g["spark"].set(hist.get("gpu_load", []) or [0, 0], 100, acc)
        # RAM
        g = self.g_ram
        g["ring"].set(m.get("ram_pct"), fmt(m.get("ram_pct"), "%"), "used", acc)
        (l1, v1), (l2, v2), (l3, v3) = g["rows"]["a"], g["rows"]["b"], g["rows"]["c"]
        l1.configure(text="Used"); v1.configure(text=fmt(m.get("ram_used"), " GB", 1))
        l2.configure(text="Total"); v2.configure(text=fmt(m.get("ram_total"), " GB", 1))
        l3.configure(text="Free"); v3.configure(text=fmt((m.get("ram_total") or 0) - (m.get("ram_used") or 0), " GB", 1) if m.get("ram_total") else "—")
        g["spark"].set(hist.get("ram_pct", []), 100, acc)
        # network
        def rate(v):
            return "—" if v is None else (f"{v:.1f} Mb/s" if v < 1000 else f"{v/1000:.2f} Gb/s")
        self.net_down.configure(text=rate(m.get("net_down")))
        self.net_up.configure(text=rate(m.get("net_up")))
        self.net_spark.set(hist.get("net_down", []))
        self.net_spark2.set(hist.get("net_up", []))
        # disks
        self.disk_io.configure(text=f"R {fmt(m.get('disk_read'), ' MB/s', 1)} · W {fmt(m.get('disk_write'), ' MB/s', 1)}")
        for mount, used, total, pct in m.get("disks", []):
            if mount not in self.disk_rows:
                r = ctk.CTkFrame(self.disk_box, fg_color="transparent")
                r.pack(fill="x", pady=5)
                top = ctk.CTkFrame(r, fg_color="transparent")
                top.pack(fill="x")
                self.label(top, mount, 12, "bold").pack(side="left")
                v = self.label(top, "", 11, color=P["MUTED"])
                v.pack(side="right")
                bar = ctk.CTkProgressBar(r, height=8, corner_radius=4, fg_color=P["TRACK"], progress_color=acc)
                bar.pack(fill="x", pady=(4, 0))
                self.disk_rows[mount] = (v, bar)
            v, bar = self.disk_rows[mount]
            v.configure(text=f"{used:,.0f} / {total:,.0f} GB")
            bar.set(pct / 100)
            bar.configure(progress_color=BAD if pct > 90 else acc)
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
            sub.configure(text={"ok": f"{len(s['sensors'])} sensors · {len(s['fans'])} fans",
                                "basic": "Basic stats only", "starting": "Loading…"}.get(s["status"], ""))
            if self.current_page == "Monitor":
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

    # ---------------------------------------------------------------- Profiles
    def _page_profiles(self, p):
        self.header(p, "Profiles", "Save looks you like and switch between them in one click.")
        save = self.card(p)
        save.pack(fill="x", pady=(0, 14))
        row = ctk.CTkFrame(save, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=14)
        self.profile_name = ctk.CTkEntry(row, placeholder_text="Name this look…", height=40, corner_radius=20,
                                         font=F(13), fg_color=P["CARD2"], border_width=0, text_color=P["TEXT"])
        self.profile_name.pack(side="left", fill="x", expand=True)
        self.profile_name.bind("<Return>", lambda e: self._save_profile())
        self.primary(row, "Save current", self._save_profile, height=40, width=140).pack(side="left", padx=(10, 0))
        self.prof_area = ctk.CTkScrollableFrame(p, fg_color=P["BG"], corner_radius=0)
        self.prof_area.pack(fill="both", expand=True)
        self.prof_area.grid_columnconfigure((0, 1, 2), weight=1, uniform="p")
        self._refresh_profiles()

    def _refresh_profiles(self):
        for w in self.prof_area.winfo_children():
            w.destroy()
        for i, (name, st) in enumerate(sorted(self.settings["profiles"].items())):
            c = self.card(self.prof_area)
            c.grid(row=i // 3, column=i % 3, sticky="ew", padx=6, pady=6)
            strip = LedStrip(c, n=16, height=30, pill=True)
            strip.pack(fill="x", padx=16, pady=(16, 6))
            cols = eng.compute_colors("Rainbow Wave" if st["effect"] == "Color Cycle" else st["effect"],
                                      st["color"], max(st["brightness"], 40), 50, 16, 0)
            strip.after(60, lambda s=strip, c2=cols: s.show(c2))
            self.label(c, name, 15, "bold", anchor="w").pack(fill="x", padx=18)
            self.label(c, f"{st['effect']} · {hexcol(st['color']).upper()} · {st['brightness']}%", 11,
                       color=P["MUTED"], anchor="w").pack(fill="x", padx=18)
            r = ctk.CTkFrame(c, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=(10, 14))
            self.secondary(r, "Load", lambda n=name: self._load_profile(n), height=32).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(r, text="✕", width=34, height=32, corner_radius=16, fg_color=P["CARD2"], hover_color="#4a1f28",
                          text_color=P["MUTED"], command=lambda n=name: self._delete_profile(n)).pack(side="left", padx=(6, 0))

    # ---------------------------------------------------------------- Settings
    def _page_settings(self, p):
        self.header(p, "Settings", "System check, appearance and startup options.")
        top = ctk.CTkFrame(p, fg_color="transparent")
        top.pack(fill="x")
        top.grid_columnconfigure(0, weight=3)
        top.grid_columnconfigure(1, weight=2)
        chk = self.card(top)
        chk.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        hr = ctk.CTkFrame(chk, fg_color="transparent")
        hr.pack(fill="x", padx=20, pady=(16, 6))
        self.caption(hr, "System check").pack(side="left")
        self.secondary(hr, "Run again", lambda: self._bg(self._run_check), height=26, width=90, corner_radius=13).pack(side="right")
        self.check_list = ctk.CTkFrame(chk, fg_color="transparent")
        self.check_list.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        opt = self.card(top)
        opt.grid(row=0, column=1, sticky="nsew")
        self.caption(opt, "Appearance").pack(fill="x", padx=20, pady=(16, 6))
        self.glass_sw = ctk.CTkSwitch(opt, text="Frosted glass window", font=F(12), text_color=P["TEXT"],
                                      command=self._toggle_glass)
        self.glass_sw.pack(anchor="w", padx=20, pady=4)
        if self.settings.data.get("glass", True):
            self.glass_sw.select()
        if not fx.glass_supported():
            self.glass_sw.configure(text="Frosted glass (Windows 10/11 only)")
        r, self.opacity = self.slider_row(opt, "Window opacity", int(self.settings.data.get("opacity", 100)),
                                          self._set_opacity, lo=60, hi=100)
        r.pack(fill="x", padx=20, pady=(8, 4))
        self.caption(opt, "Startup").pack(fill="x", padx=20, pady=(14, 6))
        self.autostart_sw = ctk.CTkSwitch(opt, text="Start with Windows", font=F(12), text_color=P["TEXT"],
                                          command=self._toggle_autostart)
        self.autostart_sw.pack(anchor="w", padx=20, pady=4)
        if self._autostart_enabled():
            self.autostart_sw.select()
        self.restore_sw = ctk.CTkSwitch(opt, text="Re-apply lighting on launch", font=F(12), text_color=P["TEXT"],
                                        command=lambda: self.settings.__setitem__("restore_on_start", self.restore_sw.get() == 1))
        self.restore_sw.pack(anchor="w", padx=20, pady=4)
        if self.settings["restore_on_start"]:
            self.restore_sw.select()
        self.caption(opt, "Helpers").pack(fill="x", padx=20, pady=(14, 6))
        for txt, cmd in (("Get PawnIO driver", lambda: webbrowser.open(eng.PAWNIO_PAGE)),
                         ("Locate OpenRGB.exe", self._browse_openrgb),
                         ("OpenRGB supported devices", lambda: webbrowser.open(eng.RELEASES_PAGE))):
            self.secondary(opt, txt, cmd, height=32, anchor="w", corner_radius=16).pack(fill="x", padx=20, pady=3)
        ctk.CTkFrame(opt, fg_color="transparent", height=12).pack()

        logc = self.card(p)
        logc.pack(fill="both", expand=True, pady=(16, 0))
        self.caption(logc, "Activity").pack(fill="x", padx=20, pady=(14, 4))
        self.logbox = ctk.CTkTextbox(logc, fg_color=P["CARD"], text_color=P["TEXT"], font=ctk.CTkFont(family=MONO, size=11),
                                     corner_radius=0, border_width=0, wrap="word")
        self.logbox.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for tag, col in (("ok", OK), ("warn", WARN), ("bad", BAD), ("info", INFO)):
            self.logbox.tag_config(tag, foreground=col)
        self.logbox.configure(state="disabled")

    def _show_checks(self, results):
        for w in self.check_list.winfo_children():
            w.destroy()
        icons = {"ok": ("✓", OK), "warn": ("!", WARN), "bad": ("✕", BAD), "info": ("i", INFO)}
        for level, msg in results:
            g, col = icons.get(level, ("•", P["MUTED"]))
            r = ctk.CTkFrame(self.check_list, fg_color=P["CARD2"], corner_radius=12)
            r.pack(fill="x", pady=3)
            ctk.CTkLabel(r, text=g, width=24, height=24, corner_radius=12, fg_color=col, text_color="#0b0b0b",
                         font=F(12, "bold")).pack(side="left", padx=10, pady=8)
            self.label(r, msg, 11, anchor="w", justify="left", wraplength=470).pack(side="left", fill="x", expand=True, padx=(0, 10), pady=6)

    def _toggle_glass(self):
        on = self.glass_sw.get() == 1
        self.settings["glass"] = on
        messagebox.showinfo(eng.APP_NAME, f"Frosted glass will be turned {'on' if on else 'off'} the next time "
                                          "Central RGB starts.")

    def _set_opacity(self, v):
        self.settings.data["opacity"] = v
        self.settings.save()
        fx.set_opacity(self, v)

    # ---------------------------------------------------------------- navigation / accent / animation
    def show_page(self, name):
        self.current_page = name
        self.pages[name].tkraise()
        for n, b in self.nav.items():
            on = n == name
            b.configure(fg_color=P["CARD"] if on else "transparent", text_color=P["TEXT"] if on else P["MUTED"])
            self.nav_bars[n].configure(fg_color=self.accent if on else P["SIDE"])
        if name in ("Monitor", "Fans"):
            self.after(10, lambda: (self._refresh_monitor(self.snap) if name == "Monitor" else self._refresh_fans(self.snap)))

    def _update_accent(self):
        h, s, v = colorsys.rgb_to_hsv(*(x / 255 for x in self.color))
        if self.effect in ("Color Cycle", "Rainbow Wave", "Off") or s < 0.25:
            acc = DEFAULT_ACCENT
        else:
            acc = hexcol([c * 255 for c in colorsys.hsv_to_rgb(h, min(1, s) * 0.85, 0.95)])
        self.accent = acc
        hov = hexcol(mix(hex2rgb(acc), (255, 255, 255), 0.15))
        for kind, w in self.accent_widgets:
            try:
                if kind == "button":
                    w.configure(fg_color=acc, hover_color=hov)
                elif kind == "slider":
                    w.configure(progress_color=acc)
                elif kind == "seg":
                    w.configure(selected_color=acc, selected_hover_color=hov)
            except tk.TclError:
                pass
        for n, t in self.tiles.items():
            t.select(n == self.effect, acc)
        for sw in (self.autostart_sw, self.restore_sw, self.glass_sw):
            sw.configure(progress_color=acc)
        for card in self.device_cards:
            card.switch.configure(progress_color=acc)
        if hasattr(self, "nav_bars"):
            self.nav_bars[self.current_page].configure(fg_color=acc)

    def _animate(self):
        t = time.time()
        st = self._current_state()
        try:
            self.preview.show(eng.compute_colors(st["effect"], st["color"], max(st["brightness"], 8), st["speed"], 40, t))
            if self.current_page == "Lighting":
                for name, tile in self.tiles.items():
                    tile.strip.show(eng.compute_colors(name, self.color, 100, 50, 12, t))
            elif self.current_page == "Devices":
                ex = set(self.settings["excluded"])
                for i, card in enumerate(self.device_cards):
                    card.strip.show([(0, 0, 0)] if card.key in ex else eng.compute_colors(
                        st["effect"], st["color"], max(st["brightness"], 8), st["speed"], card.strip.n, t, offset=i * 0.07))
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

    def _connect_flow(self):
        if not self.manager.server_running():
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
        for delay in (4000, 12000):
            self.q.put(("call", lambda d=delay: self.after(d, lambda: self._bg(self._rescan, False, True))))
        if self.settings["restore_on_start"] or self.background:
            self.engine.paused = False
            self.engine.force_reapply()

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
        self.hex_entry.delete(0, "end")
        self.hex_entry.insert(0, hexcol(self.color).upper())
        self.preview_label.configure(text=f"{self.effect.upper()} · {hexcol(self.color).upper()}")
        self._update_accent()

    def _state_changed(self):
        st = self._current_state()
        self.engine.set_state(**st)
        if self.connected:
            self.engine.paused = False
        self.settings["state"] = st
        self.preview_label.configure(text=f"{self.effect.upper()} · {hexcol(self.color).upper()}")

    def _set_color(self, rgb, from_wheel=False):
        self.color = tuple(int(c) for c in rgb)
        if self.effect in ("Off", "Color Cycle", "Rainbow Wave"):
            self.effect = "Static"
        if not from_wheel:
            self.wheel.set_rgb(self.color)
        self.swatch.itemconfigure(self.swatch_item, fill=hexcol(self.color))
        self.hex_entry.delete(0, "end")
        self.hex_entry.insert(0, hexcol(self.color).upper())
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
        self.settings["state"] = self._current_state()
        self.engine.stop()
        self.monitor.stop()       # hands fans back to the BIOS
        self.destroy()


def main():
    if eng.IS_WIN:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            # own taskbar identity, so Windows shows the Central RGB icon (not Python's)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CentralRGB.App")
        except Exception:
            pass
    App(background="--background" in sys.argv).mainloop()


if __name__ == "__main__":
    main()
