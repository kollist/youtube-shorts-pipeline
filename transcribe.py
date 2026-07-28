"""
transcribe.py
Transcribes a long video into a timestamped transcript using faster-whisper.

Usage:
    python transcribe.py input/myvideo.mp4

Output:
    transcripts/myvideo.json   -> list of {start, end, text} segments
"""

import sys
import json
import time
from pathlib import Path

from faster_whisper import WhisperModel

from run_control import check_cancelled

# "small" is a good speed/accuracy tradeoff for clip-selection purposes.
# Bump to "medium" or "large-v3" if your CPU/GPU can handle it and you want
# cleaner captions. On CPU-only machines, "small" or "base" is far more
# realistic for a daily pipeline.
MODEL_SIZE = "small"


def transcribe(video_path: str, model_size: str = MODEL_SIZE, cancel_event=None) -> list[dict]:
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    print(f"[transcribe] Loading Whisper model '{model_size}'...")
    # device="auto" will use GPU if available (much faster), else falls back to CPU
    model = WhisperModel(model_size, device="auto", compute_type="auto")

    print(f"[transcribe] Transcribing {video_path.name} ... (this can take a while)")
    t0 = time.time()
    # word_timestamps=True costs a bit more compute but is what makes the
    # word-by-word karaoke-style burned-in captions in cut_clips.py possible -
    # without per-word timing captions can only be shown a full sentence at a time.
    segments, info = model.transcribe(str(video_path), word_timestamps=True)

    results = []
    for seg in segments:
        check_cancelled(cancel_event)
        results.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [
                {"start": round(w.start, 3), "end": round(w.end, 3), "text": w.word.strip()}
                for w in (seg.words or [])
            ],
        })

    print(f"[transcribe] Done in {time.time() - t0:.1f}s. "
          f"Detected language: {info.language} "
          f"({len(results)} segments)")
    return results


def save_transcript(video_path: str, segments: list[dict], out_dir: str = "transcripts") -> str:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    out_path = out_dir / f"{stem}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"[transcribe] Saved transcript -> {out_path}")
    return str(out_path)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe.py <video_path> [model_size]")
        sys.exit(1)

    video_path = sys.argv[1]
    model_size = sys.argv[2] if len(sys.argv) > 2 else MODEL_SIZE

    segments = transcribe(video_path, model_size)
    save_transcript(video_path, segments)
