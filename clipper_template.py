"""
clipper_template.py
The "KadClipper" look for clips: the layout every clipper channel uses, built for this project.

  background   the same clip, blurred and darkened, filling the 9:16 frame
  clip         the whole clip at full width (nothing cropped away), a little above the centre
  top          a neon pill with the channel handle (below the phone's status bar)
  captions     the karaoke captions, placed under the clip in the free middle area (clear of the phone's description/buttons at the bottom)
  progress     a thin neon bar along the bottom that fills as the clip plays (a reason to watch to the end)
  last 2.5 s   a big "FOLLOW @handle - for more GTA 6" card under the clip

Settings live in data/clip_template.json (so the dashboard can switch the template on and off); nothing changes while "enabled" is false.
The overlays are drawn once with PIL and composited by ffmpeg, so a clip still costs one ffmpeg pass.
"""

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).parent
CONFIG = BASE / "data" / "clip_template.json"
CACHE = BASE / "data" / "clip_template_cache"
W, H = 1080, 1920

DEFAULTS = {
    "enabled": False,
    "handle": "kadclipper",
    "cta": "FOR MORE GTA 6",
    "account": "kadclipper",                 # the dashboard account that posts these clips (accounts.py)
    "pink": [255, 52, 150], "orange": [255, 154, 40], "cyan": [38, 224, 232],
    "video_y": -30,                          # the clip's centre sits this many pixels above the frame centre
    "caption_margin_v": 560,                 # captions: distance from the bottom edge (under the clip, above the phone buttons)
    "title_margin_v": 415,                   # the hook line: distance from the top edge
}

_FONTS = ["/System/Library/Fonts/Supplemental/Impact.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/HelveticaNeue.ttc"]


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        pass
    cfg["handle"] = re.sub(r"[^A-Za-z0-9_.]", "", str(cfg.get("handle") or "")) or DEFAULTS["handle"]
    return cfg


def save(**changes) -> dict:
    cfg = load()
    for k, v in changes.items():
        if k in DEFAULTS and v is not None:
            cfg[k] = v
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({k: cfg[k] for k in DEFAULTS}, indent=2), encoding="utf-8")
    return load()


def active() -> dict | None:
    cfg = load()
    return cfg if cfg["enabled"] else None


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in _FONTS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _gradient(w: int, h: int, c0, c1) -> Image.Image:
    g = Image.new("RGBA", (w, h))
    px = g.load()
    for x in range(w):
        t = x / max(1, w - 1)
        col = tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3)) + (255,)
        for y in range(h):
            px[x, y] = col
    return g


