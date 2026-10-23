"""
series.py
Story series: a "bible" (characters, visual style, voices, a planned arc of episodes)
written once by the model, then one episode script at a time that follows it and
remembers what happened before - so a series keeps the same cast, look and plot.

Folder layout (all under stories/, gitignored except the JSON scripts):
    stories/<slug>/series.json                 the bible + episode list
    stories/<slug>/episodes/ep01/story.json    one episode (same format story_images.py / story_video.py read)
Older single stories (stories/<name>/story.json) show up as one-episode "standalone" series.
"""

import json
import re
import time
from pathlib import Path

import token_budget
from select_clips import MODEL_FALLBACK_CHAIN, GroqGenerationError, call_groq

STORIES_DIR = Path(__file__).parent / "stories"

# What the model can pick for each character's voice (free edge-tts voices, tuned).
VOICES = {
    "teen_girl":      {"voice": "en-US-MichelleNeural",   "rate": "-6%",  "pitch": "-4Hz"},
    "teen_girl_2":    {"voice": "en-US-EmmaNeural",       "rate": "-4%",  "pitch": "+0Hz"},
    "teen_boy":       {"voice": "en-US-BrianNeural",      "rate": "-12%", "pitch": "-10Hz"},
    "teen_boy_2":     {"voice": "en-US-GuyNeural",        "rate": "-6%",  "pitch": "+0Hz"},
    "adult_woman":    {"voice": "en-US-JennyNeural",      "rate": "-8%",  "pitch": "-6Hz"},
    "adult_man":      {"voice": "en-US-ChristopherNeural", "rate": "-6%", "pitch": "-4Hz"},
    "creepy_whisper": {"voice": "en-US-EricNeural",       "rate": "-18%", "pitch": "-14Hz"},
}
MOODS = ("tense", "happy")
SCENES_MIN, SCENES_MAX = 5, 10

PITCHES = [
    {"title": "The Yearbook", "genre": "romance / supernatural thriller",
     "premise": "I found my crush in a 1994 yearbook. He hasn't aged a day. He asked me out today. She digs through older yearbooks and finds him in every decade, always beside a different girl - each one later reported missing. He texts her: 'Third time's the charm.'"},
    {"title": "The Love Notes", "genre": "romance / mystery thriller",
     "premise": "For nine days someone has been leaving a girl love notes in her locker - and the handwriting is hers. The notes predict small things that come true. The last one says: 'Say no when he asks you to the dance. I didn't.'"},
    {"title": "The Last Dance", "genre": "romance / ghost drama",
     "premise": "The boy who died last spring asks her to prom. She says yes. Each dance with him costs her something, and he has a reason he can't tell her."},
    {"title": "The Rule", "genre": "school horror / romance",
     "premise": "Our school has one rule: never answer when someone knocks three times on the library door after dark. She gets locked in with the boy she likes - and the knocking starts."},
    {"title": "3:07 AM", "genre": "psychological thriller / romance",
     "premise": "My boyfriend texted me 'look outside' at 3:07 AM. He's been in the hospital since Tuesday."},
]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "series"


def _llm_json(system: str, user: str, provider: str | None = None) -> dict:
    """Asks a model for a JSON object. Order: your Claude subscription via Claude Code (when USE_CLAUDE_CODE=1 - the best
    writer), then the Groq chain (fast, small), then OpenRouter's free models (slow and flaky on long jobs - last resort).
    provider="claude" | "groq" | "openrouter" forces exactly one, and fails loudly instead of falling back."""
    import claude_cli
    import openrouter_llm
    last = None
    if "json" not in (system + user).lower():                     # Groq / OpenRouter JSON mode reject a prompt that never says "JSON" (Claude doesn't care)
        system += "\n\nRespond with a single JSON object."
    if provider == "claude" or (provider is None and claude_cli.enabled()):
        try:
            return claude_cli.chat_json(system, user)
        except claude_cli.ClaudeCliError as e:
            if provider == "claude":
                raise RuntimeError(f"Claude Code failed: {e}")
            last = e
            print(f"[llm] Claude Code unavailable ({e}); using the free models.")
    if provider in (None, "groq"):
        for model in MODEL_FALLBACK_CHAIN:
            if token_budget.remaining_budget(model) < 3000:
                continue
            try:
                raw = call_groq(user, system, model=model).strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
                return json.loads(raw)
            except Exception as e:                                # any failure of THIS model (budget, 400, bad JSON, network): try the next one
                last = e
        if provider == "groq":
            raise RuntimeError(f"Groq couldn't produce a usable answer ({last}).")
    if provider in (None, "openrouter") and openrouter_llm.available():
        try:
            return openrouter_llm.chat_json_any(system, user)[0]
        except openrouter_llm.OpenRouterError as e:
            last = e
    raise RuntimeError(f"No model could produce a usable answer ({last}). Try again, or wait for the Groq budget to reset.")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


