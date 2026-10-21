"""
fetch_model.py - downloads a Hugging Face model folder in a way that survives a flaky connection:
curl drops a stalled connection and resumes from the exact byte, over and over, until every file is complete.

    python fetch_model.py mflux-community/z-image-turbo-mflux-q4 models/zimage-q4
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4")


def fetch(repo: str, dest: str) -> None:
    out_dir = Path(dest)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = json.load(urllib.request.urlopen(f"https://huggingface.co/api/models/{repo}?blobs=true", timeout=30))
    files = [s for s in info["siblings"] if not s["rfilename"].lower().endswith(SKIP_SUFFIXES) and s["rfilename"] != ".gitattributes"]
    print(f"{repo}: {len(files)} files, {sum(s.get('size') or 0 for s in files) / 1e9:.1f} GB", flush=True)
    for s in sorted(files, key=lambda s: s.get("size") or 0):
        name, size = s["rfilename"], s.get("size") or 0
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        while not (target.exists() and target.stat().st_size == size):
            have = target.stat().st_size if target.exists() else 0
            print(f"  {name} ({size / 1e9:.2f} GB) from byte {have}", flush=True)
            subprocess.run(["curl", "-L", "-C", "-", "--silent", "--show-error", "--connect-timeout", "20",
                            "--speed-time", "20", "--speed-limit", "20000", "-o", str(target),
                            f"https://huggingface.co/{repo}/resolve/main/{name}"])
            time.sleep(2)
    print("ALL FILES READY", flush=True)


if __name__ == "__main__":
    fetch(sys.argv[1], sys.argv[2])
