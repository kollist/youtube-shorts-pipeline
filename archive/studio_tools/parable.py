"""
parable.py
Parable shorts: a tiny original fable with animal characters, a one-line moral, then the same lesson in a
real-world setting, ending on a question that makes people comment. The structure follows the Arabic
"snake and mice" reference video (fable -> moral -> "and this is how it works on people").

    python parable.py "divide and rule" --render
Saves stories/parable-<slug>/story.json (a standalone story in the Series tab: make pictures, render, post there).
"""

import argparse
import re
from pathlib import Path

from series import STORIES_DIR, VOICES, _llm_json, _write, slugify

STYLE = ("dark moody storybook illustration, soft painterly shading, cinematic rim lighting, muted blue-grey palette with one warm "
         "accent color, rich texture, vertical composition, expressive animal faces, absolutely no words, letters or numbers "
         "anywhere in the picture, every sign, scroll and object is blank and unmarked")

WRITER_SYSTEM = """You write a 45-55 second vertical "parable" short for TikTok / Reels / YouTube Shorts: a tiny ORIGINAL fable that reveals how
something works in real life. Narrated aloud by one narrator over illustrated pictures.

Structure (8 scenes, 100-115 spoken words in total, ~13 words per scene - the narrator is slow, so this runs about 50 seconds):
1. hook (1 scene): an unsettling or curious situation that makes people ask "why?" - a specific image, never "Once upon a time" and never a greeting.
2. fable (4 scenes): 2-3 animal characters. Set-up -> the trick/threat -> it works -> the cost. Concrete actions, rising tension, one clear cause and effect.
3. moral (1 scene): the lesson as ONE short, quotable sentence.
4. real_world (1 scene): "Now look at ..." - the same mechanism in human life (work, friendships, money, internet, politics). Specific, not preachy.
5. question (1 scene): a last line that lands, then a question that splits the audience ("Which one are you?").
Rules:
- The fable must be your own invention. Do NOT say it is ancient, Chinese, Arabic, Aesop's or "an old proverb" and never invent a source or a statistic.
  If you reuse a well-known idea, tell it freshly and don't attribute it.
- Plain spoken English, short sentences, no purple prose, no emojis. Numbers as words.
- Each scene has ONE picture: "image_prompt" describes one clear moment (who, doing what, where, camera) in at most 40 words.
  Use {style} at the end and {Name} placeholders for characters (e.g. "{Cobra} coils above {Mouse}, low angle, {style}").
  Never put words, letters or signs in a picture. Real-world scenes use a human character defined the same way.
- "characters": 2-4 characters (animals and at most one human) each with a FIXED "look" repeated in every picture, 15-25 words: species, colors, size, one distinguishing feature.
- "emphasis": for each scene, ONE key word from its narration (the most important word) to highlight in the captions.
Respond with ONLY this JSON:
{"title": "2-5 words", "hook_line": "first line, max 12 words", "moral": "the moral in one sentence",
 "characters": {"Name": {"look": "..."}},
 "scenes": [{"stage": "hook|fable|moral|real_world|question", "image_prompt": "... {style}", "narration": "...", "emphasis": "word"}],
 "caption": "Instagram caption: a hook line (max 100 chars) + one comment question", "hashtags": ["5 relevant hashtags with #"]}"""


def create_parable(theme: str, voice: str = "adult_man", log=print) -> Path:
    log(f"[parable] Writing a parable about: {theme}")
    out = _llm_json(WRITER_SYSTEM, f"Theme / lesson: {theme}\nExactly 8 scenes.")
    raw = [s for s in out.get("scenes", []) if s.get("narration") and s.get("image_prompt")]
    if len(raw) < 5:
        raise RuntimeError("The writer produced too few usable scenes - try again.")
    chars = {n: {"role": "", "look": c.get("look", ""), **VOICES["adult_man"]} for n, c in (out.get("characters") or {}).items()}
    from explainer import clean_image_prompt
    scenes = []
    emphasis = {}
    for i, s in enumerate(raw[:10], 1):
        prompt = clean_image_prompt(s["image_prompt"].strip())
        prompt = prompt if "{style}" in prompt else prompt.rstrip(". ") + ", {style}"
        text = re.sub(r"\s+", " ", s["narration"]).strip()
        scenes.append({"image": f"images/scene{i}.png", "min_seconds": 5, "stage": s.get("stage", ""), "image_prompt": prompt,
                       "lines": [{"who": "Narrator", "text": text}]})
        w = re.sub(r"[^A-Za-z']", "", str(s.get("emphasis", ""))).lower()
        if w and re.search(rf"\b{re.escape(w)}\b", text, re.I):
            emphasis[w] = "&H3DD9FF&"          # yellow, like the reference's highlighted word
    words = sum(len(s["lines"][0]["text"].split()) for s in scenes)

    slug = f"parable-{slugify(out.get('title') or theme)[:36]}"
    folder = STORIES_DIR / slug
    tags = " ".join(t if t.startswith("#") else f"#{t}" for t in out.get("hashtags", [])[:5])
    story = {"title": out.get("title") or theme, "format": "parable", "summary": out.get("moral", ""), "audience": "parable",
             "style": STYLE, "music": {"mood": "fable"}, "motion": "parallax", "caption_colors": emphasis,
             "caption_size": 70, "caption_words": 5, "moral": out.get("moral", ""),
             "post_caption": out.get("caption", ""), "post_hashtags": tags,
             "characters": {"Narrator": {**VOICES[voice], "look": ""}, **chars}, "scenes": scenes}
    _write(folder / "story.json", story)
    log(f"[parable] Saved {len(scenes)} scenes, {words} spoken words (about {words / 2.4:.0f}s). Hook: {scenes[0]['lines'][0]['text']}")
    log(f"[parable] Moral: {story['moral']}")
    return folder


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("theme")
    p.add_argument("--voice", default="adult_man", choices=list(VOICES))
    p.add_argument("--render", action="store_true", help="also make the pictures (local, ~40 s each) and the video")
    a = p.parse_args()
    folder = create_parable(a.theme, a.voice)
    if a.render:
        from story_images import generate_images
        from story_video import build_story
        generate_images(str(folder))
        print(f"[parable] Video: {build_story(str(folder))}")
