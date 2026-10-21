"""
social_facebook.py - posts a video as a Facebook Page Reel.

Needs (in .env): FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN
(`python social_auth.py meta` fills both in for you).
Docs: https://developers.facebook.com/docs/video-api/guides/reels-publishing
Reels must be 9:16, 3-90 seconds; limit is 30 API-published Reels per 24 hours.
"""

import os
from pathlib import Path

from social_common import SocialError, env, http, missing_env, wait_until

NAME = "facebook"
LABEL = "Facebook Reels"
GRAPH = os.environ.get("META_GRAPH_BASE", "https://graph.facebook.com/v25.0")
MIN_SECONDS, MAX_SECONDS = 3, 90


def missing() -> list[str]:
    return missing_env("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN")


def check_connection() -> str:
    r = http("GET", f"{GRAPH}/{env('FACEBOOK_PAGE_ID')}",
             params={"fields": "name", "access_token": env("FACEBOOK_PAGE_ACCESS_TOKEN")})
    return f"Connected to the Page '{r.json().get('name', '?')}'"


def post(video_path: str, caption: str, title: str | None = None, **_) -> dict:
    page, token = env("FACEBOOK_PAGE_ID"), env("FACEBOOK_PAGE_ACCESS_TOKEN")
    data = Path(video_path).read_bytes()

    start = http("POST", f"{GRAPH}/{page}/video_reels", json={"upload_phase": "start", "access_token": token}).json()
    video_id, upload_url = start["video_id"], start["upload_url"]

    # The file goes to rupload.facebook.com (the URL Facebook returned), not graph.facebook.com.
    http("POST", upload_url, data=data, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data)),
        "Content-Type": "application/octet-stream",
    })

    finish_params = {"access_token": token, "video_id": video_id, "upload_phase": "finish",
                     "video_state": "PUBLISHED", "description": caption}
    if title:
        finish_params["title"] = title[:255]
    http("POST", f"{GRAPH}/{page}/video_reels", params=finish_params)

    def published():
        status = http("GET", f"{GRAPH}/{video_id}", params={"fields": "status", "access_token": token}).json().get("status", {})
        if status.get("video_status") in ("upload_failed", "expired", "error"):
            raise SocialError(f"Facebook rejected the Reel: {status}")
        if status.get("processing_phase", {}).get("status") == "error":
            raise SocialError(f"Facebook could not process the Reel: {status['processing_phase']}")
        pub = status.get("publishing_phase", {}).get("publish_status")
        if pub == "error":
            raise SocialError(f"Facebook could not publish the Reel: {status['publishing_phase']}")
        return pub == "published" or status.get("video_status") == "ready"

    wait_until(published, every=8, timeout=600, what="Facebook to finish processing the Reel")
    return {"id": video_id, "url": f"https://www.facebook.com/reel/{video_id}"}
