"""
blender_video.py
Free 3D explainer shorts: a scene script drives Blender (installed app, rendered headless on this Mac with its EEVEE engine),
the narration is spoken by edge-tts, and the existing story_video code adds timing, captions and music.

    python blender_video.py blender_scenes/dollar_stack.json            # full render
    python blender_video.py blender_scenes/dollar_stack.json --stills   # a few frames first (about 20 s)

Spec JSON: {"title", "voice", "music", "scene_script": "dollar_stack.py", "caption_size", "scenes": [{"narration", "min_seconds"}]}
The narration decides how long each scene lasts; the scene script receives those timings as build(t).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from run_control import check_cancelled
from series import VOICES
from story_video import (build_captions, build_voice_track, lay_out_timeline, mix_audio, run, synthesize_lines, synthesize_music)

BASE = Path(__file__).parent
OUT_DIR = BASE / "blender_videos"
FPS = 30
CANDIDATES = ["/opt/homebrew/bin/blender", "/Applications/Blender.app/Contents/MacOS/Blender", "/usr/local/bin/blender"]


def find_blender() -> str:
    path = os.environ.get("BLENDER_BIN") or shutil.which("blender") or next((c for c in CANDIDATES if Path(c).exists()), None)
    if not path:
        raise RuntimeError("Blender isn't installed. Install it once with: brew install --cask blender "
                           "(or set BLENDER_BIN in .env to its path).")
    return path


def available() -> bool:
    try:
        find_blender()
        return True
    except RuntimeError:
        return False


def _blender(args: list[str], log, cancel_event=None, done_marker: str = "", frame_total: int = 0) -> None:
    proc = subprocess.Popen([find_blender(), "-b", "-P", str(BASE / "blender_runner.py"), "--", *args],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=BASE)
    tail, ok, last = [], False, 0
    try:
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-25:]
            if done_marker and done_marker in line:
                ok = True
            m = re.match(r"Fra:(\d+)", line)
            if m and frame_total and int(m.group(1)) // 60 > last // 60:
                last = int(m.group(1))
                log(f"[blender] frame {last}/{frame_total}")
            check_cancelled(cancel_event)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    if proc.returncode != 0 or not ok:
        raise RuntimeError("Blender failed:\n" + "\n".join(l for l in tail if l.strip())[-1800:])


def build_blender_video(spec_path: str, stills: bool = False, log=print, cancel_event=None, no_music: bool = False) -> Path:
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    slug = re.sub(r"[^a-z0-9]+", "-", (spec.get("title") or spec_path.stem).lower()).strip("-")[:48] or "video"
    folder = OUT_DIR / slug
    work = folder / "build"
    work.mkdir(parents=True, exist_ok=True)

    voice = spec.get("voice", "adult_man")
    story = {"characters": {"Narrator": {**VOICES[voice], "look": ""}}, "music": {"mood": spec.get("music", "curious")},
             "caption_size": int(spec.get("caption_size", 74)), "caption_words": int(spec.get("caption_words", 5)),
             "caption_colors": spec.get("caption_colors", {}), "caption_font": spec.get("caption_font", "Georgia"),
             "scenes": [{"min_seconds": float(s.get("min_seconds", 3.0)), "lines": [{"who": "Narrator", "text": s["narration"]}]}
                        for s in spec["scenes"]]}
    log("[blender] Speaking the narration...")
    synthesize_lines(story, work / "audio")
    total = lay_out_timeline(story)
    timing = {"scenes": [[round(s["_start"], 3), round(s["_start"] + s["_len"], 3)] for s in story["scenes"]], "total": round(total, 3)}
    (work / "timing.json").write_text(json.dumps(timing))
    script = str((BASE / "blender_scenes" / spec["scene_script"]).resolve())
    log(f"[blender] {len(story['scenes'])} scenes, {total:.1f}s")

    if stills:
        marks = ",".join(f"{(a + b) / 2:.1f}" for a, b in timing["scenes"])
        shots = work / "stills"
        shutil.rmtree(shots, ignore_errors=True)
        _blender([script, str(work / "timing.json"), str(shots), "--stills", marks, "--low"], log, cancel_event, "STILLS_DONE")
        log(f"[blender] Preview frames in {shots}")
        return shots

    frames = work / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    log("[blender] Rendering the 3D scene (this is the slow part)...")
    _blender([script, str(work / "timing.json"), str(frames)], log, cancel_event, "RENDER_DONE", frame_total=int(total * FPS))
    build_voice_track(story, total, work / "voice.wav")
    music = None
    if not no_music:
        music = work / "music.wav"
        synthesize_music(total, music, mood=story["music"]["mood"], seed=__import__("music").seed_from(spec.get("title", "")))
    mix_audio(work / "voice.wav", music, work / "audio.m4a")
    build_captions(story, work / "captions.ass")
    final = folder / f"{slug}.mp4"
    log("[blender] Adding captions and sound...")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS), "-i", "frames/f%04d.png", "-i", "audio.m4a",
                    "-vf", "scale=1080:1920:flags=lanczos,subtitles=captions.ass", "-c:v", "libx264", "-crf", "21", "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(final)], cwd=work, check=True)
    shutil.rmtree(frames, ignore_errors=True)       # the PNG frames are large; the video is the result
    log(f"[blender] Done -> {final}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--stills", action="store_true", help="render one low-res frame per scene first")
    ap.add_argument("--no-music", action="store_true")
    a = ap.parse_args()
    build_blender_video(a.spec, stills=a.stills, no_music=a.no_music)
