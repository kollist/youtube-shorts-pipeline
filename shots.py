"""
shots.py
Per-scene "motion prompts" for turning a story's pictures into real video clips with an image-to-video tool
(Kling, Google Flow/Veo, Dreamina/Seedance, Hailuo... using the free daily credits of their web apps).

Claude (via series._llm_json) reads the scenes and writes, for each picture, one short prompt describing ONLY what moves
(camera + subject action), and marks the few "hero" scenes where real animation pays off most - so a day's free credits
animate the shots that matter and the rest keep the app's own depth-parallax motion.

Clips animated this way come back through import_clip() into <episode>/motion/sceneN.mp4, which the video builder prefers
over its own camera-drift animation.
"""

import json
import re
from pathlib import Path

from series import _llm_json

SYSTEM = """You prepare motion prompts for an image-to-video model (Kling / Veo / Seedance style). The model is given the scene's
still picture and your prompt, and animates it for ~5 seconds. Write ONE prompt per scene describing only MOTION:
- first the camera move (slow push-in, slow pull-back, gentle pan, low-angle tracking, handheld drift, static),
- then what the subject does (one concrete action: turns its head, blinks, breathes, wings flutter, hair and cloth move, eyes narrow),
- then ambient motion (dust, fog drifting, light flicker, rain, grass swaying).
Rules: max 40 words; keep the same characters and composition; no cuts; no text, no captions, no new characters;
do not re-describe the picture's look. One action per clip - simple motion animates far better than complicated motion.
Also mark "hero": true on the 3-4 scenes where animation matters most (the hook, the turning point, the final image) and false elsewhere.
Respond with ONLY: {"shots": [{"scene": 1, "hero": true, "prompt": "..."}]} - one entry per scene, in order."""


def plan_shots(ep_dir: str, heroes: int = 4) -> list[dict]:
    ep = Path(ep_dir)
    path = ep / "story.json"
    story = json.loads(path.read_text(encoding="utf-8"))
    scenes = story["scenes"]
    brief = []
    for i, s in enumerate(scenes, 1):
        pic = re.sub(r"\{(\w+)\}", lambda m: (story["characters"].get(m.group(1), {}).get("look") or m.group(1)).split(",")[0], s.get("image_prompt", ""))
        pic = pic.replace(story.get("style", "")[:40], "").strip(" ,.")[:240]
        brief.append(f"Scene {i} ({s.get('stage') or 'scene'}): picture = {pic}\n   narration = {' '.join(l['text'] for l in s['lines'])[:200]}")
    out = _llm_json(SYSTEM, f"Story: {story.get('title')}\nChoose at most {heroes} hero scenes.\n\n" + "\n".join(brief))
    by_scene = {int(x["scene"]): x for x in out.get("shots", []) if x.get("prompt") and str(x.get("scene", "")).isdigit()}
    if len(by_scene) < max(2, len(scenes) // 2):
        raise RuntimeError("The writer returned too few motion prompts - try again.")
    chosen = 0
    for i, s in enumerate(scenes, 1):
        x = by_scene.get(i)
        if not x:
            continue
        s["motion_prompt"] = re.sub(r"\s+", " ", x["prompt"]).strip()[:400]
        s["hero"] = bool(x.get("hero")) and chosen < heroes
        chosen += s["hero"]
    path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
    return shot_list(ep_dir)


CAMERAS = ["slow cinematic push-in", "gentle pan to the right", "slow pull-back reveal", "subtle handheld drift", "slow tilt upward"]


def motion_prompt(scene: dict, index: int) -> str:
    """What should move: the scene's own prompt if it has one, else a camera move plus the scene description."""
    if scene.get("motion_prompt") or scene.get("wan_prompt"):
        return scene.get("motion_prompt") or scene["wan_prompt"]
    subject = re.sub(r"\{\w+\}", "", scene.get("image_prompt", "")).strip(" ,.")
    subject = re.sub(r"\s+", " ", subject)[:260]
    return (f"{CAMERAS[index % len(CAMERAS)]}. {subject}. Natural subtle motion: breathing, blinking, hair and cloth moving, "
            "light flicker. Keep the same character and composition. No cuts, no text.")


def shot_list(ep_dir: str) -> list[dict]:
    ep = Path(ep_dir)
    story = json.loads((ep / "story.json").read_text(encoding="utf-8"))
    from series import STORIES_DIR
    return [{"scene": i, "hero": bool(s.get("hero")), "prompt": motion_prompt(s, i - 1), "written": bool(s.get("motion_prompt") or s.get("wan_prompt")),
             "picture": (ep / s["image"]).resolve().relative_to(STORIES_DIR.resolve()).as_posix(), "has_picture": (ep / s["image"]).exists(),
             "seconds": round(sum(len(l["text"].split()) for l in s["lines"]) / 2.4 + 1.5, 1)} for i, s in enumerate(story["scenes"], 1)]


def set_prompt(ep_dir: str, scene: int, prompt: str) -> None:
    path = Path(ep_dir) / "story.json"
    story = json.loads(path.read_text(encoding="utf-8"))
    story["scenes"][scene - 1]["motion_prompt"] = prompt.strip()[:400]
    path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")


def motion_clip_path(ep_dir, scene: int) -> Path:
    return Path(ep_dir) / "motion" / f"scene{scene}.mp4"


def motion_clips(ep_dir) -> list[int]:
    return sorted(int(m.group(1)) for p in (Path(ep_dir) / "motion").glob("scene*.mp4") if (m := re.fullmatch(r"scene(\d+)\.mp4", p.name)))


def import_clip(ep_dir: str, scene: int, data: bytes) -> Path:
    path = motion_clip_path(ep_dir, scene)
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return path
