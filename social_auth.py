"""
social_auth.py
One-time logins for the platforms that need one. Run each once; tokens that expire
are refreshed automatically afterwards (stored in social_tokens.json, never in git).

  python social_auth.py meta     # Facebook + Instagram: turns a short-lived token into a permanent Page token
  python social_auth.py instagram # re-checks which Instagram account is linked to your Page (no new token needed)
  python social_auth.py tiktok   # TikTok login (paste-the-address flow, because TikTok only accepts https redirects)

.env keys used: META_APP_ID, META_APP_SECRET | TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI
"""

import argparse
import base64
import getpass
import hashlib
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from dotenv import set_key

import social_tiktok
from social_common import BASE_DIR, SocialError, env, http, save_token

ENV_FILE = BASE_DIR / ".env"
GRAPH = os.environ.get("META_GRAPH_BASE", "https://graph.facebook.com/v25.0")
TIKTOK_AUTHORIZE = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_SCOPES = "user.info.basic,video.publish,video.upload"


# ---------------- Meta (Facebook + Instagram) ----------------

def login_meta(user_token: str, app_id: str, app_secret: str, page_id: str | None = None) -> dict:
    """Short-lived user token -> long-lived user token -> that user's Pages, each
    with a Page token that doesn't expire. Saves the chosen Page's id/token (and its
    linked Instagram account, if any) into .env."""
    long_lived = http("GET", f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": app_secret, "fb_exchange_token": user_token,
    }).json()["access_token"]
    pages = http("GET", f"{GRAPH}/me/accounts", params={
        "fields": "id,name,access_token,instagram_business_account", "access_token": long_lived,
    }).json().get("data", [])
    if not pages:
        raise SocialError("This login manages no Facebook Pages. Make sure you ticked the Page when approving "
                          "the permissions (pages_show_list, pages_manage_posts, pages_read_engagement).")
    if page_id:
        pages = [p for p in pages if p["id"] == page_id]
        if not pages:
            raise SocialError(f"Page {page_id} isn't among this login's Pages.")
    elif len(pages) > 1:
        listing = "\n".join(f"  {p['id']}  {p['name']}" for p in pages)
        raise SocialError(f"This login manages {len(pages)} Pages - re-run with --page-id <id>:\n{listing}")
    page = pages[0]
    set_key(str(ENV_FILE), "FACEBOOK_PAGE_ID", page["id"])
    set_key(str(ENV_FILE), "FACEBOOK_PAGE_ACCESS_TOKEN", page["access_token"])
    ig = page.get("instagram_business_account", {}).get("id")
    if ig:
        set_key(str(ENV_FILE), "INSTAGRAM_USER_ID", ig)
    return {"page": page["name"], "page_id": page["id"], "instagram_user_id": ig}


# ---------------- TikTok ----------------

def tiktok_authorize_url(client_key: str, redirect_uri: str, state: str) -> str:
    return TIKTOK_AUTHORIZE + "?" + urlencode({
        "client_key": client_key, "response_type": "code", "scope": TIKTOK_SCOPES,
        "redirect_uri": redirect_uri, "state": state,
    })


def parse_callback(url: str, expected_state: str) -> str:
    q = parse_qs(urlparse(url.strip()).query)
    if q.get("error"):
        raise SocialError(f"Login was refused: {q['error'][0]} {q.get('error_description', [''])[0]}")
    if q.get("state", [None])[0] != expected_state:
        raise SocialError("The address you pasted doesn't match this login attempt (state differs). Start again.")
    if "code" not in q:
        raise SocialError("No 'code' in that address - paste the full address from the browser's address bar.")
    return q["code"][0]


def login_tiktok(redirect_uri: str, pasted_url: str, state: str) -> dict:
    code = parse_callback(pasted_url, state)
    r = http("POST", f"{social_tiktok.API}/v2/oauth/token/", data={
        "client_key": env("TIKTOK_CLIENT_KEY"), "client_secret": env("TIKTOK_CLIENT_SECRET"),
        "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
    if "access_token" not in r:
        raise SocialError(f"TikTok refused the login: {r}")
    save_token("tiktok", {"access_token": r["access_token"], "refresh_token": r["refresh_token"],
                          "open_id": r.get("open_id"), "expires_at": time.time() + int(r["expires_in"])})
    return {"scopes": r.get("scope"), "open_id": r.get("open_id")}



def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("meta")
    m.add_argument("--user-token", help="Short-lived token from Graph API Explorer (or prompted)")
    m.add_argument("--page-id")
    sub.add_parser("instagram")
    sub.add_parser("tiktok")
    args = parser.parse_args()

    try:
        if args.cmd == "meta":
            app_id, secret = env("META_APP_ID"), env("META_APP_SECRET")
            if not (app_id and secret):
                raise SocialError("Set META_APP_ID and META_APP_SECRET in .env first (your app's Settings > Basic page).")
            token = args.user_token or getpass.getpass("Paste the short-lived user token from Graph API Explorer (it won't show as you paste): ").strip()
            out = login_meta(token, app_id, secret, args.page_id)
            print(f"Saved to .env: Page '{out['page']}' ({out['page_id']})"
                  + (f" and its Instagram account {out['instagram_user_id']}." if out["instagram_user_id"] else
                     ". No Instagram professional account is linked to this Page, so Instagram posting won't work yet."))
        elif args.cmd == "instagram":
            page_id, page_token = env("FACEBOOK_PAGE_ID"), env("FACEBOOK_PAGE_ACCESS_TOKEN")
            if not (page_id and page_token):
                raise SocialError("Run `python social_auth.py meta` first.")
            r = http("GET", f"{GRAPH}/{page_id}", params={"fields": "name,instagram_business_account", "access_token": page_token}).json()
            ig = r.get("instagram_business_account", {}).get("id")
            if not ig:
                raise SocialError(f"Meta still shows no Instagram account linked to the Page '{r.get('name')}'. Link it from the Page's own "
                                  "settings (Page -> Settings -> Linked accounts -> Instagram), not just from Accounts Center.")
            set_key(str(ENV_FILE), "INSTAGRAM_USER_ID", ig)
            print(f"Linked: Page '{r.get('name')}' -> Instagram account {ig}. Saved to .env. Test it: python social_post.py test instagram")
        elif args.cmd == "tiktok":
            key, redirect = env("TIKTOK_CLIENT_KEY"), env("TIKTOK_REDIRECT_URI")
            if not (key and env("TIKTOK_CLIENT_SECRET") and redirect):
                raise SocialError("Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in .env first. "
                                  "TikTok only accepts https redirect addresses; register one in your app's Login Kit settings.")
            state = secrets.token_urlsafe(16)
            url = tiktok_authorize_url(key, redirect, state)
            print("Opening TikTok's login page. Approve, and you'll land on your redirect address - the page itself may "
                  "show an error, that's fine.\nCopy the FULL address from the browser's address bar and paste it here.\n\n" + url + "\n")
            webbrowser.open(url)
            out = login_tiktok(redirect, input("Pasted address: "), state)
            print(f"TikTok login saved (scopes: {out['scopes']}). Test it: python social_post.py test tiktok")
    except SocialError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
