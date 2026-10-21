"""
scp_story.py
Turns an SCP Foundation article into a "Foundation tape" short for the horror format (horror_video.py): the containment procedures become the RULES.
SCP Foundation content is licensed CC BY-SA 3.0 (https://scp-wiki.wikidot.com/licensing-guide): we MUST credit the work, the author and the link, and release the
video under CC BY-SA 3.0. The credit is stored in story.json ("credit"), burned into the end card, and written to credit.txt for the video description.

    python scp_story.py 173
"""

import argparse
import re
from pathlib import Path

import requests

from series import STORIES_DIR, VOICES, _llm_json, _write, slugify

STYLE = ("dark anime key art, painterly cinematic horror illustration, a concrete-and-fluorescent-light government facility at night, "
         "moody lighting with deep shadows and one cold light source, rich detail, film still quality, vertical composition, "
         "absolutely no text, no letters, no numbers, no signs with writing")


def fetch_scp(number: str) -> dict:
    from bs4 import BeautifulSoup
    n = re.sub(r"\D", "", str(number)).zfill(3)
    url = f"https://scp-wiki.wikidot.com/scp-{n}"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (educational adaptation; credits kept)"}, timeout=40)
    if r.status_code != 200:
        raise RuntimeError(f"Could not fetch {url} (HTTP {r.status_code}).")
    soup = BeautifulSoup(r.text, "html.parser")
    box = soup.find(id="page-content")
    if box is None:
        raise RuntimeError("Could not find the article text on that page.")
    for junk in box.select(".licensebox, .rate-module-box, .page-rate-widget-box, script, style, .footnotes-footer"):
        junk.decompose()
    text = re.sub(r"\n{3,}", "\n\n", box.get_text("\n", strip=True))
    author = ""
    m = re.search(r"([A-Za-z0-9_\-\.]+), from the", r.text)           # the licence box credits "<author>, from the SCP Wiki"
    if m:
        author = m.group(1)
    return {"item": f"SCP-{n}", "url": url, "text": text[:6500], "author": author}


SYSTEM = """You adapt an SCP Foundation article into a 45-55 second vertical horror short, told as a Foundation ORIENTATION TAPE for new night-shift staff.
Use ONLY facts that are in the article text you are given - never invent abilities, history or incidents. The containment procedures become the RULES.
Structure (8 scenes, 90-105 words in total - SHORT; 8-15 words per scene, plain spoken English, short sentences, deadpan instructor tone that slowly cracks):
1. intro: "Welcome to Site-19. This tape covers SCP-xxx." One cold sentence about what it is and that one mistake is fatal.
2. rules 1-4: each scene = one rule taken from the containment procedures, spoken as a command, then ONE concrete, creepy detail from the article (why it matters).
3. rule 5 / twist scene: the rule that is already being broken (by the viewer / the tape's own operator). Specific, quiet, cold.
4. final scene (the scare, 14-22 words): present tense, second person, the entity is RIGHT THERE and the last thing said is short and unexplained. Do not repeat a sentence or idea already said. Then ONE last sentence that is a
   question to the viewer (6-9 words, about the subject, e.g. whether they could survive it) - it will be shown as text, not spoken.
PICTURES - this is where the fear comes from: the entity (or the sign of it) must be in EVERY picture from scene 2 on, never in the same place: behave according to its canon
(e.g. if it only moves unseen, show it slightly closer in each picture). Scenes 2-7: small and in the background / at the edge of frame / reflected / half hidden.
The FINAL picture shows it right behind the hero, large, in focus, the hero not yet aware. Describe the entity only with traits from the article. First picture = poster: hero low-angle, entity
faint behind, empty dark space at the top for the title.
"image_prompt" = one clear moment, max 45 words, ending with {style}; use {Hero} for the character (a Foundation guard or junior researcher, 20 words: age, uniform, one detail).
Respond with ONLY this JSON:
{"title_lines": ["SCP-173", "THE SCULPTURE"], "hero_look": "...", "tape_label": "SITE-19 ARCHIVE - TAPE 173 - CONFIDENTIAL" (max 44 characters),
 "caption": "Instagram hook line (max 90 chars) + one question",
 "scenes": [{"kind": "intro|rule|twist", "rule_no": 0, "narration": "...", "image_prompt": "... {style}"}]}
(rule_no: 1..4 for rule scenes, 5 for the twist scene, 0 for the intro; the final scare is the last scene with kind "twist".)"""


