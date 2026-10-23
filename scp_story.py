"""
scp_story.py
Turns an SCP Foundation article into a "Foundation tape" short for the horror format (horror_video.py): the containment procedures become the RULES.
SCP Foundation content is licensed CC BY-SA 3.0 (https://scp-wiki.wikidot.com/licensing-guide): we MUST credit the work, the author and the link, and release the
video under CC BY-SA 3.0. The credit is stored in story.json ("credit"), burned into the end card, and written to credit.txt for the video description.

    python scp_story.py 173
"""

import argparse
import json
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
    if not author:                                                       # some pages lay the credit out differently: data/scp_authors.json = {"4153": "The Great Hippo"}
        try:
            overrides = json.loads((Path(__file__).parent / "data" / "scp_authors.json").read_text(encoding="utf-8"))
            author = overrides.get(n.lstrip("0") or "0", "") or overrides.get(n, "")
        except (OSError, json.JSONDecodeError):
            pass
    return {"item": f"SCP-{n}", "url": url, "text": text[:6500], "author": author}


SYSTEM = """You turn an SCP Foundation article into a 55-65 second vertical horror short for people who have NEVER heard of SCP. If a viewer does not understand what is happening, they leave -
so this is explained like a gripping true-crime documentary told by a calm, serious narrator, not read like a rulebook.
Use ONLY facts in the article text - never invent abilities, history or incidents. No jargon without a plain-words explanation (say "a secret organization that locks away things that
should not exist", never "Euclid class" or "D-class" unless you explain it in the same breath).
The Foundation runs MANY sites (Site-19, Site-17, Site-64, Site-81...), task forces, researchers and other anomalies - do NOT default to Site-19. Use the site, facility, team,
people and related anomalies that THIS article actually names, and draw on all of its material (every procedure, incident, addendum and interview), not just the opening paragraph. NEVER say "Rule one / Rule two".
IT MUST READ AS ONE CONTINUOUS SCRIPT, spoken in a single breath of storytelling - NOT eight separate lines. The 8 scenes below are only where the PICTURE changes: the text of each scene
continues the sentence/thought of the one before it, joined by natural connectors ("But", "And here is the problem", "So", "Which means"), with sentences of varied length. No fragments, no list-like beats,
no scene that restarts, repeats or summarises the previous one, and no one-line "slogans". Read it aloud in your head: it should sound like one person telling you a story.
Story order (8 scenes, 130-150 words total, plain spoken English):
1. HOOK + WHAT IT IS: one chilling, concrete sentence that makes people need to know more, then what the thing is, in plain words ("This is a statue. It is alive.").
2. WHAT IT DOES: its one terrifying ability or behaviour, said simply, with the consequence ("The moment nobody is looking at it, it moves. Fast. It kills in a second.").
3. WHY IT IS DANGEROUS: one specific fact from the article that makes it real (where it was found, what it did, what it leaves behind).
4. HOW THE FOUNDATION KEEPS IT LOCKED UP: the containment, explained as a story ("It lives in a sealed room. Nobody ever goes in alone. Two guards must stare at it without blinking - the whole time.").
5. HOW IT IS WATCHED: the monitoring and procedures in plain steps - who watches, how often, what they do and what happens if they slip.
6. THE MISTAKE: the one thing that goes wrong (from the article's incidents or procedures), told in second person - you are the one on watch.
7. THE TURN: the moment you realise it already happened. Quiet and cold.
8. THE SCARE: the ENTITY speaks. The last spoken line is the creature itself talking to the viewer in FIRST PERSON ("I", "me", "you"), present tense, close and intimate, never the narrator describing it: it is right behind them and it tells them so, turned into a taunt that fits what it does (e.g. "Turn around. I am right here, inches from your neck. Go on... blink."). Short, 12-20 words, not explained. Then ONE final sentence: a question to the viewer
   (6-9 words) - it is shown as text, not spoken.
Each scene has a "label": 1-3 plain words shown on screen (e.g. "WHAT IT IS", "WHAT IT DOES", "HOW IT'S CONTAINED", "WHO WATCHES IT", "THE MISTAKE"). Scene 1 may have label "".
PICTURES - this is where the fear comes from: the entity (or the sign of it) is in EVERY picture from scene 2 on, never in the same place, behaving as its canon says (e.g. if it only moves unseen,
slightly closer each time). Scenes 2-7: small / background / edge of frame / reflected / half hidden. The FINAL picture shows it right behind the hero, large, in focus, the hero unaware.
Describe the entity only with traits from the article. Picture 1 = poster: hero low-angle, entity faint behind, empty dark space at the top for the title.
"image_prompt" = one clear moment, max 45 words, ending with {style}; use {Hero} for the character (a Foundation guard or junior researcher, 20 words: age, uniform, one detail).
Respond with ONLY this JSON:
{"title_lines": ["SCP-173", "THE SCULPTURE"], "poster_tag": "2-4 word tag under the title, e.g. THE STATUE THAT MOVES", "hero_look": "...", "tape_label": "<the site named in the article> ARCHIVE - <ITEM> - CONFIDENTIAL" (max 44 characters; if no site is named: FOUNDATION ARCHIVE - <ITEM> - CONFIDENTIAL),
 "caption": "Instagram hook line (max 90 chars) + one question",
 "scenes": [{"kind": "intro|rule|twist", "rule_no": 0, "label": "WHAT IT IS", "narration": "...", "image_prompt": "... {style}"}]}
(kind: scene 1 "intro"; scenes 2-6 "rule" with rule_no 1..5 in order; scenes 7-8 "twist" with rule_no 6.)"""


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
                   "label": str(s.get("label") or "").upper()[:24], "image_prompt": prompt, "lines": [{"who": "Narrator", "text": re.sub(r"\s+", " ", s["narration"]).strip()}]})
    words = sum(len(s["lines"][0]["text"].split()) for s in sc)
    title_lines = [t.upper() for t in out.get("title_lines", [])][:3] or [art["item"]]
    credit = {"item": art["item"], "author": art["author"], "url": art["url"], "license": "CC BY-SA 3.0",
              "line": f"Based on {art['item']} by {art['author'] or 'its author'} - {art['url'].replace('https://', '')} - CC BY-SA 3.0"}
    slug = f"scp-{slugify(art['item'] + ' ' + ' '.join(title_lines[1:]))[:40]}"
    folder = Path(dest) if dest else STORIES_DIR / slug          # a series episode folder, or a stand-alone story
    story = {"title": " ".join(title_lines).title(), "format": "scp", "title_lines": title_lines, "audience": "horror", "style": STYLE, "tape_label": out.get("tape_label", "")[:58],
             "music": {"mood": "eerie"}, "motion": "pan", "caption_colors": {}, "caption_size": 84, "caption_words": 3, "credit": credit,
             "poster_tag": str(out.get("poster_tag") or "FOUNDATION ORIENTATION TAPE").upper()[:34], "post_caption": out.get("caption", ""), "summary": f"Foundation orientation tape for {art['item']}.",
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
