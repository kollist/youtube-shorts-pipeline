"""
cut_clips.py
Takes a source video + a clip plan (from select_clips.py) and produces
vertical 9:16 .mp4 Shorts with burned-in captions.

Usage:
    python cut_clips.py input/myvideo.mp4 clips/myvideo_plan.json

Output:
    output/myvideo_clip01.mp4
    output/myvideo_clip01.json   <- metadata (title/description) for upload step
    ... etc
"""

import sys
import json
import subprocess
from pathlib import Path


def format_srt_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h, remainder = divmod(millis, 3600_000)
    m, remainder = divmod(remainder, 60_000)
    s, ms = divmod(remainder, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt_for_clip(segments: list[dict], clip_start: float, clip_end: float) -> str:
    """Build an SRT subtitle string for the portion of the transcript inside this clip,
    with timestamps re-based to start at 0 for the clip itself."""
    lines = []
    idx = 1
    for seg in segments:
        if seg["end"] <= clip_start or seg["start"] >= clip_end:
            continue
        rel_start = max(seg["start"], clip_start) - clip_start
        rel_end = min(seg["end"], clip_end) - clip_start
        if rel_end <= rel_start:
            continue
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(rel_start)} --> {format_srt_timestamp(rel_end)}")
        lines.append(seg["text"].strip())
        lines.append("")
        idx += 1
    return "\n".join(lines)


def cut_clip(
    source_video,
    start: float,
    end: float,
    out_path,
    srt_path=None,
    vertical: bool = True,
):
    duration = end - start
    source = Path(source_video)

    # Build the video filter chain:
    # 1. Crop/scale to 9:16 vertical (center crop, then scale to 1080x1920)
    # 2. Burn in subtitles if provided
    filters = []
    if vertical:
        filters.append("scale=-2:1920,crop=1080:1920")
    if srt_path:
        filters.append(
            f"subtitles='{srt_path}':force_style="
            "'FontName=Arial,FontSize=14,PrimaryColour=&HFFFFFF&,"
            "OutlineColour=&H000000&,BorderStyle=3,Outline=2,Alignment=2,MarginV=120'"
        )

    vf = ",".join(filters) if filters else None

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(source),
        "-t", str(duration),
    ]
    if vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]

    print(f"[cut_clips] Cutting {start:.1f}s-{end:.1f}s -> {out_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {out_path}:\n{result.stderr[-2000:]}")


def process_all_clips(
    source_video,
    plan_path,
    transcript_path=None,
    out_dir="output",
    burn_captions: bool = True,
):
    source_video = Path(source_video)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source_video.stem

    with open(plan_path, "r", encoding="utf-8") as f:
        clips = json.load(f)

    segments = None
    if burn_captions and transcript_path:
        with open(transcript_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

    produced = []
    for i, clip in enumerate(clips, start=1):
        clip_id = f"{stem}_clip{i:02d}"
        out_video = out_dir / f"{clip_id}.mp4"
        srt_path = None

        if segments is not None:
            srt_text = build_srt_for_clip(segments, clip["start"], clip["end"])
            if srt_text.strip():
                srt_path = out_dir / f"{clip_id}.srt"
                srt_path.write_text(srt_text, encoding="utf-8")

        cut_clip(
            source_video,
            clip["start"],
            clip["end"],
            out_video,
            srt_path=str(srt_path) if srt_path else None,
        )

        meta = {
            "video_path": str(out_video),
            "title": clip["title"],
            "description": clip["description"],
            "start": clip["start"],
            "end": clip["end"],
        }
        meta_path = out_dir / f"{clip_id}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        produced.append(meta)

    print(f"[cut_clips] Produced {len(produced)} clip(s) in {out_dir}/")
    return produced


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python cut_clips.py <source_video> <plan_json> [transcript_json]")
        sys.exit(1)

    source_video_arg = sys.argv[1]
    plan_path_arg = sys.argv[2]
    transcript_path_arg = sys.argv[3] if len(sys.argv) > 3 else None

    process_all_clips(source_video_arg, plan_path_arg, transcript_path_arg)
