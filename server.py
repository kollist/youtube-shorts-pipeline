"""
server.py
Web UI for the pipeline: run it from a browser instead of the CLI, watch
each step's output stream in live as it runs, and upload finished clips to
YouTube individually once they land in the clips panel.

Usage:
    ./venv/bin/python server.py
    -> open http://localhost:8000
"""

import asyncio
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import traceback
from base64 import b64decode
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

load_dotenv()

from pipeline import run_pipeline
from select_clips import (
    DEFAULT_MAX_DURATION,
    DEFAULT_MIN_DURATION,
    MODEL_FALLBACK_CHAIN,
    build_performance_hint,
    build_system_prompt,
    build_user_prompt,
    load_transcript,
    parse_clips_json,
    save_plan,
    validate_clips,
)
from transcribe import transcribe as run_transcribe, save_transcript
from cut_clips import make_split_screen_variant, process_all_clips
from upload_youtube import upload_from_meta_file, YouTubeUploadLimitExceeded
from token_budget import all_usage_today
from clip_log import read_log
from discover import discover, discover_filler_candidates
from youtube_analytics import fetch_video_stats, get_channel_stats
from queue_daily import SUPPORTED_EXTENSIONS, run_daily_queue
from download import download_video
from run_control import RunCancelled

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"
CLIPS_DIR = BASE_DIR / "clips"
FILLER_DIR = BASE_DIR / "filler"
INPUT_THUMB_DIR = INPUT_DIR / ".thumbnails"
FILLER_THUMB_DIR = FILLER_DIR / ".thumbnails"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
TRANSCRIPTS_DIR.mkdir(exist_ok=True)
CLIPS_DIR.mkdir(exist_ok=True)
FILLER_DIR.mkdir(exist_ok=True)
INPUT_THUMB_DIR.mkdir(exist_ok=True)
FILLER_THUMB_DIR.mkdir(exist_ok=True)

# HTTP Basic Auth for the whole app - there's otherwise no login of any kind,
# and this server is meant to also be reachable through a public tunnel (see
# run_public_tunnel.sh), so it can't be left wide open to anyone with the
# link. Credentials persist in .env (gitignored) so they survive restarts;
# generated once on first run if not already set.
WEB_UI_USERNAME = os.environ.get("WEB_UI_USERNAME", "admin")
WEB_UI_PASSWORD = os.environ.get("WEB_UI_PASSWORD")
if not WEB_UI_PASSWORD:
    WEB_UI_PASSWORD = secrets.token_urlsafe(9)
    with (BASE_DIR / ".env").open("a") as f:
        f.write(f"\nWEB_UI_USERNAME={WEB_UI_USERNAME}\nWEB_UI_PASSWORD={WEB_UI_PASSWORD}\n")
    print(f"[server] Generated web UI login - username: {WEB_UI_USERNAME}  password: {WEB_UI_PASSWORD}")
    print("[server] Saved to .env - reuse these to log back in next time.")


class BasicAuthMiddleware:
    """Raw ASGI (not BaseHTTPMiddleware) so it can also gate the /ws
    WebSocket handshake, not just regular HTTP requests."""

    def __init__(self, app, username: str, password: str):
        self.app = app
        self.username = username
        self.password = password

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        if self._is_valid(headers.get(b"authorization")):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http":
            response = Response(
                "Authentication required",
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Shorts Pipeline"'},
            )
            await response(scope, receive, send)
        else:
            await receive()  # consume websocket.connect before closing
            await send({"type": "websocket.close", "code": 4401})

    def _is_valid(self, auth_header) -> bool:
        if not auth_header or not auth_header.startswith(b"Basic "):
            return False
        try:
            username, _, password = b64decode(auth_header[6:]).decode().partition(":")
        except Exception:
            return False
        return secrets.compare_digest(username, self.username) and secrets.compare_digest(password, self.password)


