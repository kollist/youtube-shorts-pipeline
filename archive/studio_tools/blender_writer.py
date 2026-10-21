"""
blender_writer.py
Topic in -> a finished 3D explainer short out (free; Blender renders on this Mac).
Claude writes (1) the narration, split into scenes, and (2) a Blender scene script using blender_kit's helpers - one composed
shot per narration beat. The script is checked by a quick low-resolution test render; if Blender reports an error, the error is
sent back to Claude to fix (up to 3 tries). Then the full render runs and the video lands in the Studio results strip.

    python blender_writer.py "How tall is a stack of a billion dollar bills?"
"""

import ast
import json
import re
import shutil
from pathlib import Path

import blender_video
from series import VOICES, _llm_json

BASE = Path(__file__).parent
SCENES_DIR = BASE / "blender_scenes"
EXAMPLE_SCRIPT = SCENES_DIR / "dollar_stack.py"
EXAMPLE_SPEC = SCENES_DIR / "dollar_stack.json"


def kit_api() -> str:
    """The helper functions Claude may call, read straight from blender_kit.py so the prompt never goes stale."""
    tree = ast.parse((BASE / "blender_kit.py").read_text(encoding="utf-8"))
    lines = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_") and node.name not in ("args", "render_frames", "set_range", "f", "camera_path", "sky_keys"):
            doc = (ast.get_docstring(node) or "").split("\n")[0]
            lines.append(f"k.{node.name}({ast.unparse(node.args)})" + (f"  # {doc}" if doc else ""))
    return "\n".join(lines)


SYSTEM = """You make vertical 3D explainer shorts (like "how big is X", "what if Y") rendered in Blender by a Python scene script.
You output the narration AND the scene script. Be rigorous: this is an educational video, so every number must be real, checkable
and derived (put the arithmetic in the script's docstring). Never invent statistics. If a figure is uncertain, don't use it.

NARRATION: 5-6 scenes, ~12-16 words each, 65-85 words total, plain spoken English, numbers written as words. Scene 1 is a hook with a
surprising, specific claim. The last scene ends with a short question. No greetings.

SCENE SCRIPT (Python, runs inside Blender, 720x1280 vertical):
    import blender_kit as k
    def build(t):              # t = [(start_s, end_s), ...] one entry per narration scene, in order
        k.reset(sky=(r, g, b))
        with k.shot(t[0], cam=(x,y,z), cam_end=(x,y,z), look=(x,y,z), look_end=(x,y,z), sky=(r,g,b)):
            ...objects and labels for this shot...
        ...one `with k.shot(...)` per narration scene (use last=True on the final shot)...
        k.set_range(t[-1][1])
Available helpers (k = blender_kit):
{api}

RULES THAT MAKE SHOTS READABLE:
- ONE idea per shot, built at the scale where its subject is clearly visible (each shot can use its own units: metres, km...).
- Portrait frame: the camera sees about 0.55x its distance in width and about 1.0x its distance in height. Put the main subject
  about 1.2x its own height away; the camera looks at the subject's middle (look=...). Camera moves slowly: cam -> cam_end.
- Labels: k.text size about 1/10 of the camera distance, never wider than ~0.5x the camera distance (portrait is narrow);
  keep each label to 1-3 words per line and use separate k.text calls per line. Labels face the camera automatically.
- Colours: soft, flat, high contrast against the sky. Dark sky for space/night/abstract, light sky for daytime. White/gold text.
- CAPTIONS are burned into the bottom ~22% of every frame, so nothing important may sit there. Keep the subject and all labels inside the
  upper ~75% of the picture (the camera already lifts the scene a little), and never put a label near the very top or bottom edge.
- Draw things in true proportion when you can; if you exaggerate a size so it is visible, say so in the label or narration.
- Only use the helpers listed. Objects are made by calling them inside the `with k.shot` block. No imports except blender_kit and math.
Respond with ONLY this JSON (escape newlines in the script as \\n):
{{"title": "2-4 words", "scenes": [{{"narration": "...", "min_seconds": 3}}], "facts": [{{"claim": "...", "derivation": "..."}}],
 "caption": "Instagram caption: hook line (max 100 chars) + one question", "hashtags": ["#a", "#b", "#c", "#d", "#e"], "script": "..."}}"""

