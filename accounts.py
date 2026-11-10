"""
accounts.py
Account profiles: more than one set of social accounts (a second YouTube channel, Facebook Page, Instagram and TikTok) in one dashboard.

  default      the original login: .env, token.json and social_tokens.json exactly as before (nothing to migrate)
  <name>       its own .env.<name> (Page id/token, Instagram id, optional app-key overrides), its own token.<name>.json for YouTube,
               and its own "<platform>@<name>" entries in social_tokens.json

A series names the account it posts to in series.json ("account": "alkhobeer"); no entry = the default account.

Safety rule: a non-default account NEVER falls back to the default account's Page/Instagram ids or tokens - a missing key must mean
"not connected", not "quietly post to the other channel". Only the developer-app keys (Meta app, TikTok app) are shared, because
one app can log in several accounts.

The active account is a context variable, so every function that reads keys (social_common.env/load_token/save_token, google_auth) is
account-aware without changing its signature: wrap a call in `with accounts.use("alkhobeer"):`.
"""

import contextvars
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values

BASE = Path(__file__).parent
DEFAULT = "default"
REGISTRY = BASE / "data" / "accounts.json"            # {"alkhobeer": {"label": "..."}} - names only, no secrets
STORIES = BASE / "stories"

# These identify WHERE a post goes. They are read from the account's own file only, never from the default account.
PER_ACCOUNT_KEYS = {"FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_ACCESS_TOKEN", "INSTAGRAM_USER_ID"}

_current: contextvars.ContextVar[str] = contextvars.ContextVar("account", default=DEFAULT)
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,30}")


def clean_name(name: str | None) -> str:
    """A safe account id (it becomes part of file names). Empty/None = the default account."""
    n = (name or "").strip().lower()
    if not n or n == DEFAULT:
        return DEFAULT
    if not _NAME.fullmatch(n):
        raise ValueError("An account id uses only lowercase letters, digits, - and _ (up to 31 characters), for example: alkhobeer")
    return n


def current() -> str:
    return _current.get()


@contextmanager
def use(name: str | None):
    token = _current.set(clean_name(name))
    try:
        yield
    finally:
        _current.reset(token)


# ---------------------------------------------------------------- where each account keeps things
def env_file(name: str | None = None) -> Path:
    n = clean_name(name) if name is not None else current()
    if n == DEFAULT:
        return Path(os.environ.get("SHORTS_ENV_FILE") or BASE / ".env")
    return BASE / f".env.{n}"


def youtube_token_file(name: str | None = None) -> str | None:
    """None = the default account (google_auth keeps using its own TOKEN_FILE)."""
    n = clean_name(name) if name is not None else current()
    return None if n == DEFAULT else str(BASE / f"token.{n}.json")


def token_key(platform: str) -> str:
    """The key in social_tokens.json."""
    n = current()
    return platform if n == DEFAULT else f"{platform}@{n}"


_cache: dict[str, tuple[float, dict]] = {}


def _file_values(path: Path) -> dict:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]
    vals = {k: (v or "").strip() for k, v in dotenv_values(path).items()}
    _cache[str(path)] = (mtime, vals)
    return vals


def value(name: str) -> str | None:
    """One key for the active account (see the safety rule at the top)."""
    n = current()
    if n == DEFAULT:
        v = os.environ.get(name)
        return v.strip() if v and v.strip() else None
    own = _file_values(env_file(n)).get(name)
    if own:
        return own
    if name in PER_ACCOUNT_KEYS:
        return None
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def has_own(name: str, account: str | None = None) -> bool:
    n = clean_name(account) if account is not None else current()
    if n == DEFAULT:
        return bool((os.environ.get(name) or "").strip())
    return bool(_file_values(env_file(n)).get(name))


# ---------------------------------------------------------------- the list of accounts
def _registry() -> dict:
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def series_accounts() -> dict[str, list[str]]:
    """account id -> the series slugs that post to it (read from stories/*/series.json)."""
    out: dict[str, list[str]] = {}
    for sj in sorted(STORIES.glob("*/series.json")):
        try:
            acct = clean_name(json.loads(sj.read_text(encoding="utf-8")).get("account"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        out.setdefault(acct, []).append(sj.parent.name)
    return out


def list_accounts() -> list[dict]:
    reg, used = _registry(), series_accounts()
    ids = [DEFAULT] + sorted((set(reg) | set(used)) - {DEFAULT})
    return [{"id": i, "label": (reg.get(i) or {}).get("label") or ("Main account" if i == DEFAULT else i), "series": used.get(i, [])} for i in ids]


def create(name: str, label: str = "") -> dict:
    n = clean_name(name)
    if n == DEFAULT:
        raise ValueError("That name is taken: 'default' is the main account.")
    reg = _registry()
    if n in reg:
        raise ValueError(f"The account '{n}' already exists.")
    reg[n] = {"label": (label or n).strip()[:60]}
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": n, "label": reg[n]["label"]}


def for_series(slug: str) -> str:
    """The account a series posts to (series.json "account"); anything missing or invalid = the default account."""
    try:
        return clean_name(json.loads((STORIES / slug / "series.json").read_text(encoding="utf-8")).get("account"))
    except (OSError, json.JSONDecodeError, ValueError):
        return DEFAULT
