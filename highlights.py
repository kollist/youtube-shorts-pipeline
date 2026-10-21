"""
highlights.py
Finds the high-energy moments in a long livestream VOD from its audio alone,
so only those few windows need transcribing and judging by the model instead
of the whole 4-10 hour recording.

Streamer highlights are reactions: screaming, laughing, rage quits. They often
have almost no words ("NO NO NO", "BRO"), so a transcript-only picker misses
them. A loud spike relative to the streamer's own recent baseline is a much
better first-pass signal.

Usage (standalone, prints the windows it would send to the model):
    python highlights.py input/stream.mp4 --max-windows 20
"""

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from run_control import check_cancelled

SAMPLE_RATE = 16000
HOP_SECONDS = 0.5          # loudness is measured once per hop
BASELINE_SECONDS = 90      # rolling-median window that defines "normal" volume
SMOOTH_SECONDS = 3         # a spike must be sustained this long, not a single click
MIN_EXCESS_DB = 5.0        # peaks quieter than baseline + this are not highlights
SILENCE_FLOOR_DB = -70.0   # digital silence/intermissions must not look like a baseline to beat

# Roughly the voice band. Game music, explosions, and bass-heavy sound effects
# sit mostly outside it, so a loud boss fight doesn't outrank an actual scream.
VOICE_FILTER = "highpass=f=300,lowpass=f=3400"

DEFAULT_LEAD_SECONDS = 35  # context before the peak; the setup of the moment
DEFAULT_TAIL_SECONDS = 25  # aftermath after the peak


def _probe_duration(video_path: str) -> float | None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", video_path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def loudness_series(video_path: str, cancel_event=None) -> np.ndarray:
    """Voice-band loudness in dB, one value per HOP_SECONDS, decoded by ffmpeg
    and measured in one-minute blocks so a multi-hour VOD never has to fit in
    memory as raw audio."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", video_path, "-vn", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-af", VOICE_FILTER, "-f", "s16le", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    hop_samples = int(SAMPLE_RATE * HOP_SECONDS)
    block_bytes = hop_samples * 2 * 120  # 60s of int16 audio
    levels: list[np.ndarray] = []
    leftover = b""
    try:
        while True:
            check_cancelled(cancel_event)
            data = proc.stdout.read(block_bytes)
            if not data:
                break
            data = leftover + data
            usable = (len(data) // (hop_samples * 2)) * hop_samples * 2
            leftover = data[usable:]
            if not usable:
                continue
            samples = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768.0
            frames = samples.reshape(-1, hop_samples)
            rms = np.sqrt(np.mean(frames ** 2, axis=1))
            levels.append(20 * np.log10(rms + 1e-7))
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.stdout.close()
        proc.wait()

    if not levels:
        raise RuntimeError(f"ffmpeg produced no audio from {video_path} - does it have an audio track?")
    return np.maximum(np.concatenate(levels), SILENCE_FLOOR_DB)


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    window = max(3, window | 1)  # odd, so the window is centered on each point
    padded = np.pad(values, window // 2, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, window), axis=1)


def find_peaks(levels: np.ndarray, max_peaks: int, min_gap_seconds: float) -> list[dict]:
    """Loudest sustained moments relative to the local baseline, strongest first,
    at least min_gap_seconds apart. Fewer than max_peaks come back if nothing
    else clears MIN_EXCESS_DB - a quiet stream shouldn't be padded with noise."""
    baseline = _rolling_median(levels, int(BASELINE_SECONDS / HOP_SECONDS))
    excess = np.maximum(levels - baseline, 0.0)

    smooth_n = max(1, int(SMOOTH_SECONDS / HOP_SECONDS))
    score = np.convolve(excess, np.ones(smooth_n) / smooth_n, mode="same")

    gap = int(min_gap_seconds / HOP_SECONDS)
    work = score.copy()
    peaks = []
    while len(peaks) < max_peaks:
        i = int(np.argmax(work))
        if work[i] < MIN_EXCESS_DB:
            break
        peaks.append({"time": round(i * HOP_SECONDS, 1), "score": round(float(work[i]), 2)})
        work[max(0, i - gap):i + gap + 1] = 0.0
    return peaks


