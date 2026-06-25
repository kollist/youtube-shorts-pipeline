"""
upload_youtube.py
Handles OAuth 2.0 login (one-time, cached after) and uploads a clip to your
YouTube channel as a Short via the Data API v3 videos.insert endpoint.

ONE-TIME SETUP (do this before running anything):
1. Go to https://console.cloud.google.com/ -> create a project (or reuse one).
2. APIs & Services -> Library -> enable "YouTube Data API v3".
3. APIs & Services -> OAuth consent screen -> set up as "External" + add your
   own Google account as a test user (you don't need Google's review for
   personal use with test users).
4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
   -> Application type: "Desktop app". Download the JSON.
5. Save that file as client_secret.json in this project folder (or point
   YOUTUBE_CLIENT_SECRET_FILE in .env at it).
6. First time you run this script, a browser window will open asking you to
   log in and grant access. After that, a token.json is cached and you won't
   need to log in again until the token expires/is revoked.

Usage:
    python upload_youtube.py output/myvideo_clip01.json
"""

import os
import shutil
import sys
import json
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

CLIENT_SECRET_FILE = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_FILE = os.environ.get("YOUTUBE_TOKEN_FILE", "token.json")


def get_authenticated_service():
    creds = None
    if Path(TOKEN_FILE).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(CLIENT_SECRET_FILE).exists():
                raise FileNotFoundError(
                    f"Missing {CLIENT_SECRET_FILE}. Download OAuth client JSON "
                    f"from Google Cloud Console first (see module docstring)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


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

    # Make sure #Shorts is present somewhere so YouTube reliably classifies it
    if "#shorts" not in description.lower() and "#shorts" not in title.lower():
        description = f"{description}\n#Shorts".strip()

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

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[upload]   ...{int(status.progress() * 100)}% uploaded")

    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    print(f"[upload] Done -> {url}")
    return {"video_id": video_id, "url": url}


def archive_uploaded_clip(meta_path: str, video_path: str):
    """Moves a clip's .mp4/.srt/.json out of output/ into output/uploaded/
    once it's live on YouTube, so output/ only ever shows pending clips."""
    meta_path = Path(meta_path)
    video_path = Path(video_path)
    archive_dir = video_path.parent / "uploaded"
    archive_dir.mkdir(parents=True, exist_ok=True)

    for path in (video_path, video_path.with_suffix(".srt"), meta_path):
        if path.exists():
            shutil.move(str(path), str(archive_dir / path.name))


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

    archive_uploaded_clip(meta_path, meta["video_path"])

    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upload_youtube.py <clip_meta_json> [privacy_status]")
        sys.exit(1)

    meta_path = sys.argv[1]
    privacy = sys.argv[2] if len(sys.argv) > 2 else "public"
    upload_from_meta_file(meta_path, privacy_status=privacy)
