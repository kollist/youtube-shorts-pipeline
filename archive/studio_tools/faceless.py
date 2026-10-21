"""
faceless.py
"Stock-footage video" generator: topic -> script + search keywords (this app's own model chain) ->
MoneyPrinterTurbo (https://github.com/harry0703/MoneyPrinterTurbo, MIT) matches footage from Pexels or your own
clips, speaks the script, adds subtitles + background music, and assembles the video -> faceless/<name>.mp4.
See mpt_bridge.py for how that helper is installed and run.
"""

import json
import re
import shutil
import time
from pathlib import Path

import requests

import mpt_bridge
from run_control import check_cancelled
from series import _llm_json

FACELESS_DIR = Path(__file__).parent / "faceless"

# Friendly names -> the voice ids MoneyPrinterTurbo expects (edge-tts voices, free).
VOICES = {
    "Jenny - US woman, warm": "en-US-JennyNeural-Female",
    "Aria - US woman, confident": "en-US-AriaNeural-Female",
    "Emma - US woman, cheerful": "en-US-EmmaNeural-Female",
    "Guy - US man, passionate": "en-US-GuyNeural-Male",
    "Christopher - US man, calm": "en-US-ChristopherNeural-Male",
    "Brian - US man, casual": "en-US-BrianNeural-Male",
}

SCRIPT_SYSTEM = """You write narration for a short vertical video that is illustrated with stock footage.
Rules: the FIRST sentence is a hook (a surprising fact or a question that makes people stay); short spoken sentences;
no emojis, no hashtags, no stage directions, no "in this video"; concrete and specific; end on a payoff or a question.
Also give 6-10 English search terms for footage, each 1-3 words, concrete and filmable (things you can actually
see: "city skyline night", "hands typing", "ocean waves") - never abstract ideas.
Respond with ONLY this JSON: {"title": "...", "script": "...", "terms": ["...", "..."]}"""


def write_script(topic: str, seconds: int = 45, language: str = "English") -> dict:
    """The model writes the narration and the footage search terms."""
    words = int(seconds * 2.4)
    out = _llm_json(SCRIPT_SYSTEM, f"Topic: {topic}\nLanguage: {language}\nTarget length: about {words} spoken words ({seconds} seconds).")
    script = re.sub(r"\s+", " ", str(out.get("script", ""))).strip()
    terms = [str(t).strip() for t in out.get("terms", []) if str(t).strip()][:10]
    if len(script.split()) < 20 or not terms:
        raise RuntimeError("The model's script was too short or had no footage keywords - try again.")
    return {"title": str(out.get("title") or topic)[:90], "script": script, "terms": terms}


def _upload_local(path: Path) -> str:
    with open(path, "rb") as f:
        r = requests.post(f"{mpt_bridge.MPT_URL}/api/v1/video_materials", files={"file": (path.name, f, "video/mp4")}, timeout=300)
    r.raise_for_status()
    return r.json()["data"]["file"]


def generate(topic: str = "", script: str = "", terms: list[str] | None = None, source: str = "pexels",
             local_files: list[str] | None = None, aspect: str = "9:16", voice: str = "Jenny - US woman, warm",
             music: bool = True, subtitles: bool = True, seconds: int = 45, name: str | None = None,
             log=print, cancel_event=None) -> Path:
    """Returns the finished video's path (faceless/<name>.mp4)."""
    if not (topic or script):
        raise RuntimeError("Give a topic or a script.")
    title = topic or script[:60]
    if not script:
        log(f"[faceless] Writing the script for '{topic}'...")
        written = write_script(topic, seconds)
        script, terms, title = written["script"], written["terms"], written["title"]
        log(f"[faceless] Title: {title}\n[faceless] Script: {script}\n[faceless] Footage terms: {', '.join(terms)}")
    check_cancelled(cancel_event)

    if source == "pexels" and not mpt_bridge_has_pexels_key():
        raise RuntimeError("Add a free Pexels API key to .env as PEXELS_API_KEY (pexels.com/api), or choose 'my own clips'.")
    log("[faceless] Starting the MoneyPrinterTurbo helper...")
    mpt_bridge.start(log=lambda m: log(f"[faceless] {m}"))

    body = {
        "video_subject": title, "video_script": script, "video_terms": terms or [], "video_aspect": aspect,
        "video_source": source, "voice_name": VOICES.get(voice, voice), "voice_volume": 1.0, "voice_rate": 1.0,
        "bgm_type": "random" if music else "", "bgm_volume": 0.18, "subtitle_enabled": subtitles,
        "subtitle_position": "custom", "custom_position": 68.0, "font_name": "BeVietnamPro-Bold.ttf", "font_size": 64,
        "text_fore_color": "#FFFFFF", "stroke_color": "#000000", "stroke_width": 2.0,
        "video_clip_duration": 4, "video_concat_mode": "random", "video_count": 1,
    }
    if source == "local":
        files = [Path(p) for p in (local_files or [])]
        if not files:
            raise RuntimeError("Pick at least one of your own clips.")
        log(f"[faceless] Sending {len(files)} of your clips to the helper...")
        body["video_materials"] = [{"provider": "local", "url": _upload_local(p), "duration": 0} for p in files]

    r = requests.post(f"{mpt_bridge.MPT_URL}/api/v1/videos", json=body, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"The helper refused the job: {r.text[:400]}")
    task_id = r.json()["data"]["task_id"]
    log(f"[faceless] Job {task_id} started (footage -> voice -> subtitles -> assembly)...")

    last = -1
    started = time.time()
    while True:
        check_cancelled(cancel_event)
        t = requests.get(f"{mpt_bridge.MPT_URL}/api/v1/tasks/{task_id}", timeout=30).json().get("data", {})
        state, progress = t.get("state"), t.get("progress", 0)
        if progress != last:
            log(f"[faceless] {progress}%")
            last = progress
        if state == 1:
            break
        if state == -1:
            raise RuntimeError(f"The helper failed: {t.get('message') or 'see third_party/MoneyPrinterTurbo/helper.log'}")
        if time.time() - started > 1800:
            raise RuntimeError("Timed out after 30 minutes.")
        time.sleep(3)

    final = next(iter(sorted((mpt_bridge.MPT_DIR / "storage" / "tasks" / task_id).glob("final-*.mp4"))), None)
    if final is None:
        raise RuntimeError("The helper finished but its video file is missing.")
    FACELESS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (name or title).lower()).strip("-")[:50] or "video"
    out = FACELESS_DIR / f"{slug}-{time.strftime('%m%d-%H%M')}.mp4"
    shutil.copy(final, out)
    (out.with_suffix(".json")).write_text(json.dumps({"title": title, "script": script, "terms": terms, "source": source,
                                                      "voice": voice, "made_with": "MoneyPrinterTurbo"}, ensure_ascii=False, indent=1))
    log(f"[faceless] Done -> {out}")
    return out


def mpt_bridge_has_pexels_key() -> bool:
    import os
    return bool(os.environ.get("PEXELS_API_KEY", "").strip())


def list_videos() -> list[dict]:
    FACELESS_DIR.mkdir(exist_ok=True)
    rows = []
    for mp4 in sorted(FACELESS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta = {}
        try:
            meta = json.loads(mp4.with_suffix(".json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        rows.append({"file": mp4.name, "title": meta.get("title", mp4.stem), "script": meta.get("script", ""), "size_mb": round(mp4.stat().st_size / 1048576, 1)})
    return rows