def _pill(text: str, font, c0, c1, pad_x=46, pad_y=22, sub: str | None = None) -> Image.Image:
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = tmp.textlength(text, font=font)
    w, h = int(tw + 2 * pad_x), int(font.size + 2 * pad_y)
    body = _gradient(w, h, c0, c1)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(body, (0, 0), mask)
    d = ImageDraw.Draw(out)
    d.text((w // 2 + 3, h // 2 + 4), text, font=font, fill=(0, 0, 0, 120), anchor="mm")
    d.text((w // 2, h // 2), text, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return out


def overlay_paths(cfg: dict) -> tuple[Path, Path]:
    """(the always-on overlay, the end card), drawn once per setting."""
    key = re.sub(r"\W+", "_", f"{cfg['handle']}_{cfg['cta']}_{cfg['pink']}_{cfg['orange']}_{cfg['cyan']}_{cfg['video_y']}")
    CACHE.mkdir(parents=True, exist_ok=True)
    ui, end = CACHE / f"ui_{key}.png", CACHE / f"end_{key}.png"
    if ui.exists() and end.exists():
        return ui, end
    pink, orange, cyan = tuple(cfg["pink"]), tuple(cfg["orange"]), tuple(cfg["cyan"])
    # --- always on: the handle pill at the top, a tiny GTA 6 tag
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pill = _pill("@" + cfg["handle"].upper(), _font(58), pink, orange)
    im.alpha_composite(pill, ((W - pill.width) // 2, 215))
    tag = _pill("GTA 6", _font(40), (24, 16, 54), (40, 22, 80), pad_x=30, pad_y=12)
    d = ImageDraw.Draw(tag); d.rounded_rectangle([0, 0, tag.width - 1, tag.height - 1], radius=tag.height // 2, outline=cyan + (255,), width=3)
    im.alpha_composite(tag, ((W - tag.width) // 2, 215 + pill.height + 16))
    im.save(ui)
    # --- the last 2.5 seconds: the follow card, under the clip
    ev = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ev)
    cy = H // 2 + 560 + cfg["video_y"] // 2 - 240
    d.rounded_rectangle([60, cy, W - 60, cy + 250], radius=44, fill=(14, 8, 34, 235), outline=pink + (255,), width=6)
    d.text((W // 2, cy + 82), "FOLLOW", font=_font(96), fill=(255, 255, 255, 255), anchor="mm")
    handle = _pill("@" + cfg["handle"].upper(), _font(66), pink, orange, pad_x=44, pad_y=16)
    ev.alpha_composite(handle, ((W - handle.width) // 2, cy + 130))
    d.text((W // 2, cy + 280), cfg["cta"], font=_font(46), fill=cyan + (255,), anchor="mm")
    ev.save(end)
    return ui, end


def hex_color(rgb) -> str:
    return "0x%02X%02X%02X" % tuple(rgb)


def filter_chain(cfg: dict, duration: float) -> tuple[str, list[str], str]:
    """Returns (filter_complex up to the picture with every overlay, the extra ffmpeg input args, the output label).
    Inputs: 0 = the clip, 1 = the always-on overlay, 2 = the end card."""
    ui, end = overlay_paths(cfg)
    extra = ["-loop", "1", "-t", f"{duration:.2f}", "-i", str(ui), "-loop", "1", "-t", f"{duration:.2f}", "-i", str(end)]
    start_cta = max(0.5, duration - 2.5)
    chain = (
        f"[0:v]split[c_bg][c_fg];"
        f"[c_bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=28:3,eq=brightness=-0.18:saturation=0.9[bg];"
        f"[c_fg]scale={W}:-2[fg];"
        f"[bg][fg]overlay=0:(H-h)/2+({cfg['video_y']}),setsar=1[base];"
        f"[base][1:v]overlay=0:0[with_ui];"
        f"[with_ui][2:v]overlay=0:0:enable='gte(t,{start_cta:.2f})'[with_end];"
        f"color=c={hex_color(cfg['pink'])}:s={W}x14:r=30:d={max(duration, 0.1):.2f}[bar];"
        f"[with_end][bar]overlay=x='-W+W*t/{max(duration, 0.1):.2f}':y=H-14:eval=frame[stacked]"
    )
    return chain, extra, "stacked"


def _bgr(rgb) -> str:
    return "&H00%02X%02X%02X" % (rgb[2], rgb[1], rgb[0])


HIGHLIGHT = "&H003CD6FF&"                                # the spoken word: bright gold (ASS colours are BGR)


def ass_header(cfg: dict, width: int = W, height: int = H) -> str:
    """Caption styles for the template: Impact, no box, a thick dark-purple outline and shadow; a separate Title style for the hook line above the clip."""
    outline = "&H003A0A16"                               # the template's deep purple
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Impact,96,&H00FFFFFF,&H000000FF,{outline},&H80000000,0,0,0,0,100,100,1,0,1,9,4,2,50,50,{cfg['caption_margin_v']},1
Style: Title,Impact,78,&H00FFFFFF,&H000000FF,{outline},&H80000000,0,0,0,0,100,100,1,0,1,8,4,8,70,70,{cfg['title_margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def title_line(title: str, duration: float, max_chars: int = 24) -> str | None:
    """The hook line above the clip: upper case, at most 2 lines, shown for the whole clip."""
    from cut_clips import _format_ass_timestamp
    words = re.sub(r"[{}\\]", "", (title or "").upper()).split()
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    if not lines:
        return None
    text = "\\N".join(lines[:2]) + ("..." if len(lines) > 2 else "")
    return f"Dialogue: 1,{_format_ass_timestamp(0)},{_format_ass_timestamp(duration)},Title,,0,0,0,,{{\\fad(200,0)}}{text}"
