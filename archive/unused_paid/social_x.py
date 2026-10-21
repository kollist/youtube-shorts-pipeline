"""
social_x.py - posts a video to X (Twitter) with the v2 API.

Needs (in .env): X_CLIENT_ID (and X_CLIENT_SECRET if your app is a confidential
client), then a one-time login:  python social_auth.py x
The app needs the scopes tweet.read tweet.write users.read media.write offline.access.
X's API is paid/pay-per-use for new developers - check your plan before posting a lot.
Docs: https://docs.x.com/x-api/media/quickstart/media-upload-chunked
"""

import os
import time
from pathlib import Path

from social_common import NotConfigured, SocialError, env, http, load_token, missing_env, save_token, wait_until

NAME = "x"
LABEL = "X"
API = os.environ.get("X_API_BASE", "https://api.x.com")
SEGMENT = 4 * 1024 * 1024  # X: keep each APPEND at or below 5 MB


def missing() -> list[str]:
    gone = missing_env("X_CLIENT_ID")
    if not gone and not load_token(NAME):
        gone.append("login (run: python social_auth.py x)")
    return gone


def _access_token() -> str:
    tok = load_token(NAME)
    if not tok:
        raise NotConfigured("X isn't logged in yet - run: python social_auth.py x")
    if tok["expires_at"] - time.time() < 300:  # access tokens last about 2 hours
        auth = (env("X_CLIENT_ID"), env("X_CLIENT_SECRET")) if env("X_CLIENT_SECRET") else None
        r = http("POST", f"{API}/2/oauth2/token", auth=auth, data={
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": env("X_CLIENT_ID"),
        }).json()
        if "access_token" not in r:
            raise SocialError(f"X login expired - run: python social_auth.py x ({r})")
        # X rotates refresh tokens: the old one stops working once a new one is issued.
        tok = {"access_token": r["access_token"], "refresh_token": r.get("refresh_token", tok["refresh_token"]),
               "expires_at": time.time() + int(r["expires_in"])}
        save_token(NAME, tok)
    return tok["access_token"]


def _auth() -> dict:
    return {"Authorization": f"Bearer {_access_token()}"}


def check_connection() -> str:
    me = http("GET", f"{API}/2/users/me", headers=_auth()).json().get("data", {})
    return f"Connected as @{me.get('username', '?')}"


def post(video_path: str, caption: str, **_) -> dict:
    data = Path(video_path).read_bytes()

    init = http("POST", f"{API}/2/media/upload/initialize", headers=_auth(),
                json={"media_type": "video/mp4", "total_bytes": len(data), "media_category": "tweet_video"}).json()
    media_id = init["data"]["id"]

    for i, start in enumerate(range(0, len(data), SEGMENT)):
        http("POST", f"{API}/2/media/upload/{media_id}/append", headers=_auth(),
             data={"segment_index": str(i)}, files={"media": ("chunk.mp4", data[start:start + SEGMENT], "application/octet-stream")})

    fin = http("POST", f"{API}/2/media/upload/{media_id}/finalize", headers=_auth()).json().get("data", {})
    info = fin.get("processing_info")
    if info:
        def processed():
            s = http("GET", f"{API}/2/media/upload", headers=_auth(),
                     params={"command": "STATUS", "media_id": media_id}).json().get("data", {}).get("processing_info", {})
            if s.get("state") == "failed":
                raise SocialError(f"X could not process the video: {s.get('error', s)}")
            return s.get("state") == "succeeded"
        wait_until(processed, every=max(3, info.get("check_after_secs", 5)), timeout=600, what="X to process the video")

    tweet = http("POST", f"{API}/2/tweets", headers=_auth(),
                 json={"text": caption[:280], "media": {"media_ids": [media_id]}}).json()["data"]
    return {"id": tweet["id"], "url": f"https://x.com/i/status/{tweet['id']}"}
