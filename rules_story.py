"""
rules_story.py
The "Night shift as X - 6 rules" horror format, modelled on what the study found winning (research/FORMAT_STUDY.md):
poster-style title in frame 1, numbered rules, a new picture/crop every ~3-4 s, highlighted captions, a twist on the last rule.
This writes the story (Claude via series._llm_json) into stories/rules-<slug>/story.json, ready for story_images.generate_images
(pictures, local) and rules_video.build_rules_video (assembly).

    python rules_story.py "a hotel receptionist"
"""

import argparse
import re
from pathlib import Path

from series import STORIES_DIR, VOICES, _llm_json, _write, slugify

STYLE = ("anime key art, painterly cinematic illustration, dramatic moody lighting with one glowing light source, deep shadows, rich detail, "
         "film still quality, vertical composition, absolutely no text, no letters, no numbers, no signs with writing")

SYSTEM = """You write a 55-60 second vertical horror short in the "Night shift as X - 6 rules" format, for an English-speaking TikTok / Reels / Shorts audience.
Format (this exact structure):
1. intro: second person, present tense. "You just got a job as ...". Say what the job is, that the first night starts now, and that there are six rules you must never break.
2. rules 1-5: each scene = ONE rule, spoken as a command, then ONE short, creepy, concrete detail that makes you understand why it matters (without explaining the monster).
   Rules should be strange, specific and slightly contradictory (never answer the phone after 3 AM; if a guest has no reflection, give them room 13; ...).
3. rule 6 + twist: the last scene breaks the pattern - the sixth rule is the one you are already breaking, or it was written by someone who is no longer there. End on a cold, specific line (not an explanation).
4. last line is a question for the comments in 6-8 words ("Which rule would you break first?" - do not copy this one).
Rules for the writing: plain spoken English, short sentences, no purple prose, no "suddenly". 16-24 words per scene, 8 scenes, 125-150 words in total.
Hero: the same single person in every picture. "hero_look" = 18-25 words (age, hair, clothes, one distinguishing detail).
Every picture: "image_prompt" = one clear moment (what the hero sees/does, the setting, camera angle), max 40 words, ending with {style}; use {Hero} for the character.
The FIRST scene's picture is the poster: the hero from a dramatic low angle in the setting, with empty dark space at the top for a title.
Respond with ONLY this JSON:
{"title_lines": ["NIGHT SHIFT", "AS A HOTEL RECEPTIONIST"], "hero_look": "...", "caption": "Instagram caption hook line (max 90 chars) + one question",
 "scenes": [{"kind": "intro|rule|twist", "rule_no": 0, "narration": "...", "image_prompt": "... {style}"}]}
(rule_no is 1..5 for rule scenes, 6 for the twist scene, 0 for the intro.)"""


def create_rules_story(job: str, voice: str = "adult_man", log=print) -> Path:
    log(f"[rules] Writing 'night shift as {job}'...")
    out = _llm_json(SYSTEM, f"The job: {job}. Make the setting vivid and specific (what the place looks like at 3 AM).")
    scenes = [s for s in out.get("scenes", []) if s.get("narration") and s.get("image_prompt")]
    if len(scenes) < 6:
        raise RuntimeError("The writer returned too few scenes - try again.")
    from prompt_utils import clean_image_prompt
    sc = []
    for i, s in enumerate(scenes[:9], 1):
        prompt = clean_image_prompt(s["image_prompt"].strip())
        prompt = prompt if "{style}" in prompt else prompt.rstrip(". ") + ", {style}"
        sc.append({"image": f"images/scene{i}.png", "min_seconds": 3.2, "kind": s.get("kind", "rule"), "rule_no": int(s.get("rule_no") or 0),
                   "image_prompt": prompt, "lines": [{"who": "Narrator", "text": re.sub(r"\s+", " ", s["narration"]).strip()}]})
    words = sum(len(s["lines"][0]["text"].split()) for s in sc)
    title_lines = [t.upper() for t in out.get("title_lines", [])][:3] or ["NIGHT SHIFT", f"AS {job.upper()}"]
    slug = f"rules-{slugify(' '.join(title_lines))[:40]}"
    folder = STORIES_DIR / slug
    story = {"title": " ".join(title_lines).title(), "format": "rules", "title_lines": title_lines, "audience": "horror", "style": STYLE,
             "music": {"mood": "eerie"}, "motion": "pan", "caption_colors": {}, "caption_size": 84, "caption_words": 3,
             "post_caption": out.get("caption", ""), "summary": f"A first night on the job as {job}, with six rules you must not break.",
             "characters": {"Narrator": {**VOICES[voice], "rate": "+10%", "pitch": "-2Hz", "look": ""}, "Hero": {**VOICES[voice], "look": out.get("hero_look", "")}}, "scenes": sc}
    _write(folder / "story.json", story)
    log(f"[rules] Saved {len(sc)} scenes, {words} words (about {words / 2.5:.0f}s). Title: {' / '.join(title_lines)}")
    for s in sc:
        log(f"   [{s['kind']} {s['rule_no']}] {s['lines'][0]['text']}")
    return folder


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("--voice", default="adult_man", choices=list(VOICES))
    a = ap.parse_args()
    create_rules_story(a.job, a.voice)
