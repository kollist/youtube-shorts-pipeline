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
import subprocess
import tempfile
import time
from pathlib import Path

from faster_whisper import WhisperModel

from run_control import check_cancelled

# "small" is a good speed/accuracy tradeoff for clip-selection purposes.
# Bump to "medium" or "large-v3" if your CPU/GPU can handle it and you want
# cleaner captions. On CPU-only machines, "small" or "base" is far more
# realistic for a daily pipeline.
MODEL_SIZE = "small"


def _segment_to_dict(seg, offset: float = 0.0) -> dict:
    return {
        "start": round(seg.start + offset, 2),
        "end": round(seg.end + offset, 2),
        "text": seg.text.strip(),
        "words": [
            {"start": round(w.start + offset, 3), "end": round(w.end + offset, 3), "text": w.word.strip()}
            for w in (seg.words or [])
        ],
    }


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
        results.append(_segment_to_dict(seg))

    print(f"[transcribe] Done in {time.time() - t0:.1f}s. "
          f"Detected language: {info.language} "
          f"({len(results)} segments)")
    return results


def transcribe_windows(
    video_path: str,
    windows: list[dict],
    model_size: str = MODEL_SIZE,
    cancel_event=None,
) -> list[dict]:
    """Transcribe only the given [start, end] windows of a long video (e.g. the
    loud moments found by highlights.py) instead of the whole thing. Returned
    timestamps are absolute positions in the full video, same as transcribe()."""
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")

    print(f"[transcribe] Loading Whisper model '{model_size}'...")
    model = WhisperModel(model_size, device="auto", compute_type="auto")

    results: list[dict] = []
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        for i, w in enumerate(windows, 1):
            check_cancelled(cancel_event)
            wav = Path(tmp) / f"window_{i}.wav"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", str(w["start"]), "-t", str(w["end"] - w["start"]),
                 "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                check=True,
            )
            print(f"[transcribe] Window {i}/{len(windows)} ({w['start']:.0f}s-{w['end']:.0f}s)...")
            segments, _ = model.transcribe(str(wav), word_timestamps=True)
            for seg in segments:
                check_cancelled(cancel_event)
                results.append(_segment_to_dict(seg, offset=w["start"]))

    print(f"[transcribe] Done in {time.time() - t0:.1f}s ({len(results)} segments "
          f"across {len(windows)} windows).")
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
