"""
pipeline.py
End-to-end orchestrator: long video -> transcript -> Groq clip selection ->
ffmpeg cutting -> YouTube upload.

Usage examples:

  # Pass a YouTube URL directly — video is downloaded automatically
  python pipeline.py https://www.youtube.com/watch?v=XXXX --max-clips 8 --upload

  # Or a local file as before
  python pipeline.py input/myvideo.mp4 --max-clips 8 --upload --privacy public

  # Just generate clips, review them yourself, upload later
  python pipeline.py https://www.youtube.com/watch?v=XXXX --max-clips 8

  # Upload everything already sitting in output/ that hasn't been uploaded yet
  python pipeline.py --upload-only

Hitting "20 shorts/day":
  Realistically, one long video rarely yields 20 *good* standalone clips.
  The intended pattern is to run this script across multiple source videos
  per day (e.g. 3-4 long videos x 5-6 clips each) and let --max-clips cap
  the per-video count so quality doesn't collapse. See queue_daily.py for a
  simple multi-video daily queue runner built on top of this.
"""

import argparse
import json
import time
from pathlib import Path

from download import download_video
from highlights import build_stream_transcript
from transcribe import transcribe, save_transcript
from select_clips import (
    load_transcript,
    select_clips,
    save_plan,
    DEFAULT_MIN_DURATION,
    DEFAULT_MAX_DURATION,
)
from cut_clips import process_all_clips
from upload_youtube import upload_from_meta_file
from run_control import check_cancelled, interruptible_sleep

UPLOAD_DELAY_SECONDS = 5  # small pause between uploads, be gentle on quota/network


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def annotate_clips(clips: list[dict], stem: str, streamer: str | None, mode: str, source_info: dict) -> None:
    """Stamps each planned clip with where it came from (streamer, mode, source
    link, and how loud the detector thought its moment was) so the Analytics tab
    can group results by it later. Shared by the automatic pipeline and the
    "paste a plan from an outside model" path, so both are tracked the same way."""
    windows = (_read_json(Path("transcripts") / f"{stem}.windows.json") or {}).get("windows", [])
    for c in clips:
        c["source"] = stem
        c["streamer"] = streamer
        c["mode"] = mode
        c["source_url"] = source_info.get("url")
        window = next((w for w in windows if w["start"] <= c["start"] <= w["end"]), None)
        if window:
            c["peak_score"] = window["score"]


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "www."))


def run_pipeline(
    video_path: str,
    max_clips: int = 8,
    whisper_model: str = "small",
    do_upload: bool = False,
    privacy_status: str = "public",
    burn_captions: bool = True,
    add_voiceover: bool = False,
    min_duration: float = DEFAULT_MIN_DURATION,
    max_duration: float = DEFAULT_MAX_DURATION,
    on_clip=None,
    cancel_event=None,
    mode: str = "talk",
    streamer: str | None = None,
    max_windows: int | None = None,
):
    """mode="stream" is for hours-long livestream VODs: instead of transcribing
    everything, find the loud/animated moments from the audio and only
    transcribe and judge those (see highlights.py)."""
    if _is_url(video_path):
        check_cancelled(cancel_event)
        print(f"[pipeline] Downloading video from URL...")
        video_path = download_video(video_path, cancel_event=cancel_event)
        print(f"[pipeline] Downloaded -> {video_path}")

    video_path = Path(video_path)
    stem = video_path.stem

    transcript_json_path = Path("transcripts") / f"{stem}.json"
    windows_sidecar = Path("transcripts") / f"{stem}.windows.json"

    if mode == "stream":
        check_cancelled(cancel_event)
        transcript_json_path = Path(build_stream_transcript(
            str(video_path),
            max_windows=max_windows or max(10, max_clips * 3),
            whisper_model=whisper_model,
            cancel_event=cancel_event,
        ))
        return _select_cut_upload(
            video_path, stem, transcript_json_path, max_clips, min_duration, max_duration,
            burn_captions, add_voiceover, do_upload, privacy_status, on_clip, cancel_event,
            mode, streamer,
        )

    # A leftover stream-mode transcript only covers the loud windows, not the
    # whole video - treating it as complete would make this run clip from a
    # handful of moments instead of the full recording.
    needs_transcription = not transcript_json_path.exists() or windows_sidecar.exists()
    # A transcript saved before word-level timestamps were added has no
    # "words" field, which forces the karaoke captions to fall back to the
    # old full-sentence style for the clip body - reusing it as-is here
    # would silently give you sentence captions on every clip cut from this
    # video no matter how many times you re-run this, since burn_captions
    # doesn't control transcription at all. Re-transcribe once to upgrade it.
    if not needs_transcription and burn_captions:
        with open(transcript_json_path, "r", encoding="utf-8") as f:
            existing_segments = json.load(f)
        if not any(seg.get("words") for seg in existing_segments):
            print(f"[pipeline] Existing transcript predates word-level timestamps "
                  f"(needed for karaoke captions) - re-transcribing: {transcript_json_path}")
            needs_transcription = True

    if needs_transcription:
        check_cancelled(cancel_event)
        segments = transcribe(str(video_path), whisper_model, cancel_event=cancel_event)
        transcript_json_path = Path(save_transcript(str(video_path), segments))
        windows_sidecar.unlink(missing_ok=True)
    else:
        print(f"[pipeline] Found existing transcript, skipping re-transcription: {transcript_json_path}")

    return _select_cut_upload(
        video_path, stem, transcript_json_path, max_clips, min_duration, max_duration,
        burn_captions, add_voiceover, do_upload, privacy_status, on_clip, cancel_event,
        mode, streamer,
    )


