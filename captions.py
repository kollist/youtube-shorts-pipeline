"""
captions.py
Captions and hashtags per platform, written to be seen: a hook in the first line, one natural question, a few well-chosen tags.

What it follows (from the research behind it - mostly creator/marketing guides, not Meta's own rules):
  - Instagram cuts a caption after ~125 characters, so the first line is the hook. 3-5 hashtags; Facebook 1-3.
  - Tags that don't fit the video, or the same block on every post, read as spam. So tags come from pools by category
    (broad reach + niche + community) and rotate: the same set is never used twice in a row on a platform.
  - A hook must be something the video delivers. Captions that promise more than the video shows lose viewers
    in the first seconds, which hurts reach more than a good caption helps.
  - No "like / comment / share / tag a friend" demands (Meta calls that engagement bait and demotes it). A real question is fine.

Claude (your subscription) writes the wording; the tags are picked in code. If Claude is unavailable, plain templates are used.
"""

import json
import random
import re
import zlib
from pathlib import Path

HISTORY = Path(__file__).parent / "data" / "caption_history.json"
AI_NOTE = ""          # an optional note appended to captions (e.g. "Made with AI art & voice."); empty = none

POOLS = {
    "horror": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
               "niche": ["#horrorstories", "#scarystories", "#creepystories", "#creepystory", "#scarystorytime", "#mystery", "#paranormal",
                         "#unexplained", "#darkstories", "#thriller", "#supernatural", "#urbanlegends", "#haunted", "#storytime"],
               "community": ["#horrorcommunity", "#horrorfans", "#creepypasta", "#horrorlovers"]},
    "wisdom": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
               "niche": ["#wisdom", "#lifelessons", "#moralstories", "#parable", "#storytelling", "#mindset", "#deepthoughts", "#fables", "#storytime"],
               "community": ["#personalgrowth", "#selfgrowth", "#motivation", "#thinkdeeper"]},
    "facts": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
              "niche": ["#didyouknow", "#facts", "#funfacts", "#mindblown", "#science", "#explained", "#learnsomethingnew", "#education", "#numbers", "#math"],
              "community": ["#sciencefacts", "#stem", "#curiosity", "#factsdaily"]},
    "kids": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
             "niche": ["#kidsstories", "#bedtimestories", "#storiesforkids", "#cartoon", "#kidscartoon", "#storytime"],
             "community": ["#momlife", "#parenting", "#kidsvideo"]},
    "clips": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
              "niche": ["#streamer", "#twitch", "#funnymoments", "#clips", "#gaming", "#streamerclips", "#livestream", "#highlights"],
              "community": ["#ishowspeed", "#speed", "#kaicenat", "#kai"]},
    "sim": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
            "niche": ["#satisfying", "#oddlysatisfying", "#simulation", "#physics", "#satisfyingvideos", "#relaxing", "#asmr", "#marbles", "#3d", "#mesmerizing"],
            "community": ["#satisfyingasmr", "#physicslovers", "#oddlysatisfyingvideos", "#calming"]},
    "general": {"reach": ["#reels", "#viral", "#trending", "#explorepage"],
                "niche": ["#storytime", "#story", "#shorts", "#interesting", "#watchthis"],
                "community": ["#storytelling", "#creator"]},
}
TIKTOK_REACH = ["#fyp", "#foryou", "#foryoupage", "#viral"]


def category_for(genre: str = "", fmt: str = "", name: str = "", text: str = "") -> str:
    blob = f"{genre} {fmt} {name} {text}".lower()
    if name.startswith("sim-") or fmt == "sim" or any(w in blob for w in ("simulation", "marble", "satisfying", "physics sim")):
        return "sim"
    if fmt == "parable" or "parable" in blob or "fable" in blob:
        return "wisdom"
    if any(w in blob for w in ("horror", "thriller", "supernatural", "mystery", "creepy", "scary", "yearbook", "haunt", "ghost")) or name.startswith("motion-"):
        return "horror"
    if fmt == "stickman" or name.startswith("3d-") or any(w in blob for w in ("explainer", "science", "how tall", "how long", "fact")):
        return "facts"
    if any(w in blob for w in ("kids", "toddler", "bedtime", "fruit garden")):
        return "kids"
    if any(w in blob for w in ("speed", "kai cenat", "streamer", "stream")):
        return "clips"
    return "general"


def _history() -> dict:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _remember(platform: str, tags: list[str]) -> None:
    h = _history()
    h.setdefault(platform, []).append(tags)
    h[platform] = h[platform][-8:]
    HISTORY.parent.mkdir(exist_ok=True)
    HISTORY.write_text(json.dumps(h), encoding="utf-8")


