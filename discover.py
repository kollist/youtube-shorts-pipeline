"""
discover.py
Surfaces recent uploads from a small, curated list of verified official /
public-domain YouTube channels - so every suggestion is rights-safe by
construction, not by trusting a generic search - ranked by view velocity
(views per day since upload, a real objective trendiness signal) plus a
short model-written note on Shorts potential, reusing the same Groq
fallback chain as clip selection.

ONE-TIME SETUP:
    Needs a YouTube Data API key (separate from the OAuth client used for
    uploading, since this only ever reads public channel data):
    1. https://console.cloud.google.com/ -> same project as your upload
       OAuth client (or a new one) -> APIs & Services -> enable
       "YouTube Data API v3" if not already enabled.
    2. APIs & Services -> Credentials -> Create Credentials -> API key.
    3. Add it to .env as YOUTUBE_API_KEY=...
"""

import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv

from select_clips import MODEL_FALLBACK_CHAIN, GroqGenerationError, call_groq
from token_budget import GroqBudgetExhausted

load_dotenv()

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"

# Small, curated set of verified official/public-domain channels - add more
# here as the niche expands. Each one should be a channel you've personally
# confirmed is an official/government source, not a reposting third party
# (see the NASA vs. "Space SPAN" distinction from earlier in this project).
CURATED_CHANNELS = {
    "NASA": "UCLA_DiR1FfKNvjuUpBHmylQ",
}


def _api_get(path: str, **params) -> dict:
    if not YOUTUBE_API_KEY:
        raise RuntimeError(
            "YOUTUBE_API_KEY is not set. Get one at https://console.cloud.google.com/ "
            "(APIs & Services -> Credentials -> Create Credentials -> API key) and add "
            "it to .env as YOUTUBE_API_KEY=... (see discover.py's module docstring)."
        )
    params["key"] = YOUTUBE_API_KEY
    url = f"{YOUTUBE_API_BASE}/{path}?{urlencode(params)}"
    with urlopen(url, timeout=30) as resp:
        return json.load(resp)


def _uploads_playlist_id(channel_id: str) -> str:
    data = _api_get("channels", part="contentDetails", id=channel_id)
    return data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]


# Long streams from the two streamers this project clips. These are the official channels
# (found through the YouTube API): the stream channels hold the full VODs, the main
# channels hold the edited uploads. Anything under MIN_STREAM_SECONDS (shorts, clips, short
# videos) is dropped - Discover is for hours-long streams worth mining for moments.
STREAMER_CHANNELS = {
    "IShowSpeed": [("Live Speedy", "UC2bW_AY9BlbYLGJSXAbjS4Q"), ("IShowSpeed", "UCWsDFcIhY2DBi3GB5uykGXA")],
    "Kai Cenat": [("Kai Cenat Live", "UCvCfpQXRXdJdL07pzTIA6Cw"), ("Kai Cenat", "UCoEmptob-eEGKk18c2VplJg")],
}
MIN_STREAM_SECONDS = 40 * 60
_STREAM_CACHE: dict = {"at": 0.0, "videos": []}
STREAM_CACHE_SECONDS = 600   # the YouTube API has a daily quota; don't refetch on every page view


