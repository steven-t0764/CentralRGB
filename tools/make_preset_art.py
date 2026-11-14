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


ART = {"calm-water": calm_water, "rain": rain, "side-to-side": side_to_side, "crimson": crimson,
       "rgbarz": rgbarz, "gradient-wave": gradient_wave, "neon-storm": neon_storm, "black-ice": black_ice}

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, fn in ART.items():
        fn().convert("RGB").save(OUT / f"{name}.jpg", quality=90, optimize=True)
        print("wrote", name)
