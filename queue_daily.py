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
the model will return fewer if a video doesn't support that many strong clips.
Add more source videos to input/ on days you want higher output.
"""

import argparse
import time
from pathlib import Path

from pipeline import run_pipeline
from upload_youtube import upload_from_meta_file, YouTubeUploadLimitExceeded
from select_clips import DEFAULT_MIN_DURATION, DEFAULT_MAX_DURATION, MODEL_FALLBACK_CHAIN
from token_budget import GroqBudgetExhausted, all_usage_today
from run_control import RunCancelled, check_cancelled, interruptible_sleep

INPUT_DIR = Path("input")
SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}


def find_source_videos():
    return sorted(
        p for p in INPUT_DIR.glob("*")
        if p.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def run_daily_queue(
    target: int = 20,
    whisper_model: str = "small",
    do_upload: bool = False,
    privacy: str = "public",
    spacing_minutes: float = 20.0,
    min_duration: float = DEFAULT_MIN_DURATION,
    max_duration: float = DEFAULT_MAX_DURATION,
    burn_captions: bool = True,
    add_voiceover: bool = False,
    on_clip=None,
    cancel_event=None,
) -> list[dict]:
    """Process every video in input/ toward a daily clip target, then
    (optionally) upload everything produced, spaced out over the day. Shared
    by the CLI entry point below and the web UI's "Daily Queue" panel, which
    streams this function's print() output the same way it does for a
    single-video run."""
    videos = find_source_videos()
    if not videos:
        print(f"[queue] No videos found in {INPUT_DIR}/. Drop .mp4/.mov/.mkv/.webm files there first.")
        return []

    per_video_cap = max(1, target // len(videos))
    print(f"[queue] Found {len(videos)} source video(s). "
          f"Targeting ~{per_video_cap} clips per video (target={target}).")

    all_produced = []
    for video in videos:
        check_cancelled(cancel_event)
        print(f"\n[queue] === Processing {video.name} ===")
        try:
            produced = run_pipeline(
                str(video),
                max_clips=per_video_cap,
                whisper_model=whisper_model,
                do_upload=False,  # we control upload pacing separately below
                min_duration=min_duration,
                max_duration=max_duration,
                burn_captions=burn_captions,
                add_voiceover=add_voiceover,
                on_clip=on_clip,
                cancel_event=cancel_event,
            )
        except GroqBudgetExhausted as e:
            print(f"[queue] {e}\n"
                  f"[queue] Stopping here rather than losing today's earlier results - "
                  f"{video.name} and any remaining videos will need to wait for the quota to reset.")
            break
        except RunCancelled:
            raise  # user hit Stop - don't treat it as "this video failed, try the next one"
        except Exception as e:
            print(f"[queue] {video.name} failed, skipping it and continuing with "
                  f"the rest of today's videos: {e}")
            continue
        all_produced.extend(produced)

    print(f"\n[queue] Total clips produced today: {len(all_produced)}")
    usage = all_usage_today(MODEL_FALLBACK_CHAIN)
    for m in MODEL_FALLBACK_CHAIN:
        u = usage[m]
        print(f"[queue] Groq budget used today ({m}): {u['used']:,}/{u['cap']:,} tokens "
              f"({u['remaining']:,} remaining).")

    if do_upload:
        print(f"[queue] Uploading {len(all_produced)} clip(s), "
              f"spaced {spacing_minutes} min apart...")
        for i, meta in enumerate(all_produced):
            check_cancelled(cancel_event)
            meta_json_path = Path(meta["video_path"]).with_suffix(".json")
            try:
                upload_from_meta_file(str(meta_json_path), privacy_status=privacy)
            except YouTubeUploadLimitExceeded as e:
                print(f"[queue] {e}\n"
                      f"[queue] Stopping uploads here - this is an account-level daily cap, "
                      f"so every remaining upload would fail the same way. Clips not yet "
                      f"uploaded are still sitting in output/, untouched.")
                break
            except Exception as e:
                print(f"[queue] Upload failed for {meta_json_path}: {e}")

            if i < len(all_produced) - 1:
                print(f"[queue] Sleeping {spacing_minutes} min before next upload...")
                interruptible_sleep(spacing_minutes * 60, cancel_event)
    else:
        print("[queue] Clips ready in output/. Review them, then run:\n"
              "  python pipeline.py --upload-only")

    return all_produced


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=20, help="Total clips to aim for today")
    parser.add_argument("--whisper-model", default="small")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    parser.add_argument("--spacing-minutes", type=float, default=20.0,
                         help="Minutes to wait between uploads when --upload is set")
    parser.add_argument("--min-duration", type=float, default=DEFAULT_MIN_DURATION,
                         help="Target minimum clip length in seconds (default: 30)")
    parser.add_argument("--max-duration", type=float, default=DEFAULT_MAX_DURATION,
                         help="Target maximum clip length in seconds (default: 45)")
    parser.add_argument("--no-captions", action="store_true", help="Disable burned-in captions")
    parser.add_argument("--voiceover", action="store_true", help="Add an AI-narrated voiceover intro to each clip")
    args = parser.parse_args()

    run_daily_queue(
        target=args.target,
        whisper_model=args.whisper_model,
        do_upload=args.upload,
        privacy=args.privacy,
        spacing_minutes=args.spacing_minutes,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        burn_captions=not args.no_captions,
        add_voiceover=args.voiceover,
    )


if __name__ == "__main__":
    main()
