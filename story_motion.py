"""
story_motion.py
Makes a still picture move: a depth model (Depth Anything V2 Small, Apache-2.0, in
models/depth/da2-small) estimates how near each part of the picture is, and the
"camera" then drifts through it so near things shift against the background
(parallax) instead of the whole picture just sliding. On top of that: drifting
dust/embers, slow light flicker, film grain, and optional camera shake.

This is camera movement, not character animation - eyes don't blink and mouths
don't move. Real animation needs an image-to-video model, which is too heavy for
a 16 GB Mac.

Usage (test one picture):
    python story_motion.py stories/the-new-boy/images/scene1.png out.mp4 --seconds 6
"""

import argparse
import subprocess
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

DEPTH_DIR = Path(__file__).parent / "models" / "depth" / "da2-small"
FPS = 30
OUT_W, OUT_H = 1080, 1920
_depth_model = None


def _load_depth_model():
    global _depth_model
    if _depth_model is None:
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        if not DEPTH_DIR.exists():
            raise FileNotFoundError(f"Depth model not found at {DEPTH_DIR}")
        _depth_model = (AutoImageProcessor.from_pretrained(str(DEPTH_DIR)),
                        AutoModelForDepthEstimation.from_pretrained(str(DEPTH_DIR)).eval())
    return _depth_model


def estimate_depth(image: Image.Image, cache: Path | None = None) -> np.ndarray:
    """(H, W) float array in 0..1 where 1 = nearest. Cached on disk as an 8-bit PNG."""
    if cache is not None and cache.exists():
        return np.asarray(Image.open(cache), dtype=np.float32) / 255.0
    processor, model = _load_depth_model()
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        pred = model(**inputs).predicted_depth            # larger = nearer
    pred = F.interpolate(pred[None], size=(image.height, image.width), mode="bicubic", align_corners=False)[0, 0].numpy()
    lo, hi = np.percentile(pred, [2, 98])
    depth = np.clip((pred - lo) / max(1e-6, hi - lo), 0, 1)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray((depth * 255).astype(np.uint8)).save(cache)
    return depth


def _smooth(depth: torch.Tensor, passes: int = 2) -> torch.Tensor:
    """Softens depth edges so near objects don't tear away from what's behind them."""
    for _ in range(passes):
        depth = F.avg_pool2d(depth, 9, stride=1, padding=4, count_include_pad=False)
    return depth


def _ease(x: float) -> float:
    return x * x * (3 - 2 * x)


# (direction x, direction y, push-in strength) - varied per scene so a video doesn't repeat one move
MOVES = [(1.0, 0.4, 1.0), (-1.0, -0.3, 1.0), (0.6, -0.8, 0.6), (-0.7, 0.7, 1.0), (1.0, 0.0, 0.3)]


class Dust:
    """Soft drifting specks (dust in light, pollen, embers) that sell the depth of a scene."""
    def __init__(self, w: int, h: int, count: int, color: tuple, seed: int):
        rng = np.random.default_rng(seed)
        self.w, self.h, self.color = w, h, np.array(color, dtype=np.float32)
        self.pos = rng.uniform([0, 0], [w, h], size=(count, 2))
        self.vel = np.stack([rng.normal(0, 5, count), -np.abs(rng.normal(9, 4, count))], axis=1)   # px/s, drifting up
        self.size = rng.uniform(1.2, 3.2, count)
        self.phase = rng.uniform(0, 6.28, count)
        self.base = rng.uniform(0.25, 0.8, count)
        yy, xx = np.mgrid[-6:7, -6:7]
        self.dist2 = (xx ** 2 + yy ** 2).astype(np.float32)

    def draw(self, frame: np.ndarray, t: float) -> None:
        pos = (self.pos + self.vel * t) % [self.w, self.h]
        for (x, y), s, ph, b in zip(pos, self.size, self.phase, self.base):
            xi, yi = int(x), int(y)
            if 6 <= xi < self.w - 6 and 6 <= yi < self.h - 6:
                blob = np.exp(-self.dist2 / (2 * s * s))[..., None] * (b * (0.6 + 0.4 * np.sin(t * 1.7 + ph)))
                frame[yi - 6:yi + 7, xi - 6:xi + 7] += blob * self.color


def parallax_clip(image_path: Path, length: float, index: int, out: Path, depth_cache: Path | None = None,
                  fx: list[str] | None = None, shake: float = 0.0, fade: float = 0.3, seed: int = 0) -> None:
    """Renders `length` seconds of drifting camera over the picture into `out` (1080x1920 mp4, no sound)."""
    fx = fx if fx is not None else ["dust", "grain", "flicker"]
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    depth = torch.from_numpy(estimate_depth(img, depth_cache))[None, None].float()
    depth = _smooth(F.interpolate(depth, size=(h, w), mode="bilinear", align_corners=False))
    rgb = torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0).permute(2, 0, 1)[None]

    ys, xs = torch.meshgrid(torch.linspace(-1, 1, h), torch.linspace(-1, 1, w), indexing="ij")
    base = torch.stack([xs, ys], dim=-1)[None]                      # (1,h,w,2)
    dx_dir, dy_dir, push = MOVES[index % len(MOVES)]
    amp, zoom_max = 0.035, 0.07 * push
    frames = int(length * FPS)
    rng = np.random.default_rng(seed + index)
    dust = Dust(w, h, 70, (1.0, 0.93, 0.8), seed + index) if "dust" in fx else None

    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
           "-vf", f"scale={OUT_W}:{OUT_H}:flags=lanczos,fade=t=in:st=0:d={fade},fade=t=out:st={length - fade:.2f}:d={fade},format=yuv420p",
           "-an", "-c:v", "libx264", "-crf", "21", "-preset", "medium", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    shake_xy = np.zeros(2)
    try:
        for f in range(frames):
            s = _ease(f / max(1, frames - 1))
            travel = (2 * s - 1)
            if shake:
                shake_xy = 0.85 * shake_xy + rng.normal(0, shake * 0.004, 2)   # smoothed random jitter
            near = depth - 0.45                                     # near things move one way, far things the other
            scale = (1.0 + zoom_max * s * (0.4 + depth)).permute(0, 2, 3, 1)   # push in, near things faster
            grid = base / scale + torch.cat([near * amp * travel * dx_dir, near * amp * travel * dy_dir], dim=1).permute(0, 2, 3, 1)
            grid = grid + torch.tensor(shake_xy, dtype=torch.float32)
            frame = F.grid_sample(rgb, grid, mode="bilinear", padding_mode="border", align_corners=True)[0].permute(1, 2, 0).numpy()
            t = f / FPS
            if "flicker" in fx:
                frame = frame * (1.0 + 0.035 * np.sin(t * 2.3) + 0.02 * np.sin(t * 7.1 + 1.0))
            if dust is not None:
                dust.draw(frame, t)
            if "grain" in fx:
                frame = frame + rng.normal(0, 0.018, frame.shape).astype(np.float32)
            proc.stdin.write((np.clip(frame, 0, 1) * 255).astype(np.uint8).tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding the animated scene")
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("out")
    parser.add_argument("--seconds", type=float, default=6)
    parser.add_argument("--move", type=int, default=0)
    parser.add_argument("--shake", type=float, default=0.0)
    args = parser.parse_args()
    parallax_clip(Path(args.image), args.seconds, args.move, Path(args.out), Path(args.out).with_suffix(".depth.png"), shake=args.shake)
    print("wrote", args.out)
