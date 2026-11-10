"""
test_accounts.py - checks that a second account can never use the main account's channels. Run: python test_accounts.py
Everything happens in a throwaway folder; the real .env, tokens and posts are never touched.
"""
import json
import os
import tempfile
from pathlib import Path

tmp = Path(tempfile.mkdtemp(prefix="acct-test-"))
os.environ["SHORTS_ENV_FILE"] = str(tmp / ".env")
os.environ["FACEBOOK_PAGE_ID"] = "MAIN_PAGE"
os.environ["FACEBOOK_PAGE_ACCESS_TOKEN"] = "MAIN_PAGE_TOKEN"
os.environ["INSTAGRAM_USER_ID"] = "MAIN_IG"
os.environ["META_APP_ID"] = "SHARED_APP"
os.environ["TIKTOK_CLIENT_KEY"] = "SHARED_TT_KEY"

import accounts
import social_common
import social_facebook
import social_post
import setup_guides

accounts.BASE = tmp
accounts.REGISTRY = tmp / "data" / "accounts.json"
accounts.STORIES = tmp / "stories"
social_common.TOKENS_FILE = tmp / "social_tokens.json"
setup_guides.ENV_FILE = tmp / ".env"
(tmp / "stories" / "tales").mkdir(parents=True)
(tmp / "stories" / "tales" / "series.json").write_text(json.dumps({"title": "T", "account": "second"}))
(tmp / "stories" / "plain").mkdir()
(tmp / "stories" / "plain" / "series.json").write_text(json.dumps({"title": "P"}))


def check(cond, what):
    print(("ok    " if cond else "FAIL  ") + what)
    if not cond:
        raise SystemExit(1)


# --- names
check(accounts.clean_name("") == "default" and accounts.clean_name("Default") == "default", "empty / 'default' is the main account")
for bad in ("../x", "a b", "x" * 40, "-x"):
    try:
        accounts.clean_name(bad); check(False, f"refuses {bad!r}")
    except ValueError:
        check(True, f"refuses {bad!r}")

# --- the registry and which series use which account
check(accounts.create("second", "Second Channel")["id"] == "second", "creates an account")
try:
    accounts.create("second"); check(False, "refuses a duplicate")
except ValueError:
    check(True, "refuses a duplicate")
check(accounts.for_series("tales") == "second" and accounts.for_series("plain") == "default" and accounts.for_series("nope") == "default", "a series picks its account (missing = main)")
listing = {a["id"]: a for a in accounts.list_accounts()}
check(list(listing) == ["default", "second"] and listing["second"]["series"] == ["tales"] and listing["second"]["label"] == "Second Channel", "the account list shows labels and series")

# --- keys never cross over
check(social_common.env("FACEBOOK_PAGE_ID") == "MAIN_PAGE", "main account reads its own Page id")
with accounts.use("second"):
    check(social_common.env("FACEBOOK_PAGE_ID") is None, "second account does NOT fall back to the main Page id")
    check(social_common.env("FACEBOOK_PAGE_ACCESS_TOKEN") is None and social_common.env("INSTAGRAM_USER_ID") is None, "... nor its token or Instagram id")
    check(social_common.env("META_APP_ID") == "SHARED_APP", "the developer-app key IS shared")
    check(social_facebook.missing() == ["FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN"], "Facebook shows as not connected for the second account")
check(social_facebook.missing() == [], "main account Facebook unaffected")
check(accounts.current() == "default", "the account context is restored afterwards")

# --- saving keys goes to the account's own file
saved = setup_guides.save_keys("meta", {"META_APP_ID": "OWN_APP"}, "second")
check(saved == ["META_APP_ID"] and (tmp / ".env.second").exists(), "keys for the second account go to .env.second")
check(os.environ["META_APP_ID"] == "SHARED_APP" and "OWN_APP" not in (tmp / ".env").read_text() if (tmp / ".env").exists() else True, "... and not into the main .env or the shared environment")
with accounts.use("second"):
    check(social_common.env("META_APP_ID") == "OWN_APP", "an own app key overrides the shared one")
