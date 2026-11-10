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
        "account_notes": ["This account has its own YouTube login. Press Log in and sign in with the Google account that owns THIS series' channel (if Google asks which channel, pick this one).",
                          "The Google Cloud project and the OAuth file above are shared. If this is a different Google account, add it as a Test user first (OAuth consent screen -> Test users)."],
    },
    "meta": {
        "label": "Facebook + Instagram", "level": "Medium", "time": "about 30 minutes", "needs": "A Facebook Page you manage, and an Instagram Professional (Creator or Business) account linked to that Page.",
        "steps": [
            {"text": "Link your Instagram Professional account to your Facebook Page (Page settings -> Linked accounts).", "url": "https://www.facebook.com/pages/?category=your_pages"},
            {"text": "Create an app on Meta for Developers (type: Business). It stays in Development mode: that works for your own Page and account without any review.", "url": "https://developers.facebook.com/apps/creation/"},
            {"text": "App settings -> Basic: copy the App ID and App Secret into the boxes below.", "url": "https://developers.facebook.com/apps/"},
            {"text": "Open the Graph API Explorer, pick your app, and generate a User token with: pages_show_list, pages_manage_posts, instagram_basic, instagram_content_publish, business_management (and pages_read_engagement if your app offers it - a brand-new app often does not, and posting works without it). Tick your Page and its Instagram account when asked.", "url": "https://developers.facebook.com/tools/explorer/"},
            {"text": "Paste that token below and press Log in. It is exchanged for a Page token that doesn't expire. Instagram also needs ngrok for a temporary public link to the video: `brew install ngrok`, then `ngrok config add-authtoken ...`.", "url": "https://dashboard.ngrok.com/get-started/your-authtoken"},
        ],
        "keys": [{"env": "META_APP_ID", "label": "App ID", "secret": False}, {"env": "META_APP_SECRET", "label": "App Secret", "secret": True}],
        "login": "meta", "covers": ["facebook", "instagram"],
        "account_notes": ["The Meta app below is shared. Its App ID and Secret are not saved again here.",
                          "The Facebook account that owns the new Page must be allowed on the app while it is in Development mode: App roles -> Roles -> add that account as a Developer or Tester, and accept the invite. (Or create the Page from the same Facebook profile that owns the app.)",
                          "Generate the User token while logged in as that account and tick the NEW Page and its Instagram account. Page ID: type the new Page's ID if the login manages several Pages.",
                          "Link the new Instagram Professional account to the new Page first (Page settings -> Linked accounts)."],
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
        "account_notes": ["The TikTok app is shared: its keys are not entered again. Press Get login link, and approve with the NEW TikTok account (log out of the other one in that browser first).",
                          "While the app is unaudited, the new TikTok account may need to be added as a target user in the app's Sandbox settings. Posts arrive in that account's inbox as drafts, as for the main account."],
        "keys": [{"env": "TIKTOK_CLIENT_KEY", "label": "Client key", "secret": False}, {"env": "TIKTOK_CLIENT_SECRET", "label": "Client secret", "secret": True},
                 {"env": "TIKTOK_REDIRECT_URI", "label": "Redirect URI (https, with trailing slash)", "secret": False}],
        "login": "tiktok",
    },
}

ALLOWED_ENV = {k["env"] for g in GUIDES.values() for k in g["keys"]}


def key_state(platform: str, account: str | None = None) -> list[dict]:
    """Which keys are set - never their values. For another account, "inherited" = it has no value of its own and uses the main account's app key
    (one developer app can log in several accounts)."""
    import accounts
    out = []
    for k in GUIDES[platform]["keys"]:
        own = accounts.has_own(k["env"], account)
        shared = bool((os.environ.get(k["env"]) or "").strip())
        out.append({"env": k["env"], "label": k["label"], "secret": k["secret"], "set": own or shared, "inherited": (not own) and shared and accounts.clean_name(account) != accounts.DEFAULT})
    return out


def save_keys(platform: str, values: dict, account: str | None = None) -> list[str]:
    """Writes the given keys to the account's env file (.env for the main account; empty values are skipped, so re-saving doesn't wipe a key). Returns the names saved."""
    import accounts
    if platform not in GUIDES:
        raise ValueError("Unknown platform")
    acct = accounts.clean_name(account)
    target = ENV_FILE if acct == accounts.DEFAULT else accounts.env_file(acct)
    saved = []
    target.touch(exist_ok=True)
    if acct != accounts.DEFAULT:
        try:
            target.chmod(0o600)
        except OSError:
            pass
    if any((v or "").strip() for v in (values or {}).values()):
        import shutil
        shutil.copy2(target, target.with_name(target.name + ".bak"))        # one backup of the previous file, so a wrong paste can be undone
    for env_name, value in (values or {}).items():
        value = (value or "").strip()
        if env_name in ALLOWED_ENV and value and env_name in {k["env"] for k in GUIDES[platform]["keys"]}:
            set_key(str(target), env_name, value)
            if acct == accounts.DEFAULT:
                os.environ[env_name] = value                                   # another account's keys must never leak into the shared environment
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
