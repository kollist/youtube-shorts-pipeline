"""
download.py
Downloads a YouTube (or any yt-dlp-supported) video into the input/ directory.
Called automatically by pipeline.py when you pass a URL instead of a local file.

Usage (standalone):
    python download.py https://www.youtube.com/watch?v=XXXXXXXXXXX

Requires yt-dlp:
    pip install yt-dlp
"""

import subprocess
import sys
from pathlib import Path

import yt_dlp

from run_control import RunCancelled


def _has_audio_stream(path: str) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def download_video(url: str, out_dir: str = "input", cancel_event=None, on_progress=None) -> str:
    """Download a video from url into out_dir, return the local file path.
    on_progress(percent) is called periodically during the download (percent
    is None if yt-dlp can't report a total size yet, e.g. right at the start)."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    def _hook(status: dict) -> None:
        # yt-dlp calls progress_hooks repeatedly during a download; raising
        # its own DownloadCancelled here is the supported way to abort a
        # download cleanly mid-flight instead of leaving a partial file and
        # internal state in a weird spot.
        if cancel_event is not None and cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Run stopped by user.")
        if on_progress and status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            percent = round(status.get("downloaded_bytes", 0) / total * 100, 1) if total else None
            on_progress(percent)

    ydl_opts = {
        # bestvideo*+bestaudio (vs. restricting to ext=mp4/m4a) matches far
        # more codec pairings before falling back to "best" - a video with no
        # combined-format option above ~1080p (common for 4K YouTube uploads)
        # would otherwise fail that stricter pair and "best" would silently
        # resolve to a video-only stream, since ffmpeg then has nothing to mux
        # the missing audio track from.
        "format": "bestvideo*+bestaudio/best",
        "outtmpl": str(Path(out_dir) / "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "restrictfilenames": True,  # sanitise title so it's safe as a filename
        # YouTube extraction needs a JS runtime to solve player challenges; yt-dlp
        # only enables "deno" by default, which usually isn't installed. Fall back
        # to node (commonly already present) to avoid 403s on the video/audio formats.
        "js_runtimes": {"deno": {}, "node": {}},
        "progress_hooks": [_hook],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadCancelled:
        raise RunCancelled("Run stopped by user.")

    downloads = info.get("requested_downloads", [])
    if downloads and "filepath" in downloads[0]:
        video_path = downloads[0]["filepath"]
    else:
        # fallback: reconstruct expected path from template
        video_path = ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp4"

    # A video+audio merge that silently didn't happen (out of disk space,
    # ffmpeg missing, a postprocessor error) leaves yt-dlp's separate
    # video-only fragment sitting at this same "final" path instead of a
    # merged file - transcription would otherwise fail on it much later with
    # an opaque error deep inside faster-whisper's audio decoding.
    if not _has_audio_stream(video_path):
        raise RuntimeError(
            f"Downloaded '{Path(video_path).name}' has no audio track - the video+audio "
            f"merge likely failed (check disk space and that ffmpeg is on PATH). Delete "
            f"this file and try the download again."
        )

    return video_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download.py <youtube-url>")
        sys.exit(1)
    path = download_video(sys.argv[1])
    print(f"Downloaded -> {path}")