BIBLE_SYSTEM = f"""You are the head writer of a hit vertical-video story series for teens and adults
(YouTube Shorts / TikTok / Reels), told with AI-illustrated pictures and voices. Create the series bible.
Rules: keep it PG-13 - eerie and emotional, no gore, nothing sexual; characters in school settings are
teenagers and any romance is innocent. Every episode is about 60 seconds, ends on a cliffhanger, and the
whole planned arc pays off.

Respond with ONLY this JSON:
{{
  "logline": "one sentence",
  "style": "one line describing the pictures: art style, color palette, lighting, mood (no character names), ending with 'vertical composition, no text'",
  "music_mood": "tense" or "happy",
  "characters": {{
     "<Name>": {{"look": "fixed physical description used in EVERY picture: age, hair, clothes, distinguishing features", "voice": one of {list(VOICES)}, "role": "who they are"}}
  }},
  "arc": [ {{"title": "episode title", "summary": "what happens, 2 sentences", "cliffhanger": "the last beat that makes people need the next episode"}} ]
}}
The first character listed is the narrator/protagonist who tells the story in first person. 3-5 characters total.
Make the arc escalate: each episode reveals something that changes how earlier moments look."""

EPISODE_SYSTEM = f"""You write one 60-second episode of a vertical-video story series. It is read aloud by character voices over
{SCENES_MIN}-{SCENES_MAX} AI pictures. It must be genuinely catchy. Use 8 scenes (about 7 seconds each; never fewer than 6):
- LINE 1 IS THE HOOK: at most 18 words, a specific strange concrete detail with a threat or mystery in it. No backstory
  openings ("Three weeks ago...", "It all started when..."). A viewer must NEED the next sentence.
- Short spoken sentences (under 14 words). Total spoken words 110-135.
- Escalate every scene: a new clue, danger or emotional hit. Plant at least two small details that mean more on a rewatch.
- The final line is the cliffhanger for the next episode (or, for the last episode, the twist that reframes everything).
- First person from the protagonist for narration; other characters speak in short quoted lines.
- PG-13: eerie and emotional, no gore, nothing sexual. School characters are teenagers; romance stays innocent.
- Only the protagonist narrates. Any OTHER character's line is exactly what that character says to someone, in their own
  first-person words ("Meet me at the old oak."), never a description of what they did ("Lena pointed at...", "His reply popped up...").
  When something must be described, the protagonist narrates it.
- "lines" hold ONLY words a character says out loud (or the protagonist narrates). Never write stage directions or sound
  effects as lines ("the camera flashes", "she gasps") - actions belong in the image_prompt, not in the spoken text.
- Be concrete and specific (a date, a name on a page, an object, a number), never vague ("something eerie", "a chill runs
  down my spine", "a strange feeling"). Cut cliche filler.
- Pictures: every scene needs an "image_prompt" describing ONE clear image. Use {{style}} and {{CharacterName}} placeholders
  (they expand to the fixed style and that character's fixed look). When a face isn't needed, prefer shots from behind,
  silhouettes, over-the-shoulder, hands, objects, phone screens, hallways - they keep characters looking consistent.
Respond with ONLY this JSON:
{{"title": "episode title", "summary": "2 sentences of what happened, for continuity",
  "scenes": [ {{"image_prompt": "...", "min_seconds": 6, "lines": [ {{"who": "<character name>", "text": "..."}} ]}} ]}}"""


