"""
voiceover.py
Generates a short AI narration line for a clip (a hook or added context, in
a faceless-channel voice) and synthesizes it to speech with word-level
timing, so cut_clips.py can burn it in as a spoken intro ahead of the
clip's own audio. This is what makes a repurposed clip "transformative"
rather than a straight repost under YouTube's reused-content monetization
policy - captions and framing help, but nothing beats added spoken content.

ONE-TIME SETUP: none - edge-tts is free and needs no API key or account.
The narration text itself goes through Groq, reusing the same GROQ_API_KEY
as select_clips.py.
"""

import asyncio
import json
from pathlib import Path

import edge_tts

from select_clips import call_groq, GroqGenerationError

DEFAULT_VOICE = "en-US-ChristopherNeural"

NARRATION_SYSTEM_PROMPT = (
    "You write a one-sentence spoken intro line for a YouTube Shorts clip. It "
    "plays as a short voiceover right before the clip's own audio starts, so it "
    "should tease or add context to the moment - never describe it flatly, and "
    "never say things like 'in this clip' or 'this video shows'. 6-14 words, "
    "casual spoken tone, no hashtags or emoji. Respond as JSON: {\"line\": \"...\"}."
)


def build_narration_prompt(title: str, description: str, clip_text: str) -> str:
    return (
        f"Clip title: {title}\n"
        f"Clip description: {description}\n"
        f"What's said in the clip: {clip_text[:600]}\n\n"
        "Write the one-sentence spoken intro."
    )


def generate_narration_line(title: str, description: str, clip_text: str) -> str:
    prompt = build_narration_prompt(title, description, clip_text)
    raw = call_groq(prompt, NARRATION_SYSTEM_PROMPT)
    try:
        line = json.loads(raw)["line"].strip()
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as e:
        raise GroqGenerationError(f"Narration model returned unexpected output: {raw[:300]}") from e
    if not line:
        raise GroqGenerationError("Narration model returned an empty line.")
    return line


async def _synthesize(text: str, out_path: Path, voice: str) -> list[dict]:
    words = []
    communicate = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    with open(out_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration are in 100-nanosecond units.
                words.append({
                    "start": chunk["offset"] / 10_000_000,
                    "end": (chunk["offset"] + chunk["duration"]) / 10_000_000,
                    "text": chunk["text"],
                })
    return words


def synthesize_voiceover(text: str, out_path: str, voice: str = DEFAULT_VOICE) -> list[dict]:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    words = asyncio.run(_synthesize(text, out_path, voice))
    if not words:
        raise RuntimeError("edge-tts returned no speech/timing data - check your internet connection.")
    return words


def generate_voiceover_for_clip(
    clip: dict, clip_text: str, out_dir: str, clip_id: str, voice: str = DEFAULT_VOICE
) -> dict:
    """Writes {clip_id}_vo.mp3 in out_dir and returns
    {"audio_path", "words", "text"} for cut_clips.add_voiceover_intro."""
    line = generate_narration_line(clip.get("title", ""), clip.get("description", ""), clip_text)
    audio_path = Path(out_dir) / f"{clip_id}_vo.mp3"
    words = synthesize_voiceover(line, str(audio_path), voice)
    return {"audio_path": str(audio_path), "words": words, "text": line}