def _iso_duration_seconds(iso: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


# --- the GTA 6 niche: there is no fixed list of streamers for a brand-new game, so this SEARCHES for long GTA 6 streams and videos from the last two weeks,
# and also reads every channel in data/clip_channels.json (channels that said yes to clipping - the safe list). Results from the safe list are marked.
GTA6 = "GTA 6"
GTA6_QUERIES = ["GTA 6 gameplay", "GTA VI live stream", "GTA 6 full playthrough"]
GTA6_JUNK = re.compile(r"\bgta\s*(5|v)\b|before gta|pre-?load|install|trailer|react|leak|fake|android|mobile|waiting for|countdown|superhero|barred game|everything we know|breakdown|ost\b", re.I)     # not GTA 6 footage: the old game, trailers, fakes
GTA6_TITLE = re.compile(r"\bgta\s*(6|vi)\b|grand theft auto\s*(6|vi)\b", re.I)
CLIP_CHANNELS = Path(__file__).parent / "data" / "clip_channels.json"        # {"channels": [{"label": "...", "id": "UC..."}]}
_GTA_CACHE: dict = {"at": 0.0, "videos": []}


def allowed_channels() -> list[dict]:
    try:
        return [c for c in json.loads(CLIP_CHANNELS.read_text(encoding="utf-8")).get("channels", []) if c.get("id")]
    except (OSError, json.JSONDecodeError):
        return []


def discover_gta6(days: int = 14, per_query: int = 25, force: bool = False) -> list[dict]:
    """Long (40+ min) GTA 6 videos and streams from the last `days` days: YouTube search (100 quota units per query, so cached) + the permission list."""
    import time
    from datetime import timedelta
    if not force and time.time() - _GTA_CACHE["at"] < STREAM_CACHE_SECONDS and _GTA_CACHE["videos"]:
        return _GTA_CACHE["videos"]
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    found: dict[str, dict] = {}
    for q in GTA6_QUERIES:
        data = _api_get("search", part="snippet", q=q, type="video", order="viewCount", videoDuration="long", publishedAfter=after, maxResults=per_query)
        for it in data.get("items", []):
            sn = it["snippet"]; vid = it["id"]["videoId"]; sn["title"] = html.unescape(sn["title"])
            if GTA6_TITLE.search(sn["title"]) and not GTA6_JUNK.search(sn["title"]):
                found.setdefault(vid, {"video_id": vid, "title": sn["title"], "published_at": sn["publishedAt"], "channel": sn["channelTitle"], "channel_id": sn["channelId"],
                                       "thumbnail": sn.get("thumbnails", {}).get("medium", {}).get("url", "")})
    allowed = {c["id"] for c in allowed_channels()}
    for c in allowed_channels():
        for v in _recent_uploads(c["id"], max_results=15):
            v.update(channel=c.get("label", ""), channel_id=c["id"])
            found.setdefault(v["video_id"], v)
    vids = list(found.values())
    if vids:
        ids = ",".join(v["video_id"] for v in vids[:50])
        details = {i["id"]: i for i in _api_get("videos", part="contentDetails", id=ids).get("items", [])}
        for v in vids:
            v["duration_sec"] = _iso_duration_seconds(details.get(v["video_id"], {}).get("contentDetails", {}).get("duration", ""))
        vids = _attach_stats([v for v in vids if v.get("duration_sec", 0) >= MIN_STREAM_SECONDS][:50])
    for v in vids:
        v.update(streamer=GTA6, url=f"https://www.youtube.com/watch?v={v['video_id']}", allowed=v.get("channel_id") in allowed)
    vids.sort(key=lambda v: v["published_at"], reverse=True)
    _GTA_CACHE.update(at=time.time(), videos=vids)
    return vids


def discover_streams(streamer: str | None = None, per_channel: int = 50, force: bool = False) -> list[dict]:
    """Recent long streams from the streamers above, newest first. Each carries its
    length, views and views per day. `streamer` filters to one of them."""
    import time
    if streamer == GTA6:
        return discover_gta6(force=force)
    if force or time.time() - _STREAM_CACHE["at"] > STREAM_CACHE_SECONDS or not _STREAM_CACHE["videos"]:
        collected = []
        for name, channels in STREAMER_CHANNELS.items():
            for label, channel_id in channels:
                vids = _recent_uploads(channel_id, max_results=per_channel)
                for v in vids:
                    v.update(streamer=name, channel=label, url=f"https://www.youtube.com/watch?v={v['video_id']}")
                if not vids:
                    continue
                ids = ",".join(v["video_id"] for v in vids)
                details = {i["id"]: i for i in _api_get("videos", part="contentDetails", id=ids).get("items", [])}
                for v in vids:
                    v["duration_sec"] = _iso_duration_seconds(details.get(v["video_id"], {}).get("contentDetails", {}).get("duration", ""))
                collected.extend(v for v in vids if v["duration_sec"] >= MIN_STREAM_SECONDS)
        collected = _attach_stats(collected)
        collected.sort(key=lambda v: v["published_at"], reverse=True)
        _STREAM_CACHE.update(at=time.time(), videos=collected)
    videos = _STREAM_CACHE["videos"]
    return [v for v in videos if streamer in (None, "", "all", v["streamer"])]


def _recent_uploads(channel_id: str, max_results: int = 15) -> list[dict]:
    playlist_id = _uploads_playlist_id(channel_id)
    data = _api_get("playlistItems", part="snippet", playlistId=playlist_id, maxResults=max_results)
    videos = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        video_id = snippet["resourceId"]["videoId"]
        videos.append({
            "video_id": video_id,
            "title": snippet["title"],
            "published_at": snippet["publishedAt"],
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        })
    return videos


def _attach_stats(videos: list[dict]) -> list[dict]:
    if not videos:
        return videos
    ids = ",".join(v["video_id"] for v in videos)
    data = _api_get("videos", part="statistics", id=ids)
    stats_by_id = {item["id"]: item.get("statistics", {}) for item in data.get("items", [])}
    now = datetime.now(timezone.utc)
    for v in videos:
        stats = stats_by_id.get(v["video_id"], {})
        view_count = int(stats.get("viewCount", 0))
        published = datetime.fromisoformat(v["published_at"].replace("Z", "+00:00"))
        days = max(1.0, (now - published).total_seconds() / 86400)
        v["view_count"] = view_count
        v["days_since_published"] = round(days, 1)
        v["view_velocity"] = round(view_count / days, 1)
    return videos


def _call_with_fallback(user_prompt: str, system_prompt: str) -> str:
    """Same fallback-chain idea as select_clips.select_clips(), scaled down
    for a single, cheap annotation call instead of a whole video's chunks."""
    last_err = None
    for model in MODEL_FALLBACK_CHAIN:
        try:
            return call_groq(user_prompt, system_prompt, model=model)
        except (GroqBudgetExhausted, GroqGenerationError) as e:
            last_err = e
            continue
    raise last_err


def _annotate_with_model(videos: list[dict]) -> list[dict]:
    """Adds a qualitative 'why this could work for Shorts' note on top of the
    objective view-velocity signal. Degrades gracefully (no scores, sorted by
    view velocity alone) if every model in the fallback chain is exhausted."""
    if not videos:
        return videos

    system_prompt = """You help pick which long-form videos are worth turning into
YouTube Shorts. You'll get a list of candidate videos with their title and view
velocity (views per day since upload - a real, objective trendiness signal).

For each video, write a "shorts_potential" score from 1-10 and a one-sentence
"reason" - considering both the view velocity AND whether the title itself
suggests strong hook material (a surprising claim, a clear stakes/numbers
angle, a dramatic moment) versus a flat/administrative title that's unlikely
to clip well even if the underlying video is popular.

Respond with ONLY a JSON object of this exact shape, no markdown fences, no
preamble:
{"scores": [{"video_id": "abc123", "shorts_potential": 8, "reason": "..."}]}
"""
    user_prompt = json.dumps([
        {"video_id": v["video_id"], "title": v["title"], "view_velocity": v["view_velocity"]}
        for v in videos
    ], ensure_ascii=False)

    try:
        raw = _call_with_fallback(user_prompt, system_prompt).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        scores = {s["video_id"]: s for s in json.loads(raw).get("scores", [])}
    except Exception as e:
        print(f"[discover] Model annotation unavailable, sorting by view velocity only: {e}")
        scores = {}

    for v in videos:
        s = scores.get(v["video_id"], {})
        v["shorts_potential"] = s.get("shorts_potential")
        v["reason"] = s.get("reason", "")
    return videos


def _search_videos(query: str, max_results: int = 15) -> list[dict]:
    """A plain keyword search (search.list), unlike _recent_uploads which is
    scoped to one curated channel - used for filler/background gameplay
    footage, where there's no single "official" channel to point at the way
    NASA's is for space content. Costs 100 quota units per call (YouTube
    Data API's search endpoint is expensive relative to a 10,000/day default
    quota), so callers should not hit this on every page load."""
    data = _api_get(
        "search", part="snippet", type="video", q=query,
        order="viewCount", maxResults=max_results, safeSearch="strict",
    )
    videos = []
    for item in data.get("items", []):
        snippet = item["snippet"]
        videos.append({
            "video_id": item["id"]["videoId"],
            "title": snippet["title"],
            "channel": snippet.get("channelTitle", ""),
            "published_at": snippet["publishedAt"],
            "thumbnail": snippet.get("thumbnails", {}).get("medium", {}).get("url", ""),
        })
    return videos


def discover_filler_candidates(
    query: str = "minecraft parkour gameplay no copyright",
    max_results: int = 15,
) -> list[dict]:
    """Candidate background/filler footage (e.g. Minecraft parkour) via a
    keyword search, for the split-screen clip layout - NOT rights-verified
    the way CURATED_CHANNELS is. A search result showing up here is not
    permission to use it; check the channel's own description/license before
    downloading anything into filler/ (many "no copyright gameplay" channels
    explicitly grant reuse, but not all - "no copyright" in a title isn't a
    guarantee)."""
    videos = _search_videos(query, max_results=max_results)
    for v in videos:
        v["url"] = f"https://www.youtube.com/watch?v={v['video_id']}"
    videos = _attach_stats(videos)
    videos.sort(key=lambda v: v["view_count"], reverse=True)
    return videos


def discover(max_results_per_channel: int = 15) -> list[dict]:
    all_videos = []
    for channel_name, channel_id in CURATED_CHANNELS.items():
        videos = _recent_uploads(channel_id, max_results=max_results_per_channel)
        for v in videos:
            v["channel"] = channel_name
            v["url"] = f"https://www.youtube.com/watch?v={v['video_id']}"
        all_videos.extend(videos)

    all_videos = _attach_stats(all_videos)
    all_videos = _annotate_with_model(all_videos)
    all_videos.sort(key=lambda v: v.get("shorts_potential") or v["view_velocity"] / 100, reverse=True)
    return all_videos


if __name__ == "__main__":
    for v in discover():
        print(f"{v['shorts_potential']} | {v['title']} | {v['view_velocity']} views/day | {v['reason']}")
