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


def download_video(url: str, out_dir: str = "input") -> str:
    """Download a video from url into out_dir, return the local file path."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(Path(out_dir) / "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "restrictfilenames": True,  # sanitise title so it's safe as a filename
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
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
