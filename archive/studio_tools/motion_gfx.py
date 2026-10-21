"""
motion_gfx.py
The drawing toolkit for motion_video.py: everything is drawn by code (Pillow + numpy) - no AI image or video model, no
GPU, no cost. Faces are generated from a seed, so the same name always gets the same face (consistent characters for free).

Contents: fonts, easing, aged-paper and dark backgrounds, procedural portraits, yearbook cards, chat bubbles, a lock-screen
notification, rubber stamps.
"""

import math
import random
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1080, 1920

_FONT_FILES = {
    "serif": ["/System/Library/Fonts/Supplemental/Georgia.ttf", "/System/Library/Fonts/Supplemental/Baskerville.ttc",
              "/System/Library/Fonts/Supplemental/Times New Roman.ttf"],
    "serif_bold": ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "/System/Library/Fonts/Supplemental/Baskerville.ttc",
                   "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"],
    "sans": ["/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Supplemental/Arial.ttf"],
    "sans_bold": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/HelveticaNeue.ttc"],
    "mono": ["/System/Library/Fonts/Supplemental/Courier New.ttf", "/System/Library/Fonts/Menlo.ttc"],
    "mono_bold": ["/System/Library/Fonts/Supplemental/Courier New Bold.ttf", "/System/Library/Fonts/Menlo.ttc"],
    "impact": ["/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf"],
}


@lru_cache(maxsize=256)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_FILES.get(kind, _FONT_FILES["sans"]):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- easing

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def ease_out(x: float) -> float:
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_pop(x: float) -> float:
    """Overshoots a little then settles - for stamps and pop-ins."""
    x = clamp01(x)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


# ---------------------------------------------------------------- backgrounds

