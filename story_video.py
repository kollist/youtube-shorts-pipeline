"""
story_video.py
Turns a story folder (story.json + one image per scene) into a finished vertical
video: character voices (free edge-tts), slow pan/zoom over each picture, big
color-coded captions, and a synthesized music bed. Everything runs locally except
the voice synthesis, which needs an internet connection.

Usage:
    python story_video.py stories/talking-fruit-garden
    python story_video.py stories/talking-fruit-garden --music my_track.mp3
    python story_video.py stories/talking-fruit-garden --no-music

Output: <story folder>/<folder name>.mp4 - a preview to review. Nothing is uploaded.
"""

import argparse
import asyncio
import json
import re
import subprocess
from pathlib import Path

import edge_tts
import numpy as np

from run_control import check_cancelled

W, H, FPS = 1080, 1920, 30
LEAD = 0.5      # silence before a scene's first line
GAP = 0.3       # between lines
TAIL = 0.8      # after a scene's last line
FADE = 0.3      # per-scene fade in/out

# Words that get their own color in the captions, so the colors being taught
# are shown as well as said. ASS colors are &HBBGGRR&.
COLOR_WORDS_DEFAULT = {"red": "&H4D4DFF&", "yellow": "&H3DD9FF&"}


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed:\n{result.stderr[-1500:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def _speakable(text: str) -> str:
    """Strips invisible characters; returns "" when nothing is left that a voice can actually say
    (a line like "..." or an em dash - a silent beat)."""
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff\u00ad]", "", text or "").strip()
    return text if re.search(r"\w", text) else ""


def _silence(out: Path, seconds: float = 0.7) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", str(seconds), "-c:a", "libmp3lame", str(out)])


async def _speak(text: str, voice: str, rate: str, pitch: str, out: Path) -> None:
    """Speaks one line with edge-tts. A line with nothing speakable in it ("...", a dash) becomes a short pause instead of
    crashing the whole render with "No audio was received"."""
    spoken = _speakable(text)
    if not spoken:
        _silence(out)
        return
    for attempt in range(3):
        try:
            await edge_tts.Communicate(spoken, voice, rate=rate, pitch=pitch).save(str(out))
            if out.exists() and out.stat().st_size > 200:
                return
            raise RuntimeError("empty audio file")
        except Exception:
            if attempt == 2:
                # last resort: don't lose the whole video over one line - a pause for as long as the words would take
                print(f"[story] WARNING: could not speak {spoken[:50]!r} (voice service gave no audio) - using a pause instead.", flush=True)
                _silence(out, max(0.7, len(spoken.split()) / 2.6))
                return
            await asyncio.sleep(2)


def synthesize_lines(story: dict, audio_dir: Path) -> None:
    audio_dir.mkdir(parents=True, exist_ok=True)
    chars = story["characters"]
    for si, scene in enumerate(story["scenes"], 1):
        for li, line in enumerate(scene["lines"], 1):
            c = chars[line["who"]]
            path = audio_dir / f"s{si}_l{li}.mp3"
            asyncio.run(_speak(line["text"], c["voice"], c.get("rate", "+0%"), c.get("pitch", "+0Hz"), path))
            line["_audio"] = path
            line["_dur"] = probe_duration(path)


def lay_out_timeline(story: dict) -> float:
    """Gives every scene a start/length and every line a start time (seconds)."""
    t = 0.0
    for scene in story["scenes"]:
        scene["_start"] = t
        cursor = t + LEAD
        for line in scene["lines"]:
            line["_start"] = cursor
            cursor += line["_dur"] + GAP
        scene["_len"] = max(scene.get("min_seconds", 0), cursor - GAP + TAIL - t)
        t += scene["_len"]
    return t


def build_voice_track(story: dict, total: float, out: Path) -> None:
    lines = [ln for s in story["scenes"] for ln in s["lines"]]
    if not lines:                                   # a wordless story (music + picture only): the voice track is just silence
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{total:.2f}", str(out)])
        return
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for ln in lines:
        cmd += ["-i", str(ln["_audio"])]
    parts = [f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={int(ln['_start'] * 1000)}:all=1[v{i}]"
             for i, ln in enumerate(lines)]
    mix = "".join(f"[v{i}]" for i in range(len(lines)))
    chain = ";".join(parts) + f";{mix}amix=inputs={len(lines)}:normalize=0:duration=longest,apad=whole_dur={total:.2f}[voice]"
    run(cmd + ["-filter_complex", chain, "-map", "[voice]", "-t", f"{total:.2f}", str(out)])


# ---- music: a simple placeholder bed synthesized in code (no downloads, no licensing) ----
NOTE = {"C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.00, "A4": 440.00, "B4": 493.88,
        "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99, "A5": 880.00, "C6": 1046.50, "C3": 130.81,
        "F3": 174.61, "G3": 196.00}
CHORDS = [("C3", ["C4", "E4", "G4"]), ("F3", ["C4", "F4", "A4"]), ("G3", ["B4", "D5", "G4"]), ("C3", ["C4", "E4", "G4"])]
MELODY = [  # one list per bar, eight eighth-notes each ("-" = rest)
    ["E5", "G5", "A5", "G5", "E5", "D5", "C5", "-"],
    ["A5", "G5", "E5", "G5", "A5", "C6", "A5", "-"],
    ["G5", "E5", "D5", "E5", "G5", "A5", "G5", "-"],
    ["E5", "D5", "C5", "D5", "E5", "G5", "C5", "-"],
]


def _pluck(freq: float, length: float, sr: int, decay: float, bright: float = 0.35) -> np.ndarray:
    t = np.arange(int(length * sr)) / sr
    tone = np.sin(2 * np.pi * freq * t) + bright * np.sin(2 * np.pi * freq * 2 * t) + 0.12 * np.sin(2 * np.pi * freq * 4.1 * t)
    return tone * np.exp(-decay * t) * np.minimum(1, t * 400)  # 2-3 ms attack avoids clicks


def _write_wav(buf: np.ndarray, out: Path, sr: int) -> None:
    fade_in, fade_out = int(1.0 * sr), int(2.0 * sr)
    buf[:fade_in] *= np.linspace(0, 1, fade_in)
    buf[-fade_out:] *= np.linspace(1, 0, fade_out)
    buf = buf / max(1e-9, np.abs(buf).max()) * 0.7
    stereo = np.repeat((buf * 32767).astype(np.int16)[:, None], 2, axis=1)
    tmp = out.with_suffix(".raw")
    tmp.write_bytes(stereo.tobytes())
    run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(sr), "-ac", "2", "-i", str(tmp), str(out)])
    tmp.unlink()


