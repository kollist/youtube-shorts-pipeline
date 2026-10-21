"""
rules_video.py
Assembles a "Night shift as X - 6 rules" short from stories/rules-*/story.json + its pictures, built to hold attention:
  - frame 1 is a poster (big stylised title over the key art) - no silence, no fade-in
  - a hard cut (a different crop / zoom of the picture) about every 3.4 s
  - a "RULE n" badge that pops in on every rule, with a low hit
  - captions highlighted word by word as the narrator says them (word timings from the voice engine)
  - sound design: a whoosh on every cut, a hit on every rule, a riser and sting for the twist, an eerie bed underneath

    python rules_video.py stories/rules-night-shift-as-a-hotel-receptionist
"""

import argparse
import asyncio
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import edge_tts
import text_layers as g
from music import SR, Track, bell, noise, pluck
from story_video import _silence, _speakable, build_voice_track, probe_duration, run, synthesize_music

W, H, FPS = 1080, 1920, 30
SHOT = 3.4                                     # target seconds per shot
POSTER_PATTERN = ("1+0.04*{e}", "(iw-iw/zoom)*0.5", "(ih-ih/zoom)*0.5")        # the title card: whole frame, barely moving, nothing cropped
PATTERNS = [                                   # (zoom expr, x expr, y expr) - zoompan, e = progress 0..1
    ("1+0.12*{e}", "(iw-iw/zoom)*0.5", "(ih-ih/zoom)*0.5"),
    ("1.26+0.07*{e}", "(iw-iw/zoom)*0.5", "(ih-ih/zoom)*0.28"),
    ("1.16+0.09*{e}", "(iw-iw/zoom)*0.18", "(ih-ih/zoom)*0.62"),
    ("1.22-0.07*{e}", "(iw-iw/zoom)*0.82", "(ih-ih/zoom)*0.4"),
    ("1.30+0.05*{e}", "(iw-iw/zoom)*0.7", "(ih-ih/zoom)*0.25"),
]


async def _tts(text: str, voice: str, rate: str, pitch: str, mp3: Path) -> list[tuple[float, float, str]]:
    spoken = _speakable(text)
    if not spoken:
        _silence(mp3)
        return []
    words, chunks = [], []
    for attempt in range(3):
        try:
            words, chunks = [], []
            async for ch in edge_tts.Communicate(spoken, voice, rate=rate, pitch=pitch, boundary="WordBoundary").stream():
                if ch["type"] == "audio":
                    chunks.append(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append((ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]))
            if chunks:
                mp3.write_bytes(b"".join(chunks))
                return words
        except Exception:
            await asyncio.sleep(2)
    print(f"[rules] WARNING: could not speak {spoken[:40]!r} - using a pause", flush=True)
    _silence(mp3, max(0.8, len(spoken.split()) / 2.6))
    return []


