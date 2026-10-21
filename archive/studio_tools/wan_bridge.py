"""
wan_bridge.py
Bridge to WanGP / Wan2GP (https://github.com/deepbeepmeep/Wan2GP): open-source Wan, LTX and Hunyuan video models that
turn a still picture into a few seconds of real motion (hair moving, eyes blinking, a camera that actually travels).

Why a bridge and not built in: WanGP needs an NVIDIA (or some AMD) graphics card - it doesn't run on a Mac - so it
runs on a GPU machine you control (a rented GPU, Colab, a friend's PC). This module packages your episode's pictures
into a WanGP queue file, and takes the finished clips back so the video builder uses them instead of the camera-drift
animation for those scenes.

LICENSE (read before use): WanGP's SOFTWARE is licensed non-commercial - we don't copy or bundle any of its code,
you install it yourself. Videos it OUTPUTS may be used commercially, but a commercial release must include a notice
that it was produced using WanGP; this app adds that line automatically to the description when Wan clips are used.
Full text: https://github.com/deepbeepmeep/Wan2GP/blob/main/LICENSE.txt

THE JOB FILE FORMAT IS UNTESTED against a real WanGP install (no GPU here). Validate on your GPU machine first:
    python wgp.py --process wan_jobs.zip --dry-run
If it complains, send me the message and I'll adjust the keys.
"""

import json
import re
import shutil
import zipfile
from pathlib import Path

ATTRIBUTION = "Some clips were generated with WanGP (https://github.com/deepbeepmeep/Wan2GP)."

# model_type values come from WanGP's own defaults/ folder.
MODELS = {
    "wan22_i2v": {"label": "Wan 2.2 Image-to-Video 14B (best motion, needs a big GPU)", "model_type": "i2v_2_2",
                  "resolution": "480x832", "video_length": 81, "steps": 30},
    "ltx2_distilled": {"label": "LTX-2 distilled 19B (faster)", "model_type": "ltx2_distilled",
                       "resolution": "480x832", "video_length": 121, "steps": 8},
}
CAMERAS = ["slow cinematic push-in", "gentle pan to the right", "slow pull-back reveal", "subtle handheld drift", "slow tilt upward"]


def motion_prompt(scene: dict, index: int) -> str:
    """What should move: the scene's own wan_prompt if set, else a camera move plus the scene description."""
    if scene.get("wan_prompt"):
        return scene["wan_prompt"]
    subject = re.sub(r"\{\w+\}", "", scene.get("image_prompt", "")).strip(" ,.")
    subject = re.sub(r"\s+", " ", subject)[:260]
    return (f"{CAMERAS[index % len(CAMERAS)]}. {subject}. Natural subtle motion: breathing, blinking, hair and cloth moving, "
            "light flicker. Keep the same character and composition. No cuts, no text.")


def export_pack(ep_dir: str, model: str = "wan22_i2v") -> Path:
    """Writes <episode>/wan/wan_jobs.zip (queue.json + the pictures) and a how-to. Returns the zip path."""
    ep = Path(ep_dir)
    story = json.loads((ep / "story.json").read_text(encoding="utf-8"))
    cfg = MODELS[model]
    out_dir = ep / "wan"
    out_dir.mkdir(exist_ok=True)
    manifest, picked = [], []
    for i, scene in enumerate(story["scenes"], 1):
        image = ep / scene["image"]
        if not image.exists():
            continue
        name = f"task{i}_image_start_0{image.suffix}"
        picked.append((image, name))
        manifest.append({"id": i, "params": {
            "model_type": cfg["model_type"], "base_model_type": cfg["model_type"], "settings_version": 2.0,
            "prompt": motion_prompt(scene, i - 1), "negative_prompt": "", "image_prompt_type": "S", "image_start": name,
            "resolution": cfg["resolution"], "video_length": cfg["video_length"], "num_inference_steps": cfg["steps"],
            "seed": 7 + i, "repeat_generation": 1,
        }})
    if not manifest:
        raise RuntimeError("Make this episode's pictures first - Wan animates each picture.")
    zip_path = out_dir / "wan_jobs.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("queue.json", json.dumps(manifest, indent=2))
        for image, name in picked:
            z.write(image, name)
    (out_dir / "HOW_TO.txt").write_text(
        f"1. On a GPU machine with WanGP installed (https://github.com/deepbeepmeep/Wan2GP), copy wan_jobs.zip next to wgp.py.\n"
        f"2. Check it:  python wgp.py --process wan_jobs.zip --dry-run\n"
        f"3. Run it:    python wgp.py --process wan_jobs.zip --output-dir ./renders\n"
        f"4. Outputs come out in the order of the pictures: task1 = scene 1, task2 = scene 2, ...\n"
        f"5. Back in this app: Series > the episode > Wan clips > upload each clip against its scene number.\n"
        f"Model: {cfg['label']}.\n{ATTRIBUTION}\n", encoding="utf-8")
    return zip_path


def clip_path(ep_dir: str | Path, scene: int) -> Path:
    return Path(ep_dir) / "wan" / f"scene{scene}.mp4"


def import_clip(ep_dir: str, scene: int, data: bytes) -> Path:
    path = clip_path(ep_dir, scene)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return path


def wan_clips(ep_dir: str | Path) -> list[int]:
    return sorted(int(m.group(1)) for p in (Path(ep_dir) / "wan").glob("scene*.mp4") if (m := re.fullmatch(r"scene(\d+)\.mp4", p.name)))


def attribution_if_used(ep_dir: str | Path) -> str:
    return ATTRIBUTION if wan_clips(ep_dir) else ""
