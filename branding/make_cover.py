"""Facebook cover / banner: a local FLUX picture of a dark containment corridor with something at the far end, taped over with VHS damage and the page name.
The title sits in the middle third so the mobile crop (which trims both sides) never cuts it."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from story_images import generate_still

OUT = Path(__file__).parent; W, H = 1640, 624; rng = np.random.default_rng(5)
raw = OUT / "cover_raw.png"
if not raw.exists():
    generate_still("a long empty concrete containment corridor at night, one flickering fluorescent light, wet floor reflections, heavy steel doors, at the far end a tall pale statue-like figure standing "
                   "motionless in the shadows, dark anime key art, painterly cinematic horror illustration, moody, deep shadows, film still, wide shot, absolutely no text, no letters, no numbers, no signs with writing",
                   raw, width=1344, height=512, seed=21)
img = Image.open(raw).convert("RGB").resize((W, H), Image.LANCZOS)
a = np.asarray(img, np.float32) / 255
a = a * 0.8                                                                          # darker so the title reads
yy, xx = np.mgrid[0:H, 0:W]; r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
a *= (1 - 0.6 * np.clip(r - 0.5, 0, 1) ** 1.5)[..., None]
a[..., 0] *= 1.05; a[..., 2] *= 1.08
a *= (1 - 0.14 * (np.arange(H) % 4 < 2))[:, None, None]; a += rng.normal(0, 0.03, a.shape)
sh = 8; a[:, sh:, 0] = a[:, :-sh, 0] * 0.5 + a[:, sh:, 0] * 0.5
for y in rng.integers(40, H - 40, 5):
    h = int(rng.integers(5, 14)); a[y:y + h] = np.roll(a[y:y + h], int(rng.integers(-60, 60)), axis=1)
img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
F = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"
def txt(draw, xy, s, font, fill, **k): draw.text(xy, s, font=font, fill=fill, anchor="mm", **k)
for dx, col in ((-6, (255, 40, 50, 150)), (6, (40, 220, 235, 130)), (0, (238, 238, 232, 255))):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    txt(d, (W / 2 + dx, H / 2 - 20), "FOUNDATION TAPES", ImageFont.truetype(F, 104), col)
    if dx == 0:
        txt(d, (W / 2, H / 2 + 62), "classified files, told on corrupted tape", ImageFont.truetype(F, 38), (225, 225, 220, 230))
        d.ellipse((W / 2 - 62, H / 2 + 120 - 12, W / 2 - 38, H / 2 + 120 + 12), fill=(235, 30, 40, 255)); d.text((W / 2 - 22, H / 2 + 120), "REC", font=ImageFont.truetype(F, 34), fill=(238, 238, 232, 235), anchor="lm")
    img = Image.alpha_composite(img, lay.filter(ImageFilter.GaussianBlur(1.2)) if dx else lay)
img.convert("RGB").save(OUT / "cover.png"); print("ok")