EDITOR_SYSTEM = """You are a ruthless story editor for viral vertical videos. You get a DRAFT episode (JSON) and must return a
BETTER one in exactly the same JSON schema. Fix, in this order:
1. HOOK: line 1 must be at most 18 words, specific and strange, with a threat or a mystery; if it is vague, rewrite it
   (a good one states an impossible concrete fact plus a personal stake, e.g. "I found my crush in a 1994 yearbook. He hasn't aged a day.").
2. Remove every stage direction / sound effect / description that is not something a person would say aloud.
3. Replace vague or cliche lines with concrete ones. Keep sentences short and spoken.
4. Make sure each scene escalates and that at least two details pay off on a rewatch.
5. Make the final line a hard cliffhanger (or twist) that makes the next episode necessary.
6. Keep 6-10 scenes, 110-135 spoken words total, the same characters, and valid image_prompt fields with {style} / {Name} placeholders.
Return ONLY the improved JSON."""


def parse_scp_numbers(text: str) -> list[str]:
    """'173, 096 and SCP-049' -> ['173', '096', '049'] (3+ digits kept as typed, shorter ones padded)."""
    out = []
    for n in re.findall(r"\d{1,4}", text or ""):
        n = n.zfill(3)
        if n not in out:
            out.append(n)
    return out


def is_scp(series: dict) -> bool:
    return series.get("format") == "scp"


def create_scp_series(title: str, numbers: str) -> str:
    """A 'Foundation Tapes' series: one episode per SCP article. The scripts are written when an episode is made (fetched from the wiki)."""
    nums = parse_scp_numbers(numbers)
    if not nums:
        raise RuntimeError("Give at least one SCP number, like 173 or 096, 049.")
    title = title.strip() or "Foundation Tapes"
    slug = slugify(title)
    sdir = STORIES_DIR / slug
    if (sdir / "series.json").exists():
        raise RuntimeError(f"A series called '{slug}' already exists.")
    from scp_story import STYLE
    data = {"title": title, "slug": slug, "format": "scp", "genre": "SCP Foundation", "premise": "", "style": STYLE, "music_mood": "eerie", "characters": {},
            "logline": "Orientation tapes from Site-19, one containment file per episode. Adapted from the SCP Foundation wiki (CC BY-SA 3.0).",
            "arc": [{"title": f"SCP-{n}", "summary": f"Foundation orientation tape for SCP-{n}.", "cliffhanger": "", "scp": n} for n in nums],
            "created": time.strftime("%Y-%m-%d")}
    _write(sdir / "series.json", data)
    print(f"[series] Saved '{title}': {', '.join('SCP-' + n for n in nums)}")
    return slug


def add_episode(slug: str, hint: str = "") -> list[dict]:
    """Adds episode(s) to an existing series. SCP series: `hint` is SCP number(s). Story series: the AI plans the next chapter (hint = optional idea)."""
    path = STORIES_DIR / slug / "series.json"
    series = _read(path)
    added = []
    if is_scp(series):
        have = {e.get("scp") for e in series["arc"]}
        for n in parse_scp_numbers(hint):
            if n not in have:
                e = {"title": f"SCP-{n}", "summary": f"Foundation orientation tape for SCP-{n}.", "cliffhanger": "", "scp": n}
                series["arc"].append(e); added.append(e)
        if not added:
            raise RuntimeError("Those SCPs are already in this series (or no number was given).")
    else:
        done = "\n".join(f"{i}. {e['title']}: {e['summary']} (ends: {e.get('cliffhanger', '')})" for i, e in enumerate(series["arc"], 1))
        out = _llm_json("You extend a serialized short-video story. Given the series and its planned episodes so far, plan ONE new episode that continues the story, "
                        "raises the stakes and ends on a cliffhanger. Respond with ONLY {\"title\": \"...\", \"summary\": \"2 sentences\", \"cliffhanger\": \"the last beat\"}.",
                        f"SERIES: {series['title']} - {series.get('logline', '')}\nCHARACTERS: {', '.join(series['characters'])}\nEPISODES SO FAR:\n{done}\n"
                        + (f"IDEA FROM THE CREATOR FOR THE NEW EPISODE: {hint}\n" if hint.strip() else ""))
        if not out.get("title") or not out.get("summary"):
            raise RuntimeError("The model's episode plan was incomplete - try again.")
        e = {"title": str(out["title"])[:80], "summary": out["summary"], "cliffhanger": out.get("cliffhanger", "")}
        series["arc"].append(e); added.append(e)
    _write(path, series)
    return added