(tmp / ".env.second").write_text((tmp / ".env.second").read_text() + "FACEBOOK_PAGE_ID=SECOND_PAGE\nFACEBOOK_PAGE_ACCESS_TOKEN=SECOND_TOKEN\n")
with accounts.use("second"):
    check(social_common.env("FACEBOOK_PAGE_ID") == "SECOND_PAGE" and social_facebook.missing() == [], "after login the second account reads its own Page")
check(social_common.env("FACEBOOK_PAGE_ID") == "MAIN_PAGE", "main account still reads the main Page")
ks = {k["env"]: k for k in setup_guides.key_state("tiktok", "second")}
check(ks["TIKTOK_CLIENT_KEY"]["inherited"] and ks["TIKTOK_CLIENT_KEY"]["set"], "an unset app key shows as inherited from the main account")

# --- tokens and the YouTube login are separate
social_common.save_token("tiktok", {"access_token": "MAIN"})
with accounts.use("second"):
    check(social_common.load_token("tiktok") is None, "second account has no TikTok login of its own yet")
    social_common.save_token("tiktok", {"access_token": "SECOND"})
check(social_common.load_token("tiktok")["access_token"] == "MAIN", "the main TikTok login is untouched")
with accounts.use("second"):
    check(social_common.load_token("tiktok")["access_token"] == "SECOND", "the second TikTok login is its own")
store = json.loads(social_common.TOKENS_FILE.read_text())
check(set(store) == {"tiktok", "tiktok@second"}, "tokens are stored under separate names")
import google_auth
with accounts.use("second"):
    check(google_auth.token_file_for_account().endswith("token.second.json"), "second account has its own YouTube token file")
check(google_auth.token_file_for_account() == google_auth.TOKEN_FILE, "main account keeps the original token file")
with accounts.use("second"):
    yt = social_post.youtube_missing()
check(bool(yt) and "login" in yt[0], "YouTube is 'not connected' for the second account until it has logged in (never opens a consent window mid-post)")

# --- a post really goes through the account it was asked for
seen = []


def fake_post(video_path, caption, **_):
    seen.append((social_common.env("FACEBOOK_PAGE_ID"), social_common.env("FACEBOOK_PAGE_ACCESS_TOKEN")))
    return {"id": "1", "url": "u"}


social_facebook.post = fake_post
social_post.MODULES["facebook"] = social_facebook
social_post.video_seconds = lambda p: 30.0
social_common.SOCIAL_LOG = tmp / "social_log.jsonl"
r = social_post.post_video("x.mp4", "t", "d", ["facebook"], account="second")
check(r["all_ok"] and seen[-1] == ("SECOND_PAGE", "SECOND_TOKEN") and r["account"] == "second", "post_video(account='second') posts with the second Page")
r = social_post.post_video("x.mp4", "t", "d", ["facebook"])
check(r["all_ok"] and seen[-1] == ("MAIN_PAGE", "MAIN_PAGE_TOKEN") and r["account"] == "default", "post_video() with no account posts with the main Page")
accounts.create("third", "Third")
r = social_post.post_video("x.mp4", "t", "d", ["facebook"], account="third")
check(not r["all_ok"] and "isn't set up" in r["results"]["facebook"]["error"] and len(seen) == 2, "an account that is not connected REFUSES to post (it does not use the main Page)")
log = [json.loads(x) for x in (tmp / "social_log.jsonl").read_text().splitlines()]
check([x["account"] for x in log] == ["second", "default"], "the post log records which account posted")
rows = {p["name"]: p for p in social_post.platform_status("third")}
check(not rows["facebook"]["configured"] and social_post.platform_status()[1]["configured"], "platform_status is per account")
print("\nAll account checks passed.")