app = FastAPI()
app.add_middleware(BasicAuthMiddleware, username=WEB_UI_USERNAME, password=WEB_UI_PASSWORD)
app.mount("/media/output", StaticFiles(directory=OUTPUT_DIR), name="output-media")
app.mount("/media/input-thumbnails", StaticFiles(directory=INPUT_THUMB_DIR), name="input-thumbnails")
app.mount("/media/filler-thumbnails", StaticFiles(directory=FILLER_THUMB_DIR), name="filler-thumbnails")
app.mount("/static", StaticFiles(directory=BASE_DIR / "web_static"), name="static")

run_lock = threading.Lock()


class RunState:
    """Server-side record of the in-progress (or just-finished) run, so a
    page reload - or a second tab - can catch up on what already happened
    and keep watching, instead of the browser's only knowledge of a run
    being tied to the one WebSocket connection that started it."""

    def __init__(self):
        self.active = False
        self.log: list[dict] = []
        self.subscribers: list[asyncio.Queue] = []
        self.cancel_event = threading.Event()

    def start(self):
        self.active = True
        self.log = []
        self.cancel_event.clear()

    def push(self, msg: dict):
        self.log.append(msg)
        for q in self.subscribers:
            q.put_nowait(msg)

    def finish(self):
        self.active = False


run_state = RunState()


class LineStreamer:
    """File-like object that tees writes to the real stdout while also
    recording completed lines into the shared RunState (which fans them out
    to every connected subscriber, not just the one that started the run)."""

    def __init__(self, loop: asyncio.AbstractEventLoop, state: RunState):
        self._loop = loop
        self._state = state
        self._buf = ""

    def write(self, s: str) -> int:
        sys.__stdout__.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._loop.call_soon_threadsafe(self._state.push, {"type": "log", "line": line})
        return len(s)

    def flush(self):
        sys.__stdout__.flush()


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "web_static" / "index.html")


