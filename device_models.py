"""Component models for the device editor: RAM, graphics card, fans, cooler, strip, keyboard, mouse, board.

Each model is drawn in two layers:
  * the body (metal, plastic, PCB), rendered once at 2x and cached
  * the lights, redrawn every frame from the device's live LED colors and given a soft bloom
so the picture always shows exactly what the hardware is doing.
All artwork is original (no vendor logos)."""
from __future__ import annotations

import colorsys
import math
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SS = 2  # supersampling for the body


# ---------------------------------------------------------------- helpers
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _vgrad(w, h, top, bottom):
    g = Image.linear_gradient("L").resize((max(1, w), max(1, h)))
    return Image.composite(Image.new("RGB", (w, h), bottom), Image.new("RGB", (w, h), top), g)


def _rr_mask(w, h, r):
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def _poly_mask(size, pts):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m


def _paste_grad(img, box, top, bottom, mask=None, radius=0):
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = x1 - x0, y1 - y0
    g = _vgrad(w, h, top, bottom)
    if mask is None:
        mask = _rr_mask(w, h, radius) if radius else Image.new("L", (w, h), 255)
    img.paste(g, (x0, y0), mask)


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _sample(colors, t, wrap=False):
    """Color at position t (0..1) along a list of LED colors, blended between neighbours."""
    n = len(colors)
    if n == 1:
        return tuple(colors[0])
    if wrap:
        f = (t % 1.0) * n
        i = int(f) % n
        return _lerp(colors[i], colors[(i + 1) % n], f - int(f))
    f = min(max(t, 0.0), 1.0) * (n - 1)
    i = min(int(f), n - 2)
    return _lerp(colors[i], colors[i + 1], f - i)


def _bloom(base, light, strength=1.0, radius=12):
    """Add the light layer on top of the body with a wide soft glow and a tight bright core."""
    wide = light.filter(ImageFilter.GaussianBlur(radius))
    tight = light.filter(ImageFilter.GaussianBlur(max(1, radius // 4)))
    if strength != 1.0:
        wide = wide.point(lambda v: min(255, int(v * strength)))
    out = ImageChops.add(base, wide)
    out = ImageChops.add(out, tight)
    return ImageChops.lighter(out, light)


# ---------------------------------------------------------------- base class
class Model:
    W, H = 560, 260
    BG = (18, 24, 33)

    def __init__(self, n_leds, bg=None):
        self.n = max(1, n_leds)
        if bg:
            self.BG = _rgb(bg) if isinstance(bg, str) else tuple(bg)
        big = Image.new("RGB", (self.W * SS, self.H * SS), self.BG)
        self.body_big(big, ImageDraw.Draw(big))
        self.body = big.resize((self.W, self.H), Image.LANCZOS)

    def body_big(self, img, d):           # draw the body at SS scale
        pass

    def lights(self, img, d, colors):     # draw the LEDs (1x scale) on a black layer
        pass

    def render(self, colors) -> Image.Image:
        colors = [tuple(c) for c in colors] or [(0, 0, 0)]
        light = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        self.lights(light, ImageDraw.Draw(light), colors)
        return _bloom(self.body, light, *self.glow)

    glow = (0.9, 12)


# metal palette
GM_TOP, GM_BOT, GM_EDGE, GM_DARK = (92, 97, 106), (48, 52, 59), (128, 134, 144), (30, 33, 38)


def _fan(img, d, cx, cy, r, s=SS, frame=True, blades=9):
    """A fan seen from the front: square frame, ring diffuser, translucent blades, hub."""
    if frame:
        fr = r * 1.18
        _paste_grad(img, (cx - fr, cy - fr, cx + fr, cy + fr), (60, 64, 72), (34, 37, 43), radius=int(fr * 0.22))
        d.rounded_rectangle((cx - fr, cy - fr, cx + fr, cy + fr), int(fr * 0.22), outline=(96, 102, 112), width=s)
        for sx in (-1, 1):
            for sy in (-1, 1):
                hx, hy = cx + sx * fr * 0.80, cy + sy * fr * 0.80
                hr = fr * 0.07
                d.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=(18, 20, 24), outline=(90, 95, 104), width=s)
    d.ellipse((cx - r * 1.04, cy - r * 1.04, cx + r * 1.04, cy + r * 1.04), fill=(22, 24, 28))
    d.ellipse((cx - r * 0.93, cy - r * 0.93, cx + r * 0.93, cy + r * 0.93), fill=(12, 13, 16))
    for k in range(blades):                                   # curved blades
        a0 = k * 2 * math.pi / blades
        pts = []
        for i in range(9):
            t = i / 8
            rr = r * (0.30 + 0.60 * t)
            a = a0 + 0.9 * t
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        for i in range(8, -1, -1):
            t = i / 8
            rr = r * (0.30 + 0.60 * t)
            a = a0 + 0.9 * t + 0.42 - 0.12 * t
            pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
        d.polygon(pts, fill=(54, 58, 66), outline=(78, 83, 92))
    hr = r * 0.32
    hx0, hy0, dia = int(cx - hr), int(cy - hr), int(2 * hr)
    _paste_grad(img, (hx0, hy0, hx0 + dia, hy0 + dia), (74, 78, 86), (38, 41, 47), mask=_circle_mask(dia))
    d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr), outline=(104, 110, 120), width=s)
    d.ellipse((cx - hr * 0.35, cy - hr * 0.35, cx + hr * 0.35, cy + hr * 0.35), fill=(26, 28, 32))


