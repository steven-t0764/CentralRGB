"""Generates the preview artwork for the lighting presets (presets/*.jpg).

Run:  python tools/make_preset_art.py
All images are drawn from scratch with numpy + Pillow, so they're original and free to ship.
"""
import colorsys
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 480, 300
OUT = Path(__file__).resolve().parent.parent / "presets"
rng = random.Random(7)
nrng = np.random.default_rng(7)
Y, X = np.mgrid[0:H, 0:W].astype(np.float32)


def to_img(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def lerp(a, b, t):
    t = np.clip(t, 0, 1)[..., None]
    return np.array(a, np.float32) * (1 - t) + np.array(b, np.float32) * t


def noise(scale, octaves=4):
    out = np.zeros((H, W), np.float32)
    amp = 1.0
    for o in range(octaves):
        s = max(2, int(scale / 2 ** o))
        small = nrng.random((H // s + 2, W // s + 2)).astype(np.float32)
        img = Image.fromarray((small * 255).astype(np.uint8)).resize((W + 2 * s, H + 2 * s), Image.BICUBIC)
        out += np.asarray(img, np.float32)[s:s + H, s:s + W] / 255 * amp
        amp *= 0.5
    return (out - out.min()) / (out.max() - out.min() + 1e-6)


def glow(img, radius=8, strength=1.0):
    blur = img.filter(ImageFilter.GaussianBlur(radius))
    return to_img(np.asarray(img, np.float32) + np.asarray(blur, np.float32) * strength)


def calm_water():
    n = noise(140, 3)
    v = np.sin(X / 38 + n * 7 + np.sin(Y / 47) * 2.2)
    ridge = np.exp(-(v ** 2) * 9)
    base = lerp((2, 6, 18), (14, 40, 92), (Y / H) * 0.6 + n * 0.5)
    col = base + ridge[..., None] * np.array([150, 190, 235], np.float32) * (0.35 + 0.65 * n[..., None])
    return glow(to_img(col), 6, 0.4)


def rain():
    bg = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bg)
    for i in range(14):
        h = i / 14
        r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(h, 0.95, 1))
        x, y, s = rng.randint(-60, W), rng.randint(-60, H), rng.randint(90, 190)
        d.ellipse((x - s, y - s, x + s, y + s), fill=(r, g, b))
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    top = bg.copy()
    d = ImageDraw.Draw(top, "RGBA")
    for _ in range(170):
        x, y, r = rng.randint(0, W), rng.randint(0, H), rng.choice([3, 4, 5, 6, 8, 10, 13])
        d.ellipse((x - r, y - r, x + r, y + r), fill=(0, 0, 0, 70))                          # drop shadow rim
        d.ellipse((x - r + 1, y - r + 1, x + r - 1, y + r - 1), fill=(255, 255, 255, 40))
        d.ellipse((x - r * 0.45, y - r * 0.7, x - r * 0.05, y - r * 0.3), fill=(255, 255, 255, 200))  # highlight
    return top


def side_to_side():
    a = np.zeros((H, W, 3), np.float32)
    x = 0
    while x < W:
        w = rng.choice([10, 14, 18, 24, 30])
        h = (x / W * 0.95 + rng.uniform(-0.03, 0.03)) % 1
        a[:, x:x + w] = [c * 255 for c in colorsys.hsv_to_rgb(h, 0.85, 1)]
        x += w
    shade = 0.75 + 0.25 * np.sin(Y / H * math.pi)[..., None]
    img = to_img(a * shade).filter(ImageFilter.GaussianBlur(2.2))
    return glow(img, 4, 0.25)


def crimson():
    img = Image.new("RGB", (W, H), (6, 0, 0))
    big = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(big)
    for _ in range(22):                                        # out-of-focus background bubbles
        x, y, r = rng.randint(0, W), rng.randint(0, H), rng.randint(20, 60)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(rng.randint(80, 160), 0, 4))
    img = Image.blend(img, big.filter(ImageFilter.GaussianBlur(14)), 0.8)
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(26):
        x, y, r = rng.randint(0, W), rng.randint(0, H), rng.randint(8, 34)
        for k in range(6):                                     # glossy rim
            rr = r - k
            d.ellipse((x - rr, y - rr, x + rr, y + rr), outline=(255, 30 + k * 12, 20, 255 - k * 38), width=1)
        d.ellipse((x - r * 0.5, y - r * 0.7, x - r * 0.1, y - r * 0.35), fill=(255, 190, 170, 180))
    return glow(img, 7, 0.7)