def _ensure_thumbnail(video_path: Path, thumb_dir: Path = INPUT_THUMB_DIR) -> str:
    """Fast-seek a frame out of a local video and cache it, so the Input/Filler
    tabs don't re-run ffmpeg on every request - only for files that don't have
    a cached thumbnail yet, or whose source file changed since."""
    thumb_path = thumb_dir / f"{video_path.stem}.jpg"
    if thumb_path.exists() and thumb_path.stat().st_mtime >= video_path.stat().st_mtime:
        return thumb_path.name

    cmd = [
        "ffmpeg", "-y",
        "-ss", "1",
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", "scale=320:-1",
        str(thumb_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg thumbnail failed for {video_path}:\n{result.stderr[-500:]}")
    return thumb_path.name


def _list_input_files() -> list[dict]:
    files = []
    for path in sorted(INPUT_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            thumb_name = _ensure_thumbnail(path)
            thumbnail = f"/media/input-thumbnails/{thumb_name}"
        except Exception as e:
            print(f"[server] Could not generate thumbnail for {path.name}: {e}")
            thumbnail = None
        transcript_path = TRANSCRIPTS_DIR / f"{path.stem}.json"
        plan_path = CLIPS_DIR / f"{path.stem}_plan.json"
        plan_clip_count = None
        if plan_path.exists():
            try:
                with open(plan_path, "r", encoding="utf-8") as f:
                    plan_clip_count = len(json.load(f))
            except (json.JSONDecodeError, OSError):
                plan_clip_count = None

        files.append({
            "filename": path.name,
            "stem": path.stem,
            "path": str(path),
            "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
            "thumbnail": thumbnail,
            "has_transcript": transcript_path.exists(),
            "plan_clip_count": plan_clip_count,
        })
    return files


@app.get("/api/input-files")
async def input_files():
    """Video files already sitting in input/ - from a past download, or
    dropped in manually - so they can be run without fetching them again."""
    loop = asyncio.get_event_loop()
    files = await loop.run_in_executor(None, _list_input_files)
    return {"files": files}


def _delete_input_file(path: Path) -> None:
    """Removes a video from input/ along with everything keyed off its stem -
    the cached thumbnail, transcript, and clip plan - since none of those mean
    anything once the source video is gone. Clips already cut to output/ are
    left alone, same as clear_all_clips leaves the source video untouched the
    other way around."""
    stem = path.stem
    path.unlink()
    thumb_path = INPUT_THUMB_DIR / f"{stem}.jpg"
    if thumb_path.exists():
        thumb_path.unlink()
    transcript_path = TRANSCRIPTS_DIR / f"{stem}.json"
    if transcript_path.exists():
        transcript_path.unlink()
    plan_path = CLIPS_DIR / f"{stem}_plan.json"
    if plan_path.exists():
        plan_path.unlink()


@app.delete("/api/input-files/{filename}")
async def delete_input_file(filename: str):
    path = INPUT_DIR / Path(filename).name  # strip any directory components
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    _delete_input_file(path)
    return {"deleted": filename}


@app.delete("/api/input-files")
async def delete_all_input_files():
    """Clears out every video in input/ at once, along with each one's
    thumbnail/transcript/plan - for starting a clean slate rather than
    deleting a long list one at a time."""
    deleted = []
    for path in sorted(INPUT_DIR.glob("*")):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        _delete_input_file(path)
        deleted.append(path.name)
    return {"deleted": deleted}


def _list_filler_files() -> list[dict]:
    files = []
    for path in sorted(FILLER_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            thumb_name = _ensure_thumbnail(path, thumb_dir=FILLER_THUMB_DIR)
            thumbnail = f"/media/filler-thumbnails/{thumb_name}"
        except Exception as e:
            print(f"[server] Could not generate thumbnail for {path.name}: {e}")
            thumbnail = None
        files.append({
            "filename": path.name,
            "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
            "thumbnail": thumbnail,
        })
    return files


@app.get("/api/filler-files")
async def filler_files():
    """Gameplay/background clips sitting in filler/ - your own footage, used
    as the bottom half of the split-screen clip layout (see cut_clips.py's
    make_split_screen_variant). Never auto-populated from the internet."""
    loop = asyncio.get_event_loop()
    files = await loop.run_in_executor(None, _list_filler_files)
    return {"files": files}


@app.post("/api/upload-filler")
async def upload_filler(file: UploadFile = File(...)):
    dest = FILLER_DIR / Path(file.filename).name  # strip any directory components
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dest)}


@app.delete("/api/filler-files/{filename}")
async def delete_filler_file(filename: str):
    path = FILLER_DIR / Path(filename).name  # strip any directory components
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    path.unlink()
    thumb_path = FILLER_THUMB_DIR / f"{path.stem}.jpg"
    if thumb_path.exists():
        thumb_path.unlink()
    return {"deleted": filename}


@app.get("/api/discover-filler")
async def discover_filler(q: str = "minecraft parkour gameplay no copyright"):
    """Search results for filler/background footage candidates - NOT
    rights-verified like the main Discover tab's curated channels. Showing up
    here isn't permission to use it; check the source channel's own license
    before downloading anything."""
    loop = asyncio.get_event_loop()
    try:
        videos = await loop.run_in_executor(None, lambda: discover_filler_candidates(q))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"videos": videos}


@app.get("/api/discover-input")
async def discover_input(q: str):
    """Plain keyword search for source videos to bring into input/ - same
    underlying YouTube search as the Filler tab's Discover (not the
    rights-verified curated Discover tab), just without a filler-specific
    default query. Showing up here isn't permission to use it; check the
    source's own license before using or downloading anything."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Enter something to search for.")
    loop = asyncio.get_event_loop()
    try:
        videos = await loop.run_in_executor(None, lambda: discover_filler_candidates(q))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"videos": videos}


@app.get("/api/input-file/{stem}/transcript")
async def get_input_transcript(stem: str):
    transcript_path = TRANSCRIPTS_DIR / f"{stem}.json"
    if not transcript_path.exists():
        raise HTTPException(status_code=404, detail="No transcript yet for this file.")
    segments = load_transcript(str(transcript_path))
    text = " ".join(s["text"].strip() for s in segments)
    return {"segments": segments, "text": text}


@app.get("/api/input-file/{stem}/prompt")
async def get_input_prompt(
    stem: str,
    max_clips: int = 8,
    min_duration: float = DEFAULT_MIN_DURATION,
    max_duration: float = DEFAULT_MAX_DURATION,
):
    """The exact prompt this pipeline would send to Groq, built over the
    FULL transcript in one piece (no chunking) - meant for pasting into a
    more capable outside model that doesn't need our free-tier-driven
    per-request token limits, not for us to call automatically."""
    transcript_path = TRANSCRIPTS_DIR / f"{stem}.json"
    if not transcript_path.exists():
        raise HTTPException(status_code=400, detail="Transcribe this file first - the prompt needs the transcript.")
    segments = load_transcript(str(transcript_path))
    return {
        "system": build_system_prompt(min_duration, max_duration, build_performance_hint()),
        "user": build_user_prompt(segments, max_clips),
    }


@app.post("/api/input-file/{stem}/plan")
async def post_input_plan(stem: str, payload: dict):
    """Turns a pasted JSON response (from an outside model, given the prompt
    above) into a real, validated clip plan - same timestamp-snapping and
    duration checks the automated selection path uses, so a plan from any
    source gets the same guarantees before it's cut/uploaded."""
    raw = payload.get("raw", "")
    if not raw or not raw.strip():
        raise HTTPException(status_code=400, detail="Paste the model's JSON response first.")

    transcript_path = TRANSCRIPTS_DIR / f"{stem}.json"
    if not transcript_path.exists():
        raise HTTPException(status_code=400, detail="Transcribe this file first - validating timestamps needs the transcript.")
    segments = load_transcript(str(transcript_path))

    try:
        clips = parse_clips_json(raw)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    validated = validate_clips(clips, segments)
    if not validated:
        raise HTTPException(
            status_code=400,
            detail="None of the pasted clips passed validation (bad/misaligned timestamps, "
                   "too short, or over the 180s Shorts limit).",
        )

    plan_path = save_plan(stem, validated, out_dir=str(CLIPS_DIR))
    return {"clips": validated, "plan_path": plan_path}


@app.get("/api/discover")
async def discover_videos():
    loop = asyncio.get_event_loop()
    try:
        videos = await loop.run_in_executor(None, discover)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"videos": videos}