def pick_tags(category: str, platform: str, seed_text: str = "", remember: bool = True) -> list[str]:
    """Instagram: 1 reach + 3 niche + 1 community. Facebook: 1 reach + 2 niche. TikTok: 2 reach + 2 niche. YouTube: #shorts + 2 niche.
    Within those slots, picks the least-recently-used tags, so consecutive posts don't carry the same block."""
    pool = POOLS.get(category, POOLS["general"])
    rng = random.Random(zlib.crc32(f"{seed_text}|{platform}".encode()))
    recent = [t for s in _history().get(platform, [])[-3:] for t in s]
    def take(options, k):
        opts = sorted(options, key=lambda t: (recent.count(t), rng.random()))
        return opts[:k]
    if platform == "instagram":
        tags = take(pool["reach"], 1) + take(pool["niche"], 3) + take(pool["community"], 1)
    elif platform == "facebook":
        tags = take(pool["reach"], 1) + take(pool["niche"], 2)
    elif platform == "tiktok":
        tags = take(TIKTOK_REACH, 2) + take(pool["niche"], 2)
    else:                                                   # youtube
        tags = ["#shorts"] + take(pool["niche"], 2)
    if remember:
        _remember(platform, tags)
    return tags


SYSTEM = """You write social captions for a short vertical video. Be specific and scroll-stopping, never generic.

For INSTAGRAM: "hook" = the first line, max 90 characters, must work alone (it is all most people read). Use ONE of these formulas, and
vary it - pick the one that fits the video: curiosity gap (a specific, odd detail, not the ending); a direct challenge or "be honest" question;
contrarian ("Everyone thinks X. The video shows Y."); stakes with a number; second person ("You'd notice it too late."). Then "body" = one short
line of context, and "question" = one natural question people actually want to answer (an opinion or a choice, NOT a demand to like, share,
comment, tag or follow - those get demoted).
For FACEBOOK: "text" = 2-3 short lines. The first sentence leads with the clearest keyword/topic of the video and a hook; a calm, conversational
tone; ends with one genuine question.
For YOUTUBE: "title" = max 70 characters, curiosity-driven, no ALL CAPS, no "Part"/colon-subtitle style; "description" = 1-2 lines.
For TIKTOK: "text" = one hook line plus one question, max 120 characters.
Rules: everything must be true to the video - tease, don't spoil, and never promise something the video doesn't show. At most 2 emoji in a
caption. No hashtags (they are added separately). No "link in bio". Plain words, no hype like "mind-blowing" or "you won't believe".
Respond with ONLY:
{"instagram": {"hook": "", "body": "", "question": ""}, "facebook": {"text": ""}, "youtube": {"title": "", "description": ""}, "tiktok": {"text": ""}}"""


def _fallback(info: dict) -> dict:
    hook = (info.get("hook") or info.get("title") or "Watch this").strip()
    hook = hook if len(hook) <= 90 else hook[:87].rstrip() + "..."
    q = random.Random(zlib.crc32(hook.encode())).choice(["Would you have noticed?", "What would you have done?", "Be honest - did you see that coming?"])
    return {"instagram": {"hook": hook, "body": (info.get("summary") or "")[:140], "question": q}, "facebook": {"text": f"{hook}\n\n{q}"},
            "youtube": {"title": (info.get("title") or hook)[:70], "description": (info.get("summary") or hook)[:200]}, "tiktok": {"text": f"{hook} {q}"[:120]}}


def write_captions(info: dict, platforms: list[str] | None = None, remember: bool = True) -> dict:
    """info: {title, summary, hook, category}. Returns {"instagram": text, "facebook": text, "tiktok": text,
    "youtube_title": str, "youtube": description} - ready to post, tags included."""
    from series import _llm_json
    category = info.get("category") or "general"
    brief = (f"Video title: {info.get('title', '')}\nWhat happens / what it explains: {(info.get('summary') or '')[:500]}\n"
             f"Opening line of the video: {info.get('hook', '')}\nCategory: {category}")
    try:
        w = _llm_json(SYSTEM, brief)
        if not (isinstance(w.get("instagram"), dict) and w["instagram"].get("hook")):
            raise ValueError("incomplete")
    except Exception:
        w = _fallback(info)
    seed = info.get("title", "")
    ai = f"\n\n{AI_NOTE}" if AI_NOTE else ""
    ig, fb, tt, yt = w.get("instagram", {}), w.get("facebook", {}), w.get("tiktok", {}), w.get("youtube", {})
    out = {}
    ig_body = " ".join(x for x in (ig.get("body", "").strip(), ig.get("question", "").strip()) if x)
    out["instagram"] = f"{ig.get('hook', '').strip()}\n\n{ig_body}\n\n{' '.join(pick_tags(category, 'instagram', seed, remember))}{ai}".replace("\n\n\n\n", "\n\n")
    out["facebook"] = f"{fb.get('text', '').strip()}\n\n{' '.join(pick_tags(category, 'facebook', seed, remember))}{ai}"
    out["tiktok"] = f"{tt.get('text', '').strip()} {' '.join(pick_tags(category, 'tiktok', seed, remember))}"
    out["youtube_title"] = (yt.get("title") or info.get("title") or "").strip()[:100]
    out["youtube"] = f"{yt.get('description', '').strip()}\n\n{' '.join(pick_tags(category, 'youtube', seed, remember))}{chr(10) * 2 + AI_NOTE if AI_NOTE else ''}".strip()
    return out


if __name__ == "__main__":
    import sys
    demo = {"title": "He Hasn't Aged a Day", "category": "horror", "hook": "I found my crush in a 1994 yearbook. He hasn't aged a day.",
            "summary": "A teen finds her crush in a decades-old yearbook, unchanged, and starts texting him."}
    for k, v in write_captions(demo, remember=False).items():
        print(f"--- {k}\n{v}\n")
