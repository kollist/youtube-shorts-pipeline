"""
motion_video.py
Free, code-drawn short videos - the kind of thing Claude makes with code (see Downloads/the_yearbook_short.mp4): animated
yearbook pages with generated faces, a phone chat with typing dots, a lock-screen notification, rubber stamps, a zoom into a
face with glowing eyes. No AI image/video model, no GPU, no cost; the only network use is the free edge-tts voice.

A video is a small JSON script ("spec"): scenes with a line of narration and a list of animated elements. Times inside a scene
are fractions (0-1) of that scene's length, because the length comes from how long the narration takes to say.

    python motion_video.py motion_examples/yearbook.json
    -> motion_videos/yearbook/yearbook.mp4

Element types (every element takes "at": 0-1, and optional "anim": fade|slide_up|pop|none):
  text            {"text", "size", "kind": serif_bold|sans_bold|mono|impact..., "color": [r,g,b], "y": 0-1, "align"}
  portrait_grid   {"title", "subtitle", "style": "class"|"year", "people": [{"name","label","seed","gender"}], "cols", "ring": name,
                   "ring_at", "stamps": [{"name","at","text"}], "lines": n, "drift": px}
  chat            {"contact", "avatar_seed", "messages": [{"from": "me"|"them", "text", "at"}]}
  notification    {"time", "date", "app", "sender", "text"}
  face            {"seed", "gender", "expression", "zoom": [z0, z1], "red_eyes_at": 0-1}
  image           {"path", "zoom": [z0, z1]}
  stamp           {"text", "x": 0-1, "y": 0-1, "size", "angle"}
Scene fields: "narration", "min_seconds", "bg": {"type": "paper"|"dark", "tone"/"kind"}, "camera": {"zoom": [z0, z1], "shift": [dx, dy]},
"shake": 0-1, "elements": [...].
"""

import argparse
import json
import math
import re
import subprocess
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

import motion_gfx as g
from run_control import check_cancelled
from series import VOICES
from story_video import (FPS, build_captions, build_voice_track, lay_out_timeline, mix_audio, run,
                         synthesize_lines, synthesize_music)

W, H = g.W, g.H
OUT_DIR = Path(__file__).parent / "motion_videos"


# ------------------------------------------------------------------ animation helpers

def _anim(spec: dict, t: float, start: float, dur: float = 0.5) -> tuple[float, float, float]:
    """(alpha, dy, scale) for an element's entrance at time t."""
    x = (t - start) / max(1e-6, dur)
    if x <= 0:
        return 0.0, 0.0, 1.0
    kind = spec.get("anim", "fade")
    if kind == "none":
        return 1.0, 0.0, 1.0
    if kind == "slide_up":
        e = g.ease_out(x)
        return e, (1 - e) * 70, 1.0
    if kind == "pop":
        e = g.ease_pop(x)
        return g.clamp01(x * 2), 0.0, 0.7 + 0.3 * e
    return g.ease_out(x), 0.0, 1.0


class El:
    def __init__(self, spec: dict, length: float, base: Path):
        self.spec, self.length, self.base = spec, length, base
        self.start = float(spec.get("at", 0.0)) * length

    def draw(self, canvas: Image.Image, t: float) -> None:
        raise NotImplementedError


