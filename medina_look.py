"""
medina_look.py
The look of the "Khbir" (الخبير) series, deliberately NOT the camcorder / SCP tape look:

  colour     a warm lantern grade (amber highlights, indigo shadows) that turns cold and blue as the dread rises; a lantern flicker instead of glitches
  frame      a thin gold double border with eight-point zellige stars in the corners and a small arch badge with the series name and the tale number
  title      the first picture is framed by a horseshoe arch in gold on deep indigo, the title in Diwan Thuluth calligraphy
  end card   a calm indigo card with a star ornament and the wordmark (no static, no "tape")
  captions   ivory words, the spoken word in saffron (see rules_video._captions colours)

Palette: gold (214,164,62) - saffron (255,190,60) - ivory (246,238,220) - indigo (14,20,44) - henna (168,70,40)
"""

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import horror_fx as hfx

W, H = hfx.W, hfx.H                                         # 720 x 1280 inside the effect pass
GOLD, SAFFRON, IVORY, INDIGO, HENNA = (214, 164, 62), (255, 190, 60), (246, 238, 220), (14, 20, 44), (168, 70, 40)
_SUP = "/System/Library/Fonts/Supplemental/"
_FONTS = {"thuluth": [_SUP + "Diwan Thuluth.ttf"], "kufi": [_SUP + "Diwan Kufi.ttc"], "naskh": [_SUP + "DecoTypeNaskh.ttc"],
          "geeza": ["/System/Library/Fonts/GeezaPro.ttc"]}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for p in _FONTS.get(kind, []) + _FONTS["geeza"]:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def arabic_digits(n: int, width: int = 2) -> str:
    return str(n).zfill(width).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))


# ---------------------------------------------------------------- ornaments
def star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill=None, line=None, width: int = 2) -> None:
    """The eight-point star (khatim sulaiman) of zellige: two squares, one turned 45 degrees."""
    for rot in (math.pi / 4, 0.0):
        pts = [(cx + r * math.cos(rot + k * math.pi / 2), cy + r * math.sin(rot + k * math.pi / 2)) for k in range(4)]
        if fill:
            d.polygon(pts, fill=fill)
        if line:
            d.line(pts + [pts[0]], fill=line, width=width, joint="curve")


def arch(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, fill=None, line=None, width: int = 3) -> None:
    """A rounded (moorish) arch: straight sides, a half-circle on top."""
    r = (x1 - x0) // 2
    if fill:
        d.ellipse([x0, y0, x1, y0 + 2 * r], fill=fill)
        d.rectangle([x0, y0 + r, x1, y1], fill=fill)
    if line:
        d.arc([x0, y0, x1, y0 + 2 * r], 180, 360, fill=line, width=width)
        d.line([(x0, y0 + r), (x0, y1)], fill=line, width=width)
        d.line([(x1, y0 + r), (x1, y1)], fill=line, width=width)