def create_series(title: str, premise: str, genre: str = "", episodes: int = 6) -> str:
    """Writes the series bible and saves stories/<slug>/series.json. Returns the slug."""
    slug = slugify(title)
    sdir = STORIES_DIR / slug
    if (sdir / "series.json").exists():
        raise RuntimeError(f"A series called '{slug}' already exists.")
    print(f"[series] Writing the series bible for '{title}'...")
    bible = _llm_json(BIBLE_SYSTEM, f"Title: {title}\nGenre: {genre}\nPremise: {premise}\nNumber of episodes in the arc: {episodes}")
    chars = bible.get("characters") or {}
    if not chars or not bible.get("arc"):
        raise RuntimeError("The model's series bible was missing characters or an episode arc - try again.")
    for c in chars.values():
        if c.get("voice") not in VOICES:
            c["voice"] = "teen_girl"
    data = {"title": title, "slug": slug, "premise": premise, "genre": genre, "logline": bible.get("logline", ""),
            "style": bible.get("style", ""), "music_mood": bible.get("music_mood") if bible.get("music_mood") in MOODS else "tense",
            "characters": chars, "arc": bible["arc"][:episodes], "created": time.strftime("%Y-%m-%d")}
    _write(sdir / "series.json", data)
    print(f"[series] Saved. {len(data['characters'])} characters, {len(data['arc'])} planned episodes: "
          + "; ".join(e["title"] for e in data["arc"]))
    return slug


NARRATION_VERBS = r"\b(said|says|asked|replied|whispered|pointed|flipped|flashed|popped up|appeared|turned|looked|smiled|nodded|stared|walked|reached|opened|closed|glanced)\b"


def _speaker_for(line: dict, names: list[str]) -> str:
    """Whose voice reads this line. A line that's really narration written about another
    character (starts with their name, or describes what they did) goes to the narrator -
    otherwise that character would be heard describing themselves in the third person."""
    who, text = line.get("who"), line["text"].strip()
    if who not in names:
        return names[0]
    if who != names[0]:
        starts_with_own_name = re.match(rf"^(?:{re.escape(who)}|His|Her|The)\b", text) is not None
        describes_action = re.search(NARRATION_VERBS, text, re.I) is not None and re.search(r"['\"]", text) is not None
        if starts_with_own_name or describes_action:
            return names[0]
    return who


def _story_characters(series: dict) -> dict:
    return {name: {**VOICES[c["voice"]], "look": c["look"]} for name, c in series["characters"].items()}


def build_episode_story(series: dict, number: int, ep: dict) -> dict:
    """Validates an episode written by anyone (the model, you, an outside AI) and turns it into a story.json dict."""
    plan = series["arc"][number - 1]
    names = list(series["characters"])
    narrator = names[0]
    scenes = []
    for sc in (ep.get("scenes") or [])[:SCENES_MAX]:
        lines = [{"who": _speaker_for(ln, names), "text": ln["text"].strip()}
                 for ln in sc.get("lines", []) if isinstance(ln.get("text"), str) and ln["text"].strip()]
        if lines and sc.get("image_prompt"):
            prompt = sc["image_prompt"] if "{style}" in sc["image_prompt"] else sc["image_prompt"].rstrip(". ") + ", {style}"
            scenes.append({"image": f"images/scene{len(scenes) + 1}.png", "min_seconds": float(sc.get("min_seconds") or 6),
                           "image_prompt": prompt, "lines": lines})
    if len(scenes) < SCENES_MIN:
        raise RuntimeError(f"The model wrote only {len(scenes)} usable scenes (need {SCENES_MIN}+) - try again.")

    story = {"title": ep.get("title") or plan["title"], "series": series["slug"], "episode": number, "summary": ep.get("summary", ""),
             "audience": "teens and adults", "style": series["style"], "music": {"mood": series["music_mood"]},
             "motion": "parallax", "caption_colors": {}, "title_card": f"{series['title'].upper()} · PART {number}",
             "characters": _story_characters(series), "scenes": scenes}
    return story


