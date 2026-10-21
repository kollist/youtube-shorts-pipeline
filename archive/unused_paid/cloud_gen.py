"""
cloud_gen.py
Pictures and animated clips made in the cloud (fal.ai) instead of on your Mac - nothing here runs a model locally.
fal.ai is a pay-as-you-go gateway to the strongest video models (Kling 3, Seedance 2.5, ...) with public docs:
https://fal.ai/docs/model-apis/model-endpoints/queue . Needs FAL_KEY in .env and credit on your fal.ai account.

Money: every call costs real money, so animate/generate refuse to start if the estimated total is above
CLOUD_MAX_USD (default 5) - raise it in .env on purpose. Estimates come from public price reports and may be off:
fal's dashboard is the truth. Failed requests aren't charged by fal.

Prices and field names below follow fal's model pages as read in Oct 2026 and have NOT been run against a live account
yet (no key here) - the first real call is the test; if a model rejects a field, the error text says which.
"""

import base64
import mimetypes
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from run_control import check_cancelled

load_dotenv()

QUEUE = os.environ.get("FAL_QUEUE_BASE", "https://queue.fal.run")
REST = os.environ.get("FAL_REST_BASE", "https://rest.alpha.fal.ai")
NEGATIVE = "blur, distortion, low quality, flicker, extra limbs, text, watermark, subtitles"

# image-to-video models: id, the name of the image field, extra fixed inputs, and a rough USD price per second of video
VIDEO_MODELS = {
    "kling": {
        "label": "Kling 3.0 Pro - best motion and faces", "id": "fal-ai/kling-video/v3/pro/image-to-video",
        "image_field": "start_image_url", "usd_per_sec": 0.112, "durations": [3, 15],
        "extra": {"generate_audio": False, "negative_prompt": NEGATIVE, "cfg_scale": 0.5},
    },
    "seedance": {
        "label": "Seedance 2.5 - cinematic, strong prompt following", "id": "bytedance/seedance-2.5/image-to-video",
        "image_field": "image_url", "usd_per_sec": 0.30, "durations": [4, 30],
        "extra": {"generate_audio": False, "resolution": "720p"},
    },
}
IMAGE_MODEL = {"id": "fal-ai/flux/schnell", "usd_per_image": 0.003, "label": "FLUX schnell"}


class CloudError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("FAL_KEY", "").strip())


def max_usd() -> float:
    try:
        return float(os.environ.get("CLOUD_MAX_USD", "5"))
    except ValueError:
        return 5.0


def estimate_video_usd(model: str, seconds: float, clips: int = 1) -> float:
    return round(VIDEO_MODELS[model]["usd_per_sec"] * seconds * clips, 2)


def estimate_image_usd(count: int) -> float:
    return round(IMAGE_MODEL["usd_per_image"] * 0.6 * count, 3)   # ~0.6 megapixel per vertical picture


def check_budget(estimate: float) -> None:
    if estimate > max_usd():
        raise CloudError(f"This would cost about ${estimate:.2f}, above your limit of ${max_usd():.2f} "
                         f"(CLOUD_MAX_USD in .env). Raise it on purpose, or animate fewer scenes.")


def _headers() -> dict:
    return {"Authorization": f"Key {os.environ['FAL_KEY'].strip()}", "Content-Type": "application/json"}


def _data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def _upload(path: Path) -> str:
    """Fallback if a model won't take a data URI: put the file on fal's CDN and use its URL."""
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    r = requests.post(f"{REST}/storage/upload/initiate?storage_type=fal-cdn-v3", headers=_headers(),
                      json={"content_type": mime, "file_name": path.name}, timeout=60)
    if r.status_code != 200:
        raise CloudError(f"fal upload failed ({r.status_code}): {r.text[:200]}")
    info = r.json()
    put = requests.put(info["upload_url"], data=path.read_bytes(), headers={"Content-Type": mime}, timeout=300)
    if put.status_code not in (200, 201):
        raise CloudError(f"fal upload failed ({put.status_code})")
    return info["file_url"]


def _run(model_id: str, body: dict, log=print, cancel_event=None, timeout: int = 1200, label: str | None = None) -> dict:
    """Submit to fal's queue, poll until COMPLETED, return the result JSON."""
    r = requests.post(f"{QUEUE}/{model_id}", headers=_headers(), json=body, timeout=120)
    if r.status_code in (401, 403):
        raise CloudError("fal.ai refused the key (check FAL_KEY, and that the account has credit).")
    if r.status_code == 402:
        raise CloudError("fal.ai says the account is out of credit - top up at fal.ai/dashboard/billing.")
    if r.status_code >= 400:
        raise CloudError(f"fal.ai rejected the request ({r.status_code}): {r.text[:400]}")
    job = r.json()
    deadline = time.time() + timeout
    last = None
    while True:
        check_cancelled(cancel_event)
        s = requests.get(job["status_url"], headers=_headers(), timeout=60).json()
        if s.get("status") != last:
            last = s.get("status")
            log(f"[cloud] {label or model_id}: {last}"
                + (f" (position {s['queue_position']})" if s.get("queue_position") else ""))
        if s.get("status") == "COMPLETED":
            if s.get("error"):
                raise CloudError(f"fal.ai failed the job: {s['error']}")
            break
        if time.time() > deadline:
            raise CloudError("Timed out waiting for fal.ai.")
        time.sleep(3)
    res = requests.get(job["response_url"], headers=_headers(), timeout=120)
    if res.status_code >= 400:
        raise CloudError(f"fal.ai result error ({res.status_code}): {res.text[:300]}")
    return res.json()


