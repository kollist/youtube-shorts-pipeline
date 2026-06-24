"""
queue_daily.py
Runs the pipeline across every video in input/ to hit a daily target clip
count, spreading the requested number of clips across however many source
videos you've dropped in, then uploads everything spaced out over the day
(so YouTube doesn't see 20 uploads land in the same 10 minutes).

Usage:
    # Process everything in input/, aim for ~20 total clips today, don't upload yet
    python queue_daily.py --target 20

    # Same, but also upload, spaced 30 min apart across the day
    python queue_daily.py --target 20 --upload --spacing-minutes 30

This intentionally does NOT try to force exactly 20 good clips out of weak
source material — see run_pipeline()'s max_clips as a per-video cap, and
Claude will return fewer if a video doesn't support that many strong clips.
Add more source videos to input/ on days you want higher output.
"""

import argparse
import time
from pathlib import Path

from pipeline import run_pipeline
from upload_youtube import upload_from_meta_file

INPUT_DIR = Path("input")
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


def find_source_videos():
    return sorted(
        p for p in INPUT_DIR.glob("*")
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=20, help="Total clips to aim for today")
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--spacing-minutes", type=float, default=20.0,
                         help="Minutes to wait between uploads when --upload is set")
    args = parser.parse_args()

    videos = find_source_videos()
    if not videos:
        print(f"[queue] No videos found in {INPUT_DIR}/. Drop .mp4/.mov/.mkv/.webm files there first.")
        return

    per_video_cap = max(1, args.target // len(videos))
    print(f"[queue] Found {len(videos)} source video(s). "
          f"Targeting ~{per_video_cap} clips per video (target={args.target}).")

    all_produced = []
    for video in videos:
        print(f"\n[queue] === Processing {video.name} ===")
        produced = run_pipeline(
            str(video),
            max_clips=per_video_cap,
            whisper_model=args.whisper_model,
            do_upload=False,  # we control upload pacing separately below
        )
        all_produced.extend(produced)

    print(f"\n[queue] Total clips produced today: {len(all_produced)}")

    if args.upload:
        print(f"[queue] Uploading {len(all_produced)} clip(s), "
              f"spaced {args.spacing_minutes} min apart...")
        for i, meta in enumerate(all_produced):
            meta_json_path = Path(meta["video_path"]).with_suffix(".json")
            try:
                upload_from_meta_file(str(meta_json_path), privacy_status=args.privacy)
            except Exception as e:
                print(f"[queue] Upload failed for {meta_json_path}: {e}")

            if i < len(all_produced) - 1:
                print(f"[queue] Sleeping {args.spacing_minutes} min before next upload...")
                time.sleep(args.spacing_minutes * 60)
    else:
        print("[queue] Clips ready in output/. Review them, then run:\n"
              "  python pipeline.py --upload-only")


if __name__ == "__main__":
    main()