def save_episode(slug: str, number: int, ep: dict) -> Path:
    """Checks an episode's JSON (from the model, you, or an outside AI), saves it, and returns its folder."""
    series = _read(STORIES_DIR / slug / "series.json")
    story = build_episode_story(series, number, ep)
    ep_dir = STORIES_DIR / slug / "episodes" / f"ep{number:02d}"
    _write(ep_dir / "story.json", story)
    words = sum(len(ln["text"].split()) for s in story["scenes"] for ln in s["lines"])
    print(f"[series] Episode {number} saved: {len(story['scenes'])} scenes, {words} spoken words (about {words / 2.3:.0f}s of speech).")
    print("[series] Hook: " + story["scenes"][0]["lines"][0]["text"])
    return ep_dir


def episode_prompt(slug: str, number: int) -> dict:
    """The writing prompt for an episode, to paste into any stronger outside model; paste its JSON back."""
    series = _read(STORIES_DIR / slug / "series.json")
    plan = series["arc"][number - 1]
    previous = []
    for n in range(1, number):
        p = STORIES_DIR / slug / "episodes" / f"ep{n:02d}" / "story.json"
        previous.append(f"Episode {n} '{_read(p).get('title')}': {_read(p).get('summary', '')}" if p.exists()
                        else f"Episode {n} (not written yet; planned: {series['arc'][n - 1]['summary']})")
    bible = json.dumps({"title": series["title"], "logline": series["logline"], "premise": series["premise"],
                        "characters": {k: {"role": v.get("role"), "look": v["look"]} for k, v in series["characters"].items()}}, ensure_ascii=False)
    user = (f"SERIES BIBLE: {bible}\n\nWHAT HAPPENED SO FAR:\n" + ("\n".join(previous) or "Nothing - episode 1: the hook must introduce the whole concept.")
            + f"\n\nWRITE EPISODE {number} of {len(series['arc'])}: '{plan['title']}'\nPlanned content: {plan['summary']}\nIt must END on: {plan['cliffhanger']}")
    return {"system": EPISODE_SYSTEM, "user": user}


def write_episode(slug: str, number: int, style_ref: str = "") -> Path:
    """Writes episode `number` of the series (using the bible and what happened before) and returns its folder."""
    sdir = STORIES_DIR / slug
    series = _read(sdir / "series.json")
    arc = series["arc"]
    if not 1 <= number <= len(arc):
        raise RuntimeError(f"Episode {number} isn't in the plan (the arc has {len(arc)} episodes).")
    ep_dir = sdir / "episodes" / f"ep{number:02d}"
    if is_scp(series):                                  # fetch the SCP article and adapt it into a tape script
        from scp_story import create_scp_story
        return create_scp_story(arc[number - 1]["scp"], dest=ep_dir)
    previous = []
    for n in range(1, number):
        p = sdir / "episodes" / f"ep{n:02d}" / "story.json"
        if p.exists():
            s = _read(p)
            previous.append(f"Episode {n} '{s.get('title')}': {s.get('summary', '')}")
        else:
            previous.append(f"Episode {n} (not written yet; planned: {arc[n - 1]['summary']})")

    bible_text = json.dumps({"title": series["title"], "logline": series["logline"],
                             "characters": {k: {"role": v.get("role"), "look": v["look"]} for k, v in series["characters"].items()}},
                            ensure_ascii=False)
    plan = arc[number - 1]
    user = (f"SERIES BIBLE: {bible_text}\n\nWHAT HAPPENED SO FAR:\n" + ("\n".join(previous) or "Nothing - this is episode 1, so the hook must introduce the whole concept in the first line.")
            + f"\n\nWRITE EPISODE {number} of {len(arc)}: '{plan['title']}'\nPlanned content: {plan['summary']}\nIt must END on: {plan['cliffhanger']}"
            + ("\nThis is the FINAL episode: pay off the whole arc with a twist that reframes earlier moments." if number == len(arc) else ""))
    if style_ref:
        user += ("\n\nSHOT-STYLE REFERENCE (a cinematic prompt from the Seedance library - borrow its camera language, pacing and "
                 f"visual specificity for the image prompts, NOT its story):\n{style_ref[:900]}")
    if number == 1:
        user += (f"\n\nTHE SERIES PREMISE (use its strongest line/idea as the hook and include its key beats): {series.get('premise', '')}")
    print(f"[series] Writing episode {number}: '{plan['title']}'...")
    ep = _llm_json(EPISODE_SYSTEM, user)
    print("[series] Draft written - running the editor pass (sharpen the hook, cut filler, strengthen the ending)...")
    try:
        ep = _llm_json(EDITOR_SYSTEM, "SERIES: " + bible_text + "\n\nDRAFT EPISODE JSON:\n" + json.dumps(ep, ensure_ascii=False))
    except RuntimeError as e:
        print(f"[series] Editor pass skipped ({e}); keeping the first draft.")

    return save_episode(slug, number, ep)