@app.get("/api/token-budget")
async def token_budget_status():
    usage = all_usage_today(MODEL_FALLBACK_CHAIN)
    # Report in fallback-chain order so the UI shows the model actually in
    # use first, with the models it'll fall back to after it.
    models = [
        {"model": m, **usage[m]}
        for m in MODEL_FALLBACK_CHAIN
        if m in usage
    ]
    return {"models": models}


@app.get("/api/analytics")
async def analytics():
    """Local upload log (title, hook_mechanic, duration - things only we
    know, since YouTube has no concept of "hook_mechanic") enriched with
    real view/retention numbers from the YouTube Analytics API wherever
    that's available. Degrades to local-only numbers (counts, no
    views/retention) if the API isn't enabled yet or a video is too recent
    for YouTube to have processed stats for."""
    records = read_log()
    video_ids = [r["video_id"] for r in records if r.get("video_id")]

    loop = asyncio.get_event_loop()
    stats: dict = {}
    live_data_available = False
    if video_ids:
        try:
            stats = await loop.run_in_executor(None, fetch_video_stats, video_ids)
            live_data_available = True
        except Exception as e:
            print(f"[server] Live YouTube stats unavailable, showing local data only: {e}")

    # The real channel-wide count, straight from YouTube - not len(records),
    # which only knows about clips uploaded through this pipeline since local
    # logging was added, not the channel's actual full history.
    channel_video_count = None
    try:
        channel_stats = await loop.run_in_executor(None, get_channel_stats)
        channel_video_count = channel_stats["video_count"]
    except Exception as e:
        print(f"[server] Could not fetch real channel video count: {e}")

    mechanic_buckets: dict = {}
    for r in records:
        hm = r.get("hook_mechanic", "unknown")
        bucket = mechanic_buckets.setdefault(
            hm, {"count": 0, "views_sum": 0, "pct_sum": 0.0, "with_stats": 0}
        )
        bucket["count"] += 1
        s = stats.get(r.get("video_id"))
        if s:
            bucket["views_sum"] += s["views"]
            bucket["pct_sum"] += s["avg_view_percentage"]
            bucket["with_stats"] += 1

    hook_mechanics = []
    for hm, b in mechanic_buckets.items():
        entry = {"hook_mechanic": hm, "count": b["count"]}
        if b["with_stats"]:
            entry["avg_views"] = round(b["views_sum"] / b["with_stats"], 1)
            entry["avg_view_percentage"] = round(b["pct_sum"] / b["with_stats"], 1)
        hook_mechanics.append(entry)

    recent = sorted(records, key=lambda r: r.get("uploaded_at", ""), reverse=True)[:15]
    for r in recent:
        s = stats.get(r.get("video_id"))
        if s:
            r["views"] = s["views"]
            r["avg_view_percentage"] = s["avg_view_percentage"]

    # A verdict, not just a chart - which mechanic actually wins, and by how
    # much, plus the concrete best/worst clip to go study. Needs >=2 records
    # with real stats to say anything meaningful; otherwise these stay null
    # and the UI explains why rather than showing an empty comparison.
    records_with_stats = [
        {**r, **stats[r["video_id"]]}
        for r in records
        if r.get("video_id") in stats
    ]

    mechanic_insight = None
    ranked_mechanics = sorted(
        (h for h in hook_mechanics if h.get("avg_view_percentage") is not None),
        key=lambda h: h["avg_view_percentage"],
        reverse=True,
    )
    if len(ranked_mechanics) >= 2 and ranked_mechanics[0]["hook_mechanic"] != ranked_mechanics[-1]["hook_mechanic"]:
        best, worst = ranked_mechanics[0], ranked_mechanics[-1]
        mechanic_insight = {
            "best_mechanic": best["hook_mechanic"],
            "best_pct": best["avg_view_percentage"],
            "worst_mechanic": worst["hook_mechanic"],
            "worst_pct": worst["avg_view_percentage"],
            "gap": round(best["avg_view_percentage"] - worst["avg_view_percentage"], 1),
        }

    best_clip = worst_clip = None
    if records_with_stats:
        best_clip = max(records_with_stats, key=lambda r: r["avg_view_percentage"])
        worst_clip = min(records_with_stats, key=lambda r: r["avg_view_percentage"])
        if best_clip["video_id"] == worst_clip["video_id"]:
            worst_clip = None  # only one data point - nothing to contrast

    duration_insight = None
    if len(records_with_stats) >= 4:
        by_duration = sorted(records_with_stats, key=lambda r: r["duration_sec"])
        mid = len(by_duration) // 2
        shorter, longer = by_duration[:mid], by_duration[mid:]
        duration_insight = {
            "shorter_avg_duration": round(sum(r["duration_sec"] for r in shorter) / len(shorter), 1),
            "shorter_avg_pct": round(sum(r["avg_view_percentage"] for r in shorter) / len(shorter), 1),
            "longer_avg_duration": round(sum(r["duration_sec"] for r in longer) / len(longer), 1),
            "longer_avg_pct": round(sum(r["avg_view_percentage"] for r in longer) / len(longer), 1),
        }

    # Cheap, data-driven stand-in for real A/B title testing: YouTube's actual
    # title/thumbnail experiments (Test & compare) aren't available at this
    # channel's size/eligibility tier yet, but we can still correlate title
    # *patterns* already in the wild against real retention - e.g. whether a
    # concrete number in the title (matching the stakes_or_numbers mechanic's
    # own "specific beats vague" logic) actually holds viewers better here.
    title_insight = None
    if len(records_with_stats) >= 4:
        with_number = [r for r in records_with_stats if re.search(r"\d", r.get("title", ""))]
        without_number = [r for r in records_with_stats if not re.search(r"\d", r.get("title", ""))]
        if with_number and without_number:
            title_insight = {
                "with_number_avg_pct": round(sum(r["avg_view_percentage"] for r in with_number) / len(with_number), 1),
                "with_number_count": len(with_number),
                "without_number_avg_pct": round(sum(r["avg_view_percentage"] for r in without_number) / len(without_number), 1),
                "without_number_count": len(without_number),
            }

    # The actual verdict for the split-screen experiment: real retention for
    # the split-screen variant vs the normal layout, so switching the whole
    # channel over (or not) is a decision backed by this channel's own data
    # instead of a guess. Older records predate the "format" field, so they
    # default to "normal" rather than silently vanishing from the comparison.
    format_insight = None
    split_screen = [r for r in records_with_stats if r.get("format") == "split_screen"]
    normal = [r for r in records_with_stats if r.get("format", "normal") == "normal"]
    if split_screen and normal:
        format_insight = {
            "split_screen_avg_pct": round(sum(r["avg_view_percentage"] for r in split_screen) / len(split_screen), 1),
            "split_screen_count": len(split_screen),
            "normal_avg_pct": round(sum(r["avg_view_percentage"] for r in normal) / len(normal), 1),
            "normal_count": len(normal),
        }

    return {
        "total_uploads": channel_video_count if channel_video_count is not None else len(records),
        "tracked_uploads": len(records),
        "channel_count_available": channel_video_count is not None,
        "live_data_available": live_data_available,
        "records_with_stats": len(records_with_stats),
        "mechanic_insight": mechanic_insight,
        "best_clip": best_clip,
        "worst_clip": worst_clip,
        "duration_insight": duration_insight,
        "title_insight": title_insight,
        "format_insight": format_insight,
        "hook_mechanics": hook_mechanics,
        "recent": recent,
    }


