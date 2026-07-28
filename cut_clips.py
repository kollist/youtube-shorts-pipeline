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
    with timestamps re-based to start at 0 for the clip itself. Fallback path for
    transcripts saved before word-level timestamps were added - see build_karaoke_ass_for_clip."""
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


# --- Word-by-word "karaoke" captions ----------------------------------
# Groups transcript words into short on-screen chunks and emits one ASS
# Dialogue line per word within each chunk, with that word colored/scaled up
# while it's being spoken - the highlighted-word look most Shorts/TikTok
# auto-captions use, instead of a full sentence sitting on screen at once.

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,3,3,0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# Opaque yellow in ASS's &HAABBGGRR order - the highlighted word's color.
HIGHLIGHT_COLOR = "&H0000FFFF&"


def _format_ass_timestamp(seconds: float) -> str:
    centis = int(round(max(seconds, 0.0) * 100))
    h, remainder = divmod(centis, 360_000)
    m, remainder = divmod(remainder, 6_000)
    s, cs = divmod(remainder, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _sanitize_word(text: str) -> str:
    # Strip characters that would be parsed as ASS override tags if they
    # ended up in caption text verbatim.
    return text.replace("{", "").replace("}", "").strip()


def _group_words_into_chunks(
    words: list[dict], max_words: int = 4, max_gap: float = 0.6, max_chunk_duration: float = 2.2
) -> list[list[dict]]:
    chunks = []
    current = []
    for w in words:
        if current:
            gap = w["start"] - current[-1]["end"]
            duration = w["end"] - current[0]["start"]
            if gap > max_gap or len(current) >= max_words or duration > max_chunk_duration:
                chunks.append(current)
                current = []
        current.append(w)
    if current:
        chunks.append(current)
    return chunks


def _karaoke_dialogue_lines(words: list[dict]) -> list[str]:
    lines = []
    for chunk in _group_words_into_chunks(words):
        texts = [_sanitize_word(w["text"]) for w in chunk]
        if not any(texts):
            continue
        for i in range(len(chunk)):
            start = chunk[i]["start"]
            end = chunk[i + 1]["start"] if i + 1 < len(chunk) else chunk[i]["end"]
            end = max(end, start + 0.05)
            parts = []
            for j, word_text in enumerate(texts):
                if not word_text:
                    continue
                if j == i:
                    parts.append(f"{{\\c{HIGHLIGHT_COLOR}\\fscx112\\fscy112}}{word_text}{{\\r}}")
                else:
                    parts.append(word_text)
            lines.append(
                f"Dialogue: 0,{_format_ass_timestamp(start)},{_format_ass_timestamp(end)},"
                f"Default,,0,0,0,,{' '.join(parts)}"
            )
    return lines


def build_karaoke_ass(words: list[dict], width: int, height: int, font_size: int, margin_v: int) -> str:
    header = ASS_HEADER.format(width=width, height=height, font_size=font_size, margin_v=margin_v)
    return header + "\n".join(_karaoke_dialogue_lines(words)) + "\n"


def build_karaoke_ass_for_clip(
    segments: list[dict], clip_start: float, clip_end: float, width: int, height: int, font_size: int, margin_v: int
) -> str | None:
    words = []
    for seg in segments:
        for w in seg.get("words") or []:
            if w["end"] <= clip_start or w["start"] >= clip_end:
                continue
            words.append({
                "start": max(w["start"], clip_start) - clip_start,
                "end": min(w["end"], clip_end) - clip_start,
                "text": w["text"],
            })
    if not words:
        return None
    return build_karaoke_ass(words, width, height, font_size, margin_v)


def build_subtitle_file(
    segments: list[dict], clip_start: float, clip_end: float, base_path: Path,
    width: int, height: int, font_size: int, margin_v: int,
) -> Path | None:
    """Picks word-level karaoke captions (.ass) when the transcript has
    per-word timing, falling back to plain sentence-level captions (.srt)
    for transcripts saved before that was added."""
    has_words = any(seg.get("words") for seg in segments)
    if has_words:
        ass_text = build_karaoke_ass_for_clip(segments, clip_start, clip_end, width, height, font_size, margin_v)
        if not ass_text:
            return None
        path = base_path.with_suffix(".ass")
        path.write_text(ass_text, encoding="utf-8")
        return path

    srt_text = build_srt_for_clip(segments, clip_start, clip_end)
    if not srt_text.strip():
        return None
    path = base_path.with_suffix(".srt")
    path.write_text(srt_text, encoding="utf-8")
    return path


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


def _ffprobe_resolution(path) -> tuple[int, int]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        width_str, height_str = result.stdout.strip().split("x")
        return int(width_str), int(height_str)
    except ValueError:
        raise RuntimeError(f"Could not read resolution of {path}: {result.stderr[-500:]}")


def _subtitles_filter(subtitle_path: str, split: bool) -> str:
    # A .ass file carries its own [V4+ Styles] section (incl. the per-word
    # karaoke color/scale overrides), so force_style isn't needed - and would
    # only add a redundant baseline style. The .srt fallback has no styling
    # of its own, so force_style is what gives it a font/size/position at all.
    if Path(subtitle_path).suffix.lower() == ".ass":
        return f"subtitles='{subtitle_path}'"
    style = SPLIT_SUBTITLE_STYLE if split else SUBTITLE_STYLE
    return f"subtitles='{subtitle_path}':force_style='{style}'"


def cut_clip(
    source_video,
    start: float,
    end: float,
    out_path,
    subtitle_path=None,
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
        if subtitle_path:
            chain += f";[content_raw]{_subtitles_filter(subtitle_path, split=True)}[content]"
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
        if subtitle_path:
            chain += f";[stacked]{_subtitles_filter(subtitle_path, split=False)}[capped]"
            last_label = "capped"
        cmd += ["-filter_complex", chain, "-map", f"[{last_label}]", "-map", "0:a?"]
    elif subtitle_path:
        cmd += ["-vf", _subtitles_filter(subtitle_path, split=False)]

    cmd += [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        str(out_path),
    ]

    print(f"[cut_clips] Cutting {start:.1f}s-{end:.1f}s -> {out_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {out_path}:\n{result.stderr[-2000:]}")


# --- Voiceover intro ---------------------------------------------------
# Prepends a short AI-narrated hook line to an already-cut clip: a frozen
# first frame + synthesized voiceover audio + its own karaoke captions,
# concatenated in front of the clip's own (untouched) video+audio. See
# voiceover.py for how the narration text and speech are generated.

VOICEOVER_FONT_SIZE = 64
VOICEOVER_MARGIN_V = 170


def add_voiceover_intro(clip_path, audio_path, words: list[dict]) -> None:
    clip_path = Path(clip_path)
    width, height = _ffprobe_resolution(clip_path)
    audio_duration = _ffprobe_duration(audio_path)

    tmp_frame = clip_path.with_suffix(".vo_frame.png")
    tmp_ass = clip_path.with_suffix(".vo_intro.ass")
    tmp_intro = clip_path.with_suffix(".vo_intro.mp4")
    tmp_final = clip_path.with_suffix(".vo_final.mp4")

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(clip_path), "-vframes", "1", str(tmp_frame)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed extracting a frame for the voiceover intro:\n{result.stderr[-2000:]}")

        ass_text = build_karaoke_ass(words, width, height, VOICEOVER_FONT_SIZE, VOICEOVER_MARGIN_V)
        tmp_ass.write_text(ass_text, encoding="utf-8")

        intro_cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(tmp_frame),
            "-i", str(audio_path),
            "-t", f"{audio_duration:.2f}",
            "-vf", f"scale={width}:{height},subtitles='{tmp_ass}'",
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            str(tmp_intro),
        ]
        result = subprocess.run(intro_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed building the voiceover intro:\n{result.stderr[-2000:]}")

        concat_cmd = [
            "ffmpeg", "-y",
            "-i", str(tmp_intro), "-i", str(clip_path),
            "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            str(tmp_final),
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed prepending the voiceover intro:\n{result.stderr[-2000:]}")

        tmp_final.replace(clip_path)
    finally:
        for tmp in (tmp_frame, tmp_ass, tmp_intro, tmp_final):
            tmp.unlink(missing_ok=True)


def process_all_clips(
    source_video,
    plan_path,
    transcript_path=None,
    out_dir="output",
    burn_captions: bool = True,
    add_voiceover: bool = False,
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
    if (burn_captions or add_voiceover) and transcript_path:
        with open(transcript_path, "r", encoding="utf-8") as f:
            segments = json.load(f)

    produced = []
    for i, clip in enumerate(clips, start=1):
        check_cancelled(cancel_event)
        clip_id = f"{stem}_clip{i:02d}"
        out_video = out_dir / f"{clip_id}.mp4"
        subtitle_path = None

        if burn_captions and segments is not None:
            subtitle_path = build_subtitle_file(
                segments, clip["start"], clip["end"], out_dir / clip_id,
                width=1080, height=1920, font_size=64, margin_v=170,
            )

        cut_clip(
            source_video,
            clip["start"],
            clip["end"],
            out_video,
            subtitle_path=str(subtitle_path) if subtitle_path else None,
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

        if add_voiceover:
            try:
                from voiceover import generate_voiceover_for_clip

                clip_text = ""
                if segments is not None:
                    clip_text = " ".join(
                        seg["text"] for seg in segments
                        if seg["end"] > clip["start"] and seg["start"] < clip["end"]
                    )
                vo = generate_voiceover_for_clip(clip, clip_text, str(out_dir), clip_id)
                add_voiceover_intro(out_video, vo["audio_path"], vo["words"])
                meta["voiceover_text"] = vo["text"]
            except Exception as e:
                print(f"[cut_clips] Voiceover failed for {clip_id}, keeping clip without it: {e}")

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
    subtitle_path = None
    if transcript_path.exists():
        with open(transcript_path, "r", encoding="utf-8") as f:
            segments = json.load(f)
        subtitle_path = build_subtitle_file(
            segments, meta["start"], meta["end"], out_dir / f"{clip_id}_split",
            width=1080, height=960, font_size=52, margin_v=60,
        )

    out_video = out_dir / f"{clip_id}_split.mp4"
    cut_clip(
        source_video,
        meta["start"],
        meta["end"],
        out_video,
        subtitle_path=str(subtitle_path) if subtitle_path else None,
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
