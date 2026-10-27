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

STYLE = ("dark photorealistic found-footage horror photograph, desaturated, heavy 35mm film grain, crushed blacks, one harsh light source, "
         "unsettling, vertical composition, absolutely no text, no letters, no numbers, no timestamps, no overlays")

PICTURE_RULES = """PICTURES - the fear comes from what you almost see. These are PHOTOGRAPHS from found footage and security cameras, never illustrations, and NEVER a portrait of a person facing the camera.
Shot types - use a different one for every scene:
 (a) "cctv": a grainy black-and-white security-camera frame from a high corner, wide, the place mostly empty, the entity tiny and perfectly still, far from the camera;
 (b) "pov": the viewer's point of view with a flashlight beam cutting through haze down a corridor or into a room, the entity at the far end, half swallowed by darkness;
 (c) "shoulder": over-the-shoulder - the back of {Hero}'s head, out of focus, in the foreground; the entity in a dark doorway or at the edge of the light;
 (d) "evidence": a close detail of what it leaves behind (marks, scratches, wax drips, a handprint, an open door, an unplugged machine) in dim light, nobody in frame;
 (e) "empty": the empty room where it should be, with one wrong detail.
Order: scene 1 (the poster) = "empty" or "cctv", wide and dark, a faint shape far away, a large empty dark area at the top for the title. Scenes 2-4 = evidence / cctv / empty (the entity absent or tiny).
Scenes 5-6 = pov / cctv (far away, partly hidden). Scene 7 = shoulder (closer than before, still mostly dark). Scene 8 = shoulder or cctv: the entity very close but in darkness, lit by ONE red or cold light,
partly out of focus - never a bright, sharp, full-body close-up, never touching the hero.
Every prompt: ONE strong light source (flashlight beam, emergency light, screen glow), crushed blacks, heavy film grain, desaturated, photorealistic, 40 words max, ending with {style}.
Describe the entity ONLY with traits from the article and repeat its key physical traits in every prompt that shows it (the picture model forgets). "entity_look" = 25 words: shape, skin, face (hidden or not), size, what is wrong with it.
"hero_look" = hair colour and a dark Foundation jacket, 12 words, no face. Use {Hero} only in shoulder shots, as "the back of {Hero}".
"""


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
__PICTURE_RULES__
Respond with ONLY this JSON:
{"title_lines": ["SCP-173", "THE SCULPTURE"], "poster_tag": "2-4 word tag under the title, e.g. THE STATUE THAT MOVES", "hero_look": "...", "entity_look": "...", "tape_label": "<the site named in the article> ARCHIVE - <ITEM> - CONFIDENTIAL" (max 44 characters; if no site is named: FOUNDATION ARCHIVE - <ITEM> - CONFIDENTIAL),
 "caption": "Instagram hook line (max 90 chars) + one question",
 "scenes": [{"kind": "intro|rule|twist", "rule_no": 0, "label": "WHAT IT IS", "narration": "...", "image_prompt": "... {style}"}]}