@app.post("/api/stop-run")
async def stop_run():
    """Requests that the in-progress run stop at its next safe checkpoint
    (between Groq chunks/cooldowns, between clip cuts, between spaced-out
    uploads, or between whisper segments) - a live worker thread can't be
    killed outright, so this is cooperative rather than instant."""
    if not run_state.active:
        raise HTTPException(status_code=400, detail="No run is currently active.")
    run_state.cancel_event.set()
    return {"stopping": True}


@app.get("/api/run-status")
async def run_status():
    """Lets a fresh page load (a reload, or a second tab) find out a run is
    already in progress - and catch up on everything it's logged so far -
    instead of just showing idle because no WebSocket message ever told
    this particular page load about it."""
    return {"active": run_state.active, "log": run_state.log}


@app.get("/api/existing-clips")
async def existing_clips(stem: str | None = None):
    """Clips already sitting in output/ from past runs (e.g. after a server
    restart, or clips generated via the CLI) that haven't been uploaded yet -
    uploaded ones are deleted locally once they're live on YouTube. Pass
    ?stem=<input filename stem> to scope this to one input file's clips
    (they're named f"{stem}_clipNN" by cut_clips.py)."""
    clips = []
    for meta_path in sorted(OUTPUT_DIR.glob("*.json")):
        if stem and not meta_path.stem.startswith(f"{stem}_clip"):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        video_path = Path(meta.get("video_path", ""))
        if not video_path.exists():
            continue
        clips.append({
            **meta,
            "meta_path": str(meta_path),
            "url": f"/media/output/{video_path.name}",
        })
    return {"clips": clips}


