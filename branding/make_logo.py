"""Foundation Tapes profile picture: a containment ring, a 'FT' monogram split into red/cyan like a failing VHS tape, a REC dot, scanlines, grain.
Everything important sits inside the central circle, so the round crop on Instagram / Facebook never cuts it."""
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 1080; OUT = Path(__file__).parent; rng = np.random.default_rng(13)
FONT = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"

yy, xx = np.mgrid[0:S, 0:S]; r = np.hypot(xx - S / 2, yy - S / 2) / (S / 2)
bg = np.zeros((S, S, 3), np.float32); bg[..., 0] = 0.07; bg[..., 1] = 0.065; bg[..., 2] = 0.075
glow = np.clip(1 - r * 1.15, 0, 1) ** 2                                         # a cold, dim light behind the letters
bg += glow[..., None] * np.array([0.10, 0.12, 0.13], np.float32)
base = Image.fromarray((np.clip(bg, 0, 1) * 255).astype(np.uint8))

def layer(draw_fn, blur=0):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); draw_fn(ImageDraw.Draw(im))
    return im.filter(ImageFilter.GaussianBlur(blur)) if blur else im

def ring(d):
    c = S // 2
    for rad, w, a in ((455, 6, 235), (420, 2, 150), (478, 2, 110)):
        d.ellipse((c - rad, c - rad, c + rad, c + rad), outline=(228, 228, 224, a), width=w)
    for ang in (0, 90, 180, 270):                                                # four tick marks, like a tape-reel / registration mark
        a = np.deg2rad(ang); x0, y0 = c + 478 * np.cos(a), c + 478 * np.sin(a); x1, y1 = c + 430 * np.cos(a), c + 430 * np.sin(a)
        d.line((x0, y0, x1, y1), fill=(228, 228, 224, 210), width=5)

font = ImageFont.truetype(FONT, 520)
def mono(color, dx=0):
    def f(d):
        d.text((S / 2 + dx, S / 2 - 18), "FT", font=font, fill=color, anchor="mm")
    return f

img = base.convert("RGBA")
img = Image.alpha_composite(img, layer(ring))
img = Image.alpha_composite(img, layer(mono((255, 40, 50, 150), -14), 2))       # red ghost, left
img = Image.alpha_composite(img, layer(mono((40, 220, 235, 130), 14), 2))       # cyan ghost, right
img = Image.alpha_composite(img, layer(mono((238, 238, 232, 255))))             # the letters
def rec(d):
    d.ellipse((S / 2 - 100 - 22, 770 - 22, S / 2 - 100 + 22, 770 + 22), fill=(235, 30, 40, 255))
    d.text((S / 2 - 100 + 40, 770), "REC", font=ImageFont.truetype(FONT, 56), fill=(238, 238, 232, 235), anchor="lm")
img = Image.alpha_composite(img, layer(rec))
img = Image.alpha_composite(img, layer(rec, 14))                                  # glow on the dot

a = np.asarray(img.convert("RGB"), np.float32) / 255
a *= (1 - 0.18 * (np.arange(S) % 4 < 2))[:, None, None]                          # scanlines
a += rng.normal(0, 0.035, a.shape)                                               # grain
a *= (1 - 0.55 * np.clip((r - 0.62) / 0.5, 0, 1) ** 1.6)[..., None]              # vignette
sh = 9; a[:, sh:, 0] = a[:, :-sh, 0] * 0.55 + a[:, sh:, 0] * 0.45                # a little chroma smear
for y in rng.integers(120, S - 120, 4):                                          # a few tracking tears
    h = int(rng.integers(6, 16)); off = int(rng.integers(-40, 40)); a[y:y + h] = np.roll(a[y:y + h], off, axis=1)
out = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
out.save(OUT / "logo.png")
mask = Image.new("L", (S, S), 0); ImageDraw.Draw(mask).ellipse((0, 0, S, S), fill=255)
circ = Image.new("RGB", (S, S), (255, 255, 255)); circ.paste(out, (0, 0), mask); circ.resize((320, 320), Image.LANCZOS).save(OUT / "logo_circle_preview.png")
print("ok")
