"""
select_clips.py
Sends a transcript to Groq's free hosted API (Llama 3.3 70B) and asks it to
pick the best short-form clips, returning timestamps + ready-to-post
titles/descriptions/hashtags as structured JSON. Free tier, no local compute -
just needs a Groq API key and an internet connection.

ONE-TIME SETUP:
    1. Get a free API key at https://console.groq.com/keys
    2. Add it to .env as GROQ_API_KEY=gsk_...

Usage:
    python select_clips.py transcripts/myvideo.json --max-clips 8 \
        --min-duration 30 --max-duration 45

Output:
    clips/myvideo_plan.json  -> list of clip plans:
        {
          "start": 102.5,
          "end": 142.0,
          "title": "...",
          "description": "...",
          "reason": "..."
        }
"""

import os
import re
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODEL = "llama-3.3-70b-versatile"  # free tier on Groq, far stronger than any local 7-14B model

DEFAULT_MIN_DURATION = 30
DEFAULT_MAX_DURATION = 45
DURATION_TOLERANCE = 8  # seconds of slack around the target window before a clip gets dropped
SNAP_TOLERANCE = 1.5  # how far a timestamp may drift from a real segment edge and still snap to it

# Groq's free tier caps llama-3.3-70b-versatile at 12,000 tokens/minute per request.
# A full-length video transcript can easily blow past that in one request, so we
# split it into chunks that comfortably fit, and pace requests across the minute.
CHARS_PER_TOKEN = 4  # rough heuristic for English text
MAX_INPUT_TOKENS_PER_CHUNK = 7000  # leaves headroom under 12,000 for system prompt + response
CHUNK_COOLDOWN_SECONDS = 65  # let the tokens-per-minute budget fully reset between chunks


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def chunk_segments(segments: list[dict], max_tokens: int = MAX_INPUT_TOKENS_PER_CHUNK) -> list[list[dict]]:
    """Split segments into groups that each stay under a rough per-request token
    budget, so one long transcript doesn't blow past Groq's tokens-per-minute limit."""
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_tokens = 0
    for seg in segments:
        seg_tokens = estimate_tokens(seg["text"]) + 8  # + a few tokens for timestamp formatting
        if current and current_tokens + seg_tokens > max_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(seg)
        current_tokens += seg_tokens
    if current:
        chunks.append(current)
    return chunks


def build_system_prompt(min_duration: float, max_duration: float) -> str:
    return f"""You are an expert short-form video editor who finds the most
engaging, self-contained moments in long-form video transcripts to turn into
YouTube Shorts (vertical clips).

You will be given a transcript as a JSON array of {{start, end, text}} segments
(times in seconds, already split at natural sentence/pause boundaries). Pick
the best candidate clips for Shorts.

Rules for picking clips:
- Each clip must be a SELF-CONTAINED moment that makes sense without context
  from the rest of the video (a strong hook, a punchline, a surprising fact,
  a complete story beat, a clear standalone insight).
- Target clip duration is {min_duration:.0f}-{max_duration:.0f} seconds. Only go
  outside that window if the moment is too strong to cut and no combination of
  whole segments lands inside it.
- CLEAN CUTS ONLY: "start" must exactly equal the "start" of one of the given
  segments, and "end" must exactly equal the "end" of one of the given segments.
  Never invent a timestamp in the middle of a segment - that chops a word or
  sentence in half and ruins the cut.
- Do not let clips overlap.
- Prefer moments with a strong opening line in the first 3 seconds (hook), and
  end on a complete sentence/thought, never a trailing dependent clause.
- Skip filler, rambling, or context-dependent moments.
- Only return clips you are genuinely confident are strong - quality over
  quantity. If the transcript doesn't support the requested number of good
  clips, return fewer.

For each clip, write:
- "title": punchy, <=60 characters, optimized for Shorts/curiosity
- "description": 1-2 sentences, include 2-4 relevant hashtags (always include #Shorts)
- "reason": one short sentence on why this moment works

Respond with ONLY a JSON object of this exact shape, no markdown fences, no
preamble, no explanation before or after:
{{
  "clips": [
    {{
      "start": 102.5,
      "end": 142.0,
      "title": "The mistake everyone makes with X",
      "description": "Why most people get this wrong, explained in 30 seconds. #Shorts #productivity",
      "reason": "Strong contrarian hook + clean payoff"
    }}
  ]
}}
"""


