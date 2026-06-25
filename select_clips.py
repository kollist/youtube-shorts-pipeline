"""
select_clips.py
Sends a transcript to a LOCAL Ollama model and asks it to pick the best
short-form clips, returning timestamps + ready-to-post titles/descriptions
as structured JSON. Runs fully offline/free on your own machine via Ollama.

ONE-TIME SETUP:
    brew install ollama
    ollama pull qwen2.5:7b-instruct

    (Ollama runs as a background service after install. If "ollama pull"
    says it can't connect, run `ollama serve` in a separate terminal tab
    first, or just restart your Mac once after installing.)

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

import sys
import json
import argparse
import urllib.request
import urllib.error
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:7b-instruct"  # free, local, runs on Apple Silicon
MIN_CLIP_SECONDS = 15  # matches the 15-60s rule in SYSTEM_PROMPT
MAX_CLIP_SECONDS = 65  # small buffer over the prompt's 60s ceiling

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

Respond with ONLY a JSON array, no markdown fences, no preamble, no explanation
before or after. Example shape:
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


# Plain "format": "json" only guarantees syntactically valid JSON - the model
# is still free to pick its own shape (we saw it return a video-summary object
# instead of a clip array). Passing a JSON schema constrains it to this exact
# array-of-clips shape via grammar-level decoding.
CLIPS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "start": {"type": "number"},
            "end": {"type": "number"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["start", "end", "title", "description", "reason"],
    },
}


def call_ollama(prompt: str, system: str, model: str = MODEL) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "format": CLIPS_SCHEMA,  # constrain output to this exact array shape
        "options": {
            "temperature": 0.4,
            "num_ctx": 32768,  # max context window qwen2.5:7b-instruct supports
        },
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach Ollama at {OLLAMA_URL}. Is it running?\n"
            f"Try: 'ollama serve' in a terminal, or 'ollama pull {model}' "
            f"if you haven't downloaded the model yet.\n\nOriginal error: {e}"
        )
    return body.get("response", "")


def select_clips(segments: list[dict], max_clips: int = 8, model: str = MODEL) -> list[dict]:
    user_prompt = build_user_prompt(segments, max_clips)

    print(f"[select_clips] Asking local model '{model}' (via Ollama) to pick up to {max_clips} clips...")
    raw_text = call_ollama(user_prompt, SYSTEM_PROMPT, model=model).strip()

    # Defensive parsing in case the model wraps in fences despite instructions
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    # Some local models occasionally wrap the array in an object like
    # {"clips": [...]}. Handle both shapes.
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Could not parse model response as JSON: {e}\n\nRaw response:\n{raw_text}"
        )

    if isinstance(parsed, dict):
        # try to find the first list value in the dict
        clips = next((v for v in parsed.values() if isinstance(v, list)), [])
    else:
        clips = parsed

    # Basic validation / sanitation
    valid_clips = []
    for c in clips:
        try:
            start, end = float(c["start"]), float(c["end"])
            duration = end - start
            if duration <= 0:
                continue
            if duration < MIN_CLIP_SECONDS or duration > MAX_CLIP_SECONDS:
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

    print(f"[select_clips] Got {len(valid_clips)} valid clip(s) from the local model.")
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
    parser.add_argument("--model", default=MODEL, help="Ollama model tag to use")
    args = parser.parse_args()

    segments = load_transcript(args.transcript_path)
    clips = select_clips(segments, max_clips=args.max_clips, model=args.model)
    video_stem = Path(args.transcript_path).stem
    save_plan(video_stem, clips)
