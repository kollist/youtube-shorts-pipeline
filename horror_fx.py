"""
horror_fx.py
The "corrupted tape" look for the rules-horror format. Takes a finished silent video, runs every frame through a VHS-style degradation whose strength
follows a tension curve, and inserts tape events (static bursts, freezes, blackouts, a subliminal flash frame, the tape dying at the end).
Why: analog-horror works because the damage itself reads as dread, an "official" tape that is slowly going wrong; the damage here is
timed to the story (clean at first, worse with every rule).

    process(in_mp4, out_mp4, curve=[(0, .1), (30, .5), (60, 1)], events=[{"t": 12.3, "kind": "static", "dur": 0.07}], label="HOTEL MARROW - ...")
"""

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 1280, 30


def _font(size):
    for p in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Supplemental/Courier New Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


class Tape:
    def __init__(self, label: str, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.label = label
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        self.vig = (1 - 0.55 * np.clip(d - 0.35, 0, 1) ** 1.5)[..., None].astype(np.float32)
        self.scan = np.where(np.arange(H) % 3 == 0, 0.82, 1.0).astype(np.float32)[:, None, None]
        self.noise = [self.rng.normal(0, 1, (H, W, 1)).astype(np.float32) for _ in range(6)]
        self.bands: list[dict] = []
        self._ov_cache: dict = {}
        self.font_s, self.font_m = _font(22), _font(26)

    def overlay(self, t: float, level: float) -> tuple[np.ndarray, np.ndarray]:
        """RGBA overlay (top strip): blinking REC, the tape counter, the tape label - cached per second."""
        key = (int(t), int(t * 2) % 2, int(level * 4))
        if key not in self._ov_cache:
            im = Image.new("RGBA", (W, 96), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
            if int(t * 2) % 2 == 0:
                d.ellipse([24, 28, 44, 48], fill=(235, 30, 30, 255))
            d.text((54, 24), "REC", font=self.font_m, fill=(240, 240, 240, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
            m, s = divmod(int(t), 60)
            d.text((W - 190, 24), f"SP  0:{m:02d}:{s:02d}", font=self.font_m, fill=(240, 240, 240, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
            d.text((24, 62), self.label, font=self.font_s, fill=(230, 230, 230, 235), stroke_width=2, stroke_fill=(0, 0, 0, 255))
            a = np.asarray(im, dtype=np.float32)
            self._ov_cache[key] = (a[..., :3], a[..., 3:] / 255.0)
        return self._ov_cache[key]

    def frame(self, f: np.ndarray, t: float, k: float, fi: int) -> np.ndarray:
        """f: float32 HxWx3 (0-255); k: tension 0..1."""
        lum = f.mean(axis=2, keepdims=True)
        f = lum + (f - lum) * (0.80 - 0.22 * k)                              # drained colour
        f = f * np.array([0.93, 1.0, 0.96], np.float32)                      # a sickly green-teal cast
        f = (f - 128) * (1.10 + 0.12 * k) + 128 - 8
        dx = int(1 + 5 * k)                                                  # chroma smear: red and blue drift apart
        f[..., 0] = np.roll(f[..., 0], dx, axis=1); f[..., 2] = np.roll(f[..., 2], -dx, axis=1)
        # tracking bands: horizontal strips that tear sideways, scroll up, and show up more as tension rises
        if self.rng.random() < 0.015 + 0.40 * k ** 2:
            self.bands.append({"y": int(self.rng.integers(0, H)), "h": int(self.rng.integers(14, 70 + 90 * k)), "dx": int(self.rng.integers(-30, 30) * (0.5 + k)),
                               "vy": float(self.rng.uniform(-14, -3)), "life": int(self.rng.integers(3, 10))})
        alive = []
        for b in self.bands:
            y0, y1 = int(max(0, b["y"])), int(min(H, b["y"] + b["h"]))
            if y1 > y0:
                f[y0:y1] = np.roll(f[y0:y1], b["dx"], axis=1) + 16 + self.noise[fi % 6][y0:y1] * 24
            b["y"] += b["vy"]; b["life"] -= 1
            if b["life"] > 0:
                alive.append(b)
        self.bands = alive
        f = f * self.scan
        f = f + self.noise[fi % 6] * (5 + 17 * k)                            # grain
        f = f * self.vig
        f = f * (1 + 0.025 * np.sin(t * 41) + (0.08 if self.rng.random() < 0.02 + 0.06 * k else 0))   # flicker
        rgb, a = self.overlay(t, k)
        f[:96] = f[:96] * (1 - a) + rgb * a
        return np.clip(f, 0, 255)


def _frames(path: str):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={W}:{H}:flags=bilinear", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3).astype(np.float32)
    p.wait()


def process(in_mp4: str, out_mp4: str, curve: list[tuple[float, float]], events: list[dict], label: str, flash_images: dict | None = None,
            out_size=(1080, 1920), log=print) -> Path:
    """curve: [(seconds, tension 0..1), ...] linear in between. events: {"t", "dur", "kind": static|roll|freeze|black|flash, "image": key into flash_images}."""
    tape = Tape(label)
    flash = {k: np.asarray(Image.open(v).convert("RGB").resize((W, H), Image.LANCZOS), np.float32) for k, v in (flash_images or {}).items()}
    xs, ys = zip(*curve)
    enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                            "-vf", f"scale={out_size[0]}:{out_size[1]}:flags=lanczos", "-c:v", "libx264", "-crf", "22", "-preset", "fast", "-pix_fmt", "yuv420p", str(out_mp4)],
                           stdin=subprocess.PIPE)
    held = None
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", in_mp4], capture_output=True, text=True).stdout.strip()
    total_frames = int(float(probe or 0) * FPS)
    try:
        for i, f in enumerate(_frames(in_mp4)):
            t = i / FPS; k = float(np.interp(t, xs, ys))
            ev = next((e for e in events if e["t"] <= t < e["t"] + e["dur"]), None)
            kind = ev["kind"] if ev else None
            if kind == "freeze":
                held = f if held is None else held
                f = held
            else:
                held = None
            if kind == "flash" and ev.get("image") in flash:
                f = flash[ev["image"]]
            out = tape.frame(f, t, 1.0 if kind in ("static", "roll") else k, i)
            if kind == "static":
                out = np.clip(128 + tape.noise[i % 6] * 70 + out * 0.15, 0, 255)
            elif kind == "roll":
                out = np.roll(out, int((t - ev["t"]) / ev["dur"] * H * 1.5) % H, axis=0)
            elif kind == "black":
                out = out * 0.0
            elif kind == "slam":                                  # the jump scare: the picture lunges at you, shakes, and flashes white
                k2 = min(1.0, (t - ev["t"]) / ev["dur"])
                z = 1 + 0.38 * min(1.0, k2 * 4)
                sx, sy = tape.rng.integers(-16, 17, 2) * (1 - k2)
                im = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).transform((W, H), Image.AFFINE,
                      (1 / z, 0, W / 2 - W / (2 * z) + sx, 0, 1 / z, H / 2 - H / (2 * z) + sy), Image.BILINEAR)
                out = np.asarray(im, dtype=np.float32) * (2.2 if k2 < 0.12 else 1.0)
            enc.stdin.write(out.astype(np.uint8).tobytes())
            if i % 150 == 0:
                log(f"[fx] frame {i}/{total_frames}")
        enc.stdin.close(); enc.wait()
    finally:
        if enc.poll() is None:
            enc.kill()
    return Path(out_mp4)