def load_transcript(transcript_path: str) -> list[dict]:
    with open(transcript_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_user_prompt(segments: list[dict], max_clips: int) -> str:
    transcript_json = "\n".join(
        f"{s['start']:.2f}|{s['end']:.2f}|{s['text']}"
        for s in segments
    )
    return (
        f"Find up to {max_clips} clips for YouTube Shorts from this transcript.\n\n"
        f"TRANSCRIPT:\n{transcript_json}"
    )


def _parse_reset_seconds(header: str) -> float:
    """Parse Groq's x-ratelimit-reset-tokens header (e.g. '1m5s', '8.5s') into seconds."""
    total = sum(
        float(v) * (60 if u.lower() == "m" else 1)
        for v, u in re.findall(r"(\d+(?:\.\d+)?)([mMs])", header)
    )
    return total if total > 0 else 70.0  # safe fallback if header is missing or unparseable


def call_groq(prompt: str, system: str, model: str = MODEL) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "and add it to your .env file as GROQ_API_KEY=..."
        )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "User-Agent": "python-urllib/3.14",
    }

    for attempt in range(3):
        req = urllib.request.Request(GROQ_URL, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", "ignore")
            if e.code in (413, 429) and attempt < 2:
                wait = _parse_reset_seconds(e.headers.get("x-ratelimit-reset-tokens", "")) + 5
                print(f"[select_clips] Groq rate limit hit; waiting {wait:.0f}s then retrying "
                      f"(attempt {attempt + 1}/3)...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Groq API error {e.code}: {body_text}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not reach Groq API ({GROQ_URL}): {e}")


def snap_to_segment_bounds(start: float, end: float, segments: list[dict]) -> tuple[float, float]:
    """Pull (start, end) onto the nearest real segment edge so the cut lands on a
    clean sentence boundary instead of mid-word, even if the model's timestamps drift."""
    if not segments:
        return start, end

    nearest_start = min((s["start"] for s in segments), key=lambda v: abs(v - start))
    nearest_end = min((s["end"] for s in segments), key=lambda v: abs(v - end))

    if abs(nearest_start - start) <= SNAP_TOLERANCE:
        start = nearest_start
    if abs(nearest_end - end) <= SNAP_TOLERANCE:
        end = nearest_end

    return start, end


def _select_clips_for_chunk(
    segments: list[dict],
    max_clips: int,
    model: str,
    min_duration: float,
    max_duration: float,
) -> list[dict]:
    user_prompt = build_user_prompt(segments, max_clips)
    system_prompt = build_system_prompt(min_duration, max_duration)

    raw_text = call_groq(user_prompt, system_prompt, model=model).strip()

    # Defensive parsing in case the model wraps in fences despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse model response as JSON: {e}\n\nRaw response:\n{raw_text}"
        )

    # We ask for {"clips": [...]} but tolerate a bare array too.
    if isinstance(parsed, dict):
        clips = next((v for v in parsed.values() if isinstance(v, list)), [])
    else:
        clips = parsed

    low = max(0.0, min_duration - DURATION_TOLERANCE)
    high = max_duration + DURATION_TOLERANCE
    target_center = (min_duration + max_duration) / 2

    valid_clips: list[dict] = []
    fallback_clips: list[dict] = []  # outside range but otherwise usable

    for c in clips:
        try:
            start, end = float(c["start"]), float(c["end"])
            start, end = snap_to_segment_bounds(start, end, segments)
            duration = end - start
            if duration < 5:
                continue  # too short to be useful at all
            entry = {
                "start": start,
                "end": end,
                "title": c.get("title", "Untitled Short")[:100],
                "description": c.get("description", "#Shorts"),
                "reason": c.get("reason", ""),
            }
            if low <= duration <= high:
                valid_clips.append(entry)
            else:
                fallback_clips.append(entry)
        except (KeyError, ValueError, TypeError):
            continue

    if not valid_clips and fallback_clips:
        # Duration filter wiped everything — use the clip closest to the target window
        # rather than returning nothing from this chunk.
        best = min(fallback_clips, key=lambda x: abs((x["end"] - x["start"]) - target_center))
        dur = best["end"] - best["start"]
        print(f"[select_clips] Warning: no clips in {min_duration:.0f}-{max_duration:.0f}s range "
              f"for this chunk; using closest match ({dur:.0f}s).")
        valid_clips = [best]

    return valid_clips


def select_clips(
    segments: list[dict],
    max_clips: int = 8,
    model: str = MODEL,
    min_duration: float = DEFAULT_MIN_DURATION,
    max_duration: float = DEFAULT_MAX_DURATION,
) -> list[dict]:
    chunks = chunk_segments(segments)
    if not chunks:
        return []

    per_chunk_max = max(1, -(-max_clips // len(chunks)))  # ceil(max_clips / len(chunks))

    print(f"[select_clips] Asking '{model}' (via Groq) to pick up to {max_clips} clips total, "
          f"targeting {min_duration:.0f}-{max_duration:.0f}s each, "
          f"across {len(chunks)} chunk(s)...")

    all_clips: list[dict] = []
    for i, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            print(f"[select_clips] Chunk {i}/{len(chunks)} ({len(chunk)} segments)...")
        all_clips.extend(
            _select_clips_for_chunk(chunk, per_chunk_max, model, min_duration, max_duration)
        )
        if i < len(chunks):
            time.sleep(CHUNK_COOLDOWN_SECONDS)  # stay under the tokens-per-minute limit

    all_clips = all_clips[:max_clips]
    print(f"[select_clips] Got {len(all_clips)} valid clip(s) from the model.")
    return all_clips


def save_plan(video_stem: str, clips: list[dict], out_dir: str = "clips") -> str:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_stem}_plan.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clips, f, ensure_ascii=False, indent=2)
    print(f"[select_clips] Saved clip plan -> {out_path}")
    return str(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("transcript_path", help="Path to transcript JSON from transcribe.py")
    parser.add_argument("--max-clips", type=int, default=8)
    parser.add_argument("--model", default=MODEL, help="Groq model name")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION,
                         help="Target minimum clip length in seconds (default: 30)")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION,
                         help="Target maximum clip length in seconds (default: 45)")
    args = parser.parse_args()

    segments = load_transcript(args.transcript_path)
    clips = select_clips(
        segments,
        max_clips=args.max_clips,
        model=args.model,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
    )
    video_stem = Path(args.transcript_path).stem
    save_plan(video_stem, clips)
