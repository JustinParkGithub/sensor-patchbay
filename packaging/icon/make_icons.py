#!/usr/bin/env python3
"""Draw the sensor-patchbay logo and write every icon file the app uses.

    python packaging/icon/make_icons.py

The logo: patch cables plugged into a patchbay, in front of a gear. It's drawn
here (Pillow only) rather than kept as a hand-edited image, so a tweak is a
code change and every size stays in step. Writes:

    packaging/icon/sensor-patchbay.png    1024 px master (README, Linux)
    packaging/icon/sensor-patchbay.icns   macOS app bundle
    packaging/icon/sensor-patchbay.ico    Windows executables
    ui/public/icon.png                    favicon + tray icon (copied into ui/dist by vite)
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

SS = 2                      # supersampling: draw at 2x, downscale for smooth edges
N = 1024 * SS

# The patch panel's own palette (ui/src/style.css).
BG_TOP, BG_BOTTOM = (34, 39, 46), (16, 18, 22)
GEAR, GEAR_EDGE = (50, 59, 72), (66, 77, 92)
PANEL, PANEL_EDGE, PANEL_HI = (66, 73, 84), (22, 25, 30), (88, 96, 108)
JACK_RING, JACK_HOLE = (176, 184, 196), (10, 12, 15)
SCREW = (120, 128, 140)
AMBER, TEAL, VIOLET = (224, 161, 92), (95, 184, 184), (168, 147, 224)


def s(v: float) -> int:
    """1024-unit design coordinates to canvas pixels."""
    return round(v * SS)


def darker(c, f=0.62):
    return tuple(int(x * f) for x in c)


def lighter(c, f=0.35):
    return tuple(int(x + (255 - x) * f) for x in c)


def background() -> Image.Image:
    grad = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    grad = grad.resize((N, N))
    mask = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mask).rounded_rectangle((s(40), s(40), N - s(40), N - s(40)), radius=s(200), fill=255)
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    return img


def gear_polygon(cx, cy, r_out, r_in, teeth, rot=0.0):
    """Trapezoid teeth: each tooth spans 40% of its pitch at the tip."""
    pts = []
    pitch = 2 * math.pi / teeth
    for i in range(teeth):
        a = rot + i * pitch
        for frac, r in ((-0.30, r_in), (-0.18, r_out), (0.18, r_out), (0.30, r_in)):
            ang = a + frac * pitch
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def draw_gear(img):
    d = ImageDraw.Draw(img)
    cx, cy = s(512), s(470)
    outer = gear_polygon(cx, cy, s(400), s(330), 12, rot=math.pi / 12)
    d.polygon(outer, fill=GEAR_EDGE)
    d.polygon(gear_polygon(cx, cy, s(388), s(320), 12, rot=math.pi / 12), fill=GEAR)
    d.ellipse((cx - s(330), cy - s(330), cx + s(330), cy + s(330)), fill=GEAR)
    # Spokes' lightening holes and the hub, cut back to the background tone.
    hole = darker(GEAR, 0.6)
    for i in range(6):
        a = i * math.pi / 3 + math.pi / 6
        hx, hy = cx + s(205) * math.cos(a), cy + s(205) * math.sin(a)
        d.ellipse((hx - s(62), hy - s(62), hx + s(62), hy + s(62)), fill=hole)
    d.ellipse((cx - s(95), cy - s(95), cx + s(95), cy + s(95)), fill=GEAR_EDGE)
    d.ellipse((cx - s(48), cy - s(48), cx + s(48), cy + s(48)), fill=hole)


PANEL_BOX = (150, 360, 874, 640)
COLS = [236, 374, 512, 650, 788]
ROWS = [440, 560]


def draw_panel(img):
    # Soft shadow under the panel.
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = PANEL_BOX
    ImageDraw.Draw(sh).rounded_rectangle((s(x0), s(y0 + 18), s(x1), s(y1 + 26)), radius=s(40), fill=(0, 0, 0, 150))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(s(18))))

    d = ImageDraw.Draw(img)
    d.rounded_rectangle((s(x0), s(y0), s(x1), s(y1)), radius=s(40), fill=PANEL_EDGE)
    d.rounded_rectangle((s(x0 + 8), s(y0 + 8), s(x1 - 8), s(y1 - 8)), radius=s(33), fill=PANEL)
    d.rounded_rectangle((s(x0 + 8), s(y0 + 8), s(x1 - 8), s(y0 + 22)), radius=s(7), fill=PANEL_HI)
    for sx in (x0 + 34, x1 - 34):
        for sy in (y0 + 34, y1 - 34):
            d.ellipse((s(sx - 11), s(sy - 11), s(sx + 11), s(sy + 11)), fill=SCREW)
            d.line((s(sx - 7), s(sy), s(sx + 7), s(sy)), fill=PANEL_EDGE, width=s(4))
    for y in ROWS:
        for x in COLS:
            d.ellipse((s(x - 40), s(y - 40), s(x + 40), s(y + 40)), fill=PANEL_EDGE)
            d.ellipse((s(x - 34), s(y - 34), s(x + 34), s(y + 34)), fill=JACK_RING)
            d.ellipse((s(x - 19), s(y - 19), s(x + 19), s(y + 19)), fill=JACK_HOLE)


def bezier(p0, p1, p2, p3, steps=160):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def plug(d, x, y, color):
    """A plug seated in a jack: metal collar, then the coloured boot."""
    d.ellipse((s(x - 44), s(y - 44), s(x + 44), s(y + 44)), fill=darker(color, 0.45))
    d.ellipse((s(x - 38), s(y - 38), s(x + 38), s(y + 38)), fill=color)
    d.ellipse((s(x - 24), s(y - 24), s(x + 24), s(y + 24)), fill=lighter(color, 0.25))
    d.ellipse((s(x - 26), s(y - 34), s(x - 2), s(y - 18)), fill=lighter(color, 0.55))


def cable(img, a, b, sag, color, width=34):
    """A cable from jack *a* to jack *b*, hanging *sag* units below the lower end."""
    lo = max(a[1], b[1]) + sag
    pts = [(s(x), s(y)) for x, y in bezier(a, (a[0], lo), (b[0], lo), b)]
    # Drop shadow on whatever is behind it.
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).line([(x + s(10), y + s(16)) for x, y in pts], fill=(0, 0, 0, 140),
                            width=s(width + 6), joint="curve")
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(s(10))))
    d = ImageDraw.Draw(img)
    d.line(pts, fill=darker(color, 0.45), width=s(width + 10), joint="curve")
    d.line(pts, fill=color, width=s(width), joint="curve")
    d.line([(x - s(width * 0.18), y - s(width * 0.18)) for x, y in pts[12:-12]],
           fill=lighter(color, 0.35), width=s(width * 0.22), joint="curve")
    plug(d, *a, color)
    plug(d, *b, color)


def logo() -> Image.Image:
    img = background()
    draw_gear(img)
    draw_panel(img)
    # Back to front: each cable hangs in front of the panel and of the ones before it.
    cable(img, (COLS[3], ROWS[0]), (COLS[4], ROWS[1]), 150, VIOLET)
    cable(img, (COLS[0], ROWS[0]), (COLS[2], ROWS[1]), 230, TEAL)
    cable(img, (COLS[1], ROWS[1]), (COLS[3], ROWS[1]), 300, AMBER)
    return img.resize((1024, 1024), Image.LANCZOS)


def main():
    master = logo()
    master.save(HERE / "sensor-patchbay.png")
    master.save(HERE / "sensor-patchbay.icns")
    master.save(HERE / "sensor-patchbay.ico",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    public = ROOT / "ui" / "public"
    public.mkdir(exist_ok=True)
    master.resize((256, 256), Image.LANCZOS).save(public / "icon.png")
    print("wrote", ", ".join(str(p.relative_to(ROOT)) for p in (
        HERE / "sensor-patchbay.png", HERE / "sensor-patchbay.icns",
        HERE / "sensor-patchbay.ico", public / "icon.png")))


if __name__ == "__main__":
    main()