@app.post("/api/clips/split-screen")
async def create_split_screen_variant(payload: dict):
    """Re-cuts an already-produced clip with a split-screen layout (the real
    content + captions on top, looping gameplay footage on the bottom)
    instead of the normal blurred-backdrop one - a separate clip sitting
    alongside the original, meant to be uploaded and compared against it via
    the Analytics tab rather than committing the whole channel to the new
    look on a guess. Needs at least one clip in filler/ to draw from, unless
    filler_filename picks one explicitly."""
    meta_path = payload.get("meta_path")
    if not meta_path:
        raise HTTPException(status_code=400, detail="meta_path is required")

    filler_filename = payload.get("filler_filename")
    # Strip any directory components - this is a user-facing filename, not a
    # trusted path, and filler/ is the only place it should ever resolve to.
    filler_path = str(FILLER_DIR / Path(filler_filename).name) if filler_filename else None

    loop = asyncio.get_event_loop()
    try:
        new_meta = await loop.run_in_executor(
            None,
            lambda: make_split_screen_variant(
                meta_path,
                input_dir=str(INPUT_DIR),
                transcripts_dir=str(TRANSCRIPTS_DIR),
                out_dir=str(OUTPUT_DIR),
                filler_path=filler_path,
            ),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    video_path = Path(new_meta["video_path"])
    new_meta_path = Path(meta_path).parent / f"{Path(meta_path).stem}_split.json"
    return {
        **new_meta,
        "meta_path": str(new_meta_path),
        "url": f"/media/output/{video_path.name}",
    }


@app.delete("/api/clips")
async def clear_all_clips():
    """Actually deletes every not-yet-uploaded clip sitting in output/ - the
    .mp4, its .json metadata, and its .srt captions if present. (Uploaded
    clips already have no local files by this point - upload_youtube.py
    deletes them right after a successful upload - so this only ever
    destroys clips you decided not to post.) The source video and clip plan
    aren't touched, so a cleared clip can still be re-cut later if wanted."""
    deleted = 0
    for meta_path in sorted(OUTPUT_DIR.glob("*.json")):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}

        video_path_str = meta.get("video_path", "")
        if video_path_str:
            video_path = Path(video_path_str)
            if video_path.exists():
                video_path.unlink()

        srt_path = meta_path.with_suffix(".srt")
        if srt_path.exists():
            srt_path.unlink()

        meta_path.unlink()
        deleted += 1

    return {"deleted": deleted}