def rgbarz():
    img = Image.new("RGB", (W, H), (8, 8, 12))
    d = ImageDraw.Draw(img)
    cols, gap = 26, 4
    bw = (W - gap * (cols + 1)) / cols
    for i in range(cols):
        level = 0.25 + 0.7 * abs(math.sin(i * 0.55) * math.cos(i * 0.21 + 1)) + rng.uniform(-0.08, 0.08)
        hue = i / cols * 0.85
        x0 = gap + i * (bw + gap)
        for j in range(int(level * 22)):
            y1 = H - 10 - j * 12
            r, g, b = (int(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.9, 1))
            d.rectangle((x0, y1 - 9, x0 + bw, y1), fill=(r, g, b))
    return glow(img, 9, 0.9)


def gradient_wave():
    t = (X / W) * 0.75 + (Y / H) * 0.35 + 0.06 * np.sin(Y / 30 + X / 70)
    stops = [(255, 50, 170), (175, 60, 255), (60, 90, 255), (0, 210, 255), (60, 255, 220)]
    t = np.clip(t, 0, 0.999) * (len(stops) - 1)
    i = t.astype(int)
    a = np.array(stops, np.float32)
    col = lerp(np.zeros(3), np.zeros(3), t)  # placeholder shape
    col = a[i] + (a[np.minimum(i + 1, len(stops) - 1)] - a[i]) * (t - i)[..., None]
    sheen = (0.85 + 0.15 * np.sin(X / 25 + Y / 60))[..., None]
    return to_img(col * sheen)


def neon_storm():
    n = noise(120, 4)
    col = lerp((20, 6, 60), (120, 40, 230), n ** 1.6)
    col = lerp(col, (40, 120, 255), np.clip((n - 0.62) * 3, 0, 1) * 0.6) if False else col
    img = to_img(col)
    bolts = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(bolts)
    for start in (150, 330):
        x, y = start + rng.randint(-30, 30), 0
        pts = [(x, y)]
        while y < H:
            x += rng.randint(-26, 26)
            y += rng.randint(14, 30)
            pts.append((x, y))
            if rng.random() < 0.25:                               # branch
                bx, by = x, y
                bp = [(bx, by)]
                for _ in range(rng.randint(2, 4)):
                    bx += rng.randint(-30, 30)
                    by += rng.randint(12, 24)
                    bp.append((bx, by))
                d.line(bp, fill=(150, 210, 255), width=2)
        d.line(pts, fill=(235, 245, 255), width=3)
    glowb = bolts.filter(ImageFilter.GaussianBlur(10))
    out = np.asarray(img, np.float32) + np.asarray(glowb, np.float32) * np.array([1.2, 1.0, 1.6]) + np.asarray(bolts, np.float32)
    return to_img(out)


def black_ice():
    n = noise(90, 4)
    col = lerp((2, 14, 30), (10, 70, 110), n ** 1.4)
    img = to_img(col)
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(26):                                           # ice shards
        cx, cy = rng.randint(0, W), rng.randint(0, H)
        pts = [(cx + rng.randint(-70, 70), cy + rng.randint(-50, 50)) for _ in range(rng.randint(3, 5))]
        d.polygon(pts, fill=(120, 220, 255, rng.randint(14, 40)), outline=(190, 245, 255, 150))
    for _ in range(18):                                           # cracks
        x, y = rng.randint(0, W), rng.randint(0, H)
        pts = [(x, y)]
        for _ in range(rng.randint(3, 7)):
            x += rng.randint(-40, 40)
            y += rng.randint(-40, 40)
            pts.append((x, y))
        d.line(pts, fill=(220, 250, 255, 200), width=1)
    return glow(img, 6, 0.6)