def synthesize_tense_music(total: float, out: Path, sr: int = 44100) -> None:
    """Slow, eerie bed for scary/dramatic stories: a low drone that swells and
    fades, a heartbeat that speeds up as the story goes on, and a sparse
    music-box melody in A minor."""
    n = int((total + 3) * sr)
    t = np.arange(n) / sr
    buf = np.zeros(n)

    # Drone: root + fifth, slowly pulsing
    swell = 0.6 + 0.4 * np.sin(2 * np.pi * 0.08 * t)
    buf += swell * (0.30 * np.sin(2 * np.pi * 55.0 * t) + 0.18 * np.sin(2 * np.pi * 110.0 * t)
                    + 0.10 * np.sin(2 * np.pi * 164.8 * t + 0.4 * np.sin(2 * np.pi * 0.2 * t)))

    def place(sound: np.ndarray, at: float, gain: float) -> None:
        i = int(at * sr)
        if i < n:
            seg = sound[: n - i]
            buf[i:i + len(seg)] += seg * gain

    # Heartbeat (two thumps), interval shrinking from 1.1s to 0.62s across the story
    thump = _pluck(52.0, 0.5, sr, 14.0, 0.6)
    at = 1.0
    while at < total:
        place(thump, at, 0.55)
        place(thump, at + 0.22, 0.38)
        at += 1.1 - 0.48 * min(1.0, at / total)

    # Music box: slow broken Am - F - C - E arpeggio, one note every 0.8s
    arps = [["A4", "C5", "E5", "C5"], ["F4", "A4", "C5", "A4"], ["C5", "E5", "G5", "E5"], ["E4", "G4", "B4", "G4"]]
    freq = dict(NOTE, E4=329.63, B4=493.88, G4=392.0)
    step = 0.8
    for i in range(int(total / step) + 1):
        note = arps[(i // 4) % 4][i % 4]
        place(_pluck(freq[note], 1.4, sr, 4.2, 0.9), 2.0 + i * step, 0.20)
    _write_wav(buf[: int(total * sr)], out, sr)


def synthesize_music(total: float, out: Path, bpm: int = 110, sr: int = 44100, mood: str = "happy", seed: int = 0) -> None:
    """mood: happy (kids), tense (scary series), or one of music.py's own beds: fable, curious, eerie, upbeat.
    seed varies the key and tempo a little per video (pass a hash of the title)."""
    if mood == "tense":
        return synthesize_tense_music(total, out, sr)
    import music
    if mood in music.MOODS:
        return music.make(mood, total, out, seed)
    beat = 60.0 / bpm
    eighth = beat / 2
    buf = np.zeros(int((total + 3) * sr))

    def place(sound: np.ndarray, at: float, gain: float) -> None:
        i = int(at * sr)
        if i < len(buf):
            seg = sound[: len(buf) - i]
            buf[i:i + len(seg)] += seg * gain

    bar_len = beat * 4
    for bar in range(int(total / bar_len) + 2):
        root, chord = CHORDS[bar % 4]
        t0 = bar * bar_len
        place(_pluck(NOTE[root], 1.2, sr, 3.0, 0.2), t0, 0.5)                       # bass on beat 1
        for b in range(4):                                                            # ukulele-like strum
            for k, n in enumerate(chord):
                place(_pluck(NOTE[n], 0.5, sr, 7.0, 0.5), t0 + b * beat + k * 0.012, 0.16)
        for i, n in enumerate(MELODY[bar % 4]):                                       # xylophone-like melody
            if n != "-":
                place(_pluck(NOTE[n], 0.45, sr, 9.0, 0.25), t0 + i * eighth, 0.22)
    _write_wav(buf[: int(total * sr)], out, sr)


def mix_audio(voice: Path, music: Path | None, out: Path) -> None:
    if music is None:
        run(["ffmpeg", "-y", "-v", "error", "-i", str(voice), "-c:a", "aac", "-b:a", "160k", str(out)])
        return
    # Music sits well under the voices (0.22) so toddlers can make out the words.
    run(["ffmpeg", "-y", "-v", "error", "-i", str(voice), "-i", str(music), "-filter_complex",
         "[1:a]aresample=44100,aformat=channel_layouts=stereo[m];[0:a][m]amix=inputs=2:weights=1 0.22:normalize=0:duration=first[a]",
         "-map", "[a]", "-c:a", "aac", "-b:a", "160k", str(out)])


def build_scene_clip(image: Path, length: float, index: int, out: Path) -> None:
    """Slow pan/zoom over a still picture, with a short fade at each end. The
    picture is enlarged first because zoompan steps in whole pixels and looks
    jittery when it zooms slowly over a small image."""
    frames = int(length * FPS)
    ease = f"on/{frames}"
    moves = [  # (zoom expression, x expression, y expression)
        (f"1+0.10*{ease}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),                       # push in
        (f"1.10-0.10*{ease}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),                    # pull out
        (f"1+0.10*{ease}", "(iw-iw/zoom)*0.25", "(ih-ih/zoom)*0.30"),                 # push toward upper left
        (f"1+0.10*{ease}", "(iw-iw/zoom)*0.75", "(ih-ih/zoom)*0.70"),                 # push toward lower right
    ]
    z, x, y = moves[index % len(moves)]
    vf = (f"scale={W * 2}:{H * 2}:flags=lanczos,"
          f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d={FADE},fade=t=out:st={length - FADE:.2f}:d={FADE},format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(image), "-vf", vf, "-an",
         "-c:v", "libx264", "-crf", "21", "-preset", "medium", str(out)])


def build_motion_scene_clip(src: Path, length: float, out: Path) -> None:
    """A clip generated by WanGP for this scene, fitted to the scene: cropped to 9:16, slowed down (up to 1.6x) or
    held on its last frame if it's shorter than the narration, trimmed if it's longer."""
    dur = probe_duration(src)
    stretch = min(1.6, length / dur) if dur < length else 1.0
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setpts={stretch:.4f}*PTS,"
          f"tpad=stop_mode=clone:stop_duration={length:.2f},trim=duration={length:.2f},setpts=PTS-STARTPTS,"
          f"fade=t=in:st=0:d={FADE},fade=t=out:st={length - FADE:.2f}:d={FADE},format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-crf", "21", "-preset", "medium", str(out)])


def _ass_time(s: float) -> str:
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def build_captions(story: dict, out: Path) -> None:
    color_words = {w.lower(): c for w, c in story.get("caption_colors", COLOR_WORDS_DEFAULT).items()}
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Kids,{story.get('caption_font', 'Arial Rounded MT Bold')},{story.get('caption_size', 92)},&H00FFFFFF,&H00FFFFFF,&H00202020,&H80000000,1,0,0,0,100,100,0,0,1,7,2,2,70,70,300,1
Style: Card,Arial Rounded MT Bold,64,&H00F0F0F0,&H00F0F0F0,&H00101010,&H80000000,1,0,0,0,100,100,6,0,1,5,2,8,70,70,170,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def colored(text: str) -> str:
        def sub(m: re.Match) -> str:
            c = color_words.get(m.group(0).lower())
            return f"{{\\c{c}}}{m.group(0)}{{\\c&HFFFFFF&}}" if c else m.group(0)
        return re.sub(r"[A-Za-z']+", sub, text)

    events = []
    if story.get("title_card"):
        events.append(f"Dialogue: 1,{_ass_time(0.2)},{_ass_time(3.0)},Card,,0,0,0,,{{\\fad(400,500)}}{story['title_card']}")
    chunk_words = story.get("caption_words", 7)
    for scene in story["scenes"]:
        for line in scene["lines"]:
            # A long line is shown as short phrases in turn, timed by how much each one has to say,
            # instead of one big block of text covering the picture.
            words = line["text"].split()
            chunks = [" ".join(words[i:i + chunk_words]) for i in range(0, len(words), chunk_words)] or [""]
            if len(chunks) > 1 and len(chunks[-1].split()) <= 2:        # don't strand a 1-2 word tail
                tail = chunks.pop()
                chunks[-1] += " " + tail
            total_chars = sum(len(c) for c in chunks) or 1
            t = line["_start"]
            for chunk in chunks:
                share = line["_dur"] * len(chunk) / total_chars
                events.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + share + 0.05)},Kids,,0,0,0,,{colored(chunk)}")
                t += share
    for scene in story["scenes"]:                   # optional on-screen text for a scene (used by wordless stories)
        if scene.get("caption"):
            events.append(f"Dialogue: 1,{_ass_time(scene['_start'] + 0.25)},{_ass_time(scene['_start'] + scene['_len'] - 0.25)},Card,,0,0,0,,{{\\fad(250,250)}}{scene['caption']}")
    out.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


