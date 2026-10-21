"""
social_common.py
Shared plumbing for posting to Facebook, Instagram, TikTok and X: reading keys
from .env, a small token store for the platforms that need a login that
refreshes (social_tokens.json), and an HTTP helper with retries and readable
errors.
"""

import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
TOKENS_FILE = Path(os.environ.get("SOCIAL_TOKENS_FILE", BASE_DIR / "social_tokens.json"))
SOCIAL_LOG = BASE_DIR / "social_log.jsonl"


class SocialError(RuntimeError):
    """A platform rejected a request, or something it needed was missing."""


class NotConfigured(SocialError):
    """The keys/login this platform needs aren't set up yet."""


def env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def missing_env(*names: str) -> list[str]:
    return [n for n in names if not env(n)]


# ---- token store (platforms whose login expires and refreshes) ----

def load_token(platform: str) -> dict | None:
    try:
        return json.loads(TOKENS_FILE.read_text(encoding="utf-8")).get(platform)
    except (OSError, json.JSONDecodeError):
        return None


def save_token(platform: str, data: dict) -> None:
    try:
        store = json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        store = {}
    store[platform] = data
    TOKENS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")
    try:
        TOKENS_FILE.chmod(0o600)  # contains refresh tokens
    except OSError:
        pass


# ---- HTTP ----

def http(method: str, url: str, *, retries: int = 3, ok: tuple = (200, 201, 202, 206), **kwargs) -> requests.Response:
    """requests with retries on network errors, 429 and 5xx, and a SocialError
    that carries the platform's own error text on any other failure."""
    kwargs.setdefault("timeout", 120)
    last = None
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, **kwargs)
        except requests.RequestException as e:
            last = f"network error: {e}"
        else:
            if resp.status_code in ok:
                return resp
            last = f"HTTP {resp.status_code}: {resp.text[:600]}"
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
        if attempt < retries - 1:
            time.sleep(2 ** attempt * 2)
    raise SocialError(f"{method} {url.split('?')[0]} failed - {last}")


def wait_until(check, *, every: float, timeout: float, what: str):
    """Calls check() until it returns something truthy (returned), raising on timeout.
    check() raises SocialError itself for a terminal failure."""
    deadline = time.time() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.time() > deadline:
            raise SocialError(f"Timed out waiting for {what}.")
        time.sleep(every)


def log_post(record: dict) -> None:
    """Posts to platforms other than YouTube. Kept apart from upload_log.jsonl on
    purpose: the YouTube analytics join treats every video_id in that file as a
    YouTube video."""
    record = dict(record)
    record.setdefault("posted_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    with open(SOCIAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
