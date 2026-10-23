"""YouTube channel banner, 2560x1440. YouTube shows the whole image on TV, a wide strip on desktop and only the centre 1546x423 on phones,
so the title lives inside that centre box."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from story_images import generate_still

OUT = Path(__file__).parent; W, H = 2560, 1440; rng = np.random.default_rng(8)
raw = OUT / "yt_banner_raw.png"
if not raw.exists():
    generate_still("a long empty concrete containment corridor at night, one flickering fluorescent light, wet floor reflections, heavy steel doors, at the far end a tall pale statue-like figure standing "
                   "motionless in the shadows, dark anime key art, painterly cinematic horror illustration, moody, deep shadows, film still, wide shot, absolutely no text, no letters, no numbers, no signs with writing",
                   raw, width=1536, height=864, seed=34)
img = Image.open(raw).convert("RGB").resize((W, H), Image.LANCZOS)
a = np.asarray(img, np.float32) / 255 * 0.78
yy, xx = np.mgrid[0:H, 0:W]; r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
a *= (1 - 0.6 * np.clip(r - 0.5, 0, 1) ** 1.5)[..., None]; a[..., 0] *= 1.05; a[..., 2] *= 1.08
a *= (1 - 0.12 * (np.arange(H) % 4 < 2))[:, None, None]; a += rng.normal(0, 0.03, a.shape)
sh = 10; a[:, sh:, 0] = a[:, :-sh, 0] * 0.5 + a[:, sh:, 0] * 0.5
for y in rng.integers(60, H - 60, 6):
    h = int(rng.integers(6, 18)); a[y:y + h] = np.roll(a[y:y + h], int(rng.integers(-80, 80)), axis=1)
img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).convert("RGBA")
F = "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"; cx, cy = W / 2, H / 2
for dx, col in ((-7, (255, 40, 50, 150)), (7, (40, 220, 235, 130)), (0, (238, 238, 232, 255))):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.text((cx + dx, cy - 30), "FOUNDATION TAPES", font=ImageFont.truetype(F, 150), fill=col, anchor="mm")
    if dx == 0:
        d.text((cx, cy + 82), "classified SCP files, told on corrupted tape", font=ImageFont.truetype(F, 50), fill=(225, 225, 220, 235), anchor="mm")
        d.ellipse((cx - 73, cy + 170 - 14, cx - 45, cy + 170 + 14), fill=(235, 30, 40, 255)); d.text((cx - 25, cy + 170), "REC", font=ImageFont.truetype(F, 44), fill=(238, 238, 232, 235), anchor="lm")
    img = Image.alpha_composite(img, lay.filter(ImageFilter.GaussianBlur(1.5)) if dx else lay)
img.convert("RGB").save(OUT / "yt_banner.png"); print("banner ok", (OUT / "yt_banner.png").stat().st_size // 1024, "KB")
Image.open(OUT / "logo.png").convert("RGB").resize((800, 800), Image.LANCZOS).save(OUT / "yt_logo.png"); print("logo ok")
