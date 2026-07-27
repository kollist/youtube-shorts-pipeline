"""
token_budget.py
Tracks Groq token usage per model against each model's free-tier daily cap,
persisted in .groq_usage.json. Each model on Groq's free tier has its own
independent daily budget, so tracking (and the fallback chain in
select_clips.py) is per-model rather than a single global count. Persisting
to disk means separate runs on the same day share the same budget instead of
each rediscovering the cap via a 429.
"""

import json
from datetime import date
from pathlib import Path

# Free-tier daily token caps per model. These are Groq-set limits that can
# change; a model not listed here falls back to DEFAULT_DAILY_TOKEN_BUDGET.
DEFAULT_DAILY_TOKEN_BUDGET = 100_000
MODEL_DAILY_BUDGETS: dict[str, int] = {
    "llama-3.3-70b-versatile": 100_000,
}

USAGE_FILE = Path(".groq_usage.json")


class GroqBudgetExhausted(RuntimeError):
    """Raised when a call would (or did) exceed a model's free-tier daily token cap."""


def _load() -> dict:
    if USAGE_FILE.exists():
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
        if data.get("date") == str(date.today()):
            data.setdefault("usage", {})
            return data
    return {"date": str(date.today()), "usage": {}}


def _save(data: dict) -> None:
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)


def daily_cap(model: str) -> int:
    return MODEL_DAILY_BUDGETS.get(model, DEFAULT_DAILY_TOKEN_BUDGET)


def record_usage(model: str, tokens: int) -> None:
    if tokens <= 0:
        return
    data = _load()
    data["usage"][model] = data["usage"].get(model, 0) + tokens
    _save(data)


def set_usage(model: str, tokens_used: int) -> None:
    """Overwrite a model's usage with an authoritative value (e.g. parsed
    from Groq's own error message), correcting local drift if calls happened
    outside our tracking (e.g. a stale process still holding pre-tracking
    code in memory - Python doesn't hot-reload)."""
    data = _load()
    data["usage"][model] = max(0, tokens_used)
    _save(data)


def tokens_used_today(model: str) -> int:
    return _load()["usage"].get(model, 0)


def remaining_budget(model: str) -> int:
    return max(0, daily_cap(model) - tokens_used_today(model))


def all_usage_today(models: list[str] | None = None) -> dict:
    """{model: {"used", "cap", "remaining"}} for every model that has recorded
    usage today, plus any explicitly requested models (e.g. the fallback
    chain) even if untouched today - used for the UI's model status list."""
    data = _load()
    tracked = set(data["usage"]) | set(models or [])
    result = {}
    for model in tracked:
        used = data["usage"].get(model, 0)
        cap = daily_cap(model)
        result[model] = {"used": used, "cap": cap, "remaining": max(0, cap - used)}
    return result