FIX_SYSTEM = """You fix a Blender scene script. You get the script and the error (or a problem) from a test render. Return ONLY
{"script": "<the corrected full script, newlines escaped as \\n>"}. Keep the same shots and labels; change only what the error requires.
Use only these helpers (k = blender_kit):
""" 


def _check_syntax(script: str) -> None:
    ast.parse(script)
    if "def build(t)" not in script:
        raise RuntimeError("The script has no build(t) function.")


def create_blender_video(topic: str, voice: str = "adult_man", music: bool = True, log=print, cancel_event=None) -> Path:
    log(f"[3d] Writing a 3D explainer about: {topic}")
    example = f"EXAMPLE SPEC:\n{EXAMPLE_SPEC.read_text(encoding='utf-8')}\n\nEXAMPLE SCENE SCRIPT:\n{EXAMPLE_SCRIPT.read_text(encoding='utf-8')}"
    system = SYSTEM.format(api=kit_api())
    out = _llm_json(system + "\n\n" + example, f"Topic: {topic}")
    scenes = [s for s in out.get("scenes", []) if s.get("narration")]
    script = out.get("script", "")
    if len(scenes) < 4 or not script:
        raise RuntimeError("The writer returned an incomplete script - try again.")
    slug = re.sub(r"[^a-z0-9]+", "-", (out.get("title") or topic).lower()).strip("-")[:36] or "explainer"
    SCENES_DIR.mkdir(exist_ok=True)
    script_path, spec_path = SCENES_DIR / f"{slug}.py", SCENES_DIR / f"{slug}.json"
    spec = {"title": out.get("title") or topic, "voice": voice if voice in VOICES else "adult_man", "music": "curious", "scene_script": script_path.name,
            "caption_colors": {}, "scenes": [{"narration": re.sub(r"\s+", " ", s["narration"]).strip(), "min_seconds": float(s.get("min_seconds", 3))} for s in scenes],
            "facts": out.get("facts", []), "caption": out.get("caption", ""), "hashtags": out.get("hashtags", [])}

    # test render (one low-res frame per scene); on an error, send it back to Claude to fix
    for attempt in range(1, 4):
        try:
            _check_syntax(script)
            script_path.write_text(script, encoding="utf-8")
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"[3d] Test render (try {attempt}/3)...")
            blender_video.build_blender_video(str(spec_path), stills=True, log=log, cancel_event=cancel_event)
            break
        except (RuntimeError, SyntaxError) as e:
            if "cancel" in str(e).lower() or attempt == 3:
                raise RuntimeError(f"The 3D scene script kept failing: {str(e)[-600:]}")
            log(f"[3d] The script had a problem ({str(e)[-160:].strip()}) - asking Claude to fix it...")
            script = _llm_json(FIX_SYSTEM + kit_api(), f"SCRIPT:\n{script}\n\nERROR:\n{str(e)[-1500:]}").get("script", script)

    final = blender_video.build_blender_video(str(spec_path), log=log, cancel_event=cancel_event, no_music=not music)
    import faceless
    faceless.FACELESS_DIR.mkdir(exist_ok=True)
    dest = faceless.FACELESS_DIR / f"3d-{slug}.mp4"
    shutil.copyfile(final, dest)
    notes = "; ".join(f"{x.get('claim')} ({x.get('derivation')})" for x in spec["facts"])
    dest.with_suffix(".json").write_text(json.dumps({"title": spec["title"], "script": " ".join(s["narration"] for s in spec["scenes"]),
                                                    "facts": notes, "caption": spec["caption"], "hashtags": spec["hashtags"]}, ensure_ascii=False), encoding="utf-8")
    log(f"[3d] Ready in Studio -> {dest.name}")
    return dest


if __name__ == "__main__":
    import sys
    create_blender_video(" ".join(sys.argv[1:]) or "How tall is a stack of a billion dollar bills?")
