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

import json
import random
import re
import subprocess
import sys
from pathlib import Path

from run_control import check_cancelled

# User-supplied gameplay/filler footage for the split-screen layout (see
# make_split_screen_variant) - drop a few loopable, rights-you-own clips in
# here (e.g. your own Minecraft parkour recordings). Never auto-sourced from
# the internet, since "rights-safe filler footage" isn't something that can
# be scraped - it has to actually be yours.
FILLER_DIR = Path("filler")
FILLER_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


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


# Subtitle force_style MUST set PlayResX/PlayResY to the real output frame
# size. libass scales MarginV against its default script resolution (288px
# tall) when PlayRes isn't set, so a "MarginV=120" meant as pixels near the
# bottom of a 1920-tall frame actually lands ~6.7x higher up - this is what
# was pushing captions into the middle of the video.
SUBTITLE_STYLE = (
    "FontName=Arial,FontSize=64,Bold=1,PrimaryColour=&HFFFFFF&,"
    "OutlineColour=&H000000&,BorderStyle=3,Outline=3,Alignment=2,"
    "MarginV=170,PlayResX=1080,PlayResY=1920"
)

# Same idea as SUBTITLE_STYLE but scaled for a half-height (1080x960) frame -
# PlayResY must match the actual frame the subtitles filter is applied to,
# same reasoning as the note above, just at half the vertical resolution.
SPLIT_SUBTITLE_STYLE = (
    "FontName=Arial,FontSize=52,Bold=1,PrimaryColour=&HFFFFFF&,"
    "OutlineColour=&H000000&,BorderStyle=3,Outline=3,Alignment=2,"
    "MarginV=60,PlayResX=1080,PlayResY=960"
)


def find_filler_clips() -> list[Path]:
    if not FILLER_DIR.exists():
        return []
    return sorted(p for p in FILLER_DIR.glob("*") if p.suffix.lower() in FILLER_EXTENSIONS)


def pick_filler_clip() -> Path:
    clips = find_filler_clips()
    if not clips:
        raise RuntimeError(
            f"No filler footage found in {FILLER_DIR}/ - drop a few of your own "
            f"loopable gameplay clips there first (.mp4/.mov/.mkv/.webm)."
        )
    return random.choice(clips)


def _ffprobe_duration(path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise RuntimeError(f"Could not read duration of filler clip {path}: {result.stderr[-500:]}")


def cut_clip(
    source_video,
    start: float,
    end: float,
    out_path,
    srt_path=None,
    vertical: bool = True,
    filler_video=None,
):
    duration = end - start
    source = Path(source_video)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(source),
        "-t", str(duration),
    ]

    if filler_video is not None:
        # Minecraft-parkour-style split screen: the real content + captions on
        # top, looping gameplay footage on the bottom (silent, a random start
        # point each time so repeated clips don't all show the identical
        # stretch). A separate layout option, not a replacement for `vertical` -
        # see make_split_screen_variant, which builds one of these from an
        # already-cut clip so it can be split-tested against the normal
        # format instead of committing the whole channel to it.
        filler_duration = _ffprobe_duration(filler_video)
        filler_offset = random.uniform(0, filler_duration - duration) if filler_duration > duration else 0.0
        cmd += [
            "-stream_loop", "-1",
            "-ss", f"{filler_offset:.2f}",
            "-i", str(filler_video),
            "-t", str(duration),
        ]

        chain = (
            "[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[content_raw];"
            "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[filler]"
        )
        last_label = "content_raw"
        if srt_path:
            chain += f";[content_raw]subtitles='{srt_path}':force_style='{SPLIT_SUBTITLE_STYLE}'[content]"
            last_label = "content"
        chain += f";[{last_label}][filler]vstack=inputs=2[stacked]"
        # Only ever the content track's audio - the filler footage is muted.
        cmd += ["-filter_complex", chain, "-map", "[stacked]", "-map", "0:a?"]
    elif vertical:
        # Center crop alone zoomed in and lost the edges of wide shots (the
        # user's "not showing everything" complaint). Instead: fill the full
        # 1080x1920 canvas with a blurred, cropped copy of the frame as a
        # backdrop, then overlay the whole original frame scaled to fit
        # without cropping on top, so no content is lost.
        chain = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=20:2[bg];"
            "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[stacked]"
        )
        last_label = "stacked"
        if srt_path:
            chain += f";[stacked]subtitles='{srt_path}':force_style='{SUBTITLE_STYLE}'[capped]"
            last_label = "capped"
        cmd += ["-filter_complex", chain, "-map", f"[{last_label}]", "-map", "0:a?"]
    elif srt_path:
        cmd += ["-vf", f"subtitles='{srt_path}':force_style='{SUBTITLE_STYLE}'"]

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
    on_clip=None,
    cancel_event=None,
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
        check_cancelled(cancel_event)
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
            "hook_mechanic": clip.get("hook_mechanic", "unknown"),
            "format": "normal",
        }
        meta_path = out_dir / f"{clip_id}.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        produced.append(meta)
        if on_clip:
            on_clip(meta)

    print(f"[cut_clips] Produced {len(produced)} clip(s) in {out_dir}/")
    return produced


