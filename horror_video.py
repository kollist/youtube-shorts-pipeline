"""
horror_video.py
The scary version of the rules format. Same story + pictures as rules_video.py, but built as a CORRUPTED ORIENTATION TAPE:

  picture : poster title, then slow shots that get faster; every frame degraded by horror_fx.py following a tension curve that rises with each
            rule; static bursts on the hits, a subliminal flash of the twist picture, a stutter, and the tape dying at the end.
  sound   : no music. A sub-bass drone, room tone, a heartbeat that speeds up from rule 4, and foley (phone, elevator, wet footsteps, keys, knock, creak)
            placed on the exact word the narrator says - slightly BEFORE the picture. Before the last line the beds fall away to near-silence; the last
            line is whispered; one sting (sound first, then the hit) lands on the reveal.
  ending  : the scare is the last thing you see; the question to the viewer appears on a dead-tape card after it.

    python horror_video.py stories/rules-night-shift-as-a-hotel-receptionist
"""

import argparse
import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

import horror_fx
import horror_sfx as sfx
import rules_video as rv
from music import SR
from series import VOICES
from story_video import W, H, FPS, probe_duration, run

CUES = [  # (regex on the spoken word, cue name) - at most one per scene (two in the finale)
    (r"^(phone|ring|rings|call|calls)\b", "phone_ring"), (r"^(elevator|dings?)\b", "elevator_ding"), (r"^(footprints?|footsteps?|steps?)\b", "wet_steps"),
    (r"^(keys?|key,)\b", "key_jingle"), (r"^(knock\w*)\b", "knock"), (r"^(door|doors|creaks?)\b", "door_creak"), (r"^(breath\w*|behind|whisper\w*)\b", "breath"),
    (r"^(snaps?|snapped|crack\w*)\b", "snap"), (r"^(scream\w*|shriek\w*)\b", "scream_stab"), (r"^(scrap\w*|scratch\w*)\b", "door_creak"),
]
SILENCE_BEFORE_FINAL = 0.9
CARD = 2.4


def _tension(sc: dict) -> float:
    if sc["kind"] == "intro":
        return 0.12
    if sc["kind"] == "rule":
        return 0.16 + 0.125 * sc["rule_no"]
    return 0.92 if not sc.get("final") else 1.0


async def _voice(text: str, who: dict, mp3: Path, whisper: bool):
    words = await rv._tts(text, who["voice"], who.get("rate", "+0%"), who.get("pitch", "+0Hz"), mp3)
    toks = text.split()
    if len(toks) == len(words):
        words = [(a, b, tk) for (a, b, _), tk in zip(words, toks)]
    if not whisper:                                                      # an old training tape: narrow band, a little wobble, squashed
        tmp = mp3.with_suffix(".t.mp3"); mp3.rename(tmp)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", "highpass=f=170,lowpass=f=4800,vibrato=f=4.6:d=0.025,acompressor=threshold=-20dB:ratio=3:makeup=3", str(mp3)]); tmp.unlink()
    if whisper:                                                          # close, breathy, in a big empty room
        tmp = mp3.with_suffix(".w.mp3"); mp3.rename(tmp)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", "highpass=f=140,aecho=0.85:0.6:48|120|230:0.38|0.26|0.16,volume=1.25", str(mp3)]); tmp.unlink()
    return words