def episode_status(ep_dir: Path) -> dict:
    story_path = ep_dir / "story.json"
    if not story_path.exists():
        return {"has_script": False}
    story = _read(story_path)
    scenes = story["scenes"]
    done = [i + 1 for i, s in enumerate(scenes) if (ep_dir / s["image"]).exists()]
    mp4s = sorted(ep_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    final = next((p for p in mp4s if not p.name.startswith("preview")), None)
    preview = next((p for p in mp4s if p.name.startswith("preview")), None)
    rel = lambda p: p.relative_to(STORIES_DIR).as_posix() if p else None
    posted = None
    if (ep_dir / "posted.json").exists():
        try:
            posted = _read(ep_dir / "posted.json")
        except (OSError, ValueError):
            posted = {"at": "earlier"}
    return {"has_script": True, "posted": posted, "title": story.get("title"), "summary": story.get("summary", ""),
            "scene_count": len(scenes), "images_done": done, "video": rel(final), "preview": rel(preview),
            "hook": scenes[0]["lines"][0]["text"] if scenes and scenes[0]["lines"] else "",
            "motion_clips": __import__("shots").motion_clips(ep_dir),
            "images": {i: rel(ep_dir / s["image"]) for i, s in enumerate(scenes, 1) if (i in done)}}


def list_series() -> list[dict]:
    out = []
    for sdir in sorted(STORIES_DIR.glob("*")):
        if not sdir.is_dir():
            continue
        if (sdir / "series.json").exists():
            series = _read(sdir / "series.json")
            eps = []
            for n, plan in enumerate(series["arc"], 1):
                st = episode_status(sdir / "episodes" / f"ep{n:02d}")
                eps.append({"number": n, "planned_title": plan["title"], "planned_summary": plan["summary"], **st})
            out.append({"slug": sdir.name, "title": series["title"], "logline": series.get("logline", ""), "genre": series.get("genre", ""),
                        "characters": list(series["characters"]), "standalone": False, "format": series.get("format", "story"), "episodes": eps})
        elif (sdir / "story.json").exists():       # an older single story
            st = episode_status(sdir)
            out.append({"slug": sdir.name, "title": st.get("title") or sdir.name, "logline": "", "genre": "", "characters": [],
                        "standalone": True, "episodes": [{"number": 1, "planned_title": st.get("title"), "planned_summary": "", **st}]})
    return out


def next_episode_number(slug: str) -> int:
    """The first episode that has no finished video yet (so a half-made one is resumed, not skipped)."""
    s = next((x for x in list_series() if x["slug"] == slug), None)
    if s is None:
        raise RuntimeError("Series not found.")
    return next((e["number"] for e in s["episodes"] if not e.get("video") and not e.get("posted")), 0)


def _remove_episode_files(ep_dir) -> list[str]:
    """Deletes an episode's video, preview, pictures and build files, keeping story.json (the script). Refuses anything that
    isn't inside stories/ or has no story.json."""
    import shutil
    ep = Path(ep_dir).resolve()
    if (STORIES_DIR.resolve() not in ep.parents and ep != STORIES_DIR.resolve()) or not (ep / "story.json").exists():
        raise RuntimeError("Refusing to clean up a folder that isn't a story.")
    removed = []
    for p in list(ep.glob("*.mp4")) + [ep / d for d in ("build", "build_horror", "images", "motion")]:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            removed.append(p.name + "/")
        elif p.exists():
            p.unlink()
            removed.append(p.name)
    return removed


def clear_episode_files(ep_dir) -> list[str]:
    """Manual "delete this episode's files" - same as after posting, but without marking it as posted."""
    return _remove_episode_files(ep_dir)


def delete_series(slug: str) -> None:
    """Deletes a whole series (or a single story) folder: script, pictures, videos - everything. Used only from an explicit, confirmed click."""
    import shutil
    target = (STORIES_DIR / Path(slug).name).resolve()
    if target.parent != STORIES_DIR.resolve() or not target.is_dir() or not ((target / "series.json").exists() or (target / "story.json").exists()):
        raise RuntimeError("That series doesn't exist.")
    shutil.rmtree(target)


def archive_posted(ep_dir, results: dict) -> list[str]:
    """After an episode has posted to every platform that was ticked: delete its video, preview, pictures and build files
    (they're large and can be remade from the script), keep story.json, and write posted.json so the episode counts as done
    and is never offered as "next" again. Returns the names removed."""
    import datetime
    removed = _remove_episode_files(ep_dir)
    ep = Path(ep_dir).resolve()
    (ep / "posted.json").write_text(json.dumps({"at": datetime.datetime.now().isoformat(timespec="seconds"),
        "results": {k: {"url": v.get("url"), "id": v.get("id")} for k, v in results.items() if v.get("ok")}}, indent=2), encoding="utf-8")
    return removed


def render_episode(slug: str, number: int, motion: str | None = None, cancel_event=None) -> Path:
    """Renders the finished video for an episode: a tape for SCP series, the narrated animated story for the rest."""
    ep = episode_dir(slug, number)
    if is_scp(_read(STORIES_DIR / slug / "series.json")):
        from horror_video import build_horror_video
        return build_horror_video(str(ep))
    from story_video import build_story
    return build_story(str(ep), motion=motion, cancel_event=cancel_event)


def make_episode(slug: str, number: int | None = None, log=print, cancel_event=None) -> int:
    """One click: write the episode (if it isn't written), make any missing pictures, render the video. Steps already done
    are skipped, so pressing it again resumes where it stopped. Returns the episode number."""
    from story_images import generate_images
    number = number or next_episode_number(slug)
    if not number:
        raise RuntimeError("Every episode in this series already has a video.")
    ep = episode_dir(slug, number)
    if not (ep / "story.json").exists():
        log(f"[auto] Step 1/3 - writing episode {number}...")
        write_episode(slug, number)
    else:
        log(f"[auto] Step 1/3 - episode {number} is already written.")
    log("[auto] Step 2/3 - making the pictures (skips any that exist)...")
    generate_images(str(ep), cancel_event=cancel_event)
    log("[auto] Step 3/3 - rendering the video...")
    render_episode(slug, number, cancel_event=cancel_event)
    log(f"[auto] Episode {number} is ready - review it, then press Post.")
    return number


def episode_dir(slug: str, number: int) -> Path:
    sdir = STORIES_DIR / slug
    return sdir if (sdir / "story.json").exists() and not (sdir / "series.json").exists() else sdir / "episodes" / f"ep{number:02d}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("title"); c.add_argument("premise"); c.add_argument("--genre", default=""); c.add_argument("--episodes", type=int, default=6)
    e = sub.add_parser("episode"); e.add_argument("slug"); e.add_argument("number", type=int)
    sub.add_parser("list")
    a = parser.parse_args()
    if a.cmd == "create":
        create_series(a.title, a.premise, a.genre, a.episodes)
    elif a.cmd == "episode":
        write_episode(a.slug, a.number)
    else:
        for s in list_series():
            print(s["slug"], "-", s["title"], f"({len(s['episodes'])} episodes)")
