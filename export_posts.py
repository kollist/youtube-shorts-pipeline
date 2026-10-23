"""
export_posts.py
MANUAL MODE: no accounts connected, nothing to set up. Packages a finished episode into exports/<series>-epNN/:
  - the video(s)                        (video.mp4 = the best quality one; video-normal.mp4 when a lighter copy exists)
  - captions.txt                        every platform's caption + hashtags, ready to copy and paste
  - one text file per platform          youtube.txt / instagram.txt / facebook.txt / tiktok.txt
Open the app on your phone or the website, upload the video, paste the text. The SCP credit line is already inside every caption.

    python export_posts.py foundation-tapes 3
"""

import json
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).parent
EXPORTS = BASE / "exports"


def episode_captions(slug: str, n: int, remember: bool = True) -> dict:
    """Captions for one episode: {"caps": {instagram, facebook, tiktok, youtube, youtube_title}, "category", "title", "summary"}.
    The licence credit (SCP episodes) is appended to every caption; the YouTube description also carries the full credit.txt."""
    import captions
    import series as s
    d = s.episode_dir(slug, n)
    story = json.loads((d / "story.json").read_text(encoding="utf-8"))
    sj = s.STORIES_DIR / slug / "series.json"
    genre = json.loads(sj.read_text(encoding="utf-8")).get("genre", "") if sj.exists() else ""
    first = story["scenes"][0]["lines"][0]["text"] if story.get("scenes") and story["scenes"][0].get("lines") else ""
    info = {"title": story["title"], "summary": story.get("summary", ""), "hook": first,
            "category": captions.category_for(genre, story.get("format", ""), slug, story["title"])}
    caps = captions.write_captions(info, remember=remember)
    credit = story.get("credit")
    if credit:
        for k in ("instagram", "facebook", "tiktok"):
            caps[k] = (caps.get(k, "") + "\n\n" + credit["line"]).strip()
        credit_txt = d / "credit.txt"
        caps["youtube"] = (caps.get("youtube", "") + "\n\n" + (credit_txt.read_text(encoding="utf-8") if credit_txt.exists() else credit["line"])).strip()
    return {"caps": caps, "category": info["category"], "title": story["title"][:100], "summary": story.get("summary", "")}


def export_episode(slug: str, n: int) -> dict:
    import series as s
    d = s.episode_dir(slug, n)
    videos = sorted(d.glob("*-HORROR*.mp4")) or sorted(d.glob("*.mp4"))
    if not videos:
        raise RuntimeError("This episode has no video yet - make it first.")
    best = next((v for v in videos if v.stem.endswith("-YT")), videos[0])
    out = EXPORTS / f"{slug}-ep{n:02d}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    shutil.copy2(best, out / "video.mp4")
    for v in videos:
        if v != best:
            shutil.copy2(v, out / "video-normal.mp4")
            break
    c = episode_captions(slug, n, remember=False)
    caps = c["caps"]
    files = {"youtube.txt": f"TITLE\n{caps.get('youtube_title', c['title'])}\n\nDESCRIPTION\n{caps.get('youtube', '')}\n",
             "instagram.txt": caps.get("instagram", "") + "\n", "facebook.txt": caps.get("facebook", "") + "\n", "tiktok.txt": caps.get("tiktok", "") + "\n"}
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    (out / "captions.txt").write_text("\n\n" + ("=" * 60 + "\n\n").join(f"### {k[:-4].upper()}\n\n{v}" for k, v in files.items()), encoding="utf-8")
    return {"folder": str(out), "files": sorted(p.name for p in out.iterdir()), "captions": {k[:-4]: v for k, v in files.items()}}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python export_posts.py <series-slug> <episode-number>")
    r = export_episode(sys.argv[1], int(sys.argv[2]))
    print(f"Saved to {r['folder']}\n  " + "\n  ".join(r["files"]))
