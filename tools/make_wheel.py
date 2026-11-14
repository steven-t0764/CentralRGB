"""Pre-render the colour wheel (presets/wheel.png) so the app doesn't draw it at startup."""
import colorsys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

S = 896                                    # diameter; the app scales it down
hue = Image.new("RGB", (S, S))
d = ImageDraw.Draw(hue)
for k in range(1440):                      # 0 deg = right, counter-clockwise
    r, g, b = colorsys.hsv_to_rgb(k / 1440, 1, 1)
    d.pieslice((0, 0, S - 1, S - 1), -(k + 1) / 4 - 0.2, -k / 4 + 0.2, fill=(int(r * 255), int(g * 255), int(b * 255)))
hue = hue.filter(ImageFilter.GaussianBlur(1))
sat = Image.radial_gradient("L").resize((S, S), Image.BILINEAR)        # 255 at the corners
sat = sat.point(lambda v: int(255 * min(1.0, v * 1.41421 / 255) ** 0.9))
img = Image.composite(hue, Image.new("RGB", (S, S), (255, 255, 255)), sat).convert("RGBA")
mask = Image.new("L", (S * 2, S * 2), 0)
ImageDraw.Draw(mask).ellipse((0, 0, S * 2 - 1, S * 2 - 1), fill=255)
img.putalpha(mask.resize((S, S), Image.LANCZOS))
out = Path(__file__).resolve().parent.parent / "presets" / "wheel.png"
img.save(out, optimize=True)
print(out, out.stat().st_size // 1024, "KB")