def _poster(story: dict, image: Path, out: Path) -> Path:
    """Frame 1: the key art with a big stylised title (movie-poster look)."""
    im = Image.open(image).convert("RGB")
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H)).convert("RGBA")
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(shade)
    for y in range(0, 760):                                              # dark gradient at the top so the title always reads
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(190 * (1 - y / 760) ** 1.5)))
    for y in range(H - 520, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(170 * ((y - (H - 520)) / 520) ** 1.4)))
    im = Image.alpha_composite(im, shade)
    lines = story.get("title_lines") or [story["title"].upper()]
    y = 150
    for i, line in enumerate(lines):
        size = 168 if i == 0 else 112
        while size > 40 and g.text_size(line, g.font("impact", size))[0] > W - 150:      # shrink until the whole line fits
            size -= 4
        col = (255, 196, 20) if i == 0 else (255, 255, 255)
        lay = g.text_layer(line, "impact", size, col, W - 80, "center", stroke=11, stroke_color=(10, 4, 4))
        im.alpha_composite(lay, ((W - lay.width) // 2, y)); y += int(size * 1.12)
    n_rules = max([s.get("rule_no", 0) for s in story["scenes"] if s.get("kind") == "rule"] + [0])
    tag = story.get("poster_tag") or (f"{n_rules + 1} RULES TO SURVIVE" if story.get("format") == "rules" else f"{n_rules} RULES TO SURVIVE")
    badge = g.text_layer(tag, "impact", 70, (255, 60, 50), W - 100, "center", stroke=8, stroke_color=(10, 4, 4))
    im.alpha_composite(badge, ((W - badge.width) // 2, H - 640))
    im.convert("RGB").save(out)
    return out


def _shot(image: Path, dur: float, pattern: int, out: Path) -> None:
    frames = max(2, int(round(dur * FPS)))
    pat = POSTER_PATTERN if pattern < 0 else PATTERNS[pattern % len(PATTERNS)]
    z, x, y = (p.format(e=f"(on/{frames})") for p in pat)
    vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,crop={W * 2}:{H * 2},"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},unsharp=3:3:0.5,format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(image), "-vf", vf, "-an", "-c:v", "libx264", "-crf", "20", "-preset", "medium", str(out)])


def _ass_time(s: float) -> str:
    h, rem = divmod(max(0, s), 3600); m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def _captions(scenes: list[dict], out: Path) -> None:
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Impact,96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,9,0,2,60,60,330,1
Style: Badge,Impact,190,&H003C3CFF,&H003C3CFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,10,0,8,60,60,230,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for sc in scenes:
        if sc["badge"]:
            ev.append(f"Dialogue: 2,{_ass_time(sc['start'])},{_ass_time(sc['start'] + 1.5)},Badge,,0,0,0,,{{\\fad(50,300)\\fscx150\\fscy150\\t(0,140,\\fscx100\\fscy100)}}{sc['badge']}")
        words = [(sc["start"] + sc["lead"] + a, sc["start"] + sc["lead"] + b, w) for a, b, w in sc["words"]]
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(cur) >= 3 or re.search(r"[.?!,:;]$", w[2]):
                chunks.append(cur); cur = []
        if cur:
            if chunks and len(cur) == 1:
                chunks[-1] += cur
            else:
                chunks.append(cur)
        for ci, ch in enumerate(chunks):
            for wi, (a, b, w) in enumerate(ch):
                end = ch[wi + 1][0] if wi + 1 < len(ch) else (chunks[ci + 1][0][0] if ci + 1 < len(chunks) and chunks[ci + 1][0][0] - b < 0.35 else b + 0.12)
                text = " ".join((f"{{\\c&H0014C4FF&\\fscx114\\fscy114}}{x[2].upper()}{{\\r}}" if k == wi else x[2].upper()) for k, x in enumerate(ch))
                ev.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(end)},Cap,,0,0,0,,{text}")
    out.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")


def _sfx(total: float, cuts: list[float], hits: list[float], twist: float | None, out: Path) -> None:
    tr = Track(total)
    rng = np.random.default_rng(11)
    for t in cuts:                                                         # whoosh: a quick swell of filtered noise
        n = noise(0.3, 0, rng, 28) * np.hanning(int(0.3 * SR)) * 2.0
        tr.place(n, max(0, t - 0.12), 0.22)
    for t in hits:                                                         # low hit for each rule
        tt = np.arange(int(0.7 * SR)) / SR
        tr.place(np.sin(2 * np.pi * (46 + 40 * np.exp(-tt * 14)) * tt) * np.exp(-tt * 6.5), t, 0.9)
        tr.place(noise(0.05, 60, rng, 3), t, 0.25)
    if twist is not None:
        up = noise(2.2, 0, rng, 10) * np.linspace(0, 1, int(2.2 * SR)) ** 2.5
        tr.place(up, max(0, twist - 2.2), 0.3)
        for m in (84, 85, 88):                                              # a cold dissonant sting
            tr.place(bell(440 * 2 ** ((m - 69) / 12), 3.0, 1.2), twist, 0.1)
        tt = np.arange(int(1.2 * SR)) / SR
        tr.place(np.sin(2 * np.pi * 38 * tt) * np.exp(-tt * 3), twist, 1.0)
    buf = tr.buf[: int(total * SR)]
    buf = buf / max(1e-9, np.abs(buf).max()) * 0.9
    raw = out.with_suffix(".raw"); raw.write_bytes((np.repeat(buf[:, None], 2, 1) * 32767).astype(np.int16).tobytes())
    run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw), str(out)]); raw.unlink()


