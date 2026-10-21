"""
openrouter_llm.py
Free models on OpenRouter (https://openrouter.ai/collections/free-models) as a script-writing provider. They're stronger
writers than the small Groq models we fall back on, but free usage is rate-limited (about 20 requests a minute and a daily
cap), so the list below is tried in order and the app falls through to Groq if they all refuse.
Needs OPENROUTER_API_KEY in .env. No images or video here - OpenRouter has no free models that make them.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

URL = "https://openrouter.ai/api/v1/chat/completions"
# Tried in this order; override with OPENROUTER_MODELS="a:free,b:free" in .env. Free model names change often.
DEFAULT_MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-super-vl:free",
]


def available() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def models() -> list[str]:
    raw = os.environ.get("OPENROUTER_MODELS", "")
    return [m.strip() for m in raw.split(",") if m.strip()] or DEFAULT_MODELS


class OpenRouterError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    """Models sometimes wrap JSON in prose or code fences, or think out loud first - take the outermost {...}."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise OpenRouterError("no JSON object in the reply")
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str, model: str, max_tokens: int = 4096, timeout: int = 90) -> dict:
    body = json.dumps({
        "model": model, "temperature": 0.7, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY'].strip()}", "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000", "X-Title": "Shorts studio"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise OpenRouterError(f"{model}: HTTP {e.code} {e.read().decode('utf-8', 'ignore')[:200]}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise OpenRouterError(f"{model}: {e}")
    if "error" in data:
        raise OpenRouterError(f"{model}: {str(data['error'])[:200]}")
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    try:
        return _extract_json(content)
    except (OpenRouterError, json.JSONDecodeError) as e:
        raise OpenRouterError(f"{model}: unusable reply ({e})")


def chat_json_any(system: str, user: str, log=print) -> tuple[dict, str]:
    """First free model that answers with usable JSON. Returns (json, model_used)."""
    last = None
    for model in models():
        try:
            t0 = time.time()
            out = chat_json(system, user, model)
            log(f"[openrouter] {model} answered in {time.time() - t0:.0f}s")
            return out, model
        except OpenRouterError as e:
            last = e
            log(f"[openrouter] skipped - {e}")
    raise OpenRouterError(f"every free model failed; last: {last}")