def _download(url: str, out: Path) -> Path:
    r = requests.get(url, timeout=600)
    r.raise_for_status()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    return out


def animate(image: Path, prompt: str, out: Path, model: str = "kling", seconds: int = 5, log=print, cancel_event=None) -> Path:
    """One picture -> one short video clip (silent; our own voices and music are added by the video builder)."""
    cfg = VIDEO_MODELS[model]
    lo, hi = cfg["durations"]
    seconds = max(lo, min(hi, int(seconds)))
    body = {**cfg["extra"], "prompt": prompt, "duration": str(seconds), cfg["image_field"]: _data_uri(image)}
    try:
        result = _run(cfg["id"], body, log, cancel_event, label=model)
    except CloudError as e:
        if "image" in str(e).lower() and ("url" in str(e).lower() or "uri" in str(e).lower()):
            log("[cloud] The model wouldn't take the picture inline - uploading it to fal's storage instead...")
            body[cfg["image_field"]] = _upload(image)
            result = _run(cfg["id"], body, log, cancel_event, label=model)
        else:
            raise
    url = (result.get("video") or {}).get("url")
    if not url:
        raise CloudError(f"fal.ai finished but returned no video: {str(result)[:300]}")
    return _download(url, out)


def generate_image(prompt: str, out: Path, width: int = 576, height: int = 1024, seed: int | None = None,
                   log=print, cancel_event=None) -> Path:
    body = {"prompt": prompt, "image_size": {"width": width, "height": height}, "num_images": 1,
            "enable_safety_checker": True, "output_format": "png"}
    if seed is not None:
        body["seed"] = seed
    result = _run(IMAGE_MODEL["id"], body, log, cancel_event, timeout=300, label="picture")
    images = result.get("images") or []
    if not images:
        raise CloudError(f"fal.ai returned no picture: {str(result)[:300]}")
    return _download(images[0]["url"], out)


def motion_clip_path(ep_dir, scene: int) -> Path:
    return Path(ep_dir) / "motion" / f"scene{scene}.mp4"


def motion_clips(ep_dir) -> list[int]:
    import re
    return sorted(int(m.group(1)) for p in (Path(ep_dir) / "motion").glob("scene*.mp4") if (m := re.fullmatch(r"scene(\d+)\.mp4", p.name)))


def animate_episode(ep_dir: str, scenes: list[int] | None = None, model: str = "kling", seconds: int = 5,
                    redo: bool = False, log=print, cancel_event=None) -> list[int]:
    """Animates the chosen scenes (default: every scene that has a picture and no clip yet) into <episode>/motion/sceneN.mp4.
    The video builder uses those clips instead of its camera-drift animation. Returns the scene numbers made."""
    import json
    import wan_bridge
    if not available():
        raise CloudError("Add your fal.ai key to .env as FAL_KEY first (fal.ai/dashboard/keys), and some credit to the account.")
    ep = Path(ep_dir)
    story = json.loads((ep / "story.json").read_text(encoding="utf-8"))
    todo = [i for i, sc in enumerate(story["scenes"], 1)
            if (ep / sc["image"]).exists() and (scenes is None or i in scenes) and (redo or scenes is not None or not motion_clip_path(ep, i).exists())]
    if not todo:
        log("[cloud] Nothing to animate - make the pictures first, or every scene already has a clip.")
        return []
    estimate = estimate_video_usd(model, seconds, len(todo))
    check_budget(estimate)
    log(f"[cloud] Animating {len(todo)} scene(s) with {VIDEO_MODELS[model]['label']}, {seconds}s each - estimated cost about "
        f"${estimate:.2f} (limit ${max_usd():.2f}).")
    made = []
    for n, i in enumerate(todo, 1):
        check_cancelled(cancel_event)
        scene = story["scenes"][i - 1]
        prompt = wan_bridge.motion_prompt(scene, i - 1)
        log(f"[cloud] Scene {i} ({n}/{len(todo)})...")
        t0 = time.time()
        out = animate(ep / scene["image"], prompt, motion_clip_path(ep, i), model, seconds, log, cancel_event)
        out.with_suffix(".json").write_text(json.dumps({"tool": VIDEO_MODELS[model]["label"], "model_id": VIDEO_MODELS[model]["id"],
                                                          "provider": "fal.ai", "seconds": seconds, "prompt": prompt}, indent=1))
        log(f"[cloud] Scene {i} done in {time.time() - t0:.0f}s -> {out.name}")
        made.append(i)
    return made