def _blotches(w: int, h: int, seed: int, scales=(260, 90, 30), weights=(0.55, 0.3, 0.15)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), dtype=np.float32)
    for s, wt in zip(scales, weights):
        small = rng.random((max(2, h // s + 2), max(2, w // s + 2))).astype(np.float32)
        img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
        out += np.asarray(img, dtype=np.float32) / 255.0 * wt
    return out


@lru_cache(maxsize=8)
def paper_background(seed: int = 3, tone: str = "aged") -> Image.Image:
    """Aged yearbook paper: warm cream with stains, darker toward the edges."""
    n = _blotches(W, H, seed)
    base = np.array({"aged": (232, 216, 168), "newsprint": (222, 218, 205), "cream": (240, 232, 205)}.get(tone, (232, 216, 168)), dtype=np.float32)
    img = base[None, None, :] * (0.78 + 0.34 * n[..., None])
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    img *= (1 - 0.38 * np.clip(d - 0.45, 0, 1) ** 1.4)[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")


@lru_cache(maxsize=8)
def dark_background(kind: str = "night") -> Image.Image:
    cols = {"night": ((12, 14, 24), (4, 5, 10)), "brown": ((26, 20, 14), (8, 6, 4)), "black": ((10, 10, 10), (0, 0, 0)),
            "blue": ((18, 28, 46), (5, 8, 16))}
    top, bot = cols.get(kind, cols["night"])
    t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    img = np.array(top, dtype=np.float32) * (1 - t) + np.array(bot, dtype=np.float32) * t
    img = np.repeat(img, W, axis=1)
    return Image.fromarray(img.astype(np.uint8), "RGB")


@lru_cache(maxsize=2)
def vignette_mask(strength: float = 0.55) -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    return (1 - strength * np.clip(d - 0.35, 0, 1) ** 1.6)[..., None].astype(np.float32)


# ---------------------------------------------------------------- portraits

SKIN = [(246, 226, 204), (238, 208, 178), (222, 184, 146), (178, 130, 96), (126, 86, 62)]
HAIR = [(24, 18, 16), (24, 18, 16), (40, 28, 20), (58, 40, 28), (84, 56, 34), (60, 30, 22), (196, 164, 108), (160, 160, 160)]
FEMALE_HAIR = ["bob", "long", "bun", "curly", "ponytail", "bangs_long"]
MALE_HAIR = ["side_part", "buzz", "curly_top", "pompadour", "slick", "messy"]


def _ellipse(d, cx, cy, rx, ry, fill, outline=None, width=1):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill, outline=outline, width=width)


def draw_portrait(seed: int, size=(300, 380), gender: str | None = None, tone: str = "sepia", expression: str = "neutral",
                  red_eyes: float = 0.0, suit: bool | None = None) -> Image.Image:
    """A flat-style portrait generated from `seed`. tone="sepia" gives the old-photo look; "color" keeps skin/hair colors.
    red_eyes (0-1) makes the eyes glow red."""
    rng = random.Random(seed * 7919 + 13)
    gender = gender or rng.choice(["m", "f"])
    S = 3                                              # supersample for smooth edges
    w, h = size[0] * S, size[1] * S
    u = w / 300.0                                      # design constants below are for a 300px-wide portrait
    img = Image.new("RGB", (w, h), (216, 204, 178) if tone == "sepia" else (196, 206, 214))
    d = ImageDraw.Draw(img)
    skin, hair = rng.choice(SKIN), rng.choice(HAIR)
    style = rng.choice(FEMALE_HAIR if gender == "f" else MALE_HAIR)
    suit = (gender == "m" and rng.random() < 0.75) if suit is None else suit
    cx, face_cy = w // 2, int(h * 0.42)
    fw, fh = int(w * 0.30), int(h * 0.255)             # half-width / half-height of the face

    # back hair (behind head/shoulders)
    if style in ("long", "bangs_long"):
        d.rounded_rectangle([cx - fw - 18 * u, face_cy - fh * 0.8, cx + fw + 18 * u, face_cy + fh * 2.1], radius=fw, fill=hair)
    if style == "curly":
        for k in range(14):
            a = math.pi * (0.9 + 1.2 * k / 13)
            _ellipse(d, cx + math.cos(a) * fw * 1.15, face_cy + math.sin(a) * fh * 1.05, 34 * u, 34 * u, hair)
    if style == "bun":
        _ellipse(d, cx, face_cy - fh * 1.15, 40 * u, 40 * u, hair)

    # shoulders / clothing
    cloth = rng.choice([(58, 54, 60), (84, 66, 58), (70, 80, 96), (110, 90, 84), (44, 44, 52)])
    d.polygon([(cx - w * 0.46, h), (cx - w * 0.40, h * 0.78), (cx - fw * 0.55, h * 0.70), (cx + fw * 0.55, h * 0.70),
               (cx + w * 0.40, h * 0.78), (cx + w * 0.46, h)], fill=cloth)
    # neck
    d.rectangle([cx - fw * 0.30, face_cy + fh * 0.7, cx + fw * 0.30, h * 0.74], fill=tuple(int(c * 0.88) for c in skin))
    if suit:
        d.polygon([(cx - fw * 0.55, h * 0.70), (cx, h * 0.84), (cx + fw * 0.55, h * 0.70), (cx + fw * 0.2, h * 0.70), (cx, h * 0.76), (cx - fw * 0.2, h * 0.70)],
                  fill=(236, 232, 224))
        d.polygon([(cx - 12 * u, h * 0.77), (cx + 12 * u, h * 0.77), (cx + 16 * u, h * 0.98), (cx - 16 * u, h * 0.98)], fill=(30, 26, 30))
    else:
        d.arc([cx - fw * 0.55, h * 0.64, cx + fw * 0.55, h * 0.80], 20, 160, fill=(236, 232, 224), width=int(4 * u))

    # head + ears
    _ellipse(d, cx - fw * 1.0, face_cy + fh * 0.1, 22 * u, 30 * u, tuple(int(c * 0.93) for c in skin))
    _ellipse(d, cx + fw * 1.0, face_cy + fh * 0.1, 22 * u, 30 * u, tuple(int(c * 0.93) for c in skin))
    _ellipse(d, cx, face_cy, fw, fh, skin)

    # front hair
    if style in ("side_part", "slick", "pompadour"):
        lift = 1.22 if style == "pompadour" else 1.08
        d.chord([cx - fw * 1.07, face_cy - fh * lift, cx + fw * 1.07, face_cy + fh * 0.45], 180, 360, fill=hair)
        d.polygon([(cx - fw * 1.05, face_cy - fh * 0.05), (cx - fw * 0.95, face_cy - fh * 0.55), (cx - fw * 0.1, face_cy - fh * 0.62),
                   (cx + fw * 0.95, face_cy - fh * 0.55), (cx + fw * 1.05, face_cy - fh * 0.05)], fill=hair)
        if style == "side_part":
            d.line([(cx - fw * 0.35, face_cy - fh * 0.98), (cx - fw * 0.25, face_cy - fh * 0.55)], fill=tuple(int(c * 0.5) for c in skin), width=int(4 * u))
    elif style == "buzz":
        d.chord([cx - fw * 1.02, face_cy - fh * 1.05, cx + fw * 1.02, face_cy + fh * 0.1], 190, 350, fill=tuple(int(c * 0.8) for c in hair))
    elif style in ("curly_top", "messy"):
        for k in range(9):
            a = math.pi * (1.05 + 0.9 * k / 8)
            _ellipse(d, cx + math.cos(a) * fw * 0.95, face_cy + math.sin(a) * fh * 0.98, 30 * u, 28 * u, hair)
    elif style in ("bob", "long", "bangs_long", "ponytail", "bun", "curly"):
        d.chord([cx - fw * 1.08, face_cy - fh * 1.12, cx + fw * 1.08, face_cy + fh * 0.25], 180, 360, fill=hair)
        d.rectangle([cx - fw * 1.08, face_cy - fh * 0.55, cx + fw * 1.08, face_cy - fh * 0.1], fill=hair)   # straight bangs
        if style == "bob":
            d.rectangle([cx - fw * 1.1, face_cy - fh * 0.6, cx - fw * 0.88, face_cy + fh * 0.75], fill=hair)
            d.rectangle([cx + fw * 0.88, face_cy - fh * 0.6, cx + fw * 1.1, face_cy + fh * 0.75], fill=hair)
        if style == "ponytail":
            _ellipse(d, cx + fw * 1.25, face_cy - fh * 0.2, 18 * u, 60 * u, hair)

    # eyes, brows, nose, mouth
    ey, ex = face_cy - fh * 0.05, fw * 0.45
    eye_color = (30, 24, 22)
    for sx in (-1, 1):
        _ellipse(d, cx + sx * ex, ey, 19 * u, 13 * u, (246, 242, 236))
        _ellipse(d, cx + sx * ex, ey, 8.5 * u, 8.5 * u, eye_color)
        brow_dy = -6 * u if expression == "worried" else 0
        d.line([(cx + sx * ex - 24 * u, ey - 34 * u + (brow_dy if sx > 0 else -brow_dy)), (cx + sx * ex + 24 * u, ey - 38 * u + (-brow_dy if sx > 0 else brow_dy))],
               fill=tuple(int(c * 0.55) for c in hair), width=int(5 * u))
    d.line([(cx, ey + 8 * u), (cx - 7 * u, face_cy + fh * 0.38), (cx + 5 * u, face_cy + fh * 0.4)], fill=tuple(int(c * 0.72) for c in skin), width=int(3 * u))
    my = face_cy + fh * 0.62
    if expression == "smile":
        d.arc([cx - 40 * u, my - 22 * u, cx + 40 * u, my + 22 * u], 15, 165, fill=(120, 60, 56), width=int(5 * u))
    elif expression == "worried":
        d.arc([cx - 30 * u, my - 2 * u, cx + 30 * u, my + 30 * u], 200, 340, fill=(120, 60, 56), width=int(5 * u))
    else:
        d.line([(cx - 28 * u, my), (cx + 28 * u, my + 2 * u)], fill=(120, 60, 56), width=int(5 * u))
    if rng.random() < 0.22:                                                      # glasses
        for sx in (-1, 1):
            _ellipse(d, cx + sx * ex, ey, 31 * u, 24 * u, None, outline=(40, 34, 34), width=int(3.5 * u))
        d.line([(cx - ex + 31 * u, ey), (cx + ex - 31 * u, ey)], fill=(40, 34, 34), width=int(3.5 * u))

    if red_eyes > 0:
        glow = Image.new("RGB", (w, h), (0, 0, 0))
        gd = ImageDraw.Draw(glow)
        for sx in (-1, 1):
            _ellipse(gd, cx + sx * ex, ey, int(34 * u * (0.6 + red_eyes * 0.6)), int(24 * u * (0.6 + red_eyes * 0.6)), (255, 30, 20))
        glow = glow.filter(ImageFilter.GaussianBlur(16 * u))
        img = ImageChops.add(img, glow.point(lambda v: int(v * red_eyes)))
        d = ImageDraw.Draw(img)
        for sx in (-1, 1):
            _ellipse(d, cx + sx * ex, ey, int(17 * u * red_eyes + 9 * u), int(12 * u * red_eyes + 6 * u), (255, int(60 + 40 * (1 - red_eyes)), 40))
            _ellipse(d, cx + sx * ex, ey, 5 * u, 5 * u, (255, 250, 240))

    img = img.resize(size, Image.LANCZOS)
    if tone == "sepia":
        gray = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
        tinted = ImageOps.colorize(gray, black=(34, 22, 14), white=(236, 218, 178), mid=(150, 118, 84))
        if red_eyes > 0:                                   # keep the red glow through the sepia grade
            r = np.asarray(img, dtype=np.float32)
            mask = np.clip((r[..., 0] - r[..., 1] - 60) / 120, 0, 1)[..., None]
            tinted = Image.fromarray((np.asarray(tinted, dtype=np.float32) * (1 - mask) + r * mask).astype(np.uint8))
        img = tinted
        arr = np.asarray(img, dtype=np.float32)
        arr += np.random.default_rng(seed).normal(0, 5, arr.shape[:2])[..., None]
        yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
        dd = np.sqrt(((xx - size[0] / 2) / (size[0] / 2)) ** 2 + ((yy - size[1] / 2) / (size[1] / 2)) ** 2)
        arr *= (1 - 0.25 * np.clip(dd - 0.5, 0, 1))[..., None]
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img


# ---------------------------------------------------------------- text helpers

def text_size(txt: str, f) -> tuple[int, int]:
    box = f.getbbox(txt)
    return box[2] - box[0], box[3] - box[1]


def wrap(txt: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in txt.split():
        trial = (cur + " " + word).strip()
        if text_size(trial, f)[0] <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def text_layer(txt: str, kind: str = "serif_bold", size: int = 64, color=(30, 22, 16), max_w: int = W - 160, align: str = "center",
               stroke: int = 0, stroke_color=(0, 0, 0), line_gap: float = 1.15, spacing: int = 0) -> Image.Image:
    f = font(kind, size)
    lines = wrap(txt, f, max_w) if max_w else [txt]
    lh = int(size * line_gap)
    layer = Image.new("RGBA", (max_w + 40, lh * len(lines) + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, ln in enumerate(lines):
        tw = text_size(ln, f)[0] + spacing * max(0, len(ln) - 1)
        x = {"center": (layer.width - tw) // 2, "left": 20, "right": layer.width - tw - 20}[align]
        if spacing:
            cx = x
            for ch in ln:
                d.text((cx, 10 + i * lh), ch, font=f, fill=color, stroke_width=stroke, stroke_fill=stroke_color)
                cx += f.getlength(ch) + spacing
        else:
            d.text((x, 10 + i * lh), ln, font=f, fill=color, stroke_width=stroke, stroke_fill=stroke_color)
    return layer


# ---------------------------------------------------------------- yearbook cards / stamps

def portrait_card(person: dict, size=(300, 380), name_color=(40, 28, 20), label_kind="serif", expression="neutral",
                  with_name: bool = True) -> Image.Image:
    """Photo with a thin border and the name underneath."""
    seed = int(person.get("seed", abs(hash(person["name"])) % 10000))
    photo = draw_portrait(seed, size, person.get("gender"), "sepia", person.get("expression", expression))
    cap = 54 if with_name else 8
    card = Image.new("RGBA", (size[0] + 12, size[1] + 12 + cap), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, card.width - 1, size[1] + 11], fill=(76, 58, 44, 255))
    card.paste(photo.convert("RGBA"), (6, 6))
    if with_name:
        label = person.get("label") or person["name"]
        f = font(label_kind, 26)
        tw = text_size(label, f)[0]
        d.text(((card.width - tw) // 2, size[1] + 22), label, font=f, fill=name_color)
    return card


def stamp_layer(text: str = "MISSING", color=(176, 28, 36), size: int = 56, angle: float = -14) -> Image.Image:
    f = font("mono_bold", size)
    tw, th = text_size(text, f)
    pad = 16
    layer = Image.new("RGBA", (tw + pad * 4, th + pad * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([4, 4, layer.width - 5, layer.height - 5], outline=color + (235,), width=7)
    d.rectangle([14, 14, layer.width - 15, layer.height - 15], outline=color + (200,), width=2)
    d.text((pad * 2, pad * 1.1), text, font=f, fill=color + (235,))
    arr = np.asarray(layer).copy()
    rng = np.random.default_rng(len(text))
    arr[..., 3] = (arr[..., 3] * (0.62 + 0.38 * (rng.random(arr.shape[:2]) > 0.18))).astype(np.uint8)   # worn ink
    return Image.fromarray(arr).rotate(angle, expand=True, resample=Image.BICUBIC)


def red_ring(size: tuple[int, int], progress: float, color=(190, 24, 32), width: int = 9) -> Image.Image:
    """A hand-drawn-looking red circle that draws itself (progress 0-1)."""
    w, h = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = []
    n = max(2, int(120 * clamp01(progress)))
    for k in range(n + 1):
        a = -math.pi / 2 + 2.1 * math.pi * k / 120
        wob = 1 + 0.025 * math.sin(a * 3 + 1.0)
        pts.append((w / 2 + math.cos(a) * (w / 2 - width * 2) * wob, h / 2 + math.sin(a) * (h / 2 - width * 2) * wob))
    if len(pts) > 1:
        d.line(pts, fill=color + (235,), width=width, joint="curve")
    return layer


# ---------------------------------------------------------------- phone UI

def bubble_layer(text: str, mine: bool, max_w: int = 640, size: int = 40) -> Image.Image:
    f = font("sans", size)
    lines = wrap(text, f, max_w - 56)
    tw = max(text_size(ln, f)[0] for ln in lines)
    bw, bh = tw + 56, int(len(lines) * size * 1.3) + 36
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=34, fill=(10, 132, 255, 255) if mine else (44, 46, 54, 255))
    for i, ln in enumerate(lines):
        d.text((28, 16 + i * size * 1.3), ln, font=f, fill=(255, 255, 255))
    return layer


def typing_dots(phase: float) -> Image.Image:
    layer = Image.new("RGBA", (150, 74), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, 149, 73], radius=37, fill=(44, 46, 54, 255))
    for k in range(3):
        lift = max(0.0, math.sin(phase * math.pi * 2 - k * 0.9))
        a = int(110 + 145 * lift)
        _ellipse(d, 38 + k * 37, 37 - lift * 6, 9, 9, (200, 202, 210, a))
    return layer


def chat_header(contact: str, avatar_seed: int, status: str = "online") -> Image.Image:
    layer = Image.new("RGBA", (W, 170), (22, 24, 32, 255))
    d = ImageDraw.Draw(layer)
    d.text((40, 84), "<", font=font("sans_bold", 54), fill=(10, 132, 255))
    av = draw_portrait(avatar_seed, (96, 96), None, "color").convert("RGBA")
    mask = Image.new("L", (96, 96), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 95, 95], fill=255)
    layer.paste(av, (110, 58), mask)
    d.text((230, 62), contact, font=font("sans_bold", 44), fill=(245, 245, 248))
    d.text((230, 112), status, font=font("sans", 30), fill=(90, 210, 120))
    return layer


def notification_card(app: str, sender: str, text: str, when: str = "now") -> Image.Image:
    layer = Image.new("RGBA", (960, 230), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, 959, 229], radius=44, fill=(58, 60, 72, 235))
    d.rounded_rectangle([34, 30, 80, 76], radius=12, fill=(52, 199, 89, 255))
    d.text((98, 38), app.upper(), font=font("sans", 28), fill=(210, 212, 220))
    d.text((960 - 40 - text_size(when, font("sans", 28))[0], 38), when, font=font("sans", 28), fill=(170, 172, 182))
    d.text((34, 100), sender, font=font("sans_bold", 40), fill=(255, 255, 255))
    d.text((34, 154), text, font=font("sans", 38), fill=(230, 232, 238))
    return layer


# ---------------------------------------------------------------- compositing

def paste_layer(canvas: Image.Image, layer: Image.Image, x: float, y: float, alpha: float = 1.0, scale: float = 1.0, center: bool = False):
    if layer is None or alpha <= 0.002:
        return
    if scale != 1.0:
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BILINEAR)
    if center:
        x, y = x - layer.width / 2, y - layer.height / 2
    if alpha < 1.0:
        a = layer.getchannel("A").point(lambda v: int(v * alpha))
        layer = layer.copy()
        layer.putalpha(a)
    canvas.paste(layer, (int(x), int(y)), layer)
