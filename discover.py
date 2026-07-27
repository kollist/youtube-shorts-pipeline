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

import json
import os
from datetime import datetime, timezone
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
