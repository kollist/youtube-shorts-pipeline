"""text_layers.py - font loading and styled text layers (used for the horror poster title)."""

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
