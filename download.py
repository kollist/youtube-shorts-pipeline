"""
download.py
Downloads a YouTube (or any yt-dlp-supported) video into the input/ directory.
Called automatically by pipeline.py when you pass a URL instead of a local file.

Usage (standalone):
    python download.py https://www.youtube.com/watch?v=XXXXXXXXXXX

Requires yt-dlp:
    pip install yt-dlp
"""

import sys
from pathlib import Path

import yt_dlp

from run_control import RunCancelled


def download_video(url: str, out_dir: str = "input", cancel_event=None) -> str:
    """Download a video from url into out_dir, return the local file path."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    def _check_cancel(_status: dict) -> None:
        # yt-dlp calls progress_hooks repeatedly during a download; raising
        # its own DownloadCancelled here is the supported way to abort a
        # download cleanly mid-flight instead of leaving a partial file and
        # internal state in a weird spot.
        if cancel_event is not None and cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Run stopped by user.")

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(Path(out_dir) / "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "restrictfilenames": True,  # sanitise title so it's safe as a filename
        # YouTube extraction needs a JS runtime to solve player challenges; yt-dlp
        # only enables "deno" by default, which usually isn't installed. Fall back
        # to node (commonly already present) to avoid 403s on the video/audio formats.
        "js_runtimes": {"deno": {}, "node": {}},
        "progress_hooks": [_check_cancel],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadCancelled:
        raise RunCancelled("Run stopped by user.")

    downloads = info.get("requested_downloads", [])
    if downloads and "filepath" in downloads[0]:
        return downloads[0]["filepath"]
    # fallback: reconstruct expected path from template
    return ydl.prepare_filename(info).rsplit(".", 1)[0] + ".mp4"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python download.py <youtube-url>")
        sys.exit(1)
    path = download_video(sys.argv[1])
    print(f"Downloaded -> {path}")
