"""
select_clips.py
Sends a transcript to Claude and asks it to pick the best short-form clips,
returning timestamps + ready-to-post titles/descriptions as structured JSON.

Usage:
    python select_clips.py transcripts/myvideo.json --max-clips 8

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
import sys
import json
import argparse
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are an expert short-form video editor who finds the most
engaging, self-contained moments in long-form video transcripts to turn into
YouTube Shorts (vertical, <=60s clips).

You will be given a transcript as a JSON array of {start, end, text} segments
(times in seconds). Pick the best candidate clips for Shorts.

Rules for picking clips:
- Each clip must be a SELF-CONTAINED moment that makes sense without context
  from the rest of the video (a strong hook, a punchline, a surprising fact,
  a complete story beat, a clear standalone insight).
- Clip duration should be between 15 and 60 seconds.
- Do not let clips overlap.
- Prefer moments with a strong opening line in the first 3 seconds (hook).
- Skip filler, rambling, or context-dependent moments.
- Only return clips you are genuinely confident are strong - quality over
  quantity. If the transcript doesn't support the requested number of good
  clips, return fewer.

For each clip, write:
- "title": punchy, <=60 characters, optimized for Shorts/curiosity
- "description": 1-2 sentences, include 2-4 relevant hashtags (always include #Shorts)
- "reason": one short sentence on why this moment works

Respond with ONLY a JSON array, no markdown fences, no preamble. Example shape:
[
  {
    "start": 102.5,
    "end": 142.0,
    "title": "The mistake everyone makes with X",
    "description": "Why most people get this wrong, explained in 30 seconds. #Shorts #productivity",
    "reason": "Strong contrarian hook + clean payoff"
  }
]
"""


def load_transcript(transcript_path: str) -> list[dict]:
    with open(transcript_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_user_prompt(segments: list[dict], max_clips: int) -> str:
    transcript_json = json.dumps(segments, ensure_ascii=False)
    return (
        f"Find up to {max_clips} clips for YouTube Shorts from this transcript.\n\n"
        f"TRANSCRIPT:\n{transcript_json}"
    )


def select_clips(segments: list[dict], max_clips: int = 8) -> list[dict]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to your .env file.")

    client = Anthropic(api_key=api_key)

    user_prompt = build_user_prompt(segments, max_clips)

    print(f"[select_clips] Asking Claude to pick up to {max_clips} clips...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    # Defensive parsing in case the model wraps in fences despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        clips = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse Claude's response as JSON: {e}\n\nRaw response:\n{raw_text}"
        )

    # Basic validation / sanitation
    valid_clips = []
    for c in clips:
        try:
            start, end = float(c["start"]), float(c["end"])
            if end <= start:
                continue
            if (end - start) > 65:  # hard safety cap
                continue
            valid_clips.append({
                "start": start,
                "end": end,
                "title": c.get("title", "Untitled Short")[:100],
                "description": c.get("description", "#Shorts"),
                "reason": c.get("reason", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue

    print(f"[select_clips] Got {len(valid_clips)} valid clip(s) from Claude.")
    return valid_clips


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
    args = parser.parse_args()

    segments = load_transcript(args.transcript_path)
    clips = select_clips(segments, max_clips=args.max_clips)
    video_stem = Path(args.transcript_path).stem
    save_plan(video_stem, clips)