def build_rules_video(story_dir: str, log=print, music: bool = True) -> Path:
    sdir = Path(story_dir).resolve()
    story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
    work = sdir / "build"; work.mkdir(exist_ok=True)
    voice = story["characters"]["Narrator"]
    log("[rules] Speaking the lines (with word timing)...")
    t, scenes = 0.0, []
    for i, sc in enumerate(story["scenes"], 1):
        mp3 = work / f"v{i}.mp3"
        text = sc["lines"][0]["text"]
        words = asyncio.run(_tts(text, voice["voice"], voice.get("rate", "+0%"), voice.get("pitch", "+0Hz"), mp3))
        tokens = text.split()
        if len(tokens) == len(words):                       # the engine drops punctuation; put it back so captions can break at sentence ends
            words = [(a, b, tok) for (a, b, _), tok in zip(words, tokens)]
        dur = probe_duration(mp3); lead = 0.04 if i == 1 else 0.12
        length = max(2.6, lead + dur + 0.16)
        badge = f"RULE {sc['rule_no']}" if sc.get("kind") == "rule" and sc.get("rule_no") else ("RULE 6" if sc.get("kind") == "twist" and (not scenes or scenes[-1]["kind"] != "twist") else "")
        scenes.append({"i": i, "kind": sc.get("kind"), "start": t, "len": length, "lead": lead, "mp3": mp3, "words": words, "badge": badge, "image": sdir / sc["image"]})
        t += length
    total = t
    log(f"[rules] {len(scenes)} scenes, {total:.1f}s")

    log("[rules] Cutting the shots...")
    clips, cuts, hits, twist_at = [], [], [], None
    for sc in scenes:
        if not sc["image"].exists():
            raise RuntimeError(f"Missing picture: {sc['image'].name} - make the pictures first.")
        if sc["badge"]:
            hits.append(sc["start"])
        if sc["kind"] == "twist" and twist_at is None:
            twist_at = sc["start"]
        n = max(1, int(round(sc["len"] / SHOT)))
        segs = []
        if sc["i"] == 1:                                                   # poster first, then closer cuts of the same art
            poster = _poster(story, sc["image"], work / "poster.png")
            first = min(2.6, sc["len"] * 0.5)
            segs.append((poster, first)); rest = sc["len"] - first; k = max(1, int(round(rest / SHOT)))
            segs += [(sc["image"], rest / k)] * k
        else:
            segs = [(sc["image"], sc["len"] / n)] * n
        for j, (img, d) in enumerate(segs):
            clip = work / f"s{sc['i']}_{j}.mp4"
            _shot(img, d, -1 if (sc["i"] == 1 and j == 0) else sc["i"] * 2 + j, clip)
            clips.append(clip)
            if not (sc["i"] == 1 and j == 0):
                cuts.append(sc["start"] + sum(x[1] for x in segs[:j]))
    (work / "clips.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "clips.txt"), "-c", "copy", str(work / "silent.mp4")])

    log("[rules] Sound...")
    voice_story = {"scenes": [{"lines": [{"_audio": sc["mp3"], "_start": sc["start"] + sc["lead"]}]} for sc in scenes]}
    build_voice_track(voice_story, total, work / "voice.wav")
    _sfx(total, cuts, hits, twist_at, work / "sfx.wav")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(work / "voice.wav"), "-i", str(work / "sfx.wav")]
    prep = "[0:a]aresample=44100,aformat=channel_layouts=stereo[v];[1:a]aresample=44100,aformat=channel_layouts=stereo[s];"
    if music:
        synthesize_music(total, work / "music.wav", mood=story["music"]["mood"], seed=__import__("music").seed_from(story["title"]))
        cmd += ["-i", str(work / "music.wav")]
        mix = prep + "[2:a]aresample=44100,aformat=channel_layouts=stereo[m];[v][s][m]amix=inputs=3:weights=1 0.85 0.2:normalize=0:duration=first[a]"
    else:
        mix = prep + "[v][s]amix=inputs=2:weights=1 0.85:normalize=0:duration=first[a]"
    run(cmd + ["-filter_complex", mix, "-map", "[a]", "-c:a", "aac", "-b:a", "192k", str(work / "audio.m4a")])
    _captions(scenes, work / "captions.ass")

    final = sdir / f"{sdir.name}.mp4"
    log("[rules] Final render...")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "silent.mp4", "-i", "audio.m4a", "-vf", "subtitles=captions.ass", "-c:v", "libx264", "-crf", "22",
                    "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(final)], cwd=work, check=True)
    log(f"[rules] Done -> {final}")
    return final


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("story_dir")
    ap.add_argument("--no-music", action="store_true")
    a = ap.parse_args()
    build_rules_video(a.story_dir, music=not a.no_music)
