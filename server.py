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
import shutil
import sys
import threading
import traceback
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pipeline import run_pipeline
from select_clips import DEFAULT_MAX_DURATION, DEFAULT_MIN_DURATION
from upload_youtube import upload_from_meta_file

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
INPUT_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI()
app.mount("/media/output", StaticFiles(directory=OUTPUT_DIR), name="output-media")
app.mount("/static", StaticFiles(directory=BASE_DIR / "web_static"), name="static")

run_lock = threading.Lock()


class LineStreamer:
    """File-like object that tees writes to the real stdout while also
    pushing completed lines into an asyncio queue for the WebSocket to
    forward to the browser."""

    def __init__(self, loop: asyncio.AbstractEventLoop, out_queue: asyncio.Queue):
        self._loop = loop
        self._queue = out_queue
        self._buf = ""

    def write(self, s: str) -> int:
        sys.__stdout__.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._loop.call_soon_threadsafe(self._queue.put_nowait, {"type": "log", "line": line})
        return len(s)

    def flush(self):
        sys.__stdout__.flush()


@app.get("/")
async def index():
    return FileResponse(BASE_DIR / "web_static" / "index.html")


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return result


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket):
    await ws.accept()
    config = await ws.receive_json()

    if not run_lock.acquire(blocking=False):
        await ws.send_json({"type": "error", "message": "A pipeline run is already in progress."})
        await ws.close()
        return

    loop = asyncio.get_event_loop()
    out_queue: asyncio.Queue = asyncio.Queue()

    def on_clip(meta: dict):
        clip = dict(meta)
        clip["meta_path"] = str(Path(meta["video_path"]).with_suffix(".json"))
        clip["url"] = f"/media/output/{Path(meta['video_path']).name}"
        loop.call_soon_threadsafe(out_queue.put_nowait, {"type": "clip", "clip": clip})

    def worker():
        old_stdout = sys.stdout
        sys.stdout = LineStreamer(loop, out_queue)
        try:
            produced = run_pipeline(
                config["video_path"],
                max_clips=int(config.get("max_clips", 8)),
                whisper_model=config.get("whisper_model", "small"),
                do_upload=False,
                burn_captions=bool(config.get("burn_captions", True)),
                min_duration=float(config.get("min_duration", DEFAULT_MIN_DURATION)),
                max_duration=float(config.get("max_duration", DEFAULT_MAX_DURATION)),
                on_clip=on_clip,
            )
            loop.call_soon_threadsafe(out_queue.put_nowait, {"type": "done", "count": len(produced)})
        except Exception as e:
            traceback.print_exc()
            loop.call_soon_threadsafe(out_queue.put_nowait, {"type": "error", "message": str(e)})
        finally:
            sys.stdout = old_stdout
            run_lock.release()

    threading.Thread(target=worker, daemon=True).start()

    try:
        while True:
            msg = await out_queue.get()
            await ws.send_json(msg)
            if msg["type"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await ws.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