class Text(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        self.layer = g.text_layer(spec["text"], spec.get("kind", "serif_bold"), int(spec.get("size", 72)), tuple(spec.get("color", (240, 232, 214))),
                                  int(spec.get("max_w", W - 160)), spec.get("align", "center"), int(spec.get("stroke", 0)),
                                  tuple(spec.get("stroke_color", (0, 0, 0))), spacing=int(spec.get("spacing", 0)))
        self.typewriter = bool(spec.get("typewriter"))

    def draw(self, canvas, t):
        a, dy, sc = _anim(self.spec, t, self.start)
        layer = self.layer
        if self.typewriter and a > 0:
            n = int(len(self.spec["text"]) * g.clamp01((t - self.start) / max(0.3, self.spec.get("dur", 1.5))))
            layer = g.text_layer(self.spec["text"][:n] or " ", self.spec.get("kind", "serif_bold"), int(self.spec.get("size", 72)),
                                 tuple(self.spec.get("color", (240, 232, 214))), int(self.spec.get("max_w", W - 160)), self.spec.get("align", "center"))
            a = 1.0
        y = self.spec.get("y", 0.5)
        y = y * H if y <= 1 else y
        g.paste_layer(canvas, layer, (W - layer.width) / 2, y - layer.height / 2 + dy, a, sc)


class PortraitGrid(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        people = spec["people"]
        cols = int(spec.get("cols", 3))
        style = spec.get("style", "class")
        pw = {2: 420, 3: 290, 4: 215}.get(cols, 290)
        ph = int(pw * 1.27)
        gap = 22
        card_h = ph + 12 + 56
        rows = math.ceil(len(people) / cols)
        head_h = 250 if style == "class" else 330
        self.page_h = min(H, head_h + rows * (card_h + gap) + (170 if spec.get("lines") else 40))
        page = Image.new("RGBA", (W, self.page_h), (0, 0, 0, 0))
        title_kind = "serif_bold"
        if style == "class":
            page.alpha_composite(g.text_layer(spec.get("school", "").upper(), "serif", 28, (70, 52, 38), spacing=8, max_w=W - 100), (-20 + 0, 20))
            page.alpha_composite(g.text_layer(spec.get("title", ""), title_kind, 84, (36, 26, 18), max_w=W - 100), (-20, 60))
        else:
            page.alpha_composite(g.text_layer(spec.get("title", ""), title_kind, 150, (36, 26, 18), max_w=W - 100), (-20, 30))
            page.alpha_composite(g.text_layer(spec.get("subtitle", "").upper(), "mono", 38, (70, 52, 38), spacing=10, max_w=W - 100), (-20, 200))
        ImageDrawLine(page, 90, head_h - 24, W - 90, head_h - 24)
        self.slots = {}
        total_w = cols * (pw + 12) + (cols - 1) * gap
        x0 = (W - total_w) // 2
        for i, p in enumerate(people):
            c, r = i % cols, i // cols
            x, y = x0 + c * (pw + 12 + gap), head_h + r * (card_h + gap)
            card = g.portrait_card(p, (pw, ph), expression=p.get("expression", "neutral"))
            page.alpha_composite(card, (x, y))
            self.slots[p["name"]] = (x, y, card.width, ph + 12)
        for k in range(int(spec.get("lines", 0))):
            ln = Image.new("RGBA", (int((W - 240) * (0.55 + 0.45 * ((k * 37) % 5) / 4)), 8), (110, 92, 74, 200))
            page.alpha_composite(ln, (120, head_h + rows * (card_h + gap) + 24 + k * 28))
        self.page = page
        self.ring_name = spec.get("ring")
        self.ring_at = float(spec.get("ring_at", 0.4)) * length
        self.stamps = [(s["name"], float(s.get("at", 0.5)) * length, g.stamp_layer(s.get("text", "MISSING"), size=int(s.get("size", 46)))) for s in spec.get("stamps", [])]
        self.drift = float(spec.get("drift", 0))
        self.y0 = int(spec["y"]) if "y" in spec else max(40, int((H - 380 - self.page_h) / 2))

    def draw(self, canvas, t):
        a, dy, sc = _anim(self.spec, t, self.start, 0.6)
        if a <= 0:
            return
        oy = self.y0 - self.drift * g.clamp01(t / self.length) + dy
        frame = Image.new("RGBA", self.page.size, (0, 0, 0, 0))
        frame.alpha_composite(self.page)
        if self.ring_name and t >= self.ring_at:
            x, y, w, h = self.slots[self.ring_name]
            ring = g.red_ring((int(w * 1.22), int(h * 1.12)), (t - self.ring_at) / 0.9)
            frame.alpha_composite(ring, (int(x - w * 0.11), int(y - h * 0.06)))
        for name, at, layer in self.stamps:
            if t >= at and name in self.slots:
                x, y, w, h = self.slots[name]
                e = g.ease_pop((t - at) / 0.28)
                s = layer.resize((max(1, int(layer.width * (1.9 - 0.9 * e))), max(1, int(layer.height * (1.9 - 0.9 * e)))), Image.BILINEAR)
                al = s.getchannel("A").point(lambda v: int(v * g.clamp01((t - at) / 0.12)))
                s.putalpha(al)
                frame.alpha_composite(s, (int(x + w / 2 - s.width / 2), int(y + h * 0.28 - s.height / 2)))
        g.paste_layer(canvas, frame, 0, oy, a, sc if sc != 1.0 else 1.0)


def ImageDrawLine(page, x0, y0, x1, y1):
    from PIL import ImageDraw
    ImageDraw.Draw(page).line([(x0, y0), (x1, y1)], fill=(50, 36, 26, 230), width=4)


class Chat(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        self.header = g.chat_header(spec.get("contact", "Elias"), int(spec.get("avatar_seed", 1)))
        self.msgs = []
        y = int(spec.get("y", 380))
        for m in spec["messages"]:
            lay = g.bubble_layer(m["text"], m.get("from") == "me", max_w=760, size=52)
            x = W - lay.width - 50 if m.get("from") == "me" else 50
            at = float(m.get("at", 0.3)) * length
            self.msgs.append({"layer": lay, "x": x, "y": y, "at": at, "them": m.get("from") != "me", "typing": float(m.get("typing", 1.1))})
            y += lay.height + 40
        self.stamp_time = spec.get("time_label", "Today 6:12 PM")

    def draw(self, canvas, t):
        a, _, _ = _anim(self.spec, t, self.start, 0.3)
        if a <= 0:
            return
        g.paste_layer(canvas, self.header, 0, 0, a)
        g.paste_layer(canvas, g.text_layer(self.stamp_time, "sans", 28, (140, 144, 156), max_w=600), (W - 640) / 2, 260, a)
        for m in self.msgs:
            if t >= m["at"]:
                e = g.ease_out((t - m["at"]) / 0.3)
                g.paste_layer(canvas, m["layer"], m["x"], m["y"] + (1 - e) * 40, e)
            elif m["them"] and t >= m["at"] - m["typing"]:
                g.paste_layer(canvas, g.typing_dots(t * 1.1), m["x"], m["y"], 1.0)


class Notification(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        self.card = g.notification_card(spec.get("app", "Messages"), spec.get("sender", ""), spec.get("text", ""), spec.get("when", "now"))
        self.clock = g.text_layer(spec.get("time", "11:47"), "sans", 230, (238, 240, 246), max_w=900)
        self.date = g.text_layer(spec.get("date", "Monday, October 19"), "sans", 44, (190, 196, 210), max_w=900)

    def draw(self, canvas, t):
        a = g.ease_out(t / 0.5)
        g.paste_layer(canvas, self.clock, (W - self.clock.width) / 2, 330, a)
        g.paste_layer(canvas, self.date, (W - self.date.width) / 2, 640, a)
        if t >= self.start:
            e = g.ease_pop((t - self.start) / 0.45)
            g.paste_layer(canvas, self.card, 60, 820 - (1 - min(1, e)) * 140, g.clamp01((t - self.start) / 0.25))


class Face(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        size = (940, 1190)
        seed = int(spec.get("seed", 1))
        self.calm = g.draw_portrait(seed, size, spec.get("gender"), "sepia", spec.get("expression", "smile")).convert("RGBA")
        self.red = g.draw_portrait(seed, size, spec.get("gender"), "sepia", spec.get("expression", "smile"), red_eyes=1.0).convert("RGBA")
        yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
        d = np.sqrt(((xx - size[0] / 2) / (size[0] / 2)) ** 2 + ((yy - size[1] / 2) / (size[1] / 2)) ** 2)
        feather = np.clip((1.0 - d) / 0.22, 0, 1)
        for im in (self.calm, self.red):
            im.putalpha(Image.fromarray((np.asarray(im.getchannel("A"), dtype=np.float32) * feather).astype(np.uint8)))
        self.red_at = float(spec.get("red_eyes_at", 2)) * length if spec.get("red_eyes_at") is not None else None
        self.zoom = spec.get("zoom", [1.0, 1.15])

    def draw(self, canvas, t):
        a, _, _ = _anim(self.spec, t, self.start, 0.5)
        if a <= 0:
            return
        z = self.zoom[0] + (self.zoom[1] - self.zoom[0]) * g.ease_in_out(t / self.length)
        layer = self.calm
        if self.red_at is not None and t >= self.red_at:
            k = g.clamp01((t - self.red_at) / 0.35) * (0.82 + 0.18 * math.sin(t * 9))
            layer = Image.blend(self.calm, self.red, g.clamp01(k))
        g.paste_layer(canvas, layer, W / 2, H * 0.47, a, z, center=True)


class ImageEl(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        p = Path(spec["path"])
        im = Image.open(p if p.is_absolute() else base / p).convert("RGB")
        r = max(W / im.width, H / im.height)
        self.im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS).convert("RGBA")
        self.zoom = spec.get("zoom", [1.0, 1.12])

    def draw(self, canvas, t):
        a, _, _ = _anim(self.spec, t, self.start, 0.5)
        z = self.zoom[0] + (self.zoom[1] - self.zoom[0]) * g.ease_in_out(t / self.length)
        g.paste_layer(canvas, self.im, W / 2, H / 2, a, z, center=True)


class StampEl(El):
    def __init__(self, spec, length, base):
        super().__init__(spec, length, base)
        self.layer = g.stamp_layer(spec.get("text", "MISSING"), size=int(spec.get("size", 110)), angle=float(spec.get("angle", -14)))

    def draw(self, canvas, t):
        if t < self.start:
            return
        e = g.ease_pop((t - self.start) / 0.3)
        g.paste_layer(canvas, self.layer, self.spec.get("x", 0.5) * W, self.spec.get("y", 0.5) * H, g.clamp01((t - self.start) / 0.12), 1.8 - 0.8 * e, center=True)


ELEMENTS = {"text": Text, "portrait_grid": PortraitGrid, "chat": Chat, "notification": Notification, "face": Face, "image": ImageEl, "stamp": StampEl}


# ------------------------------------------------------------------ rendering

def _background(spec: dict | None) -> Image.Image:
    spec = spec or {}
    if spec.get("type") == "paper":
        return g.paper_background(int(spec.get("seed", 3)), spec.get("tone", "aged"))
    return g.dark_background(spec.get("kind", "night"))


def render_scene(scene: dict, length: float, base: Path, out: Path, fps: int = FPS, cancel_event=None) -> None:
    bg = _background(scene.get("bg"))
    els = []
    for e in scene.get("elements", []):
        cls = ELEMENTS.get(e.get("type"))
        if cls is None:
            raise RuntimeError(f"Unknown element type '{e.get('type')}'. Choose from: {', '.join(ELEMENTS)}")
        els.append(cls(e, length, base))
    cam = scene.get("camera", {})
    z0, z1 = cam.get("zoom", [1.0, 1.0])
    sx, sy = cam.get("shift", [0, 0])
    shake = float(scene.get("shake", 0))
    vig = g.vignette_mask(float(scene.get("vignette", 0.5)))
    rng = np.random.default_rng(zlib.crc32(out.name.encode()))
    grain = [rng.normal(0, 4, (H, W, 1)).astype(np.float32) for _ in range(3)]
    frames = int(math.ceil(length * fps))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-an", "-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for f in range(frames):
            check_cancelled(cancel_event)
            t = f / fps
            canvas = bg.convert("RGBA")
            for el in els:
                el.draw(canvas, t)
            frame = canvas.convert("RGB")
            p = g.ease_in_out(t / length)
            z = z0 + (z1 - z0) * p
            ox, oy = sx * p, sy * p
            if shake:
                ox += math.sin(t * 37) * 7 * shake + math.sin(t * 91) * 3 * shake
                oy += math.cos(t * 41) * 7 * shake
            if abs(z - 1) > 1e-4 or ox or oy:
                frame = frame.transform((W, H), Image.AFFINE, (1 / z, 0, W / 2 - W / (2 * z) + ox, 0, 1 / z, H / 2 - H / (2 * z) + oy), Image.BILINEAR)
            arr = np.asarray(frame, dtype=np.float32) * vig + grain[f % 3]
            fade = min(1.0, t / 0.18, (length - t) / 0.18) if length > 0.5 else 1.0
            arr *= (0.9 + 0.1 * math.sin(t * 13)) * g.clamp01(fade) if scene.get("flicker") else g.clamp01(fade)
            proc.stdin.write(np.clip(arr, 0, 255).astype(np.uint8).tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed while encoding a scene")
    finally:
        if proc.poll() is None:
            proc.kill()


def build_motion_video(spec_path: str, out_name: str | None = None, log=print, cancel_event=None, no_music: bool = False) -> Path:
    spec_path = Path(spec_path).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    slug = re.sub(r"[^a-z0-9]+", "-", (spec.get("title") or spec_path.stem).lower()).strip("-")[:48] or "video"
    folder = OUT_DIR / slug
    work = folder / "build"
    work.mkdir(parents=True, exist_ok=True)
    (folder / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    voice = spec.get("voice", "adult_woman")
    story = {"characters": {"Narrator": {**VOICES[voice], "look": ""}}, "music": {"mood": spec.get("music", "eerie")},
             "caption_size": int(spec.get("caption_size", 76)), "caption_words": int(spec.get("caption_words", 5)), "caption_colors": {}, "caption_font": spec.get("caption_font", "Georgia"),
             "scenes": [{"min_seconds": float(s.get("min_seconds", 3.0)),
                         "lines": [{"who": "Narrator", "text": s["narration"]}] if s.get("narration") else []} for s in spec["scenes"]]}
    log("[motion] Speaking the narration...")
    synthesize_lines(story, work / "audio")
    total = lay_out_timeline(story)
    log(f"[motion] {len(spec['scenes'])} scenes, {total:.1f}s total")
    build_voice_track(story, total, work / "voice.wav")
    music = None
    if not no_music:
        music = work / "music.wav"
        synthesize_music(total, music, mood=story["music"]["mood"], seed=__import__("music").seed_from(spec.get("title", "")))
    mix_audio(work / "voice.wav", music, work / "audio.m4a")

    clips = []
    for i, (scene, sc) in enumerate(zip(spec["scenes"], story["scenes"]), 1):
        check_cancelled(cancel_event)
        log(f"[motion] Drawing scene {i}/{len(spec['scenes'])} ({sc['_len']:.1f}s)...")
        clip = work / f"scene{i}.mp4"
        render_scene(scene, sc["_len"], spec_path.parent, clip, cancel_event=cancel_event)
        clips.append(clip)
    (work / "clips.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "clips.txt"), "-c", "copy", str(work / "silent.mp4")])
    build_captions(story, work / "captions.ass")
    final = folder / (out_name or f"{slug}.mp4")
    log("[motion] Adding captions and sound...")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "silent.mp4", "-i", "audio.m4a", "-vf", "subtitles=captions.ass",
                    "-c:v", "libx264", "-crf", "24", "-preset", "medium", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(final)],
                   cwd=work, check=True)
    log(f"[motion] Done -> {final}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--no-music", action="store_true")
    a = ap.parse_args()
    build_motion_video(a.spec, no_music=a.no_music)