def aurora():
    n = noise(160, 3)
    col = lerp((2, 6, 20), (6, 18, 48), Y / H)
    for k, (c, x0) in enumerate((((40, 255, 160), 0.30), ((60, 220, 255), 0.55), ((170, 90, 255), 0.78))):
        # tall flowing curtains: bright at the bottom edge, fading upwards
        wave = np.sin(X / (60 + 25 * k) + n * 5 + k * 1.7) * 38
        edge = H * (0.62 + 0.08 * k) + wave
        up = np.clip((edge - Y) / (H * 0.55), 0, 1)
        band = np.where(Y < edge, (1 - up) ** 1.6, np.exp(-(Y - edge) / 6)) * (0.45 + 0.55 * n)
        stripes = 0.65 + 0.35 * np.sin(X / 5.5 + n * 20) ** 2
        col = col + band[..., None] * stripes[..., None] * np.array(c, np.float32) * 0.75
    img = to_img(col)
    d = ImageDraw.Draw(img)
    for _ in range(90):
        x, y = rng.randint(0, W), rng.randint(0, int(H * 0.45))
        v = rng.randint(120, 255)
        d.point((x, y), fill=(v, v, v))
    return glow(img, 10, 0.55)


def supernova():
    cx, cy = W * 0.5, H * 0.52
    r = np.hypot(X - cx, Y - cy) + 1e-3
    ang = np.arctan2(Y - cy, X - cx)
    n = noise(70, 4)
    rays = (0.5 + 0.5 * np.sin(ang * 23 + n * 4)) ** 6 * np.exp(-r / 210)
    core = np.exp(-r / 26)
    shell = np.exp(-((r - 118 - n * 30) / 16) ** 2)
    col = lerp((4, 2, 22), (40, 10, 70), np.exp(-r / 260))
    col = col + shell[..., None] * np.array([255, 120, 60], np.float32) * (0.5 + n[..., None])
    col = col + rays[..., None] * np.array([255, 210, 170], np.float32) * 1.4
    col = col + core[..., None] * np.array([255, 245, 230], np.float32) * 2.2
    col = col + np.exp(-r / 70)[..., None] * np.array([200, 80, 255], np.float32) * 0.6
    img = to_img(col)
    d = ImageDraw.Draw(img)
    for _ in range(140):
        x, y = rng.randint(0, W), rng.randint(0, H)
        v = rng.randint(90, 255)
        d.point((x, y), fill=(v, v, int(v * 0.9)))
    return glow(img, 8, 0.6)


def cascade():
    img = Image.new("RGB", (W, H), (0, 6, 2))
    d = ImageDraw.Draw(img)
    glyphs = "01<>/\\|=+*#%&$@"
    for col in range(0, W, 12):
        head = rng.randint(-40, H + 60)
        length = rng.randint(60, 220)
        for y in range(0, H, 14):
            dist = head - y
            if 0 <= dist <= length:
                k = 1 - dist / length
                g = int(60 + 195 * k)
                c = (int(200 * k ** 6), g, int(90 * k ** 3))
                ch = rng.choice(glyphs)
                if dist < 14:
                    c = (210, 255, 220)
                d.text((col, y), ch, fill=c)
            elif rng.random() < 0.05:
                d.text((col, y), rng.choice(glyphs), fill=(0, 45, 12))
    return glow(img, 4, 0.9)


def cyberpunk():
    img = Image.new("RGB", (W, H), (18, 4, 30))
    d = ImageDraw.Draw(img)
    pal = [(255, 40, 200), (0, 240, 255), (255, 230, 40), (140, 60, 255), (255, 90, 120)]
    for _ in range(70):                                            # glitch blocks
        w, h = rng.randint(30, 180), rng.randint(6, 40)
        x, y = rng.randint(-40, W), rng.randint(0, H)
        c = rng.choice(pal)
        d.rectangle((x, y, x + w, y + h), fill=tuple(int(v * rng.uniform(0.45, 1.0)) for v in c))
    a = np.asarray(img, np.float32)
    for _ in range(12):                                            # RGB channel shifts on scanline bands
        y0 = rng.randint(0, H - 20)
        h = rng.randint(4, 22)
        shift = rng.randint(-26, 26)
        a[y0:y0 + h, :, 0] = np.roll(a[y0:y0 + h, :, 0], shift, axis=1)
        a[y0:y0 + h, :, 2] = np.roll(a[y0:y0 + h, :, 2], -shift, axis=1)
    a *= (0.82 + 0.18 * (np.arange(H) % 3 != 0))[:, None, None]     # scanlines
    return glow(to_img(a), 6, 0.45)