def frame_overlay(label: str, number: str) -> tuple[np.ndarray, np.ndarray]:
    """RGB + alpha (0..1) of the gold frame and the top badge, at 720x1280."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    g = GOLD + (215,); gl = GOLD + (110,)
    d.rectangle([16, 16, W - 17, H - 17], outline=g, width=3)
    d.rectangle([26, 26, W - 27, H - 27], outline=gl, width=1)
    for cx, cy in ((16, 16), (W - 17, 16), (16, H - 17), (W - 17, H - 17)):
        star(d, cx, cy, 22, fill=INDIGO + (255,), line=g, width=3)
        star(d, cx, cy, 9, fill=GOLD + (255,))
    for cy in (H // 2,):                                      # small diamonds half way down each side
        for cx in (16, W - 17):
            star(d, cx, cy, 10, fill=GOLD + (230,))
    bw, by = 250, 58                                          # the badge: series name and tale number inside a small arch
    d.rounded_rectangle([W // 2 - bw // 2, by, W // 2 + bw // 2, by + 128], radius=52, fill=INDIGO + (205,), outline=g, width=2)
    star(d, W // 2 - bw // 2 + 4, by + 64, 9, fill=g)
    star(d, W // 2 + bw // 2 - 4, by + 64, 9, fill=g)
    d.text((W // 2, by + 56), label, font=font("thuluth", 50), fill=GOLD + (255,), anchor="mm")
    d.text((W // 2, by + 112), f"حكاية {number}", font=font("geeza", 27), fill=IVORY + (235,), anchor="mm")
    a = np.asarray(im, dtype=np.float32)
    return a[..., :3], a[..., 3:] / 255.0


def card_image(label: str) -> np.ndarray:
    """The end card at 720x1280: indigo, the star ornament, the wordmark. The viewer question is added on top as a subtitle."""
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    base = np.array(INDIGO, np.float32) * (0.75 + 0.5 * (1 - np.abs(yy - 0.45) * 1.6).clip(0, 1)) + np.zeros((H, W, 3), np.float32)
    im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA"); d = ImageDraw.Draw(im)
    g = GOLD + (255,)
    for r, w in ((150, 3), (126, 1)):
        star(d, W // 2, 270, r, line=g, width=w)
    star(d, W // 2, 270, 40, fill=g)
    d.text((W // 2, 470), label, font=font("thuluth", 120), fill=g, anchor="mm")
    d.line([(W // 2 - 150, 545), (W // 2 + 150, 545)], fill=GOLD + (150,), width=1)
    for i, cx in enumerate((-90, -45, 0, 45, 90)):
        star(d, W // 2 + cx, 1000, 11 if i % 2 == 0 else 7, fill=GOLD + (200,))
    d.rectangle([16, 16, W - 17, H - 17], outline=GOLD + (215,), width=3)
    d.rectangle([26, 26, W - 27, H - 27], outline=GOLD + (110,), width=1)
    return np.asarray(im.convert("RGB"), dtype=np.float32)


# ---------------------------------------------------------------- the per-frame treatment
class Medina(hfx.Tape):
    def __init__(self, label: str, number: str, soft: bool = False, seed: int = 7):
        super().__init__(label, seed=seed, soft=soft)
        self.fr_rgb, self.fr_a = frame_overlay(label, number)
        self.card = card_image(label)
        rng = np.random.default_rng(seed)
        self.motes = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(0.2, 0.6), rng.uniform(5, 16), rng.uniform(0, 6.28), rng.integers(2, 4)) for _ in range(16)]
        self.flick_until = 0.0

    def frame(self, f: np.ndarray, t: float, k: float, fi: int) -> np.ndarray:
        lum = f.mean(axis=2, keepdims=True)
        f = lum + (f - lum) * (0.94 - 0.32 * k)                                  # the colour drains as the dread grows
        mix = min(1.0, k * 1.2)
        warm, cold = np.array([1.08, 0.99, 0.82], np.float32), np.array([0.84, 0.97, 1.12], np.float32)
        f = f * (warm * (1 - mix) + cold * mix)                                  # lantern amber -> cold moonlight
        f = (f - 128) * (1.05 + 0.12 * k) + 128 - 3
        fl = 1 + 0.03 * math.sin(t * 7.3) + 0.02 * math.sin(t * 17.9 + 1.0)       # the lantern flame
        if t > self.flick_until and self.rng.random() < 0.004 + 0.03 * k:         # now and then it gutters, more often as it gets worse
            self.flick_until = t + self.rng.uniform(0.05, 0.16)
        if t < self.flick_until:
            fl *= 0.55 + 0.25 * self.rng.random()
        f = f * fl
        f = f + self.noise[fi % 6] * (2.5 + 7 * k) * self.grain
        f = f * (1 - (1 - self.vig) * (0.5 + 0.95 * k))
        for x0, y0, sp, dr, ph, rr in self.motes:                                # dust in the lantern light
            x = int((x0 + 22 * math.sin(t * 0.35 + ph)) % W); y = int((y0 - dr * t) % H)
            f[max(0, y - rr):y + rr, max(0, x - rr):x + rr] += 30 * sp * np.array([1.0, 0.85, 0.6], np.float32)
        f = f * (1 - self.fr_a) + self.fr_rgb * self.fr_a
        return np.clip(f, 0, 255)


# ---------------------------------------------------------------- the title picture
def poster(story: dict, image: Path, out: Path, W_: int = 1080, H_: int = 1920) -> Path:
    im = Image.open(image).convert("RGB")
    r = max(W_ / im.width, H_ / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    im = im.crop(((im.width - W_) // 2, (im.height - H_) // 2, (im.width - W_) // 2 + W_, (im.height - H_) // 2 + H_)).convert("RGBA")
    shade = Image.new("RGBA", (W_, H_), (0, 0, 0, 0)); sd = ImageDraw.Draw(shade)
    for y in range(H_):
        a = int(150 * max(0, 1 - y / 900) ** 1.4 + 150 * max(0, (y - (H_ - 600)) / 600) ** 1.4)
        sd.line([(0, y), (W_, y)], fill=(6, 8, 20, a))
    im = Image.alpha_composite(im, shade)
    lay = Image.new("RGBA", (W_, H_), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    arch(d, 130, 235, W_ - 130, 790, fill=INDIGO + (150,), line=GOLD + (235,), width=5)             # the title sits in an arch
    arch(d, 150, 255, W_ - 150, 790, line=GOLD + (120,), width=2)
    lines = story.get("title_lines") or [story["title"]]
    f1 = font("thuluth", 190)
    while f1.getlength(lines[0]) > W_ - 380 and f1.size > 60:
        f1 = font("thuluth", f1.size - 6)
    d.text((W_ // 2, 480), lines[0], font=f1, fill=GOLD + (255,), anchor="mm", stroke_width=3, stroke_fill=(10, 8, 6, 255))
    if len(lines) > 1:
        f2 = font("kufi", 110)
        while f2.getlength(lines[1]) > W_ - 380 and f2.size > 50:
            f2 = font("kufi", f2.size - 6)
        d.text((W_ // 2, 660), lines[1], font=f2, fill=IVORY + (255,), anchor="mm", stroke_width=3, stroke_fill=(10, 8, 6, 255))
    star(d, W_ // 2, 750, 22, fill=GOLD + (255,))
    tag = story.get("poster_tag") or ""
    if tag:
        ft = font("geeza", 70)
        while ft.getlength(tag) > W_ - 220 and ft.size > 36:
            ft = font("geeza", ft.size - 4)
        tw = ft.getlength(tag)
        d.rounded_rectangle([W_ // 2 - tw / 2 - 50, H_ - 700, W_ // 2 + tw / 2 + 50, H_ - 590], radius=55, fill=INDIGO + (205,), outline=SAFFRON + (255,), width=3)
        d.text((W_ // 2, H_ - 645), tag, font=ft, fill=SAFFRON + (255,), anchor="mm")
    im = Image.alpha_composite(im, lay)
    im.convert("RGB").save(out)
    return out