def find_candidate_windows(
    video_path: str,
    max_windows: int = 20,
    lead: float = DEFAULT_LEAD_SECONDS,
    tail: float = DEFAULT_TAIL_SECONDS,
    cancel_event=None,
) -> list[dict]:
    """Time-ordered windows [start, end] around each loudness peak, each carrying
    the peak time and its score. Peaks are kept lead+tail apart so windows
    never overlap."""
    print(f"[highlights] Measuring voice-band loudness of {Path(video_path).name} ...")
    levels = loudness_series(video_path, cancel_event)
    duration = len(levels) * HOP_SECONDS
    print(f"[highlights] {duration / 60:.0f} min of audio analysed.")

    peaks = find_peaks(levels, max_windows, min_gap_seconds=lead + tail)
    windows = [
        {
            "start": round(max(0.0, p["time"] - lead), 1),
            "end": round(min(duration, p["time"] + tail), 1),
            "peak": p["time"],
            "score": p["score"],
        }
        for p in peaks
    ]
    windows.sort(key=lambda w: w["start"])
    print(f"[highlights] Found {len(windows)} high-energy window(s)"
          + (f" (strongest +{max(w['score'] for w in windows):.1f} dB over baseline)" if windows else "."))
    return windows


def build_stream_transcript(
    video_path: str,
    max_windows: int,
    whisper_model: str = "small",
    lead: float = DEFAULT_LEAD_SECONDS,
    tail: float = DEFAULT_TAIL_SECONDS,
    transcripts_dir: str = "transcripts",
    cancel_event=None,
) -> str:
    """Detect high-energy windows and transcribe ONLY those, saving them as a
    normal transcript (absolute timestamps in the full video) so the rest of
    the pipeline, captions included, works unchanged. A .windows.json sidecar
    records that this transcript is partial, so a later normal-mode run knows to
    transcribe the whole video instead of trusting it, and lets a repeat stream
    run with the same settings skip all of this work."""
    from transcribe import transcribe_windows, save_transcript  # heavy import, only needed here

    stem = Path(video_path).stem
    out_dir = Path(transcripts_dir)
    transcript_path = out_dir / f"{stem}.json"
    sidecar_path = out_dir / f"{stem}.windows.json"
    params = {"max_windows": max_windows, "lead": lead, "tail": tail, "whisper_model": whisper_model}

    if transcript_path.exists() and sidecar_path.exists():
        with open(sidecar_path, "r", encoding="utf-8") as f:
            if json.load(f).get("params") == params:
                print(f"[highlights] Found existing stream transcript with the same settings, "
                      f"skipping: {transcript_path}")
                return str(transcript_path)

    windows = find_candidate_windows(video_path, max_windows, lead, tail, cancel_event)
    check_cancelled(cancel_event)
    segments = transcribe_windows(video_path, windows, whisper_model, cancel_event)

    out_dir.mkdir(parents=True, exist_ok=True)
    save_transcript(video_path, segments, str(out_dir))
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump({"params": params, "windows": windows}, f, indent=2)
    return str(transcript_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path")
    parser.add_argument("--max-windows", type=int, default=20)
    parser.add_argument("--lead", type=float, default=DEFAULT_LEAD_SECONDS)
    parser.add_argument("--tail", type=float, default=DEFAULT_TAIL_SECONDS)
    args = parser.parse_args()

    for w in find_candidate_windows(args.video_path, args.max_windows, args.lead, args.tail):
        print(f"{w['start']:8.1f}s -> {w['end']:8.1f}s   peak {w['peak']:8.1f}s   +{w['score']:.1f} dB")
