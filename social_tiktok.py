"""
social_tiktok.py - posts a video to TikTok with the Content Posting API (Direct Post).

Needs (in .env): TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, then a one-time login:
    python social_auth.py tiktok
IMPORTANT: until TikTok audits your app, every post it makes is private (SELF_ONLY)
and only works on a private TikTok account - TikTok's rule, not something code can
change. Docs: https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
"""

import os
import time
from pathlib import Path

from social_common import NotConfigured, SocialError, env, http, load_token, missing_env, save_token, wait_until

NAME = "tiktok"
LABEL = "TikTok"
API = os.environ.get("TIKTOK_API_BASE", "https://open.tiktokapis.com")
SINGLE_UPLOAD_MAX = 64 * 1024 * 1024   # TikTok: up to 64 MB can go in one request
CHUNK = 32 * 1024 * 1024               # bigger files: chunks of 5-64 MB, the last one absorbs the remainder (up to 128 MB)
UNAUDITED = "unaudited_client_can_only_post_to_private_accounts"
PRIVACY_FOR = {"public": "PUBLIC_TO_EVERYONE", "unlisted": "MUTUAL_FOLLOW_FRIENDS", "private": "SELF_ONLY"}


def missing() -> list[str]:
    gone = missing_env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    if not gone and not load_token(NAME):
        gone.append("login (run: python social_auth.py tiktok)")
    return gone


def _access_token() -> str:
    tok = load_token(NAME)
    if not tok:
        raise NotConfigured("TikTok isn't logged in yet - run: python social_auth.py tiktok")
    if tok["expires_at"] - time.time() < 300:  # access tokens last 24h
        r = http("POST", f"{API}/v2/oauth/token/", data={
            "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
        }, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
        if "access_token" not in r:
            raise SocialError(f"TikTok login expired - run: python social_auth.py tiktok ({r})")
        tok = {"access_token": r["access_token"], "refresh_token": r.get("refresh_token", tok["refresh_token"]),
               "open_id": r.get("open_id", tok.get("open_id")), "expires_at": time.time() + int(r["expires_in"])}
        save_token(NAME, tok)
    return tok["access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json; charset=UTF-8"}


def _creator_info() -> dict:
    return http("POST", f"{API}/v2/post/publish/creator_info/query/", headers=_headers(), json={}).json().get("data", {})


def check_connection() -> str:
    info = _creator_info()
    options = info.get("privacy_level_options", [])
    name = info.get("creator_nickname") or info.get("creator_username") or "?"
    note = "" if "PUBLIC_TO_EVERYONE" in options else " - only private posts allowed (app not audited yet)"
    return f"Connected as {name}{note}"


def _as_draft(video_path: str, caption: str) -> dict:
    r = post_draft(video_path, caption)
    r["note"] = ("TikTok only allows public posts from approved apps, so the video was sent to your TikTok INBOX as a draft: open TikTok, paste the caption "
                 "(it is not carried over) and press Post. " + r.get("note", "")).strip()
    return r


def post(video_path: str, caption: str, privacy: str = "public", aigc: bool = False, **_) -> dict:
    info = _creator_info()
    options = info.get("privacy_level_options") or ["SELF_ONLY"]
    level = PRIVACY_FOR.get(privacy, "PUBLIC_TO_EVERYONE")
    if level not in options:
        level = "SELF_ONLY" if "SELF_ONLY" in options else options[0]

    data = Path(video_path).read_bytes()
    size = len(data)
    if size <= SINGLE_UPLOAD_MAX:
        chunk, total = size, 1
    else:
        chunk = CHUNK
        total = size // chunk  # the last chunk absorbs the remainder (TikTok allows it to be larger)

    try:
        init = http("POST", f"{API}/v2/post/publish/video/init/", headers=_headers(), json={
            "post_info": {"title": caption[:2200], "privacy_level": level, "is_aigc": bool(aigc)},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total},
        }).json()
    except SocialError as e:
        if UNAUDITED in str(e):                              # app not approved yet: a draft in the inbox still works, and YOU publish it
            return _as_draft(video_path, caption)
        raise
    if init.get("error", {}).get("code", "ok") != "ok":
        if init["error"].get("code") == UNAUDITED:
            return _as_draft(video_path, caption)
        raise SocialError(f"TikTok refused the post: {init['error']}")
    publish_id, upload_url = init["data"]["publish_id"], init["data"]["upload_url"]

    for i in range(total):
        first = i * chunk
        last = size - 1 if i == total - 1 else first + chunk - 1
        part = data[first:last + 1]
        http("PUT", upload_url, data=part, headers={
            "Content-Type": "video/mp4", "Content-Length": str(len(part)),
            "Content-Range": f"bytes {first}-{last}/{size}",
        })

    def done():
        s = http("POST", f"{API}/v2/post/publish/status/fetch/", headers=_headers(), json={"publish_id": publish_id}).json().get("data", {})
        if s.get("status") == "FAILED":
            raise SocialError(f"TikTok failed to publish: {s.get('fail_reason', 'unknown reason')}")
        return s if s.get("status") == "PUBLISH_COMPLETE" else None

    final = wait_until(done, every=6, timeout=600, what="TikTok to publish the video")
    ids = final.get("publicaly_available_post_id") or []   # (sic) - TikTok's spelling
    note = "" if level == "PUBLIC_TO_EVERYONE" else f" (posted as {level} - TikTok only allows that until the app is audited)"
    return {"id": str(ids[0]) if ids else publish_id, "url": None, "note": note.strip()}


def post_draft(video_path: str, caption: str = "", **_) -> dict:
    """Sends the video to the creator's TikTok inbox as a DRAFT (scope video.upload). The creator opens the TikTok app and presses Post, so it is
    published by a person and is not limited to private the way an unaudited Direct Post is. TikTok does not carry a caption over: paste it yourself."""
    data = Path(video_path).read_bytes()
    size = len(data)
    chunk, total = (size, 1) if size <= SINGLE_UPLOAD_MAX else (CHUNK, size // CHUNK)
    init = http("POST", f"{API}/v2/post/publish/inbox/video/init/", headers=_headers(), json={
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total},
    }).json()
    if init.get("error", {}).get("code", "ok") != "ok":
        raise SocialError(f"TikTok refused the draft: {init['error']}")
    publish_id, upload_url = init["data"]["publish_id"], init["data"]["upload_url"]
    for i in range(total):
        first = i * chunk
        last = size - 1 if i == total - 1 else first + chunk - 1
        part = data[first:last + 1]
        http("PUT", upload_url, data=part, headers={"Content-Type": "video/mp4", "Content-Length": str(len(part)),
                                                    "Content-Range": f"bytes {first}-{last}/{size}"})

    def done():
        d = http("POST", f"{API}/v2/post/publish/status/fetch/", headers=_headers(), json={"publish_id": publish_id}).json().get("data", {})
        if d.get("status") == "FAILED":
            raise SocialError(f"TikTok failed to take the draft: {d.get('fail_reason', 'unknown reason')}")
        return d if d.get("status") in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE") else None

    final = wait_until(done, every=5, timeout=300, what="TikTok to put the draft in your inbox")
    return {"id": publish_id, "url": None, "note": f"sent to your TikTok inbox as a draft ({final.get('status')}) - open the TikTok app and press Post"}