def make_placeholders(story_dir: str) -> Path:
    """Plain dark pictures (one per scene) so the voices, music, pacing and captions can be checked in a
    minute, before spending ~4 minutes per real picture. Returns the folder they were written to."""
    from PIL import Image, ImageDraw
    sdir = Path(story_dir).resolve()
    story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
    out = sdir / "placeholders"
    out.mkdir(exist_ok=True)
    for i, scene in enumerate(story["scenes"], 1):
        im = Image.new("RGB", (576, 1024))
        d = ImageDraw.Draw(im)
        for y in range(1024):
            d.line([(0, y), (576, y)], fill=(10 + y // 40, 22 + y // 30, 40 + y // 22))
        d.text((40, 60), f"PREVIEW PICTURE - scene {i}", fill=(200, 215, 230))
        im.save(out / Path(scene["image"]).name)
    return out


def build_story(story_dir: str, music: str | None = None, no_music: bool = False,
                images_dir: str | None = None, out_name: str | None = None, motion: str | None = None,
                cancel_event=None) -> Path:
    sdir = Path(story_dir).resolve()
    story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
    work = sdir / "build"
    work.mkdir(exist_ok=True)

    print("[story] Speaking the lines...")
    synthesize_lines(story, work / "audio")
    total = lay_out_timeline(story)
    print(f"[story] {len(story['scenes'])} scenes, {total:.1f}s total")

    build_voice_track(story, total, work / "voice.wav")
    music_path = None
    if not no_music:
        if music:
            music_path = Path(music).resolve()
        else:
            print("[story] Synthesizing the placeholder music bed...")
            music_path = work / "music.wav"
            synthesize_music(total, music_path, mood=story.get("music", {}).get("mood", "happy"), seed=__import__("music").seed_from(story.get("title", "")))
    mix_audio(work / "voice.wav", music_path, work / "audio.m4a")

    clips = []
    for i, scene in enumerate(story["scenes"]):
        check_cancelled(cancel_event)
        image = Path(images_dir).resolve() / Path(scene["image"]).name if images_dir else sdir / scene["image"]
        if not image.exists():
            raise FileNotFoundError(f"Missing scene image: {image} (generate it with story_images.py)")
        print(f"[story] Scene {i + 1}/{len(story['scenes'])}: animating {image.name} ({scene['_len']:.1f}s)")
        clip = work / f"scene{i + 1}.mp4"
        # "parallax": the camera drifts through the picture using a depth map, with dust/grain/flicker.
        # "pan": the older, lighter slow zoom and pan (also the automatic fallback if depth fails).
        mode = motion or scene.get("motion") or story.get("motion", "pan")
        from shots import motion_clip_path
        motion_file = motion_clip_path(sdir, i + 1)              # a clip animated with a free web tool and dropped in (see shots.py)
        if motion_file.exists() and not images_dir:              # a real animated clip beats the camera-drift animation
            print(f"[story]   using the animated clip for scene {i + 1}")
            build_motion_scene_clip(motion_file, scene["_len"], clip)
        elif mode == "parallax":
            try:
                from story_motion import parallax_clip
                parallax_clip(image, scene["_len"], i, clip, depth_cache=work / "depth" / f"{image.stem}.png",
                              fx=scene.get("fx", story.get("fx")), shake=scene.get("shake", 0.0), fade=FADE)
            except Exception as e:
                print(f"[story]   parallax failed for {image.name} ({e}); using the simple pan instead")
                build_scene_clip(image, scene["_len"], i, clip)
        else:
            build_scene_clip(image, scene["_len"], i, clip)
        clips.append(clip)
    (work / "clips.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "clips.txt"),
         "-c", "copy", str(work / "silent.mp4")])

    build_captions(story, work / "captions.ass")
    final = sdir / (out_name or f"{sdir.name}.mp4")
    print("[story] Adding captions and sound...")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", "silent.mp4", "-i", "audio.m4a", "-vf", "subtitles=captions.ass",
         "-c:v", "libx264", "-crf", "24", "-preset", "medium", "-c:a", "copy", "-shortest",
         "-movflags", "+faststart", str(final)],
        cwd=work, check=True,
    )
    print(f"[story] Done -> {final}")
    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("story_dir")
    parser.add_argument("--music", help="Path to your own music track (replaces the synthesized placeholder)")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument("--images-dir", help="Use pictures from this folder instead (e.g. placeholders, for a quick preview)")
    parser.add_argument("--out-name", help="Output file name (default: <folder name>.mp4)")
    parser.add_argument("--motion", choices=["pan", "parallax"], help="Override the story's motion style")
    args = parser.parse_args()
    build_story(args.story_dir, args.music, args.no_music, args.images_dir, args.out_name, args.motion)
