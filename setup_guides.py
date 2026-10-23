"""
setup_guides.py
ONE description of what it takes to connect each platform, used by both the dashboard's Accounts tab and `python setup.py`.
For every platform: the steps (with the page to open), the .env keys it needs, and how to check it.

Secrets are only ever written to .env (git-ignored) and are never sent back to the browser: the dashboard only learns whether a key is set.
"""

import json
import os
from pathlib import Path

from dotenv import set_key

BASE = Path(__file__).parent
ENV_FILE = Path(os.environ.get("SHORTS_ENV_FILE") or BASE / ".env")        # tests point this at a throwaway file; never run them against the real .env

# the redirect address you register with TikTok. A page you control, so it loads and can be verified; the publish_legal_pages.py script makes one.
GUIDES = {
    "youtube": {
        "label": "YouTube Shorts", "level": "Easy", "time": "about 10 minutes", "needs": "A Google account that owns the channel.",
        "steps": [
            {"text": "Create a project in Google Cloud.", "url": "https://console.cloud.google.com/projectcreate"},
            {"text": "Turn on the \"YouTube Data API v3\" (and \"YouTube Analytics API\" if you want the Analytics tab).", "url": "https://console.cloud.google.com/apis/library/youtube.googleapis.com"},
            {"text": "OAuth consent screen: choose External, fill the name and your email, then add your own Google account as a Test user.", "url": "https://console.cloud.google.com/apis/credentials/consent"},
            {"text": "Credentials -> Create credentials -> OAuth client ID -> Application type: Desktop app. Download the JSON file.", "url": "https://console.cloud.google.com/apis/credentials"},
            {"text": "Paste the whole contents of that JSON file below and press Save. Then press Log in and approve in the browser window that opens."},
        ],
        "keys": [], "client_secret_file": True, "login": "youtube",
    },
    "meta": {
        "label": "Facebook + Instagram", "level": "Medium", "time": "about 30 minutes", "needs": "A Facebook Page you manage, and an Instagram Professional (Creator or Business) account linked to that Page.",
        "steps": [
            {"text": "Link your Instagram Professional account to your Facebook Page (Page settings -> Linked accounts).", "url": "https://www.facebook.com/pages/?category=your_pages"},
            {"text": "Create an app on Meta for Developers (type: Business). It stays in Development mode: that works for your own Page and account without any review.", "url": "https://developers.facebook.com/apps/creation/"},
            {"text": "App settings -> Basic: copy the App ID and App Secret into the boxes below.", "url": "https://developers.facebook.com/apps/"},
            {"text": "Open the Graph API Explorer, pick your app, and generate a User token with: pages_show_list, pages_manage_posts, pages_read_engagement, instagram_basic, instagram_content_publish, business_management. Tick your Page when asked.", "url": "https://developers.facebook.com/tools/explorer/"},
            {"text": "Paste that token below and press Log in. It is exchanged for a Page token that doesn't expire. Instagram also needs ngrok for a temporary public link to the video: `brew install ngrok`, then `ngrok config add-authtoken ...`.", "url": "https://dashboard.ngrok.com/get-started/your-authtoken"},
        ],
        "keys": [{"env": "META_APP_ID", "label": "App ID", "secret": False}, {"env": "META_APP_SECRET", "label": "App Secret", "secret": True}],
        "login": "meta", "covers": ["facebook", "instagram"],
    },
    "tiktok": {
        "label": "TikTok", "level": "Hard", "time": "30 minutes, then a wait for approval", "needs": "A TikTok account, and a web page you control for the app's terms and privacy pages.",
        "steps": [
            {"text": "Publish the terms/privacy pages (free, on GitHub Pages): run `python publish_legal_pages.py --name \"Your Channel\"`. It prints three addresses: terms, privacy, and the site."},
            {"text": "Create an app on TikTok for Developers. Add the two products: Login Kit and Content Posting API (turn on Direct Post). Add the scopes user.info.basic, video.publish, video.upload.", "url": "https://developers.tiktok.com/apps"},
            {"text": "Fill the terms and privacy addresses. TikTok asks you to verify the site: Manage URL properties -> URL prefix -> download the .txt file, then run `python publish_legal_pages.py --name \"Your Channel\" --verify-file ~/Downloads/tiktok....txt` and press Verify."},
            {"text": "Login Kit -> add the Redirect URI (the site address, with the trailing slash) and put the same address in the box below. Copy the Client key and Client secret into the boxes below."},
            {"text": "Press Get login link, approve in the TikTok page, copy the full address you land on (it contains ?code=...) and paste it back here."},
            {"text": "Until TikTok approves the app (submit it with a screen recording of the flow), every post is private-only, so the app sends each video to your TikTok inbox as a DRAFT: open TikTok and press Post."},
        ],
        "keys": [{"env": "TIKTOK_CLIENT_KEY", "label": "Client key", "secret": False}, {"env": "TIKTOK_CLIENT_SECRET", "label": "Client secret", "secret": True},
                 {"env": "TIKTOK_REDIRECT_URI", "label": "Redirect URI (https, with trailing slash)", "secret": False}],
        "login": "tiktok",
    },
}

ALLOWED_ENV = {k["env"] for g in GUIDES.values() for k in g["keys"]}


def key_state(platform: str) -> list[dict]:
    """Which keys are set - never their values."""
    return [{"env": k["env"], "label": k["label"], "secret": k["secret"], "set": bool((os.environ.get(k["env"]) or "").strip())}
            for k in GUIDES[platform]["keys"]]


def save_keys(platform: str, values: dict) -> list[str]:
    """Writes the given keys to .env (empty values are skipped, so re-saving doesn't wipe a key). Returns the names saved."""
    if platform not in GUIDES:
        raise ValueError("Unknown platform")
    saved = []
    ENV_FILE.touch(exist_ok=True)
    if any((v or "").strip() for v in (values or {}).values()):
        import shutil
        shutil.copy2(ENV_FILE, ENV_FILE.with_name(ENV_FILE.name + ".bak"))        # one backup of the previous .env, so a wrong paste can be undone
    for env_name, value in (values or {}).items():
        value = (value or "").strip()
        if env_name in ALLOWED_ENV and value and env_name in {k["env"] for k in GUIDES[platform]["keys"]}:
            set_key(str(ENV_FILE), env_name, value)
            os.environ[env_name] = value
            saved.append(env_name)
    return saved


def save_client_secret(text: str) -> Path:
    """The Google OAuth client JSON pasted from the console (validated, written to client_secret.json)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("That isn't valid JSON - paste the whole file contents.")
    if not isinstance(data, dict) or not ({"installed", "web"} & set(data)):
        raise ValueError("That JSON doesn't look like an OAuth client file (it should start with {\"installed\": ...}). Make sure you chose 'Desktop app'.")
    path = Path(os.environ.get("YOUTUBE_CLIENT_SECRET_FILE") or BASE / "client_secret.json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
