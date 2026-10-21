"""
social_post.py
Posts one finished clip to any mix of YouTube, Facebook Reels, Instagram Reels,
TikTok and X, and remembers which ones already went through - so retrying after
a partial failure only redoes the platforms that failed, never double-posts.
The clip's local files are deleted only once every requested platform has it.

Usage:
    python social_post.py status                          # which platforms have their keys set
    python social_post.py test facebook                   # a cheap authenticated call, posts nothing
    python social_post.py post output/clip.json --platforms youtube,tiktok
    python social_post.py video my.mp4 --title "..." --platforms tiktok,facebook   # any video file

Keys: see .env.example. One-time logins: python social_auth.py {meta|instagram|tiktok}
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

import social_facebook
import social_instagram
import social_tiktok
from social_common import NotConfigured, SocialError, env, log_post

MODULES = {m.NAME: m for m in (social_facebook, social_instagram, social_tiktok)}
ALL_PLATFORMS = ["youtube"] + list(MODULES)
LABELS = {"youtube": "YouTube Shorts", **{n: m.LABEL for n, m in MODULES.items()}}
LONG_CAPTION = 2200


def youtube_missing() -> list[str]:
    from google_auth import CLIENT_SECRET_FILE, TOKEN_FILE
    if Path(TOKEN_FILE).exists() or Path(CLIENT_SECRET_FILE).exists():
        return []
    return [f"{CLIENT_SECRET_FILE} (see google_auth.py)"]


def platform_status() -> list[dict]:
    rows = [{"name": "youtube", "label": LABELS["youtube"], "missing": youtube_missing()}]
    rows += [{"name": n, "label": m.LABEL, "missing": m.missing()} for n, m in MODULES.items()]
    for r in rows:
        r["configured"] = not r["missing"]
    return rows


def build_caption(title: str, description: str, platform: str, category: str = "") -> str:
    """The fallback caption (used when no written caption is supplied): the title as the hook, the description, and a few tags from
    captions.py's category pools - rotated so the same block isn't reused, and sized per platform. #Shorts only means something on YouTube."""
    import captions
    body = re.sub(r"#\w+", "", description).strip()
    cat = category or captions.category_for(text=f"{title} {description}")
    tags = captions.pick_tags(cat, platform, title)
    parts = [title.strip()] + ([body] if body else []) + [" ".join(tags)]
    return "\n\n".join(parts)[:LONG_CAPTION]


def video_seconds(path: str) -> float | None:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return None


def _post_one(name: str, video_path: str, title: str, description: str, privacy: str, aigc: bool, made_for_kids: bool,
              captions: dict | None = None, category: str = "", youtube_license: str = "youtube") -> dict:
    """Posts to a single platform; returns {"id", "url", ...}. Raises on failure.
    captions (optional) = the written, possibly hand-edited text per platform: {"instagram", "facebook", "tiktok", "youtube_title", "youtube"}."""
    captions = captions or {}
    if name == "youtube":
        from upload_youtube import upload_short
        r = upload_short(video_path, captions.get("youtube_title") or title, captions.get("youtube") or description,
                         privacy_status=privacy, made_for_kids=made_for_kids, license_=youtube_license)
        return {"id": r["video_id"], "url": r["url"]}

    module = MODULES.get(name)
    if module is None:
        raise SocialError(f"Unknown platform '{name}'.")
    gone = module.missing()
    if gone:
        raise NotConfigured(f"{module.LABEL} isn't set up yet - missing: {', '.join(gone)}")
    seconds = video_seconds(video_path)
    lo, hi = getattr(module, "MIN_SECONDS", None), getattr(module, "MAX_SECONDS", None)
    if seconds is not None and ((hi and seconds > hi) or (lo and seconds < lo)):
        raise SocialError(f"{module.LABEL} needs a video between {lo} and {hi} seconds; this one is {seconds:.0f}s.")
    caption = (captions.get(name) or "").strip() or build_caption(title, description, name, category)
    return module.post(video_path, caption=caption[:LONG_CAPTION], title=(captions.get("youtube_title") or title), privacy=privacy, aigc=aigc)


