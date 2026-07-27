"""
upload_youtube.py
Uploads a clip to your YouTube channel as a Short via the Data API v3
videos.insert endpoint. OAuth setup/login is shared with youtube_analytics.py -
see google_auth.py's module docstring for the one-time setup steps.

Usage:
    python upload_youtube.py output/myvideo_clip01.json
"""

import sys
import json

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from clip_log import log_upload
from google_auth import get_credentials


class YouTubeUploadLimitExceeded(RuntimeError):
    """Raised when YouTube's own daily upload cap for this channel is hit -
    an account-level limit (tighter for unverified/newer channels), not
    something a retry or a code fix can work around. Phone-verifying the
    channel (YouTube Studio -> Settings -> Channel -> Feature eligibility)
    typically raises it; otherwise it resets on its own after some time."""


def get_authenticated_service():
    return build("youtube", "v3", credentials=get_credentials())


STATIC_HASHTAGS = ["#Shorts", "#Subscribe", "#Viral", "#fyp", "#Trending"]


def upload_short(
    video_path: str,
    title: str,
    description: str,
    privacy_status: str = "public",
    category_id: str = "22",  # "People & Blogs" - change as needed
):
    """Uploads a single video file as a Short. category_id reference:
    https://developers.google.com/youtube/v3/docs/videoCategories/list
    """
    youtube = get_authenticated_service()

    # Always append a fixed set of hashtags (algorithm reach + subscribe CTA) on
    # top of whatever clip-specific hashtags the description already has.
    missing_tags = [
        tag for tag in STATIC_HASHTAGS
        if tag.lower() not in description.lower() and tag.lower() not in title.lower()
    ]
    if missing_tags:
        description = f"{description}\n{' '.join(missing_tags)}".strip()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,  # "public" | "unlisted" | "private"
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")

    print(f"[upload] Uploading '{title}' from {video_path} ...")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    try:
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"[upload]   ...{int(status.progress() * 100)}% uploaded")
    except HttpError as e:
        if e.status_code == 400 and "uploadLimitExceeded" in str(e):
            raise YouTubeUploadLimitExceeded(
                f"YouTube's daily upload limit for this channel has been reached: {e}"
            )
        raise

    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    print(f"[upload] Done -> {url}")
    return {"video_id": video_id, "url": url}


def delete_uploaded_clip(meta_path: str, video_path: str):
    """Deletes a clip's .mp4/.srt/.json from local disk once it's live on
    YouTube - it's safely stored on YouTube at that point, no need to keep
    a local copy around."""
    meta_path = Path(meta_path)
    video_path = Path(video_path)

    for path in (video_path, video_path.with_suffix(".srt"), meta_path):
        if path.exists():
            path.unlink()


def upload_from_meta_file(meta_path: str, privacy_status: str = "public"):
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    result = upload_short(
        video_path=meta["video_path"],
        title=meta["title"],
        description=meta["description"],
        privacy_status=privacy_status,
    )

    meta["youtube_video_id"] = result["video_id"]
    meta["youtube_url"] = result["url"]
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log_upload({
        "video_id": result["video_id"],
        "url": result["url"],
        "title": meta["title"],
        "hook_mechanic": meta.get("hook_mechanic", "unknown"),
        "duration_sec": round(meta["end"] - meta["start"], 1),
        "privacy_status": privacy_status,
    })

    delete_uploaded_clip(meta_path, meta["video_path"])

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_youtube.py <clip_meta_json> [privacy_status]")
        sys.exit(1)

    meta_path = sys.argv[1]
    privacy = sys.argv[2] if len(sys.argv) > 2 else "public"
    upload_from_meta_file(meta_path, privacy_status=privacy)
