"""
explainer.py
Stickman explainer videos, built on the method in kaomei/stickman-video-director (MIT license,
https://github.com/kaomei/stickman-video-director). That project is a set of writing rules and tested art styles
for "stick figure" explainers; we use its:
  - 5-stage story structure (Golden Hook -> Disrupting Assumptions -> Insider Secrets -> Ultimate Truth -> Discussion),
  - ~10-second beats with a visual change every 2-3 seconds,
  - frozen "character anchor" text repeated verbatim in every picture so the figure stays consistent,
  - rules: no words/letters in the pictures, narration is audio only, never invent facts.
Its own output is prompts for a hosted video model (Gemini Omni Flash); here the pictures are made locally
(story_images.py), voiced and assembled by story_video.py, and the clip prompts are also exported as a text file.

    python explainer.py "Why do we procrastinate?" --style 2A --seconds 60
"""

import argparse
import json
import re
from pathlib import Path

from series import STORIES_DIR, VOICES, _llm_json, _write, slugify

# Character/scene anchors condensed from the project's style catalog (references/style-catalog.md).
STYLES = {
    "1A": ("Classic Minimalist - black on white",
           "minimalist two-dimensional black line animation on a flat pure-white background, the same stick figure with a hollow "
           "circular head, connected line limbs, uniform medium line weight, up to three vivid accent colors, no shading, no gradients, absolutely no words, letters or numbers anywhere in the picture, every sign, screen, panel and object is blank and unmarked"),
    "1B": ("Classic Minimalist - white on black",
           "minimalist two-dimensional white line animation on a flat pitch-black background, the same stick figure with a hollow "
           "circular head, connected line limbs, uniform medium line weight, up to three vivid accent colors, no shading, absolutely no words, letters or numbers anywhere in the picture, every sign, screen, panel and object is blank and unmarked"),
    "2A": ("Modern Pop - studio tech",
           "a minimalist 2D animated stick figure wearing a bright red beanie (smooth rounded knit, no pom-pom) and a yellow t-shirt, simple "
           "black stick limbs and shorts, in a modern bright white studio with subtle light-gray perspective grid lines on the floor, "
           "high-key lighting, floating glowing cyan and electric blue glass interface panels, simple black lines, vibrant colors, smooth 2D animation style, absolutely no words, letters or numbers anywhere in the picture, every sign, screen, panel and object is blank and unmarked"),
    "2B": ("Modern Pop - cinematic story",
           "a minimalist 2D animated stick figure wearing a bright red beanie (smooth rounded knit, no pom-pom) and a yellow t-shirt, simple "
           "black stick limbs and shorts, in rich full-color narrative environments with cinematic lighting and depth, simple black lines, vibrant colors, smooth 2D animation style, absolutely no words, letters or numbers anywhere in the picture, every sign, screen, panel and object is blank and unmarked"),
    "3": ("Prehistoric hand-drawn dark comedy",
          "hand-drawn 2D cartoon with expressive white filled heads and black stick limbs, animal-hide costumes, earthy prehistoric caves and "
          "landscapes with warm fire accents and subtle paper texture, exaggerated funny expressions, absolutely no words, letters or numbers anywhere in the picture, every sign, screen, panel and object is blank and unmarked"),
    "4": ("Cozy storytelling",
          "2D cartoon with a white filled round head and slim torso, dark stick limbs and a simple expressive face, set in full-color everyday "
          "locations with gentle atmospheric light, cozy and warm, cinematic framing, absolutely no words, letters or numbers anywhere in the picture, every sign, screen, panel and object is blank and unmarked"),
}

WRITER_SYSTEM = """You write a stickman explainer video for YouTube Shorts / TikTok, told by a narrator over simple stick-figure pictures.
Structure it in exactly these 5 stages across the scenes (each scene is ~10 seconds of narration, 20-25 words):
1. hook - Golden Hook: an instant-curiosity line (a counter-intuitive question or a visual paradox). Never open with "Welcome" or a generic intro.
2. assumption - Disrupting Assumptions: state what everyone believes, then shatter it in one sentence.
3. secret - Unveiling Insider Secrets: reveal the hidden mechanics / the real obstacle (use 1-3 scenes for this stage).
4. truth - Ultimate Truth: the underlying logic or human psychology, with the biggest cognitive payoff.
5. elevation - a memorable punchline plus a question that makes people argue in the comments.
Rules:
- Narration is spoken aloud only; short sentences; concrete and specific; never invent statistics, quotes or facts you cannot stand behind.
- Each scene gets ONE picture. "image_prompt" describes the single key action of that scene in at most 40 words: what the stick figure DOES
  (leaps, draws a glowing line, opens a door, pushes a boulder), the props, and the camera. Concrete actions only; no abstract morphing.
  Never put words, letters, numbers or UI text in the picture. Start with the stick figure, end with {style}.
- Keep the same single character throughout; do not describe its look (it is added automatically).
Respond with ONLY this JSON:
{"title": "...", "summary": "2 sentences", "scenes": [{"stage": "hook|assumption|secret|truth|elevation", "image_prompt": "... {style}", "narration": "20-25 words"}]}"""