@lru_cache(maxsize=32)
def _circle_mask(dia):
    m = Image.new("L", (dia, dia), 0)
    ImageDraw.Draw(m).ellipse((0, 0, dia - 1, dia - 1), fill=255)
    return m


def _ring_lights(d, cx, cy, r, colors, width, segs=90, start=-90, blade_tint=True):
    """An RGB ring around a fan, colored along its LEDs, plus a faint tint on the blades."""
    for k in range(segs):
        a0 = start + k * 360 / segs
        col = _sample(colors, k / segs, wrap=True)
        d.arc((cx - r, cy - r, cx + r, cy + r), a0, a0 + 360 / segs + 1.2, fill=col, width=width)
    if blade_tint:
        avg = tuple(sum(c[i] for c in colors) // len(colors) for i in range(3))
        dim = tuple(int(v * 0.22) for v in avg)
        rr = r * 0.82
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=dim)
        hr = r * 0.3
        d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr), fill=(0, 0, 0))


# ---------------------------------------------------------------- RAM
class RamModel(Model):
    """A DDR5 stick: brushed gunmetal heat spreader with an inset plate, vent slots, top light bar."""
    X0, X1, BAR_Y0, BAR_Y1, BODY_Y1, PCB_Y1 = 40, 520, 44, 70, 196, 222

    def body_big(self, img, d):
        s = SS
        x0, x1 = self.X0 * s, self.X1 * s
        by0, by1, py1 = self.BAR_Y1 * s, self.BODY_Y1 * s, self.PCB_Y1 * s
        # PCB and gold contacts
        _paste_grad(img, (x0 + 10 * s, by1 - 6 * s, x1 - 10 * s, py1), (20, 40, 30), (12, 26, 19))
        for i in range(58):
            cx = x0 + 18 * s + i * 7.9 * s
            if x0 + 228 * s < cx < x0 + 246 * s:
                continue
            d.rectangle((cx, py1 - 14 * s, cx + 4.6 * s, py1 - 2 * s), fill=(200, 160, 70))
        d.rectangle((x0 + 230 * s, py1 - 16 * s, x0 + 244 * s, py1), fill=self.BG)          # key notch
        # diffuser housing above the spreader
        bar0 = self.BAR_Y0 * s
        _paste_grad(img, (x0 + 4 * s, bar0 - 6 * s, x1 - 4 * s, by0 + 4 * s), (44, 47, 54), (26, 28, 33), radius=8 * s)
        d.rounded_rectangle((x0 + 12 * s, bar0, x1 - 12 * s, by0), 6 * s, fill=(10, 11, 13))
        # heat spreader with chamfered corners
        c = 14 * s
        pts = [(x0, by0 + c), (x0 + c, by0), (x1 - c, by0), (x1, by0 + c), (x1, by1 - 8 * s), (x1 - 8 * s, by1),
               (x0 + 8 * s, by1), (x0, by1 - 8 * s)]
        w, h = x1 - x0, by1 - by0
        g = _vgrad(w, h, GM_TOP, GM_BOT)
        brushed = Image.effect_noise((w, h), 18).filter(ImageFilter.BoxBlur(0)).resize((w // 8, h)).resize((w, h))
        g = Image.blend(g, Image.merge("RGB", [ImageChops.multiply(ch, brushed.point(lambda v: 200 + v // 5))
                                                for ch in g.split()]), 0.5)
        img.paste(g, (x0, by0), _poly_mask((w, h), [(px - x0, py - by0) for px, py in pts]))
        d.line(pts + [pts[0]], fill=GM_EDGE, width=s)
        d.line((x0 + c, by0 + s, x1 - c, by0 + s), fill=(160, 166, 176), width=s)        # top highlight
        # inset nameplate (angled ends) and vent slots
        ix0, ix1, iy0, iy1 = x0 + 92 * s, x0 + 330 * s, by0 + 36 * s, by1 - 34 * s
        k = 20 * s
        plate = [(ix0 + k, iy0), (ix1, iy0), (ix1 - k, iy1), (ix0, iy1)]
        d.polygon(plate, fill=(40, 43, 49))
        d.line(plate + [plate[0]], fill=(110, 116, 126), width=s)
        d.line((ix0 + k, iy0 + s, ix1, iy0 + s), fill=(20, 22, 26), width=2 * s)
        for i in range(3):
            yy = iy0 + (iy1 - iy0) * (0.35 + 0.15 * i)
            d.line((ix0 + k * 1.6 + i * 6 * s, yy, ix1 - k * 1.8 - i * 6 * s, yy), fill=(60, 64, 72), width=s)
        for row in range(4):
            for col in range(7):
                vx = x0 + 356 * s + col * 15 * s + (row % 2) * 7 * s
                vy = by0 + 30 * s + row * 22 * s
                d.rounded_rectangle((vx, vy, vx + 9 * s, vy + 13 * s), 4 * s, fill=(22, 24, 28),
                                    outline=(70, 75, 84), width=s)
        for i in range(4):
            yy = by1 - 14 * s - i * 6 * s
            d.line((x0 + 20 * s, yy, x0 + 70 * s - i * 8 * s, yy), fill=(70, 75, 84), width=s)

    def lights(self, img, d, colors):
        x0, x1 = self.X0 + 13, self.X1 - 13
        y0, y1 = self.BAR_Y0 + 1, self.BAR_Y1 - 1
        w = x1 - x0
        for x in range(w):                                  # smooth diffuser gradient along the bar
            col = _sample(colors, x / max(1, w - 1))
            d.line((x0 + x, y0 + 2, x0 + x, y1 - 2), fill=col)
        # brighter LED hot spots under the diffuser
        n = len(colors)
        for i, col in enumerate(colors):
            cx = x0 + (i + 0.5) * w / n
            hot = tuple(min(255, int(v * 0.6 + 100 * (v > 0))) for v in col)
            d.ellipse((cx - 3, (y0 + y1) / 2 - 3, cx + 3, (y0 + y1) / 2 + 3), fill=hot)

    glow = (1.0, 14)


# ---------------------------------------------------------------- graphics card
class GpuModel(Model):
    """Triple-fan graphics card: angular gunmetal shroud, RGB fan rings, edge light strip, PCIe bracket."""
    FANS = [(150, 128), (280, 128), (410, 128)]
    FR = 56

    def body_big(self, img, d):
        s = SS
        x0, x1, y0, y1 = 44 * s, 528 * s, 50 * s, 208 * s
        # backplate / PCB edge and PCIe connector
        _paste_grad(img, (x0 + 14 * s, y1 - 8 * s, x1 - 40 * s, y1 + 18 * s), (28, 30, 34), (16, 17, 20))
        for i in range(36):
            cx = x0 + 120 * s + i * 6.2 * s
            if x0 + 150 * s < cx < x0 + 160 * s:
                continue
            d.rectangle((cx, y1 + 10 * s, cx + 3.6 * s, y1 + 20 * s), fill=(200, 160, 70))
        # heatsink fins peeking out under the shroud
        for i in range(70):
            fx = x0 + 30 * s + i * 6.4 * s
            d.line((fx, y1 - 6 * s, fx, y1 + 6 * s), fill=(70, 74, 82), width=s)
        # bracket
        _paste_grad(img, (18 * s, 34 * s, 40 * s, 224 * s), (150, 154, 162), (96, 100, 108))
        for i in range(4):
            d.rounded_rectangle((24 * s, (60 + i * 34) * s, 34 * s, (84 + i * 34) * s), 3 * s, fill=(30, 32, 36))
        # shroud with cut corners
        c = 22 * s
        pts = [(x0, y0 + c), (x0 + c, y0), (x1 - c * 2, y0), (x1, y0 + c * 2), (x1, y1 - c), (x1 - c, y1),
               (x0 + c, y1), (x0, y1 - c)]
        w, h = x1 - x0, y1 - y0
        img.paste(_vgrad(w, h, (82, 87, 96), (40, 43, 49)), (x0, y0), _poly_mask((w, h), [(px - x0, py - y0) for px, py in pts]))
        d.line(pts + [pts[0]], fill=GM_EDGE, width=s)
        # angular accent panels
        for a, b in (((x0 + 8 * s, y0 + 40 * s), (x0 + 40 * s, y1 - 40 * s)), ((x1 - 30 * s, y0 + 60 * s), (x1 - 8 * s, y1 - 40 * s))):
            d.polygon([a, (b[0], a[1] + 14 * s), b, (a[0], b[1] - 14 * s)], fill=(34, 37, 42))
        d.line((x0 + c, y0 + s, x1 - c * 2, y0 + s), fill=(160, 166, 176), width=s)
        # light strip housing along the top edge
        d.rounded_rectangle((x0 + 70 * s, y0 - 2 * s, x1 - 110 * s, y0 + 6 * s), 3 * s, fill=(10, 11, 13))
        for fx, fy in self.FANS:
            _fan(img, d, fx * s, fy * s, self.FR * s, frame=False)
            d.ellipse(((fx - self.FR - 8) * s, (fy - self.FR - 8) * s, (fx + self.FR + 8) * s, (fy + self.FR + 8) * s),
                      outline=(110, 116, 126), width=s)

    def lights(self, img, d, colors):
        n = len(colors)
        strip_n = max(1, n // 5)
        ring = colors[strip_n:] or colors
        per = max(1, len(ring) // 3)
        for k, (fx, fy) in enumerate(self.FANS):
            seg = ring[k * per:(k + 1) * per] or ring
            _ring_lights(d, fx, fy, self.FR + 2, seg, 4)
        sx0, sx1, sy = 44 + 72, 528 - 112, 50 + 2
        strip = colors[:strip_n]
        for x in range(sx1 - sx0):
            d.line((sx0 + x, sy - 1, sx0 + x, sy + 2), fill=_sample(strip, x / (sx1 - sx0)))

    glow = (0.9, 12)


# ---------------------------------------------------------------- fans
class FanModel(Model):
    """A row of three overlapping RGB fans (case fans / AIO radiator)."""
    POS = [(170, 138), (280, 128), (390, 118)]
    R = 74
    COUNT = 3

    def __init__(self, n_leds, bg=None, count=3):
        self.COUNT = count
        if count == 1:
            self.POS, self.R = [(280, 130)], 92
        super().__init__(n_leds, bg)

    def body_big(self, img, d):
        for fx, fy in reversed(self.POS):                    # back to front
            img_s = SS
            _fan(img, d, fx * img_s, fy * img_s, self.R * img_s)

    def lights(self, img, d, colors):
        per = max(1, len(colors) // len(self.POS))
        for k, (fx, fy) in reversed(list(enumerate(self.POS))):
            seg = colors[k * per:(k + 1) * per] or colors
            # clear the area hidden by the fan in front so rings layer correctly
            fr = self.R * 1.18
            d.rounded_rectangle((fx - fr, fy - fr, fx + fr, fy + fr), int(fr * 0.22), fill=(0, 0, 0))
            _ring_lights(d, fx, fy, self.R * 0.99, seg, 5)
            _ring_lights(d, fx, fy, self.R * 0.36, seg, 2, segs=40, blade_tint=False)

    def render(self, colors):
        # rings of back fans must be hidden by the bodies of front fans: render back to front
        colors = [tuple(c) for c in colors] or [(0, 0, 0)]
        light = Image.new("RGB", (self.W, self.H), (0, 0, 0))
        self.lights(light, ImageDraw.Draw(light), colors)
        return _bloom(self.body, light, *self.glow)

    glow = (0.85, 13)


# ---------------------------------------------------------------- LED strip / mousepad
class StripModel(Model):
    def body_big(self, img, d):
        s = SS
        _paste_grad(img, (40 * s, 112 * s, 520 * s, 148 * s), (44, 47, 54), (24, 26, 30), radius=10 * s)
        d.rounded_rectangle((52 * s, 122 * s, 508 * s, 138 * s), 6 * s, fill=(10, 11, 13))

    def lights(self, img, d, colors):
        for x in range(452):
            d.line((54 + x, 124, 54 + x, 136), fill=_sample(colors, x / 451))

    glow = (1.0, 16)


# ---------------------------------------------------------------- keyboard
class KeyboardModel(Model):
    ROWS = [15, 15, 14, 13, 12]

    def body_big(self, img, d):
        s = SS
        _paste_grad(img, (30 * s, 52 * s, 530 * s, 214 * s), (58, 62, 70), (30, 33, 38), radius=14 * s)
        d.rounded_rectangle((30 * s, 52 * s, 530 * s, 214 * s), 14 * s, outline=GM_EDGE, width=s)
        self.keys = []
        for r, cnt in enumerate(self.ROWS):
            kw = 468 / cnt
            for c in range(cnt):
                x = 46 + c * kw
                y = 66 + r * 28
                self.keys.append((x, y, x + kw - 5, y + 23))
                d.rounded_rectangle((x * s, y * s, (x + kw - 5) * s, (y + 23) * s), 4 * s, fill=(26, 28, 32),
                                    outline=(60, 64, 72), width=s)

    def lights(self, img, d, colors):
        n = len(self.keys)
        for i, (x0, y0, x1, y1) in enumerate(self.keys):
            col = _sample(colors, i / max(1, n - 1))
            d.rounded_rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), 4, outline=col, width=2)
            dim = tuple(int(v * 0.35) for v in col)
            d.rounded_rectangle((x0 + 5, y0 + 5, x0 + 11, y0 + 9), 1, fill=dim)

    glow = (0.6, 6)


# ---------------------------------------------------------------- mouse
class MouseModel(Model):
    def body_big(self, img, d):
        s = SS
        w, h = 150 * s, 220 * s
        x0, y0 = 205 * s, 20 * s
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), 70 * s, fill=255)
        img.paste(_vgrad(w, h, (70, 74, 82), (30, 33, 38)), (x0, y0), m)
        d.line((x0 + w // 2, y0 + 8 * s, x0 + w // 2, y0 + 90 * s), fill=(20, 22, 26), width=2 * s)
        d.rounded_rectangle((x0 + w // 2 - 8 * s, y0 + 34 * s, x0 + w // 2 + 8 * s, y0 + 70 * s), 8 * s,
                            fill=(24, 26, 30), outline=(90, 95, 104), width=s)

    def lights(self, img, d, colors):
        d.rounded_rectangle((276, 36, 284, 72), 4, fill=_sample(colors, 0))
        for k in range(60):                                       # logo-free light ring near the palm
            col = _sample(colors, k / 60, wrap=True)
            d.arc((248, 150, 312, 214), k * 6, k * 6 + 7, fill=col, width=3)

    glow = (1.0, 12)


# ---------------------------------------------------------------- motherboard
class BoardModel(Model):
    def body_big(self, img, d):
        s = SS
        _paste_grad(img, (120 * s, 18 * s, 440 * s, 242 * s), (26, 30, 36), (16, 18, 22), radius=6 * s)
        _paste_grad(img, (230 * s, 50 * s, 320 * s, 140 * s), (70, 74, 82), (40, 43, 49), radius=6 * s)   # socket
        for i in range(4):                                                                              # DIMM slots
            d.rectangle(((338 + i * 14) * s, 40 * s, (346 + i * 14) * s, 170 * s), fill=(34, 37, 42))
        for i in range(3):                                                                              # PCIe
            d.rectangle((150 * s, (170 + i * 22) * s, 330 * s, (178 + i * 22) * s), fill=(34, 37, 42))
        _paste_grad(img, (130 * s, 30 * s, 210 * s, 150 * s), (82, 87, 96), (44, 47, 54), radius=8 * s)   # VRM cover

    def lights(self, img, d, colors):
        for y in range(150):                                    # edge light down the right side
            d.line((432, 40 + y, 436, 40 + y), fill=_sample(colors, y / 149))
        for x in range(70):
            d.line((136 + x, 144, 136 + x, 147), fill=_sample(colors, x / 69))

    glow = (1.0, 12)


class GenericModel(StripModel):
    pass


KINDS = {"RAM": RamModel, "GPU": GpuModel, "Cooler": FanModel, "Case": FanModel, "Fan": FanModel,
         "LED strip": StripModel, "Mousepad": StripModel, "Keyboard": KeyboardModel, "Mouse": MouseModel,
         "Motherboard": BoardModel}


@lru_cache(maxsize=16)
def model_for(kind: str, n_leds: int, bg=None) -> Model:
    cls = KINDS.get(kind, GenericModel)
    if cls is FanModel and kind == "Cooler":
        return FanModel(n_leds, bg, count=1)
    return cls(n_leds, bg)


def rainbow(n, phase=0.0):
    return [tuple(int(v * 255) for v in colorsys.hsv_to_rgb((i / n + phase) % 1, 1, 1)) for i in range(n)]
