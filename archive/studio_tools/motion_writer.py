"""
motion_writer.py
Topic in -> a finished code-drawn motion-graphics short out (free: the writer is your Claude subscription / Groq,
the pictures are drawn by motion_gfx.py, the voice is edge-tts).
"""

import json
import re
import shutil
from pathlib import Path

import motion_video
from series import VOICES, _llm_json

BASE = Path(__file__).parent
EXAMPLE = (BASE / "motion_examples" / "yearbook.json")

WRITER_SYSTEM = """You write 30-45 second vertical horror/mystery short videos that are drawn by code, not filmed. You output a JSON
"spec". The picture elements you may use are ONLY these (anything else is dropped):

- portrait_grid: a yearbook / ID / class-photo page of generated faces. {"type":"portrait_grid","style":"class"|"year","school":"..","title":"Class of 1994","subtitle":"..",
  "cols":2|3,"people":[{"name":"Full Name","seed":int,"gender":"m"|"f","expression":"neutral"|"smile"}],"ring":"a name from people","ring_at":0.5,
  "stamps":[{"name":"a name","at":0.5,"text":"MISSING"}],"lines":0-3}    (2-6 people; same name+seed = same face in every scene)
- chat: a phone conversation. {"type":"chat","contact":"Name","avatar_seed":int,"time_label":"Today 6:12 PM","messages":[{"from":"them"|"me","text":"short","at":0.3}]} (2-4 short messages, at = 0-1 through the scene)
- notification: a lock screen. {"type":"notification","time":"11:47","date":"Monday, October 19","app":"Messages","sender":"Name","text":"short line","at":0.4}
- face: a big face close-up. {"type":"face","seed":int,"gender":"m"|"f","expression":"neutral"|"smile","zoom":[0.92,1.0],"red_eyes_at":0.55}  (red_eyes_at optional: eyes start glowing red at that point; use it once, at the end)
- text: big words on screen. {"type":"text","text":"..","size":80,"kind":"serif_bold","color":[240,232,214],"y":0.4,"at":0.2,"anim":"pop"}
- stamp: a rubber stamp. {"type":"stamp","text":"MISSING","x":0.5,"y":0.45,"size":110,"at":0.5}

Scene = {"narration":"1-2 spoken sentences","bg":{"type":"paper","seed":int,"tone":"aged"|"newsprint"} or {"type":"dark","kind":"night"|"brown"|"black"|"blue"},
"camera":{"zoom":[1.0,1.08]},"shake":0-0.4 (optional),"flicker":true (optional),"elements":[...]}.
Use paper backgrounds for yearbook/old-document scenes, dark for phone and horror moments.

Story rules: EXACTLY 5 or 6 scenes, each narration at most 18 words, whole video 35-45 seconds when spoken. Scene 1 hooks within one sentence with something specific and unsettling. Each scene shows the thing the narration talks about.
Escalate: ordinary -> wrong -> impossible -> a final line that lands (not an explanation). First person, plain spoken words, no purple prose.
Numbers in narration are written as words (nineteen ninety-four). Keep chat messages and on-screen text SHORT.
Respond with ONLY: {"title":"2-4 words","scenes":[...]}"""


def _clean(spec: dict) -> dict:
    scenes = []
    for sc in spec.get("scenes", []):
        if not sc.get("narration"):
            continue
        els = [e for e in sc.get("elements", []) if e.get("type") in motion_video.ELEMENTS]
        for e in els:
            if e["type"] == "portrait_grid":
                e["people"] = [p for p in e.get("people", []) if p.get("name")][:6]
                names = {p["name"] for p in e["people"]}
                if e.get("ring") not in names:
                    e.pop("ring", None)
                e["stamps"] = [s for s in e.get("stamps", []) if s.get("name") in names]
                if len(e["people"]) < 1:
                    e["people"] = [{"name": "Unknown", "seed": 1}]
            if e["type"] == "chat" and not e.get("messages"):
                e["messages"] = [{"from": "them", "text": "...", "at": 0.4}]
        sc["elements"] = els
        scenes.append(sc)
    if len(scenes) < 3:
        raise RuntimeError("The writer produced too few usable scenes - try again.")
    spec["scenes"] = scenes[:8]
    return spec


def create_motion_video(topic: str, voice: str = "adult_man", music: bool = True, log=print, cancel_event=None) -> Path:
    log(f"[motion] Writing a code-drawn short about: {topic}")
    example = EXAMPLE.read_text(encoding="utf-8")
    spec = _clean(_llm_json(WRITER_SYSTEM + "\n\nHere is a complete example of a good spec (different story):\n" + example,
                            f"Topic / idea: {topic}"))
    spec["voice"] = voice if voice in VOICES else "adult_man"
    spec["music"] = "eerie"
    slug = re.sub(r"[^a-z0-9]+", "-", spec.get("title", topic).lower()).strip("-")[:40] or "motion"
    spec_path = motion_video.OUT_DIR / f"{slug}.spec.json"
    motion_video.OUT_DIR.mkdir(exist_ok=True)
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    final = motion_video.build_motion_video(str(spec_path), log=log, cancel_event=cancel_event, no_music=not music)

    # Land in the Studio results strip (same folder as the stock-footage videos) so it can be previewed and posted.
    import faceless
    faceless.FACELESS_DIR.mkdir(exist_ok=True)
    dest = faceless.FACELESS_DIR / f"motion-{slug}.mp4"
    shutil.copyfile(final, dest)
    script = " ".join(s["narration"] for s in spec["scenes"])
    dest.with_suffix(".json").write_text(json.dumps({"title": spec.get("title", topic), "script": script}, ensure_ascii=False), encoding="utf-8")
    log(f"[motion] Ready in Studio -> {dest.name}")
    return dest


if __name__ == "__main__":
    import sys
    create_motion_video(" ".join(sys.argv[1:]) or "a haunted school yearbook")