def post_clip(meta_path: str, platforms: list[str] | None = None, privacy: str = "public", delete_when_done: bool = True) -> dict:
    """Returns {"results": {platform: {"ok", "id", "url", "error", "skipped"}}, "all_ok", "deleted"}."""
    meta_path = Path(meta_path)
    platforms = [p for p in ALL_PLATFORMS if p in (platforms or ["youtube"])]  # YouTube first, fixed order after

    def load() -> dict:
        return json.loads(meta_path.read_text(encoding="utf-8"))

    results: dict = {}
    for name in platforms:
        meta = load()
        already = meta.get("posted", {}).get(name)
        if not already and name == "youtube" and meta.get("youtube_video_id"):
            already = {"id": meta["youtube_video_id"], "url": meta.get("youtube_url")}
        if already:
            results[name] = {"ok": True, "skipped": "already posted", **already}
            continue
        try:
            if name == "youtube":
                # Reuses the existing uploader so the YouTube upload log / analytics tracking is unchanged.
                from upload_youtube import upload_from_meta_file
                r = upload_from_meta_file(str(meta_path), privacy, delete_after=False)
                entry = {"id": r["video_id"], "url": r["url"]}
            else:
                entry = _post_one(name, meta["video_path"], meta["title"], meta.get("description", ""), privacy,
                                  bool(meta.get("aigc")), bool(meta.get("made_for_kids")), category="clips")
                log_post({"platform": name, "post_id": entry["id"], "url": entry.get("url"), "title": meta["title"],
                          **{k: meta[k] for k in ("source", "streamer", "mode", "hook_mechanic", "format") if k in meta}})
            fresh = load()
            fresh.setdefault("posted", {})[name] = {k: v for k, v in entry.items() if v is not None}
            meta_path.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
            results[name] = {"ok": True, **entry}
        except Exception as e:  # one platform failing must not stop the others
            results[name] = {"ok": False, "error": str(e), "limit": type(e).__name__ == "YouTubeUploadLimitExceeded"}

    all_ok = bool(results) and all(r["ok"] for r in results.values())
    deleted = False
    if all_ok and delete_when_done:
        from upload_youtube import delete_uploaded_clip
        delete_uploaded_clip(str(meta_path), load()["video_path"])
        deleted = True
    return {"results": results, "all_ok": all_ok, "deleted": deleted}


def post_video(video_path: str, title: str, description: str = "", platforms: list[str] | None = None,
               privacy: str = "public", aigc: bool = False, made_for_kids: bool = False,
               captions: dict | None = None, category: str = "", youtube_license: str = "youtube") -> dict:
    """Any finished video file (e.g. a story from story_video.py). Nothing is deleted here."""
    results = {}
    for name in [p for p in ALL_PLATFORMS if p in (platforms or [])]:
        try:
            results[name] = {"ok": True, **_post_one(name, video_path, title, description, privacy, aigc, made_for_kids, captions, category, youtube_license)}
            if name != "youtube":
                log_post({"platform": name, "post_id": results[name]["id"], "url": results[name].get("url"), "title": title})
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}
    return {"results": results, "all_ok": bool(results) and all(r["ok"] for r in results.values())}


def _print(outcome: dict) -> None:
    for name, r in outcome["results"].items():
        if r["ok"]:
            print(f"  OK     {LABELS[name]}: {r.get('url') or r.get('id')} {r.get('note', '')}".rstrip())
        else:
            print(f"  FAILED {LABELS[name]}: {r['error']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    t = sub.add_parser("test"); t.add_argument("platform", choices=list(MODULES))
    p = sub.add_parser("post"); p.add_argument("meta_json"); p.add_argument("--platforms", default="youtube"); p.add_argument("--privacy", default="public")
    v = sub.add_parser("video"); v.add_argument("file"); v.add_argument("--title", required=True); v.add_argument("--description", default="")
    v.add_argument("--platforms", required=True); v.add_argument("--privacy", default="public")
    v.add_argument("--aigc", action="store_true", help="Label as AI-generated (TikTok)"); v.add_argument("--kids", action="store_true", help="Made for kids (YouTube)")
    args = parser.parse_args()

    if args.cmd == "status":
        for r in platform_status():
            print(f"{'ready ' if r['configured'] else 'MISSING'}  {r['label']:16s} {', '.join(r['missing'])}")
    elif args.cmd == "test":
        try:
            print(MODULES[args.platform].check_connection())
        except Exception as e:      # a clear one-line answer instead of a traceback
            print(f"{args.platform}: NOT connected - {e}")
            raise SystemExit(1)
    elif args.cmd == "post":
        _print(post_clip(args.meta_json, args.platforms.split(","), args.privacy))
    else:
        _print(post_video(args.file, args.title, args.description, args.platforms.split(","), args.privacy, args.aigc, args.kids))