def clean_image_prompt(prompt: str) -> str:
    """The pictures must carry no words (the style's own rule), but models like to write 'a sign labeled ...'.
    Drops any labeled/reads/says/text/caption clause and quoted words from the picture prompt."""
    prompt = re.sub(r"\b(?:each\s+)?(?:labeled|labelled|reads|reading|says|saying|titled|marked|with the (?:word|words|text))\b[^,.;{]*", "", prompt, flags=re.I)
    prompt = re.sub(r"[\'\"‘’“”][^\'\"‘’“”]{1,40}[\'\"‘’“”]", "", prompt)
    prompt = re.sub(r"\s+,", ",", prompt)
    prompt = re.sub(r",(?:\s*,)+", ",", prompt)
    prompt = re.sub(r",\s*(?:and|or)\s*(?=\{style\}|$)", ", ", prompt)
    return re.sub(r"\s{2,}", " ", prompt).strip()


def create_explainer(topic: str, style: str = "2A", seconds: int = 60, voice: str = "adult_man") -> Path:
    """Writes the explainer and saves stories/stickman-<slug>/story.json (a single story in the Series tab)."""
    if style not in STYLES:
        raise RuntimeError(f"Unknown style '{style}'. Choose from: {', '.join(STYLES)}")
    scenes_wanted = max(3, min(12, round(seconds / 10)))
    print(f"[explainer] Writing a {seconds}s '{STYLES[style][0]}' explainer on: {topic}")
    out = _llm_json(WRITER_SYSTEM, f"Topic: {topic}\nExactly {scenes_wanted} scenes.")
    raw = [s for s in out.get("scenes", []) if s.get("narration") and s.get("image_prompt")]
    if len(raw) < 3:
        raise RuntimeError("The model wrote too few usable scenes - try again.")

    scenes = []
    for i, s in enumerate(raw[:12], 1):
        prompt = clean_image_prompt(s["image_prompt"].strip())
        prompt = prompt if "{style}" in prompt else prompt.rstrip(". ") + ", {style}"
        scenes.append({"image": f"images/scene{i}.png", "min_seconds": 6, "stage": s.get("stage", ""),
                       "image_prompt": prompt, "lines": [{"who": "Narrator", "text": re.sub(r"\s+", " ", s["narration"]).strip()}]})
    words = sum(len(s["lines"][0]["text"].split()) for s in scenes)

    slug = f"stickman-{slugify(topic)[:40]}"
    folder = STORIES_DIR / slug
    story = {"title": out.get("title") or topic, "format": "stickman", "style_key": style, "summary": out.get("summary", ""),
             "audience": "explainer", "style": STYLES[style][1], "music": {"mood": "upbeat"}, "motion": "pan", "caption_colors": {},
             "caption_size": 66, "caption_words": 6,
             "characters": {"Narrator": {**VOICES[voice], "look": ""}}, "scenes": scenes,
             "credits": "Method: kaomei/stickman-video-director (MIT)"}
    _write(folder / "story.json", story)

    # The same beats as plain clip prompts, for pasting into a hosted video model (e.g. Gemini Omni Flash).
    lines = [f"# {story['title']} - {STYLES[style][0]}", "", f"Character/scene anchor (repeat in every clip): {STYLES[style][1]}", ""]
    for i, s in enumerate(scenes, 1):
        lines += [f"## Clip {i} ({s['stage']})", f"Visual: {s['image_prompt'].replace('{style}', STYLES[style][1])}",
                  f"Audio voiceover only, strictly no speech bubbles or text on screen: \"{s['lines'][0]['text']}\"", ""]
    (folder / "clip_prompts.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[explainer] Saved {len(scenes)} scenes, {words} spoken words (about {words / 2.4:.0f}s). Hook: {scenes[0]['lines'][0]['text']}")
    return folder


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("topic")
    p.add_argument("--style", default="2A", choices=list(STYLES))
    p.add_argument("--seconds", type=int, default=60)
    p.add_argument("--voice", default="adult_man", choices=list(VOICES))
    a = p.parse_args()
    create_explainer(a.topic, a.style, a.seconds, a.voice)
