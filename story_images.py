"""
story_images.py
Generates the picture for every scene in a story's story.json that doesn't have
one yet, using the local FLUX.2 klein 4B model in models/flux2klein (Apache-2.0,
free for commercial use). On a 16 GB Mac: about 35 seconds a picture with the MLX build (venv-mlx + models/klein-q4), 3-5 minutes without.

Usage:
    python story_images.py stories/talking-fruit-garden            # only missing images
    python story_images.py stories/talking-fruit-garden --force    # redo all
    python story_images.py stories/my-new-story --width 576 --height 1024

Prompts in story.json can use {style} and {CharacterName}, which expand to the
story's style line and that character's "look" description, so every scene
describes the same character the same way.
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from run_control import check_cancelled

MODEL_DIR = Path(__file__).parent / "models" / "flux2klein"

# Fast path: the same FLUX.2 klein model in a 4-bit Apple-silicon (MLX) build - about 35 seconds a picture
# instead of 2.5-5 minutes, with the same look. Used automatically when both of these exist
# (venv-mlx holds the mflux runner; see the README). Otherwise the slower PyTorch path below runs.
MLX_BIN = Path(__file__).parent / "venv-mlx" / "bin" / "mflux-generate-flux2"
MLX_MODEL = Path(__file__).parent / "models" / "klein-q4"


def expand_prompt(story: dict, prompt: str) -> str:
    prompt = prompt.replace("{style}", story.get("style", ""))
    for name, c in story["characters"].items():
        if c.get("look"):
            prompt = prompt.replace("{" + name + "}", c["look"])
    return prompt


def mlx_available() -> bool:
    return MLX_BIN.exists() and (MLX_MODEL / "transformer").exists()


def _generate_mlx(prompt: str, width: int, height: int, seed: int, out: Path, cancel_event=None) -> None:
    """One picture through the MLX runner. Polls so the Stop button can end it mid-picture.
    The runner never overwrites a file - given an existing name it silently saves 'name_1.png' instead, which made
    "remake this picture" do nothing - so it renders into a fresh temp folder and the result is moved over `out`."""
    with tempfile.TemporaryDirectory() as tmp:
        _run_mlx(prompt, width, height, seed, Path(tmp) / "picture.png", cancel_event)
        made = Path(tmp) / "picture.png"
        if not made.exists():
            matches = sorted(Path(tmp).glob("picture*.png"))
            if not matches:
                raise RuntimeError("The image runner finished but wrote no picture.")
            made = matches[0]
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(made), str(out))


def _run_mlx(prompt: str, width: int, height: int, seed: int, out: Path, cancel_event=None) -> None:
    with tempfile.TemporaryFile("w+") as log:
        proc = subprocess.Popen(
            [str(MLX_BIN), "--model", str(MLX_MODEL), "--base-model", "flux2-klein-4b", "--prompt", prompt,
             "--width", str(width), "--height", str(height), "--steps", "4", "--seed", str(seed), "--output", str(out)],
            stdout=log, stderr=subprocess.STDOUT, text=True)
        try:
            while proc.poll() is None:
                check_cancelled(cancel_event)
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                proc.kill()
        if proc.returncode != 0:
            log.seek(0)
            raise RuntimeError(f"The image runner failed:\n{log.read()[-800:]}")


def generate_still(prompt: str, out: Path, width: int = 576, height: int = 1024, seed: int = 7, cancel_event=None) -> Path:
    """One picture from a prompt (MLX build only - the library's 'make a still' button)."""
    if not mlx_available():
        raise RuntimeError("The fast picture build isn't installed (venv-mlx + models/klein-q4) - see the README.")
    out.parent.mkdir(parents=True, exist_ok=True)
    _generate_mlx(prompt, width, height, seed, out, cancel_event)
    return out


def generate_images(story_dir: str, width: int = 576, height: int = 1024, force: bool = False,
                    only: list[int] | None = None, cancel_event=None) -> None:
    sdir = Path(story_dir).resolve()
    story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
    todo = [(i, s) for i, s in enumerate(story["scenes"], 1)
            if (only is None or i in only) and (force or only or not (sdir / s["image"]).exists())]
    if not todo:
        print("[images] Every scene already has an image (use --force to redo them).")
        return
    use_mlx = mlx_available()
    if not use_mlx and not MODEL_DIR.exists():
        raise FileNotFoundError(f"Image model not found at {MODEL_DIR} (or the fast build at {MLX_MODEL})")
    print(f"[images] Using the {'fast Apple-silicon (MLX) build' if use_mlx else 'slower PyTorch build'} - "
          f"about {'35 seconds' if use_mlx else '3-5 minutes'} a picture.", flush=True)

    if not use_mlx:
        import torch  # heavy imports, only needed on the slow path
        from diffusers import Flux2KleinPipeline
        pipe = Flux2KleinPipeline.from_pretrained(str(MODEL_DIR), dtype=torch.bfloat16)
        # 16 GB of shared memory can't hold the text encoder and the image model at once.
        pipe.enable_model_cpu_offload(device="mps" if torch.backends.mps.is_available() else "cuda")

    for i, scene in todo:
        check_cancelled(cancel_event)
        t0 = time.time()
        out = sdir / scene["image"]
        out.parent.mkdir(parents=True, exist_ok=True)
        # A remake (a specific scene asked for again) must give a DIFFERENT picture, so it gets a fresh seed.
        prompt, seed = expand_prompt(story, scene["image_prompt"]), 7 + i + (int(time.time()) % 1000 if only else 0)
        if use_mlx:
            _generate_mlx(prompt, width, height, seed, out, cancel_event)
        else:
            image = pipe(prompt=prompt, width=width, height=height, num_inference_steps=4, guidance_scale=1.0,
                         generator=torch.Generator("cpu").manual_seed(seed)).images[0]
            image.save(out)
        print(f"[images] Scene {i}/{len(story['scenes'])}: {time.time() - t0:.0f}s -> {out.name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("story_dir")
    parser.add_argument("--width", type=int, default=576)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    generate_images(args.story_dir, args.width, args.height, args.force)