def magma():
    n = noise(110, 5)
    cells = np.abs(np.sin(X / 34 + n * 9) * np.sin(Y / 30 + n * 7))
    veins = np.exp(-cells * 9)
    col = lerp((14, 2, 2), (60, 8, 4), n)
    hot = np.clip(veins * (0.4 + n), 0, 1)
    col = col + hot[..., None] * np.array([255, 110, 20], np.float32)
    col = col + (hot ** 3)[..., None] * np.array([255, 220, 120], np.float32)
    return glow(to_img(col), 7, 0.7)


def stardust():
    n = noise(150, 4)
    col = lerp((2, 4, 16), (24, 20, 60), n ** 1.5)
    col = col + (np.clip(n - 0.55, 0, 1) * 2)[..., None] * np.array([60, 40, 110], np.float32)
    img = to_img(col)
    d = ImageDraw.Draw(img)
    for _ in range(700):
        x, y = rng.randint(0, W), rng.randint(0, H)
        v = rng.random()
        c = (255, int(200 + 55 * v), int(140 + 100 * v)) if rng.random() < 0.5 else (200, 220, 255)
        size = 0 if v < 0.85 else 1
        d.ellipse((x - size, y - size, x + size, y + size), fill=tuple(int(ch * (0.35 + 0.65 * v)) for ch in c))
    for _ in range(14):                                            # a few bright stars with spikes
        x, y = rng.randint(0, W), rng.randint(0, H)
        d.line((x - 7, y, x + 7, y), fill=(255, 245, 220))
        d.line((x, y - 7, x, y + 7), fill=(255, 245, 220))
    return glow(img, 3, 1.0)


def nebula():
    n1, n2 = noise(170, 5), noise(90, 4)
    col = lerp((4, 2, 14), (60, 10, 90), n1 ** 1.3)
    col = col + (np.clip(n2 - 0.45, 0, 1) * 1.8)[..., None] * np.array([255, 70, 170], np.float32) * n1[..., None]
    col = col + (np.clip(n1 - 0.6, 0, 1) * 2.2)[..., None] * np.array([60, 140, 255], np.float32)
    img = to_img(col)
    d = ImageDraw.Draw(img)
    for _ in range(160):
        x, y = rng.randint(0, W), rng.randint(0, H)
        v = rng.randint(100, 255)
        d.point((x, y), fill=(v, v, v))
    return glow(img, 9, 0.5)


def eclipse():
    cx, cy = W * 0.5, H * 0.5
    r = np.hypot(X - cx, Y - cy)
    ang = np.arctan2(Y - cy, X - cx)
    n = noise(60, 4)
    R = 78
    corona = np.exp(-np.clip(r - R, 0, None) / (22 + 26 * n)) * (r > R - 2)
    streams = (0.5 + 0.5 * np.sin(ang * 9 + n * 6)) ** 3 * np.exp(-np.clip(r - R, 0, None) / 90) * (r > R)
    col = lerp((2, 2, 8), (10, 8, 24), np.exp(-r / 300))
    col = col + corona[..., None] * np.array([255, 170, 80], np.float32) * 1.1
    col = col + streams[..., None] * np.array([255, 120, 200], np.float32) * 0.6
    rim = np.exp(-((r - R) / 2.5) ** 2)
    col = col + rim[..., None] * np.array([255, 245, 220], np.float32) * 1.4
    col = np.where((r < R - 1)[..., None], np.array([3, 3, 6], np.float32), col)
    return glow(to_img(col), 8, 0.6)


ART = {"tide": calm_water, "drizzle": rain, "sweep": side_to_side, "ember": crimson,
       "pulse": rgbarz, "drift": gradient_wave, "volt": neon_storm, "frost": black_ice,
       "aurora": aurora, "supernova": supernova, "cascade": cascade, "cyberpunk": cyberpunk,
       "magma": magma, "stardust": stardust, "nebula": nebula, "eclipse": eclipse}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    import sys
    only = sys.argv[1:]                    # e.g. "aurora magma" to (re)make just those
    for name, fn in ART.items():
        if only and name not in only:
            continue
        fn().convert("RGB").save(OUT / f"{name}.jpg", quality=90, optimize=True)
        print("wrote", name)