def _select_cut_upload(
    video_path, stem, transcript_json_path, max_clips, min_duration, max_duration,
    burn_captions, add_voiceover, do_upload, privacy_status, on_clip, cancel_event,
    mode, streamer,
):
    segments = load_transcript(str(transcript_json_path))

    source_info = _read_json(video_path.with_suffix(".source.json")) or {}
    streamer = streamer or source_info.get("uploader")

    clips = select_clips(
        segments,
        max_clips=max_clips,
        min_duration=min_duration,
        max_duration=max_duration,
        cancel_event=cancel_event,
        mode=mode,
        streamer=streamer,
    )
    if not clips:
        print("[pipeline] Model did not return any confident clips. Stopping.")
        return []

    annotate_clips(clips, stem, streamer, mode, source_info)
    plan_path = save_plan(stem, clips)

    produced = process_all_clips(
        str(video_path),
        plan_path,
        transcript_path=str(transcript_json_path),
        burn_captions=burn_captions,
        add_voiceover=add_voiceover,
        on_clip=on_clip,
        cancel_event=cancel_event,
    )

    if do_upload:
        for meta in produced:
            check_cancelled(cancel_event)
            meta_json_path = Path(meta["video_path"]).with_suffix(".json")
            try:
                upload_from_meta_file(str(meta_json_path), privacy_status=privacy_status)
            except Exception as e:
                print(f"[pipeline] Upload failed for {meta_json_path}: {e}")
            interruptible_sleep(UPLOAD_DELAY_SECONDS, cancel_event)

    print(f"[pipeline] Finished. {len(produced)} clip(s) produced"
          f"{' and uploaded' if do_upload else ' (not uploaded - use --upload)'}.")
    return produced


def upload_only(output_dir: str = "output", privacy_status: str = "public"):
    """Uploads any clip in output_dir whose meta JSON doesn't yet have a youtube_video_id."""
    out_dir = Path(output_dir)
    meta_files = sorted(out_dir.glob("*.json"))
    pending = []
    for meta_path in meta_files:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if "youtube_video_id" not in meta:
            pending.append(meta_path)

    print(f"[pipeline] {len(pending)} clip(s) pending upload.")
    for meta_path in pending:
        try:
            upload_from_meta_file(str(meta_path), privacy_status=privacy_status)
        except Exception as e:
            print(f"[pipeline] Upload failed for {meta_path}: {e}")
        time.sleep(UPLOAD_DELAY_SECONDS)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video_path", nargs="?",
                         help="YouTube URL or local path to the source video")
    parser.add_argument("--max-clips", type=int, default=8)
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--upload", action="store_true", help="Upload clips to YouTube after cutting")
    parser.add_argument("--upload-only", action="store_true", help="Skip processing, just upload pending clips in output/")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--no-captions", action="store_true", help="Disable burned-in captions")
    parser.add_argument("--voiceover", action="store_true", help="Add an AI-narrated voiceover intro to each clip")
    parser.add_argument("--mode", default="talk", choices=["talk", "stream"],
                         help="'stream' finds loud moments in a long livestream VOD from its audio "
                              "instead of transcribing the whole thing (default: talk)")
    parser.add_argument("--streamer", help="Streamer's name, used in clip titles (stream mode)")
    parser.add_argument("--max-windows", type=int,
                         help="How many loud windows to send to the model (stream mode; default: 3x --max-clips)")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION,
                         help="Target minimum clip length in seconds (default: 30)")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION,
                         help="Target maximum clip length in seconds (default: 45)")
    args = parser.parse_args()

    if args.upload_only:
        upload_only(privacy_status=args.privacy)
    else:
        if not args.video_path:
            parser.error("video_path is required unless --upload-only is set")
        run_pipeline(
            args.video_path,
            max_clips=args.max_clips,
            whisper_model=args.whisper_model,
            do_upload=args.upload,
            privacy_status=args.privacy,
            burn_captions=not args.no_captions,
            add_voiceover=args.voiceover,
            min_duration=args.min_duration,
            max_duration=args.max_duration,
            mode=args.mode,
            streamer=args.streamer,
            max_windows=args.max_windows,
        )