@app.post("/api/upload-video")
async def upload_video(file: UploadFile = File(...)):
    dest = INPUT_DIR / file.filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"path": str(dest)}


@app.post("/api/upload-clip")
async def upload_clip(payload: dict):
    meta_path = payload.get("meta_path")
    privacy = payload.get("privacy", "public")
    if not meta_path:
        raise HTTPException(status_code=400, detail="meta_path is required")

    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(None, upload_from_meta_file, meta_path, privacy)
    except YouTubeUploadLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


async def _pump_subscriber(ws: WebSocket, queue: asyncio.Queue):
    """Forward messages from this connection's queue to the browser until
    the run finishes, then unsubscribe - shared by both the connection that
    started the run and any that joined later via 'watch'."""
    try:
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
            if msg["type"] in ("done", "error", "stopped"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        if queue in run_state.subscribers:
            run_state.subscribers.remove(queue)
        await ws.close()


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket):
    await ws.accept()
    config = await ws.receive_json()
    my_queue: asyncio.Queue = asyncio.Queue()

    if config.get("watch"):
        # A page load (reload, or a second tab) that found an active run via
        # /api/run-status and wants to keep watching it, not start a new one.
        if not run_state.active:
            await ws.send_json({"type": "idle"})
            await ws.close()
            return
        run_state.subscribers.append(my_queue)
        await _pump_subscriber(ws, my_queue)
        return

    if not run_lock.acquire(blocking=False):
        await ws.send_json({"type": "error", "message": "A pipeline run is already in progress."})
        await ws.close()
        return

    loop = asyncio.get_event_loop()
    run_state.start()
    run_state.subscribers.append(my_queue)

    def on_clip(meta: dict):
        clip = dict(meta)
        clip["meta_path"] = str(Path(meta["video_path"]).with_suffix(".json"))
        clip["url"] = f"/media/output/{Path(meta['video_path']).name}"
        loop.call_soon_threadsafe(run_state.push, {"type": "clip", "clip": clip})

    def worker():
        old_stdout = sys.stdout
        sys.stdout = LineStreamer(loop, run_state)
        action = config.get("action", "full_run")
        cancel_event = run_state.cancel_event
        try:
            if action == "transcribe":
                # Just the transcription step, on demand - independent of
                # running the full pipeline, so it doesn't cost Groq budget
                # or redo work you don't need yet.
                video_path = config["video_path"]
                segments = run_transcribe(video_path, config.get("whisper_model", "small"), cancel_event=cancel_event)
                transcript_path = save_transcript(video_path, segments)
                loop.call_soon_threadsafe(
                    run_state.push,
                    {"type": "done", "count": 0, "transcript_path": transcript_path},
                )
            elif action == "download":
                # Just fetches a YouTube URL into input/ (or filler/, for
                # background gameplay footage) - no transcription/selection/
                # cutting - so it can be queued up ahead of time and run
                # later from the Input tab.
                target_dir = FILLER_DIR if config.get("target") == "filler" else INPUT_DIR

                def on_progress(percent):
                    loop.call_soon_threadsafe(run_state.push, {"type": "download_progress", "percent": percent})

                video_path = download_video(
                    config["url"], out_dir=str(target_dir), cancel_event=cancel_event, on_progress=on_progress,
                )
                loop.call_soon_threadsafe(
                    run_state.push,
                    {"type": "done", "count": 0, "video_path": video_path},
                )
            elif action == "cut_plan":
                # Cuts clips straight from an existing plan.json (whether it
                # came from our own selection or a pasted external-model
                # result) - skips transcription and selection entirely.
                produced = process_all_clips(
                    config["video_path"],
                    config["plan_path"],
                    transcript_path=config.get("transcript_path"),
                    out_dir=str(OUTPUT_DIR),
                    burn_captions=bool(config.get("burn_captions", True)),
                    on_clip=on_clip,
                    cancel_event=cancel_event,
                )
                loop.call_soon_threadsafe(run_state.push, {"type": "done", "count": len(produced)})
            elif action == "daily_queue":
                # Processes every video in input/ toward a daily clip target
                # in one run, then optionally uploads everything produced,
                # spaced out over the day - see queue_daily.py.
                produced = run_daily_queue(
                    target=int(config.get("target", 20)),
                    whisper_model=config.get("whisper_model", "small"),
                    do_upload=bool(config.get("upload", False)),
                    privacy=config.get("privacy", "public"),
                    spacing_minutes=float(config.get("spacing_minutes", 20.0)),
                    min_duration=float(config.get("min_duration", DEFAULT_MIN_DURATION)),
                    max_duration=float(config.get("max_duration", DEFAULT_MAX_DURATION)),
                    on_clip=on_clip,
                    cancel_event=cancel_event,
                )
                loop.call_soon_threadsafe(run_state.push, {"type": "done", "count": len(produced)})
            else:
                produced = run_pipeline(
                    config["video_path"],
                    max_clips=int(config.get("max_clips", 8)),
                    whisper_model=config.get("whisper_model", "small"),
                    do_upload=False,
                    burn_captions=bool(config.get("burn_captions", True)),
                    min_duration=float(config.get("min_duration", DEFAULT_MIN_DURATION)),
                    max_duration=float(config.get("max_duration", DEFAULT_MAX_DURATION)),
                    on_clip=on_clip,
                    cancel_event=cancel_event,
                )
                loop.call_soon_threadsafe(run_state.push, {"type": "done", "count": len(produced)})
        except RunCancelled:
            loop.call_soon_threadsafe(run_state.push, {"type": "stopped"})
        except Exception as e:
            traceback.print_exc()
            loop.call_soon_threadsafe(run_state.push, {"type": "error", "message": str(e)})
        finally:
            sys.stdout = old_stdout
            run_lock.release()
            run_state.finish()

    threading.Thread(target=worker, daemon=True).start()
    await _pump_subscriber(ws, my_queue)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
