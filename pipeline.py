"""
pipeline.py
End-to-end orchestrator: long video -> transcript -> Groq clip selection ->
ffmpeg cutting -> YouTube upload.

Usage examples:

  # Full run on one video, up to 8 clips, upload as public immediately
  python pipeline.py input/myvideo.mp4 --max-clips 8 --upload --privacy public

  # Just generate clips, review them yourself, upload later
  python pipeline.py input/myvideo.mp4 --max-clips 8

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

UPLOAD_DELAY_SECONDS = 5  # small pause between uploads, be gentle on quota/network


def run_pipeline(
    video_path: str,
    max_clips: int = 8,
    whisper_model: str = "small",
    do_upload: bool = False,
    privacy_status: str = "public",
    burn_captions: bool = True,
    min_duration: float = DEFAULT_MIN_DURATION,
    max_duration: float = DEFAULT_MAX_DURATION,
):
    video_path = Path(video_path)
    stem = video_path.stem

    transcript_json_path = Path("transcripts") / f"{stem}.json"
    if transcript_json_path.exists():
        print(f"[pipeline] Found existing transcript, skipping re-transcription: {transcript_json_path}")
    else:
        segments = transcribe(str(video_path), whisper_model)
        transcript_json_path = Path(save_transcript(str(video_path), segments))

    segments = load_transcript(str(transcript_json_path))

    clips = select_clips(
        segments,
        max_clips=max_clips,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    if not clips:
        print("[pipeline] Model did not return any confident clips. Stopping.")
        return []
    plan_path = save_plan(stem, clips)

    produced = process_all_clips(
        str(video_path),
        plan_path,
        transcript_path=str(transcript_json_path),
        burn_captions=burn_captions,
    )

    if do_upload:
        for meta in produced:
            meta_json_path = Path(meta["video_path"]).with_suffix(".json")
            try:
                upload_from_meta_file(str(meta_json_path), privacy_status=privacy_status)
            except Exception as e:
                print(f"[pipeline] Upload failed for {meta_json_path}: {e}")
            time.sleep(UPLOAD_DELAY_SECONDS)

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
    parser.add_argument("video_path", nargs="?", help="Path to the long-form source video")
    parser.add_argument("--max-clips", type=int, default=8)
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--upload", action="store_true", help="Upload clips to YouTube after cutting")
    parser.add_argument("--upload-only", action="store_true", help="Skip processing, just upload pending clips in output/")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--no-captions", action="store_true", help="Disable burned-in captions")
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
            min_duration=args.min_duration,
            max_duration=args.max_duration,
        )