def _wav(mp3: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def build_horror_video(story_dir: str, log=print) -> Path:
    sdir = Path(story_dir).resolve()
    story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
    work = sdir / "build_horror"; work.mkdir(exist_ok=True)
    narr = story["characters"]["Narrator"]; whisper_voice = VOICES["creepy_whisper"]
    label = story.get("tape_label") or f"{(story.get('title_lines') or [story['title']])[-1]} - NIGHT STAFF ORIENTATION - 1994".upper()[:60]

    # ---- 1. the end card: the viewer-question is pulled out of the last scene so the scare is the last thing heard
    scenes_in = [dict(s) for s in story["scenes"]]
    last = scenes_in[-1]["lines"][0]["text"]
    sentences = re.split(r"(?<=[.!?\u2014])\s+", last.strip())
    question = sentences[-1] if len(sentences) > 1 and sentences[-1].endswith("?") else ""
    if question:
        scenes_in[-1]["lines"] = [{"who": "Narrator", "text": " ".join(sentences[:-1])}]
    scenes_in[-1]["final"] = True

    # ---- 2. voices and timeline: ONE continuous narration. The scenes only mark where the picture changes - the pictures follow the words, there are no gaps
    #         between scenes. The only pause is a short beat before the whispered final scare.
    log("[horror] Voices...")
    main_in, fin_in = scenes_in[:-1], scenes_in[-1]
    texts = [sc["lines"][0]["text"] for sc in main_in]
    main_mp3 = work / "voice_main.mp3"
    words = asyncio.run(_voice(" ".join(texts), narr, main_mp3, False))
    VO = 0.05                                                                          # the voice starts a hair after the first picture
    n_tok = sum(len(t.split()) for t in texts); ratio = len(words) / max(1, n_tok)    # if the engine merged/split a word, scale the slices
    bounds, k = [], 0
    for c in (len(t.split()) for t in texts):
        bounds.append((int(round(k * ratio)), int(round((k + c) * ratio)))); k += c
    bounds[-1] = (bounds[-1][0], len(words))
    starts = [0.0] + [max(0.0, VO + words[bd[0]][0] - 0.06) for bd in bounds[1:]]    # the picture changes just before the scene's first word
    main_end = VO + words[-1][1] + 0.25
    scenes = []
    for i, (sc, (lo, hi)) in enumerate(zip(main_in, bounds), 1):
        is_last = i == len(main_in)
        end = (main_end + SILENCE_BEFORE_FINAL) if is_last else starts[i]
        rel = [(VO + a_ - starts[i - 1], VO + b_ - starts[i - 1], w) for a_, b_, w in words[lo:hi]]
        scenes.append({"i": i, "kind": sc.get("kind", "rule"), "rule_no": sc.get("rule_no", 0), "final": False, "start": starts[i - 1], "len": end - starts[i - 1], "lead": 0.0, "dur": 0.0,
                       "mp3": None, "words": rel, "image": sdir / sc["image"], "tail": SILENCE_BEFORE_FINAL if is_last else 0.0, "label": sc.get("label", ""),
                       "badge": (sc["label"] if sc.get("label") else f"RULE {sc['rule_no']}" if sc.get("kind") in ("rule", "twist") and sc.get("rule_no") and not any(s["kind"] == "twist" for s in scenes if sc.get("kind") == "twist") else "")})
    fmp3 = work / "voice_final.mp3"
    fwords = asyncio.run(_voice(fin_in["lines"][0]["text"], whisper_voice, fmp3, True))
    fdur = probe_duration(fmp3); flead = 0.35
    fstart = main_end + SILENCE_BEFORE_FINAL
    scenes.append({"i": len(scenes) + 1, "kind": fin_in.get("kind", "twist"), "rule_no": fin_in.get("rule_no", 0), "final": True, "start": fstart, "len": flead + fdur + 0.16, "lead": flead,
                   "dur": fdur, "mp3": fmp3, "words": fwords, "image": sdir / fin_in["image"], "tail": 0.0, "label": "", "badge": ""})
    story_end = fstart + flead + fdur + 0.16
    total = story_end + 0.6 + CARD                                                     # + tape dying + end card
    log(f"[horror] {len(scenes)} scenes, story {story_end:.1f}s, total {total:.1f}s")

    # ---- 3. shots: calm early (long), quicker later
    clips = []
    for sc in scenes:
        if not sc["image"].exists():
            raise RuntimeError(f"Missing picture {sc['image'].name} - make the pictures first.")
        target = 4.3 - 1.6 * min(1.0, _tension(sc))
        shot_time = sc["len"] - sc["tail"]
        n = max(1, int(round(shot_time / target))); segs = []
        if sc["i"] == 1:
            poster = rv._poster(story, sc["image"], work / "poster.png"); first = min(2.8, shot_time * 0.55)
            segs.append((poster, first)); rest = shot_time - first; k = max(1, int(round(rest / target))); segs += [(sc["image"], rest / k)] * k
        else:
            segs = [(sc["image"], shot_time / n)] * n
        if sc["tail"]:
            segs[-1] = (segs[-1][0], segs[-1][1] + sc["tail"])                       # hold the last picture through the silence
        for j, (img, d) in enumerate(segs):
            clip = work / f"s{sc['i']}_{j}.mp4"
            rv._shot(img, d, -1 if (sc["i"] == 1 and j == 0) else sc["i"] * 2 + j, clip); clips.append(clip)
    (work / "clips.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "clips.txt"), "-c", "copy", str(work / "silent.mp4")])

    # ---- 4. the tape: tension curve + events
    curve = [(0.0, 0.08)] + [(sc["start"] + sc["lead"], _tension(sc)) for sc in scenes] + [(story_end, 1.0), (total, 1.0)]
    final = scenes[-1]
    reveal = final["start"]
    events = []
    for sc in scenes:
        if sc["kind"] == "rule" and sc["rule_no"] >= 3:
            events.append({"t": sc["start"], "dur": 0.07, "kind": "static"})
        if sc["kind"] == "rule" and sc["rule_no"] == 4:
            events.append({"t": sc["start"] + 1.4, "dur": 0.07, "kind": "flash", "image": "twist"})                    # one subliminal frame
        if sc["kind"] == "rule" and sc["rule_no"] == 5:
            events.append({"t": sc["start"] + 2.2, "dur": 0.4, "kind": "roll"})
    events += [{"t": final["start"] - SILENCE_BEFORE_FINAL, "dur": 0.28, "kind": "freeze"},
               {"t": reveal, "dur": 0.34, "kind": "slam"},
               {"t": story_end, "dur": 0.6, "kind": "static"}, {"t": story_end + 0.45, "dur": 0.15, "kind": "black"}]
    log("[horror] Degrading the tape...")
    fxv = work / "fx.mp4"
    horror_fx.process(str(work / "silent.mp4"), str(fxv), curve, events, label, {"twist": str(final["image"])}, log=log)

    # ---- 5. sound
    log("[horror] Sound design...")
    n = int((total + 1) * SR); mix = np.zeros(n)
    def put(sound, at, gain=1.0):
        i = int(max(0, at) * SR)
        if i < n:
            seg = sound[: n - i]; mix[i:i + len(seg)] += seg * gain
    def shape(x, pts):                                                             # piecewise-linear gain envelope [(t, g), ...]
        return np.interp(np.arange(len(x)) / SR, [p[0] for p in pts], [p[1] for p in pts]) * x
    silence_at = final["start"] - SILENCE_BEFORE_FINAL + 0.25
    dr = sfx.drone(story_end)
    put(shape(dr, [(0, 0), (3, 0.22), (silence_at - 0.2, 0.26), (silence_at + 0.5, 0.0), (story_end, 0)]), 0)
    rt = sfx.room_tone(total)
    put(shape(rt, [(0, 0.05), (silence_at, 0.05), (silence_at + 0.3, 0.035), (story_end, 0.035), (story_end + 0.6, 0.0), (total, 0)]), 0)
    r4 = next((s for s in scenes if s["kind"] == "rule" and s["rule_no"] == 4), None)
    if r4:
        hb = sfx.heartbeat(silence_at - r4["start"], 64, 124)
        put(shape(hb, [(0, 0), (2, 0.5), (len(hb) / SR - 0.5, 0.65), (len(hb) / SR, 0)]), r4["start"])
    r5 = next((s for s in scenes if s["kind"] == "rule" and s["rule_no"] == 5), None)
    if r5:
        wb = sfx.whisper_bed(silence_at - r5["start"])
        put(shape(wb, [(0, 0), (3, 0.05), (len(wb) / SR - 0.4, 0.07), (len(wb) / SR, 0)]), r5["start"])
    put(_wav(main_mp3), VO, 1.0)                                                   # the narrator: one continuous take
    put(_wav(scenes[-1]["mp3"]), scenes[-1]["start"] + scenes[-1]["lead"], 1.0)    # then the whispered finale
    used = 0
    for sc in scenes:                                                              # foley on the spoken word, sound slightly BEFORE the picture it belongs to
        found = 0
        for a, b, w in sc["words"]:
            for rx, cue in CUES:
                if re.match(rx, re.sub(r"[^\w]", "", w.lower()) + (" " if False else ""), re.I) and found < (2 if sc["final"] else 1):
                    at = sc["start"] + sc["lead"] + a - 0.10
                    snd = {"phone_ring": lambda: sfx.phone_ring(2), "elevator_ding": sfx.elevator_ding, "wet_steps": lambda: sfx.wet_steps(3), "key_jingle": sfx.key_jingle,
                           "knock": sfx.knock, "door_creak": sfx.door_creak, "breath": sfx.breath, "snap": sfx.snap, "scream_stab": sfx.scream_stab}[cue]()
                    put(snd, at, 0.75 if cue not in ("breath",) else 0.5); found += 1; used += 1
                    break
        if sc["kind"] == "rule" and sc["rule_no"] >= 1:                           # a low hit on each rule number, a little quieter early
            put(np.sin(2 * np.pi * (46 + 38 * np.exp(-np.arange(int(0.6 * SR)) / SR * 14)) * np.arange(int(0.6 * SR)) / SR) * np.exp(-np.arange(int(0.6 * SR)) / SR * 7), sc["start"] - 0.05, 0.28 + 0.07 * sc["rule_no"])
    turn = next((s for s in scenes if s["kind"] == "twist" and not s["final"]), None)
    if turn:                                                                       # a smaller scare earlier, so the big one is not the only thing to flinch at
        put(sfx.scream_stab(0.4), turn["start"] + turn["lead"] + 0.2, 0.3)
        put(sfx.static_burst(0.18), turn["start"] + turn["lead"] + 0.18, 0.5)
    put(sfx.real_scream(len(story.get('title', ''))) if sfx.real_scream() is not None else sfx.jump_scream(), reveal - 0.02, 1.15)   # THE jump scare, on the slam
    st = sfx.sting(1.1)                                                            # the ONE sting: its rise ends just before the reveal picture
    put(st, reveal - 1.1 - 0.08, 0.85)
    fin = story.get("finale_sfx") or ("snap" if story.get("format") == "scp" and "173" in json.dumps(story.get("credit", {})) else "scream")
    voice_end = final["start"] + final["lead"] + final["dur"]
    if fin == "snap":
        put(sfx.snap(), voice_end + 0.06, 1.0)
    elif fin == "scream":
        put(sfx.scream_stab(), voice_end + 0.06, 0.8)
    put(sfx.tape_stop(0.8), story_end - 0.1, 0.8)
    put(sfx.static_burst(0.6), story_end, 0.5)
    mix = np.tanh(mix * 0.9)
    mix = mix / max(1e-9, np.abs(mix).max()) * 0.92
    raw = work / "mix.raw"; raw.write_bytes((np.repeat(mix[:, None], 2, 1)[: int(total * SR)] * 32767).astype(np.int16).tobytes())
    run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw), "-af", "loudnorm=I=-15:TP=-1.5:LRA=11", str(work / "audio.wav")]); raw.unlink()
    log(f"[horror] {used} foley cues placed on spoken words")

    # ---- 6. captions + the end card
    rv._captions(scenes, work / "captions.ass")
    if question:
        cap = work / "captions.ass"
        extra = (f"Dialogue: 3,{rv._ass_time(story_end + 0.7)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an5\\pos(540,960)\\fs84\\fad(200,0)}}{question.upper().replace('?', '?')}\n")
        if story.get("credit"):
            extra += (f"Dialogue: 3,{rv._ass_time(story_end + 0.7)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an2\\pos(540,1840)\\fs30\\c&H00C8C8C8&\\bord3}}{story['credit']['line']}\n")
        cap.write_text(cap.read_text(encoding="utf-8") + extra, encoding="utf-8")
    out = sdir / f"{sdir.name}-HORROR.mp4"
    log("[horror] Final render...")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "fx.mp4", "-i", "audio.wav", "-vf", f"tpad=stop_mode=clone:stop_duration={CARD + 1:.1f},subtitles=captions.ass",
                    "-t", f"{total:.2f}", "-c:v", "libx264", "-crf", "28", "-preset", "medium", "-maxrate", "6M", "-bufsize", "12M",      # the grain is heavy: bound the bitrate (~40 MB)
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], cwd=work, check=True)
    shutil.rmtree(work, ignore_errors=True)                                      # ~500 MB of intermediate clips; the result is the video
    log(f"[horror] Done -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("story_dir"); a = ap.parse_args()
    build_horror_video(a.story_dir)
