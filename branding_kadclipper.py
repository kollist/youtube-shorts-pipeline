"""
branding_kadclipper.py
Draws the profile picture and the banners for "Kad The Clipper" (@kadclipper) - original neon-sunset art in the clip template's palette, no game logos or artwork.

    python branding_kadclipper.py          -> branding/kadclipper/*.png

  profile_1080.png            the square profile picture (YouTube, Instagram, Facebook, TikTok all crop it to a circle: the mark sits inside the circle)
  youtube_banner_2560x1440    text inside YouTube's safe area (the middle 1235 x 338), art extends to the edges for TVs
  facebook_cover_1640x624     text in the middle (phones show only the middle 16:9), the bottom-left is left clear for the profile picture
  background_vertical_1080x1920   a phone-shaped background (story / highlight backdrops, or a wallpaper)
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "branding" / "kadclipper"
PINK, ORANGE, CYAN, PURPLE = (255, 52, 150), (255, 154, 40), (38, 224, 232), (22, 8, 52)
IMPACT = "/System/Library/Fonts/Supplemental/Impact.ttf"


def font(size: int):
    for p in (IMPACT, "/System/Library/Fonts/Supplemental/Arial Black.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sky(w: int, h: int, horizon: int) -> Image.Image:
    im = Image.new("RGB", (w, h), PURPLE); px = ImageDraw.Draw(im)
    stops = [(0.0, (14, 6, 40)), (0.45, (92, 18, 112)), (0.78, (222, 40, 130)), (1.0, (255, 150, 50))]
    for y in range(horizon):
        t = y / max(1, horizon - 1)
        for k in range(len(stops) - 1):
            if stops[k][0] <= t <= stops[k + 1][0]:
                c = lerp(stops[k][1], stops[k + 1][1], (t - stops[k][0]) / (stops[k + 1][0] - stops[k][0]))
                break
        px.line([(0, y), (w, y)], fill=c)
    return im


def palm(d: ImageDraw.ImageDraw, x: float, base: float, height: float, lean: float, col=(8, 3, 22)) -> None:
    """A palm-tree silhouette: a curved trunk and seven drooping fronds."""
    pts = []
    for i in range(21):
        t = i / 20
        pts.append((x + lean * height * t * t, base - height * t))
    for i in range(20):
        w = height * 0.035 * (1 - 0.45 * i / 20)
        d.line([pts[i], pts[i + 1]], fill=col, width=max(2, int(w)))
    tx, ty = pts[-1]
    L = height * 0.5
    for ang in (-170, -145, -115, -80, -50, -25, 0, -190):
        a = math.radians(ang)
        poly_l, poly_r = [], []
        for j in range(13):
            t = j / 12
            px_ = tx + math.cos(a) * L * t
            py_ = ty + math.sin(a) * L * t * 0.55 + L * 0.5 * t * t
            wd = L * 0.07 * math.sin(math.pi * min(1, t * 1.15)) + 1
            nx, ny = -math.sin(a), math.cos(a)
            poly_l.append((px_ + nx * wd, py_ + ny * wd)); poly_r.append((px_ - nx * wd, py_ - ny * wd))
        d.polygon(poly_l + poly_r[::-1], fill=col)


def scene(w: int, h: int, seed: int = 4, horizon_frac: float = 0.62, palms: bool = True, sun_x: float = 0.5) -> Image.Image:
    rnd = random.Random(seed)
    hz = int(h * horizon_frac)
    im = sky(w, h, hz); d = ImageDraw.Draw(im)
    for _ in range(int(w * h / 14000)):                                       # stars in the dark top of the sky
        x, y = rnd.randrange(w), rnd.randrange(int(hz * 0.5))
        d.point((x, y), fill=(255, 255, 255));
    r = int(min(w, h) * 0.30)
    sx, sy = int(w * sun_x), hz - int(r * 0.2)
    glow = Image.new("RGB", (w, h), (0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.ellipse([sx - r * 1.6, sy - r * 1.6, sx + r * 1.6, sy + r * 1.6], fill=(120, 20, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(r * 0.6))
    im = ImageChops.add(im, glow)
    sun = Image.new("RGB", (2 * r, 2 * r)); sd = ImageDraw.Draw(sun)
    for y in range(2 * r):
        sd.line([(0, y), (2 * r, y)], fill=lerp((255, 224, 90), PINK, y / (2 * r)))
    mask = Image.new("L", (2 * r, 2 * r), 0); md = ImageDraw.Draw(mask)
    md.ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    for k in range(7):                                                        # the retro slits cut into the lower half of the sun
        y0 = r + int(r * 0.12) + int(k * r * 0.14); md.rectangle([0, y0, 2 * r, y0 + int(3 + k * 2.2)], fill=0)
    im.paste(sun, (sx - r, sy - r), mask); d = ImageDraw.Draw(im)
    d.rectangle([0, hz, w, h], fill=(16, 5, 40))                              # the ground cuts off the lower sun
    # skyline: dark towers with a few lit windows
    x = -20
    while x < w + 20:
        bw = rnd.randint(int(w * 0.02), int(w * 0.055)); bh = rnd.randint(int(h * 0.04), int(h * 0.20))
        if abs((x + bw / 2) - w / 2) < w * 0.12:
            bh = int(bh * 0.55)
        d.rectangle([x, hz - bh, x + bw, hz], fill=(20, 6, 46))
        for _ in range(max(1, bw * bh // 2600)):
            wx, wy = x + rnd.randint(3, max(4, bw - 5)), hz - rnd.randint(6, max(7, bh - 4))
            d.rectangle([wx, wy, wx + 3, wy + 4], fill=rnd.choice([CYAN, PINK, (255, 200, 90)]))
        x += bw + rnd.randint(1, 8)
    # the neon grid floor, in perspective
    gl = Image.new("RGBA", (w, h), (0, 0, 0, 0)); g = ImageDraw.Draw(gl)
    vx = w / 2
    for i in range(-24, 25):
        g.line([(vx + i * w * 0.012, hz), (vx + i * w * 0.16, h)], fill=PINK + (150,), width=max(1, w // 900))
    yy, step = hz, 3.0
    while yy < h:
        g.line([(0, yy), (w, yy)], fill=CYAN + (130,), width=max(1, w // 1000))
        step *= 1.32; yy += step
    gl = gl.filter(ImageFilter.GaussianBlur(0.8))
    im = Image.alpha_composite(im.convert("RGBA"), gl).convert("RGB"); d = ImageDraw.Draw(im)
    if palms:                                                                 # palms at both edges
        palm(d, w * 0.07, hz + h * 0.05, h * 0.62, 0.16)
        palm(d, w * 0.93, hz + h * 0.05, h * 0.66, -0.18)
        palm(d, w * 0.15, hz + h * 0.03, h * 0.38, 0.12)
        palm(d, w * 0.86, hz + h * 0.03, h * 0.4, -0.12)
    return im


def neon_text(im: Image.Image, xy, text: str, size: int, fill=(255, 255, 255), glow=PINK, anchor="mm", spread: int = 0) -> None:
    f = font(size)
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(layer)
    ld.text(xy, text, font=f, fill=glow + (255,), anchor=anchor, stroke_width=max(2, size // 14))
    blur = layer.filter(ImageFilter.GaussianBlur(max(4, size // 7)))
    im.alpha_composite(blur); im.alpha_composite(blur)
    d = ImageDraw.Draw(im)
    d.text((xy[0] + size // 28, xy[1] + size // 24), text, font=f, fill=(10, 0, 30, 255), anchor=anchor)
    d.text(xy, text, font=f, fill=fill + (255,), anchor=anchor, stroke_width=max(1, size // 40), stroke_fill=glow + (255,))


def wordmark(im: Image.Image, cx: int, cy: int, size: int, tag: bool = True, handle: bool = True) -> None:
    neon_text(im, (cx, cy), "KAD THE CLIPPER", size, glow=PINK)
    y = cy + int(size * 0.80)
    if tag:
        neon_text(im, (cx, y), "GTA 6 CLIPS  •  EVERY DAY", int(size * 0.34), fill=(255, 255, 255), glow=CYAN)
        y += int(size * 0.5)
    if handle:
        neon_text(im, (cx, y), "@kadclipper", int(size * 0.30), fill=(255, 214, 120), glow=ORANGE)


def viewfinder(d: ImageDraw.ImageDraw, box, arm: int, width: int, col) -> None:
    x0, y0, x1, y1 = box
    for (cx, cy, sx, sy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(cx, cy + sy * arm), (cx, cy), (cx + sx * arm, cy)], fill=col, width=width, joint="curve")


def profile(size: int = 1080) -> Image.Image:
    im = scene(size, size, seed=9, horizon_frac=0.60, palms=False).convert("RGBA")
    d = ImageDraw.Draw(im)
    m = int(size * 0.22)                                                      # the viewfinder corners sit inside the circle crop
    viewfinder(d, (m, m, size - m, size - m), int(size * 0.13), int(size * 0.022), CYAN + (255,))
    f = font(int(size * 0.56))
    mask = Image.new("L", im.size, 0); ImageDraw.Draw(mask).text((size // 2, int(size * 0.5)), "K", font=f, fill=255, anchor="mm")
    grad = Image.new("RGBA", im.size)
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        gd.line([(0, y), (size, y)], fill=lerp((255, 236, 120), PINK, max(0, min(1, (y - size * 0.25) / (size * 0.5)))) + (255,))
    glow = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(glow).text((size // 2, int(size * 0.5)), "K", font=f, fill=PINK + (255,), anchor="mm", stroke_width=size // 40)
    glow = glow.filter(ImageFilter.GaussianBlur(size // 28)); im.alpha_composite(glow)
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(shadow).text((size // 2 + size // 60, int(size * 0.5) + size // 50), "K", font=f, fill=(10, 0, 30, 255), anchor="mm")
    im.alpha_composite(shadow)
    im.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(im)
    d.text((size // 2, int(size * 0.80)), "CLIPPER", font=font(int(size * 0.095)), fill=(255, 255, 255, 255), anchor="mm", stroke_width=size // 160, stroke_fill=PINK + (255,))
    return im.convert("RGB")


def youtube_banner() -> Image.Image:
    w, h = 2560, 1440
    im = scene(w, h, seed=3, horizon_frac=0.70, sun_x=0.5).convert("RGBA")
    wordmark(im, w // 2, int(h * 0.44), 190)                                  # inside the middle 1235 x 338 safe area on every device
    return im.convert("RGB")


def facebook_cover() -> Image.Image:
    w, h = 1640, 624
    im = scene(w, h, seed=5, horizon_frac=0.66, sun_x=0.5).convert("RGBA")
    wordmark(im, w // 2 + 40, int(h * 0.38), 104)
    return im.convert("RGB")


def vertical_background() -> Image.Image:
    w, h = 1080, 1920
    im = scene(w, h, seed=8, horizon_frac=0.60, sun_x=0.5).convert("RGBA")
    wordmark(im, w // 2, int(h * 0.15), 120)
    return im.convert("RGB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    profile().save(OUT / "profile_1080.png")
    youtube_banner().save(OUT / "youtube_banner_2560x1440.png")
    facebook_cover().save(OUT / "facebook_cover_1640x624.png")
    vertical_background().save(OUT / "background_vertical_1080x1920.png")
    print("wrote", sorted(p.name for p in OUT.iterdir()))