def create_scp_story(number: str, voice: str = "adult_man", log=print, dest: Path | None = None) -> Path:
    art = fetch_scp(number)
    log(f"[scp] {art['item']} - author credit: {art['author'] or '(not found)'} - {len(art['text'])} chars of article")
    out = _llm_json(SYSTEM, f"ARTICLE ({art['item']}):\n{art['text']}")
    scenes = [s for s in out.get("scenes", []) if s.get("narration") and s.get("image_prompt")]
    if len(scenes) < 6:
        raise RuntimeError("The writer returned too few scenes - try again.")
    from prompt_utils import clean_image_prompt
    sc = []
    for i, s in enumerate(scenes[:9], 1):
        prompt = clean_image_prompt(s["image_prompt"].strip())
        prompt = prompt if "{style}" in prompt else prompt.rstrip(". ") + ", {style}"
        sc.append({"image": f"images/scene{i}.png", "min_seconds": 3.0, "kind": s.get("kind", "rule"), "rule_no": int(s.get("rule_no") or 0),
                   "image_prompt": prompt, "lines": [{"who": "Narrator", "text": re.sub(r"\s+", " ", s["narration"]).strip()}]})
    words = sum(len(s["lines"][0]["text"].split()) for s in sc)
    title_lines = [t.upper() for t in out.get("title_lines", [])][:3] or [art["item"]]
    credit = {"item": art["item"], "author": art["author"], "url": art["url"], "license": "CC BY-SA 3.0",
              "line": f"Based on {art['item']} by {art['author'] or 'its author'} - {art['url'].replace('https://', '')} - CC BY-SA 3.0"}
    slug = f"scp-{slugify(art['item'] + ' ' + ' '.join(title_lines[1:]))[:40]}"
    folder = Path(dest) if dest else STORIES_DIR / slug          # a series episode folder, or a stand-alone story
    story = {"title": " ".join(title_lines).title(), "format": "scp", "title_lines": title_lines, "audience": "horror", "style": STYLE, "tape_label": out.get("tape_label", "")[:58],
             "music": {"mood": "eerie"}, "motion": "pan", "caption_colors": {}, "caption_size": 84, "caption_words": 3, "credit": credit,
             "post_caption": out.get("caption", ""), "summary": f"Foundation orientation tape for {art['item']}.",
             "characters": {"Narrator": {**VOICES[voice], "rate": "+6%", "pitch": "-3Hz", "look": ""}, "Hero": {**VOICES[voice], "look": out.get("hero_look", "")}}, "scenes": sc}
    _write(folder / "story.json", story)
    (folder / "credit.txt").write_text(
        f"{credit['line']}\n\nThis video is an adaptation of {art['item']} from the SCP Foundation wiki (https://scp-wiki.wikidot.com), written by {art['author'] or 'its author'}.\n"
        f"Source: {art['url']}\nLicensed under Creative Commons Attribution-ShareAlike 3.0 (https://creativecommons.org/licenses/by-sa/3.0/). This video is released under the same licence.\n", encoding="utf-8")
    log(f"[scp] Saved {len(sc)} scenes, {words} words (about {words / 2.5:.0f}s)")
    for s in sc:
        log(f"   [{s['kind']} {s['rule_no']}] {s['lines'][0]['text']}")
    return folder


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("number"); ap.add_argument("--voice", default="adult_man", choices=list(VOICES)); a = ap.parse_args()
    create_scp_story(a.number, a.voice)