def _source_stem_from_clip_id(clip_id: str) -> str:
    return re.sub(r"_clip\d+$", "", clip_id)


def make_split_screen_variant(
    meta_path,
    input_dir: str = "input",
    transcripts_dir: str = "transcripts",
    out_dir: str = "output",
    filler_path=None,
) -> dict:
    """Re-cuts an already-produced clip with the split-screen layout (the
    real content + captions on top, looping gameplay footage on the bottom)
    instead of the normal blurred-backdrop one - a separate variant sitting
    alongside the original, not a replacement, so it can be uploaded and
    compared against the normal format via the Analytics tab rather than
    committing the whole channel to the new look on a guess. Pass filler_path
    to pick a specific clip from filler/ (e.g. from the UI's picker); leave
    it None to pick one at random - either way, the start point within that
    clip is always random, so repeated variants don't all show the same
    stretch of footage."""
    meta_path = Path(meta_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    clip_id = meta_path.stem
    stem = _source_stem_from_clip_id(clip_id)

    source_video = next(
        (p for ext in (".mp4", ".mov", ".mkv", ".webm")
         if (p := Path(input_dir) / f"{stem}{ext}").exists()),
        None,
    )
    if source_video is None:
        raise FileNotFoundError(
            f"Could not find the original source video for this clip (expected "
            f"{input_dir}/{stem}.*) - it may have been moved or deleted since this clip was cut."
        )

    if filler_path is not None:
        filler_video = Path(filler_path)
        if not filler_video.exists():
            raise FileNotFoundError(f"Filler clip not found: {filler_video}")
    else:
        filler_video = pick_filler_clip()

    out_dir = Path(out_dir)
    transcript_path = Path(transcripts_dir) / f"{stem}.json"
    srt_path = None
    if transcript_path.exists():
        with open(transcript_path, "r", encoding="utf-8") as f:
            segments = json.load(f)
        srt_text = build_srt_for_clip(segments, meta["start"], meta["end"])
        if srt_text.strip():
            srt_path = out_dir / f"{clip_id}_split.srt"
            srt_path.write_text(srt_text, encoding="utf-8")

    out_video = out_dir / f"{clip_id}_split.mp4"
    cut_clip(
        source_video,
        meta["start"],
        meta["end"],
        out_video,
        srt_path=str(srt_path) if srt_path else None,
        filler_video=str(filler_video),
    )

    new_meta = {
        "video_path": str(out_video),
        "title": meta["title"],
        "description": meta["description"],
        "start": meta["start"],
        "end": meta["end"],
        "hook_mechanic": meta.get("hook_mechanic", "unknown"),
        "format": "split_screen",
        "source_clip": clip_id,
    }
    new_meta_path = out_dir / f"{clip_id}_split.json"
    with open(new_meta_path, "w", encoding="utf-8") as f:
        json.dump(new_meta, f, ensure_ascii=False, indent=2)

    print(f"[cut_clips] Made split-screen variant -> {out_video} (filler: {filler_video.name})")
    return new_meta


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python cut_clips.py <source_video> <plan_json> [transcript_json]")
        sys.exit(1)

    source_video_arg = sys.argv[1]
    plan_path_arg = sys.argv[2]
    transcript_path_arg = sys.argv[3] if len(sys.argv) > 3 else None

    process_all_clips(source_video_arg, plan_path_arg, transcript_path_arg)
