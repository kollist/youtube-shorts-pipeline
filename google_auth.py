"""
google_auth.py
Shared OAuth 2.0 credential handling for everything that acts on your YouTube
channel as you: uploading (upload_youtube.py) and pulling retention analytics
(youtube_analytics.py). Both live under one cached token so adding a scope
for one (e.g. yt-analytics.readonly) doesn't mean managing two separate
logins - if the cached token is missing a scope SCOPES now requires, this
automatically re-opens the consent screen to grant the fuller set instead of
silently failing or needing token.json deleted by hand.

ONE-TIME SETUP (do this before running anything):
1. Go to https://console.cloud.google.com/ -> create a project (or reuse one).
2. APIs & Services -> Library -> enable "YouTube Data API v3" and, if you
   want retention analytics too, "YouTube Analytics API".
3. APIs & Services -> OAuth consent screen -> set up as "External" + add your
   own Google account as a test user (you don't need Google's review for
   personal use with test users).
4. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
   -> Application type: "Desktop app". Download the JSON.
5. Save that file as client_secret.json in this project folder (or point
   YOUTUBE_CLIENT_SECRET_FILE in .env at it).
6. The first call to get_credentials() opens a browser window asking you to
   log in and grant access. After that, token.json is cached. If SCOPES ever
   gains a new entry and the cached token doesn't have it yet, the next call
   automatically reopens the consent screen for the added permission.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

# youtube.upload: upload videos as this channel.
# yt-analytics.readonly: read this channel's view/retention analytics.
# youtube.readonly: read this channel's own metadata (e.g. real total video
# count) - youtube.upload alone doesn't cover reads, even of your own channel.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]

CLIENT_SECRET_FILE = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_FILE = os.environ.get("YOUTUBE_TOKEN_FILE", "token.json")


def _stored_scopes(token_file: str) -> set:
    """What's actually recorded in the token file - NOT the same as reading
    Credentials.scopes after from_authorized_user_file(path, SCOPES), which
    just echoes back whatever SCOPES you pass it rather than the scopes the
    token was really granted under. Only the raw file tells the truth."""
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            return set(json.load(f).get("scopes", []))
    except (OSError, json.JSONDecodeError):
        return set()


def get_credentials() -> Credentials:
    creds = None
    has_required_scopes = False
    if Path(TOKEN_FILE).exists():
        has_required_scopes = set(SCOPES).issubset(_stored_scopes(TOKEN_FILE))
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.valid and has_required_scopes:
        return creds

    if creds and creds.expired and creds.refresh_token and has_required_scopes:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        return creds

    # No cached creds, expired without a usable refresh, or missing a scope
    # that was added since the last login - any of these need a fresh
    # consent screen (refreshing an existing token can't grant new scopes).
    if not Path(CLIENT_SECRET_FILE).exists():
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRET_FILE}. Download OAuth client JSON "
            f"from Google Cloud Console first (see module docstring)."
        )
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    return creds
