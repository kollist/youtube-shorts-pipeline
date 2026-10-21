"""
social_instagram.py - posts a video as an Instagram Reel.

Uses the same Meta login as Facebook (Instagram API with Facebook Login): the
Page access token in FACEBOOK_PAGE_ACCESS_TOKEN, and the Instagram professional
account linked to that Page (found automatically, or set INSTAGRAM_USER_ID).
Docs: https://developers.facebook.com/docs/instagram-platform/content-publishing
Two ways to hand Instagram the video (INSTAGRAM_UPLOAD_MODE in .env: auto | url | resumable):
  url        - a temporary public link to the file (public_tunnel.py, needs ngrok). This is what worked in testing.
  resumable  - a direct upload from this machine. Meta documents it as only for apps using Facebook Login for
               Business; on this app Instagram rejected it ("ProcessingFailedError"), so "auto" prefers url
               when ngrok is installed and uses resumable only when it isn't.
"""

import os
from pathlib import Path

from social_common import SocialError, env, http, missing_env, wait_until

NAME = "instagram"
LABEL = "Instagram Reels"
GRAPH = os.environ.get("META_GRAPH_BASE", "https://graph.facebook.com/v25.0")
RUPLOAD = os.environ.get("META_RUPLOAD_BASE", "https://rupload.facebook.com/ig-api-upload/v25.0")
MIN_SECONDS, MAX_SECONDS = 3, 90   # conservative: Meta's docs page doesn't state the Reels length cap


def missing() -> list[str]:
    gone = missing_env("FACEBOOK_PAGE_ACCESS_TOKEN")
    if not env("INSTAGRAM_USER_ID") and not env("FACEBOOK_PAGE_ID"):
        gone.append("INSTAGRAM_USER_ID (or FACEBOOK_PAGE_ID to look it up)")
    return gone


def _ig_user_id() -> str:
    if env("INSTAGRAM_USER_ID"):
        return env("INSTAGRAM_USER_ID")
    r = http("GET", f"{GRAPH}/{env('FACEBOOK_PAGE_ID')}",
             params={"fields": "instagram_business_account", "access_token": env("FACEBOOK_PAGE_ACCESS_TOKEN")}).json()
    acct = r.get("instagram_business_account", {}).get("id")
    if not acct:
        raise SocialError("This Facebook Page has no Instagram professional account linked to it.")
    return acct


def check_connection() -> str:
    r = http("GET", f"{GRAPH}/{_ig_user_id()}", params={"fields": "username", "access_token": env("FACEBOOK_PAGE_ACCESS_TOKEN")})
    return f"Connected to Instagram account @{r.json().get('username', '?')}"


def _wait_finished(container: str, token: str, what: str = "Instagram to process the Reel") -> None:
    def ready():
        s = http("GET", f"{GRAPH}/{container}", params={"fields": "status_code,status", "access_token": token}).json()
        code = s.get("status_code")
        if code in ("ERROR", "EXPIRED"):
            raise SocialError(f"Instagram could not process the Reel ({code}): {s.get('status', '')}")
        return code == "FINISHED"

    wait_until(ready, every=5, timeout=600, what=what)


def _post_by_url(video_path: str, caption: str, token: str, ig: str) -> str:
    from public_tunnel import public_file_url
    with public_file_url(video_path) as url:
        container = http("POST", f"{GRAPH}/{ig}/media", data={
            "media_type": "REELS", "video_url": url, "caption": caption, "share_to_feed": "true", "access_token": token,
        }).json()["id"]
        _wait_finished(container, token)       # the link must stay up until Instagram has downloaded the file
    return container


def _post_resumable(video_path: str, caption: str, token: str, ig: str) -> str:
    data = Path(video_path).read_bytes()
    container = http("POST", f"{GRAPH}/{ig}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption,
        "share_to_feed": "true", "access_token": token,
    }).json()["id"]
    http("POST", f"{RUPLOAD}/{container}", data=data, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data)),
    })
    _wait_finished(container, token)
    return container


def post(video_path: str, caption: str, **_) -> dict:
    import public_tunnel
    token, ig = env("FACEBOOK_PAGE_ACCESS_TOKEN"), _ig_user_id()
    mode = (env("INSTAGRAM_UPLOAD_MODE") or "auto").lower()
    if mode == "auto":
        mode = "url" if public_tunnel.available() else "resumable"
    container = (_post_by_url if mode == "url" else _post_resumable)(video_path, caption, token, ig)
    media_id = http("POST", f"{GRAPH}/{ig}/media_publish", data={"creation_id": container, "access_token": token}).json()["id"]
    try:
        url = http("GET", f"{GRAPH}/{media_id}", params={"fields": "permalink", "access_token": token}).json().get("permalink")
    except SocialError:
        url = None
    return {"id": media_id, "url": url}