(kind: scene 1 "intro"; scenes 2-6 "rule" with rule_no 1..5 in order; scenes 7-8 "twist" with rule_no 6.)"""

SYSTEM = SYSTEM.replace("__PICTURE_RULES__", PICTURE_RULES)

_A, _D = SYSTEM.index("Story order (8 scenes"), SYSTEM.index("Respond with ONLY this JSON:")
_HEAD, _JSON_TAIL = SYSTEM[:_A], SYSTEM[_D:]


def build_system(shape: str = "orientation", finale: str = "taunt", picture_style: str = "") -> tuple[str, bool]:
    """The writer's instructions for THIS episode: the story shape, the kind of last line and the picture look. Returns (instructions, finale_has_a_question).
    Any problem falls back to the original instructions."""
    try:
        import picture_styles as ps
        import story_variety as sv
        beat_text, question = sv.beats(shape, finale)
        labels = f'Each scene has a "label": 1-3 plain words shown on screen (e.g. {sv.SHAPE_LABELS.get(shape, sv.SHAPE_LABELS["orientation"])}). Scene 1 may have label "".\n'
        rules = ps.rules_text(picture_style) if picture_style in ps.STYLES else PICTURE_RULES
        return _HEAD + "Story order (8 scenes, 130-150 words total, plain spoken English):\n" + beat_text + "\n" + labels + rules + _JSON_TAIL, question
    except Exception:
        return SYSTEM, True


def create_scp_story(number: str, voice: str = "adult_man", log=print, dest: Path | None = None, variety_override: dict | None = None) -> Path:
    art = fetch_scp(number)
    log(f"[scp] {art['item']} - author credit: {art['author'] or '(not found)'} - {len(art['text'])} chars of article")
    user = f"ARTICLE ({art['item']}):\n{art['text']}"
    folder_name = Path(dest).name if dest else ""
    tape_no = int(m.group(1)) if (m := re.fullmatch(r"ep(\d+)", folder_name)) else 0
    try:                                                    # variety: a different shape / ending / scare / picture look from the last few tapes (never fatal)
        import picture_styles as ps
        import story_variety as sv
        variety = sv.choose(f"{art['item']}|{tape_no}")
        variety["picture_style"] = ps.pick_style(f"{art['item']}|{tape_no}")
        variety.update(variety_override or {})            # tests / manual control: {"shape": ..., "finale": ..., "profile": ..., "picture_style": ...}
    except Exception as e:
        log(f"[scp] variety unavailable ({e}); using the classic tape")
        variety = {"shape": "orientation", "finale": "taunt", "profile": "classic", "picture_style": ""}
    system, _question = build_system(variety["shape"], variety["finale"], variety["picture_style"])
    log(f"[scp] this tape: shape={variety['shape']}, ending={variety['finale']}, scare={variety['profile']}, pictures={variety['picture_style'] or 'default'}")
    out = _llm_json(system, user)
    count = lambda o: sum(len(str(x.get("narration", "")).split()) for x in o.get("scenes", []))
    for _ in range(2):                                     # a long article tempts the writer to cram: 107-second videos have happened. Make it shorter, twice at most.
        n_words = count(out)
        if n_words <= 170:
            break
        log(f"[scp] script is {n_words} words (target 130-150, about {n_words / 2.5:.0f}s) - asking for a shorter one")
        out = _llm_json(system, user + f"\n\nYOUR LAST ATTEMPT WAS {n_words} WORDS - FAR TOO LONG (it becomes a {n_words / 2.5:.0f}-second video). Every scene's narration must be ONE or TWO short sentences, about 17 words. "
                                      "Total 130-150 words. Keep every other rule and the same JSON.")
    if count(out) > 190:
        raise RuntimeError(f"The writer kept the script at {count(out)} words (it must be about 140) - try again.")
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
    kind_word = {"orientation": "orientation tape for", "incident_report": "incident report on", "survivor": "survivor's statement about",
                 "day_log": "research log on", "safety_video": "staff safety briefing for", "cold_open": "orientation tape for"}.get(variety["shape"], "orientation tape for")
    story["summary"] = f"Foundation {kind_word} {art['item']}."
    if variety["picture_style"]:
        import picture_styles as ps
        story["style"] = ps.style_string(variety["picture_style"])
    story.update({"shape": variety["shape"], "finale_type": variety["finale"], "scare_profile": variety["profile"], "picture_style": variety["picture_style"], "tape_no": tape_no})
    try:                                                    # the archivist thread: a short note on this tape's end card, and a narrator who degrades a little with every tape
        import story_variety as sv
        story["archivist_note"] = sv.archivist_note(tape_no)
    except Exception:
        story["archivist_note"] = ""
    _write(folder / "story.json", story)
    (folder / "credit.txt").write_text(
        f"{credit['line']}\n\nThis video is an adaptation of {art['item']} from the SCP Foundation wiki (https://scp-wiki.wikidot.com), written by {art['author'] or 'its author'}.\n"
        f"Source: {art['url']}\nLicensed under Creative Commons Attribution-ShareAlike 3.0 (https://creativecommons.org/licenses/by-sa/3.0/). This video is released under the same licence.\n", encoding="utf-8")
    log(f"[scp] Saved {len(sc)} scenes, {words} words (about {words / 2.5:.0f}s)")
    for s in sc:
        log(f"   [{s['kind']} {s['rule_no']}] {s['lines'][0]['text']}")
    return folder


RESTYLE_HEAD = "You rewrite ONLY the picture prompts for an existing SCP horror short. Keep the story: you are given the narration of each scene and the article facts.\n"
RESTYLE_TAIL = """
Respond with ONLY JSON: {"entity_look": "...", "hero_look": "...", "image_prompts": ["... {style}", ... one per scene, in order]}"""


def restyle_pictures(ep_dir, log=print, style_key: str = "") -> Path:
    """Rewrites every scene's image prompt in the current photographic found-footage style (script untouched), updates the style, and removes the old pictures
    so the next make_episode / generate_images draws new ones. Use it on an episode made in the older anime style."""
    import shutil
    ep_dir = Path(ep_dir)
    story = json.loads((ep_dir / "story.json").read_text(encoding="utf-8"))
    art = fetch_scp(re.sub(r"\D", "", story["credit"]["item"]))
    scenes = story["scenes"]
    listing = "\n".join(f"{i}. [{s.get('label') or 'poster'}] {' '.join(l['text'] for l in s['lines'])}" for i, s in enumerate(scenes, 1))
    import picture_styles as ps
    key = style_key or story.get("picture_style") or ps.pick_style(story["credit"]["item"])
    system = RESTYLE_HEAD + ps.rules_text(key) + RESTYLE_TAIL
    out = _llm_json(system, f"ARTICLE ({art['item']}):\n{art['text']}\n\nSCENES ({len(scenes)}):\n{listing}")
    prompts = out.get("image_prompts") or []
    if len(prompts) != len(scenes):
        raise RuntimeError(f"The writer returned {len(prompts)} picture prompts for {len(scenes)} scenes - try again.")
    for sc, pr in zip(scenes, prompts):
        sc["image_prompt"] = pr if "{style}" in pr else pr.rstrip() + " {style}"
    story["style"] = ps.style_string(key)
    story["picture_style"] = key
    if out.get("hero_look"):
        story["characters"]["Hero"]["look"] = out["hero_look"]
    story["entity_look"] = out.get("entity_look", "")
    (ep_dir / "story.json").write_text(json.dumps(story, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(ep_dir / "images", ignore_errors=True)
    for f in list(ep_dir.glob("*.mp4")):
        f.unlink()
    log(f"[scp] {story['credit']['item']}: {len(prompts)} picture prompts rewritten in the found-footage style")
    return ep_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("number"); ap.add_argument("--voice", default="adult_man", choices=list(VOICES)); a = ap.parse_args()
    create_scp_story(a.number, a.voice)
