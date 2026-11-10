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
import random
import re
import shutil
import subprocess
import zlib
from pathlib import Path

import numpy as np

import horror_fx
import horror_sfx as sfx
import rules_video as rv
from music import SR
from series import VOICES
from shots import motion_clip_path
from story_video import W, H, FPS, probe_duration, run

CUES = [  # (regex on the spoken word, cue name) - at most one per scene (two in the finale)
    (r"^(phone|ring|rings|call|calls)\b", "phone_ring"), (r"^(elevator|dings?)\b", "elevator_ding"), (r"^(footprints?|footsteps?|steps?)\b", "wet_steps"),
    (r"^(keys?|key,)\b", "key_jingle"), (r"^(knock\w*)\b", "knock"), (r"^(door|doors|creaks?)\b", "door_creak"), (r"^(breath\w*|behind|whisper\w*)\b", "breath"),
    (r"^(\u0627\u0644\u0628\u0627\u0628|\u0628\u0627\u0628)$", "door_creak"), (r"^(\u0647\u0645\u0633\u0627?|\u064a\u0647\u0645\u0633)$", "breath"), (r"^(\u0642\u062f\u0645|\u062e\u0637\u0648\u0627\u062a)$", "wet_steps"),
    (r"^(snaps?|snapped|crack\w*)\b", "snap"), (r"^(scream\w*|shriek\w*)\b", "scream_stab"), (r"^(scrap\w*|scratch\w*)\b", "door_creak"),
]
SILENCE_BEFORE_FINAL = 0.9
CARD = 2.4
GAP_JOLT = 1.0                                                                       # the narrator STOPS (real silence, not a volume dip) before the jump scare...
GAP_JOLT_REC = 1.6                                                                   # a recorded narration: a longer stop, so the suck-in, the hit and the silence after it all fit inside it
GAP_KNOCK = 0.85                                                                     # ...and again mid-story while something knocks; the words after the gap shift later


def _tension(sc: dict) -> float:
    if sc["kind"] == "intro":
        return 0.12
    if sc["kind"] == "rule":
        return 0.16 + 0.125 * sc["rule_no"]
    return 0.92 if not sc.get("final") else 1.0


async def _voice(text: str, who: dict, mp3: Path, whisper: bool, damage: float = 0.0):
    if who.get("voice") == "file":                                       # narration recorded elsewhere (narration_file.py): already cut and timed
        shutil.copy(who["raw"], mp3); words = who["words"]
    elif who.get("voice") == "clone":                                      # the Arabic series: the narrator's own cloned voice (arabic_voice.py)
        import arabic_voice as av
        words = await asyncio.to_thread(av.synth, text, mp3, 0.35 if whisper else 0.5, 0.5)
    else:
        words = await rv._tts(text, who["voice"], who.get("rate", "+0%"), who.get("pitch", "+0Hz"), mp3)
    toks = text.split()
    if len(toks) == len(words) and who.get("voice") != "clone":
        words = [(a, b, tk) for (a, b, _), tk in zip(words, toks)]
    if not whisper and who.get("voice") == "file":                       # a real voice is kept natural: just rumble and hiss off, evened out
        tmp = mp3.with_suffix(".t.mp3"); mp3.rename(tmp)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", "highpass=f=110,lowpass=f=7500,acompressor=threshold=-20dB:ratio=3:makeup=3", str(mp3)]); tmp.unlink()
    elif not whisper:                                                    # an old training tape: narrow band, a little wobble, squashed
        tmp = mp3.with_suffix(".t.mp3"); mp3.rename(tmp)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", (f"highpass=f=170,lowpass=f={int(4800 - 1500 * damage)},vibrato=f=4.6:d={0.025 + 0.02 * damage:.3f},"            # every tape the narrator is a little worse: darker, wobblier, a faint echo of someone else
                      + (f"aecho=0.8:0.5:{int(25 + 55 * damage)}:{0.10 + 0.22 * damage:.2f}," if damage > 0.15 else "") + "acompressor=threshold=-20dB:ratio=3:makeup=3"), str(mp3)]); tmp.unlink()
    if whisper and who.get("voice") == "file":                           # a recorded finale stays the person's own voice: only a little warmth and a short room, no pitch games
        tmp = mp3.with_suffix(".w.mp3"); mp3.rename(tmp)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", "highpass=f=100,lowpass=f=8000,acompressor=threshold=-22dB:ratio=2.5:makeup=3,bass=g=2:f=160,aecho=0.85:0.35:90:0.12", "-ar", "44100", str(mp3)]); tmp.unlink()
    elif whisper:                                                        # the finale: not a quiet voice - a VOICE WITH SOMETHING UNDER IT
        tmp = mp3.with_suffix(".w.mp3"); mp3.rename(tmp)
        chain = ("[0:a]aresample=44100,highpass=f=70,acompressor=threshold=-26dB:ratio=4:makeup=4,asplit=4[a][b][c][d];"
                 "[a]rubberband=pitch=0.80:formant=shifted[body];"                                          # the voice itself, ~4 semitones down with the throat made bigger
                 "[b]rubberband=pitch=0.62:formant=shifted,asoftclip=type=atan:threshold=0.5,adelay=22|22,volume=0.6[growl];"   # a distorted, much lower voice just behind it: the growl
                 "[c]rubberband=pitch=0.5:formant=shifted,lowpass=f=320,volume=0.9[sub];"                   # octave down: chest
                 "[d]highpass=f=3200,acompressor=threshold=-30dB:ratio=6:makeup=6,volume=0.12[air];"       # a trace of breath
                 "[body][growl][sub][air]amix=inputs=4:weights=1 0.8 0.8 0.3:normalize=0,"
                 "bass=g=7:f=110:w=0.7,treble=g=-4:f=5000,"
                 "aecho=0.85:0.7:60|150|330:0.45|0.34|0.22,volume=1.7,alimiter=limit=0.95")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-filter_complex", chain, "-ar", "44100", str(mp3)]); tmp.unlink()
    return words


def _normalise(raw: Path, out: Path) -> None:
    """Loudness normalisation with a STATIC gain (two passes). The one-pass filter rides the gain, so a loud hit pulled the narrator's volume down."""
    src = ["-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw)]
    base = "loudnorm=I=-15:TP=-1.5:LRA=11"
    try:
        r = subprocess.run(["ffmpeg", "-v", "info", *src, "-af", base + ":print_format=json", "-f", "null", "-"], capture_output=True, text=True).stderr
        m = json.loads(r[r.rindex("{"): r.rindex("}") + 1])
        af = f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true"
    except Exception:
        af = base
    run(["ffmpeg", "-y", "-v", "error", *src, "-af", af, str(out)])


def _wav(mp3: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


SHOW_ARCHIVIST_NOTE = False                                                          # the "TAPE 07 - ..." line on the end card; switched off at the user's request (stories still store it)


def _motion_shot(src: Path, length: float, out: Path) -> None:
    """Fit a dropped-in video clip to its scene: crop to 9:16, slow it down (up to 1.6x) if it is shorter than the narration, hold its
    last frame if still short, trim if longer. No fades - the tape degradation is applied over the whole video afterwards."""
    dur = probe_duration(src)
    stretch = min(1.6, length / dur) if dur < length else 1.0
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},setpts={stretch:.4f}*PTS,"
          f"tpad=stop_mode=clone:stop_duration={length:.2f},trim=duration={length:.2f},setpts=PTS-STARTPTS,format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-crf", "20", "-preset", "medium", str(out)])


def build_horror_video(story_dir: str, log=print, dread: bool = True, yt: bool = False) -> Path:
    sdir = Path(story_dir).resolve()
    story = json.loads((sdir / "story.json").read_text(encoding="utf-8"))
    work = sdir / "build_horror"; work.mkdir(exist_ok=True)
    try:
        import story_variety as _sv
        damage = _sv.narrator_damage(int(story.get("tape_no") or 0))
    except Exception:
        damage = 0.0
    prof = (story.get("scare_profile") or "classic") if dread else "classic"          # where the scare lands (story_variety.PROFILES); old episodes have none = classic
    if prof not in ("classic", "late", "quiet", "false_calm", "double"):
        prof = "classic"
    jr = random.Random(zlib.crc32(story.get("title", "").encode()))
    varied = bool(story.get("scare_profile"))                                          # new-style tapes move the ambient sounds around; old ones keep their timings
    knock_frac = 0.5 + (jr.uniform(-0.12, 0.08) if varied else 0.0)
    narr = story["characters"]["Narrator"]; whisper_voice = {**VOICES["creepy_whisper"], "rate": "-26%", "pitch": "-24Hz"}      # slower and lower: it takes its time
    arabic = story.get("language") == "ar"
    med = story.get("design") == "medina"                                              # the Khbir design system: lantern look, gold frame, Moroccan instruments (medina_look.py / medina_sfx.py)
    if story.get("voice_engine") == "clone":
        whisper_voice = {"voice": "clone"}                                              # the same cloned voice, lowered by the whisper filter below
    cap_kw = {"font": "Geeza Pro", "size": 84, "bold": 1, "badge_size": 130, "rtl": True} if arabic else {}
    if med:
        cap_kw.update(base="&H00DCEEF6", hi="&H003CBEFF&", outline="&H00060A12")            # ivory words, the spoken word in saffron, a warm near-black outline
    label = story.get("tape_label") or f"{(story.get('title_lines') or [story['title']])[-1]} - NIGHT STAFF ORIENTATION - 1994".upper()[:60]

    # ---- 1. the end card: the viewer-question is pulled out of the last scene so the scare is the last thing heard
    scenes_in = [dict(s) for s in story["scenes"]]
    last = scenes_in[-1]["lines"][0]["text"]
    sentences = re.split(r"(?<=[.!?\u061f\u2014])\s+", last.strip())
    question = sentences[-1] if len(sentences) > 1 and sentences[-1].endswith(("?", "\u061f")) else ""
    if question:
        scenes_in[-1]["lines"] = [{"who": "Narrator", "text": " ".join(sentences[:-1])}]
    scenes_in[-1]["final"] = True

    # ---- 2. voices and timeline: ONE continuous narration. The scenes only mark where the picture changes - the pictures follow the words, there are no gaps
    #         between scenes. The only pause is a short beat before the whispered final scare.
    log("[horror] Voices...")
    main_in, fin_in = scenes_in[:-1], scenes_in[-1]
    texts = [sc["lines"][0]["text"] for sc in main_in]
    main_mp3 = work / "voice_main.mp3"
    ext = None
    if story.get("narration_audio"):                                                   # a finished recording instead of a synthetic voice
        import narration_file as nf
        ext = nf.prepare(sdir / story["narration_audio"], texts + [fin_in["lines"][0]["text"]], work, question if story.get("question_spoken") else "")
    words = asyncio.run(_voice(" ".join(texts), {"voice": "file", "raw": ext[0], "words": ext[1]} if ext else narr, main_mp3, False, damage))
    VO = 0.05                                                                          # the voice starts a hair after the first picture
    n_tok = sum(len(t.split()) for t in texts); ratio = len(words) / max(1, n_tok)    # if the engine merged/split a word, scale the slices
    bounds, k = [], 0
    for c in (len(t.split()) for t in texts):
        bounds.append((int(round(k * ratio)), int(round((k + c) * ratio)))); k += c
    bounds[-1] = (bounds[-1][0], len(words))
    narr_wav = _wav(main_mp3).copy(); gaps = {}; jolt_gapped = False
    if dread:                                                                          # real silences in the narration: the narrator stops, the sound lands, then he goes on
        ti = next((j for j, s_ in enumerate(main_in) if s_.get("kind") == "twist"), None) if prof in ("classic", "false_calm", "double") else None
        if ext:                                                                        # recorded narration: a stop only where the voice really pauses between two lines - never inside a sentence
            quiet = [bd[0] for bd in bounds[1:-1] if words[bd[0]][0] - words[bd[0] - 1][1] >= 0.15]
            if ti is not None and quiet:
                gaps[min(quiet, key=lambda i: abs(i - bounds[ti][0]))] = GAP_JOLT_REC; jolt_gapped = True
            jg = next(iter(gaps), -99)
            far = [i for i in quiet if abs(i - jg) >= 8]
            if far:
                gaps[min(far, key=lambda i: abs(i - knock_frac * len(words)))] = GAP_KNOCK
        else:
            if ti is not None and bounds[ti][0] > 0:
                gaps[bounds[ti][0]] = GAP_JOLT; jolt_gapped = True
            jg = bounds[ti][0] if jolt_gapped else -99
            okay = [i for i in range(8, len(words) - 8) if abs(i - jg) >= 8]
            ends = [i for i in okay if re.search(r"[.!?\u061f\u060c]$", str(words[i - 1][2]))] or okay
            if ends:
                gaps[min(ends, key=lambda i: abs(i - knock_frac * len(words)))] = GAP_KNOCK
    gap_t = {}; shift = 0.0; shifted = []; cuts = []
    for i, (a_, b_, w_) in enumerate(words):
        if i in gaps:
            t0 = (words[i - 1][1] + a_) / 2
            cuts.append((int(t0 * SR), gaps[i])); gap_t[i] = t0 + shift; shift += gaps[i]
        shifted.append((a_ + shift, b_ + shift, w_))
    for pos, g_ in reversed(cuts):
        narr_wav = np.concatenate([narr_wav[:pos], np.zeros(int(g_ * SR), dtype=narr_wav.dtype), narr_wav[pos:]])
    words = shifted
    starts = [0.0] + [max(0.0, (VO + gap_t[bd[0]]) if bd[0] in gap_t else (VO + words[bd[0]][0] - 0.06)) for bd in bounds[1:]]    # the picture changes just before the scene's first word (at the start of its silence if it has one)
    slots = []
    if ext:                                                                            # recorded narration: every hit lands in a real silence of the narrator, never over a word
        slots = [VO + words[bd[0] - 1][1] + 0.03 for bd in bounds[1:] if words[bd[0]][0] - words[bd[0] - 1][1] >= 0.15]
    snap = (lambda t: min(slots, key=lambda s_: abs(s_ - t))) if slots else (lambda t: t)
    main_end = VO + words[-1][1] + 0.25
    scenes = []
    for i, (sc, (lo, hi)) in enumerate(zip(main_in, bounds), 1):
        is_last = i == len(main_in)
        end = (main_end + SILENCE_BEFORE_FINAL) if is_last else starts[i]
        rel = [(VO + a_ - starts[i - 1], VO + b_ - starts[i - 1], w) for a_, b_, w in words[lo:hi]]
        scenes.append({"i": i, "kind": sc.get("kind", "rule"), "rule_no": sc.get("rule_no", 0), "final": False, "start": starts[i - 1], "len": end - starts[i - 1], "lead": 0.0, "dur": 0.0,
                       "mp3": None, "words": rel, "image": sdir / sc["image"], "tail": SILENCE_BEFORE_FINAL if is_last else 0.0, "label": sc.get("label", ""),
                       "badge": (sc["label"] if sc.get("label") else "" if story.get("format") in ("scp", "arabic") else f"RULE {sc['rule_no']}" if sc.get("kind") in ("rule", "twist") and sc.get("rule_no") and not any(s["kind"] == "twist" for s in scenes if sc.get("kind") == "twist") else "")})
    fmp3 = work / "voice_final.mp3"
    fwords = asyncio.run(_voice(fin_in["lines"][0]["text"], {"voice": "file", "raw": ext[2], "words": ext[3]} if ext else whisper_voice, fmp3, True))
    fdur = probe_duration(fmp3); flead = 0.35
    fstart = main_end + SILENCE_BEFORE_FINAL
    scenes.append({"i": len(scenes) + 1, "kind": fin_in.get("kind", "twist"), "rule_no": fin_in.get("rule_no", 0), "final": True, "start": fstart, "len": flead + fdur + 0.16, "lead": flead,
                   "dur": fdur, "mp3": fmp3, "words": fwords, "image": sdir / fin_in["image"], "tail": 0.0, "label": "", "badge": ""})
    story_end = fstart + flead + fdur + 0.16
    total = story_end + 0.6 + CARD                                                     # + tape dying + end card
    log(f"[horror] narrator stops at " + ", ".join(f"{VO + gap_t[i]:.2f}s ({gaps[i]}s)" for i in gaps) + f"; {len(slots)} silences for the hits")
    log(f"[horror] {len(scenes)} scenes, story {story_end:.1f}s, total {total:.1f}s")

    # ---- 3. shots: calm early (long), quicker later
    clips = []
    for sc in scenes:
        mclip = motion_clip_path(sdir, sc["i"])                                       # a real video clip dropped on this scene replaces its picture
        if mclip.exists():
            clip = work / f"s{sc['i']}_motion.mp4"
            _motion_shot(mclip, sc["len"], clip); clips.append(clip)
            log(f"[horror] scene {sc['i']}: using your clip")
            continue
        if not sc["image"].exists():
            raise RuntimeError(f"Missing picture {sc['image'].name} - make the pictures first.")
        target = 4.3 - 1.6 * min(1.0, _tension(sc))
        shot_time = sc["len"] - sc["tail"]
        n = max(1, int(round(shot_time / target))); segs = []
        if sc["i"] == 1:
            poster = (__import__("medina_look").poster if med else rv._poster)(story, sc["image"], work / "poster.png"); first = min(2.8, shot_time * 0.55)
            segs.append((poster, first)); rest = shot_time - first; k = max(1, int(round(rest / target))); segs += [(sc["image"], rest / k)] * k
        else:
            segs = [(sc["image"], shot_time / n)] * n
        if sc["tail"]:
            segs[-1] = (segs[-1][0], segs[-1][1] + sc["tail"])                       # hold the last picture through the silence
        for j, (img, d) in enumerate(segs):
            clip = work / f"s{sc['i']}_{j}.mp4"
            rv._shot(img, d, -1 if (sc["i"] == 1 and j == 0) else sc["i"] * 2 + j, clip); clips.append(clip)
    if med:                                                                          # a short hold after the last line, so the lantern can die and the end card can fade in on real frames
        hold = work / "endhold.mp4"; rv._shot(scenes[-1]["image"], 1.1, 3, hold); clips.append(hold)
    (work / "clips.txt").write_text("".join(f"file '{c.name}'\n" for c in clips))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "clips.txt"), "-c", "copy", str(work / "silent.mp4")])

    # ---- 4. the tape: tension curve + events
    curve = [(0.0, 0.08)] + [(sc["start"] + sc["lead"], _tension(sc)) for sc in scenes] + [(story_end, 1.0), (total, 1.0)]
    final = scenes[-1]
    reveal = final["start"]
    turn0 = next((s for s in scenes if s["kind"] == "twist" and not s["final"]), None)
    jolt = (turn0["start"] + (0.95 if (jolt_gapped and ext) else 0.4 if jolt_gapped else 0.45)) if (dread and turn0 and prof in ("classic", "false_calm", "double")) else None
    events = []
    for sc in scenes:
        if sc["kind"] == "rule" and sc["rule_no"] >= 3 and not med:
            events.append({"t": sc["start"], "dur": 0.07, "kind": "static"})
        if sc["kind"] == "rule" and sc["rule_no"] == 4:
            events.append({"t": sc["start"] + 1.4, "dur": 0.07, "kind": "flash", "image": "twist"})                    # one subliminal frame
        if sc["kind"] == "rule" and sc["rule_no"] == 5 and not med:
            events.append({"t": sc["start"] + 2.2, "dur": 0.4, "kind": "roll"})
    events += [{"t": final["start"] - SILENCE_BEFORE_FINAL, "dur": 0.28, "kind": "freeze"},
               ({"t": jolt, "dur": 0.34, "kind": "slam"} if jolt else {"t": reveal, "dur": 0.34, "kind": "slam"}),
               {"t": story_end, "dur": 0.6, "kind": "static"}, {"t": story_end + 0.45, "dur": 6.0 if med else 0.15, "kind": "card" if med else "black"}]
    if dread:                                                                         # one-frame glimpses of the entity, spread out so you never know when
        events += [{"t": story_end * 0.55, "dur": 0.04, "kind": "flash", "image": "twist"}, {"t": story_end * 0.77, "dur": 0.04, "kind": "flash", "image": "twist"},
                   {"t": reveal + 1.1, "dur": 0.04, "kind": "flash", "image": "twist"}]
    beats = []
    if dread:
        hb0 = VO + 0.4; hb_end = (jolt - 0.35) if jolt else (reveal - 1.0)
        beats = [hb0 + b for b in sfx.heartbeat_times(hb_end - hb0, 52, 128)]
        if jolt:
            beats += [jolt + 1.2 + b for b in sfx.heartbeat_times(reveal - jolt - 1.2, 132, 132)]
    log("[horror] Degrading the tape...")
    fxv = work / "fx.mp4"
    horror_fx.process(str(work / "silent.mp4"), str(fxv), curve, events, (story.get("badge_label") or "الخبير") if med else label, {"twist": str(final["image"])}, log=log, beats=beats, soft=yt,
                      look="medina" if med else "tape", number=__import__("medina_look").arabic_digits(int(story.get("tape_no") or 0)) if med else "")

    # ---- 5. sound
    log("[horror] Sound design...")
    n = int((total + 1) * SR); mixL = np.zeros(n); mixR = np.zeros(n); px_used = []
    def put(sound, at, gain=1.0, pan=0.0):                                         # pan -1 (left ear) .. +1 (right ear)
        i = int(max(0, at) * SR)
        if i < n:
            seg = sound[: n - i] * gain; ang = (pan + 1) * np.pi / 4
            mixL[i:i + len(seg)] += seg * np.cos(ang) * 1.414; mixR[i:i + len(seg)] += seg * np.sin(ang) * 1.414
    real_put = put
    if med:
        put = lambda *a, **k: None                                                  # the SCP sound design below is skipped for this series; medina_sfx plays instead
    nL = np.zeros(n); nR = np.zeros(n)
    def put_n(sound, at):                                                          # the narrator has its own bus: nothing ever ducks it or squashes it
        i = int(max(0, at) * SR)
        if i < n:
            seg = sound[: n - i]; nL[i:i + len(seg)] += seg; nR[i:i + len(seg)] += seg
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
    if dread:
        put(shape(sfx.rising_bed(story_end), [(0, 0), (6, 0.06), (story_end * 0.8, 0.2), (story_end - 0.3, 0.26), (story_end, 0)]), 0)           # never resolves
        put(shape(sfx.drone(story_end), [(0, 0), (2, 0.3), (story_end - 0.5, 0.42), (story_end, 0)]), 0)
        hb_a = sfx.heartbeat(hb_end - hb0, 52, 128)                                # starts almost at once and speeds up; it STOPS before the jolt
        put(shape(hb_a, [(0, 0.25), (len(hb_a) / SR * 0.5, 0.6), (len(hb_a) / SR - 0.05, 0.95), (len(hb_a) / SR, 0)]), hb0)
        if jolt:
            hb_b = sfx.heartbeat(reveal - jolt - 1.2, 132, 132)
            put(shape(hb_b, [(0, 0.5), (len(hb_b) / SR, 0)]), jolt + 1.2)
        behind = [lambda k=k: sfx.pixabay("behind", 6.5, 0.0, 0.6, pick=k) for k in (0, 1)]       # something close behind you, one ear then the other (real recording if present)
        if behind[0]() is not None: px_used.append("behind")
        def _slot(k):
            return behind[k] if behind[k]() is not None else sfx.breath
        jt = (lambda f: f + jr.uniform(-0.05, 0.05)) if varied else (lambda f: f)
        for frac, snd, pan, g in ((jt(0.30), _slot(0), -0.95, 0.8), (jt(0.43), sfx.door_creak, 0.9, 0.45), (jt(0.66), _slot(1), 0.95, 0.8), (jt(0.78), sfx.door_creak, -0.9, 0.5)):
            put(snd(), snap(story_end * frac), g, pan)                                   # sounds from behind you, in one ear, on no word
        kg = next((i for i, g_ in gaps.items() if g_ == GAP_KNOCK), None)
        if kg is not None:                                                         # the narrator stops; silence; the knock; a breath close to the mic; then he goes on
            kt = VO + gap_t[kg] + 0.28
            kn = sfx.pixabay("knock", 0.7, 0.0, 0.03)
            put(kn if kn is not None else sfx.knock(), kt, 1.5, -0.7)
            if kn is not None: px_used.append("knock")
            put(sfx.breath(), kt + 0.35, 0.3, 0.85)
    fstart = scenes[-1]["start"] + scenes[-1]["lead"]
    if dread:                                                                      # real recordings (Pixabay) layered where the research says the fear is
        vb = sfx.pixabay("whisper2", 24, 2, 4)
        if vb is not None:                                                         # voices in your head: very quiet, wide, from the build-up on, gone before the silence
            span = max(4.0, silence_at - 0.5 - story_end * 0.35); vb = vb[: int(span * SR)]
            put(shape(vb, [(0, 0), (2.5, 0.14), (len(vb) / SR - 2, 0.2), (len(vb) / SR, 0)]), story_end * 0.35, 1.0, -0.45); px_used.append("voices")
        sc_ = sfx.pixabay("scare1", 3.2, 0.0, 0.05)
        hit_t = (jolt if jolt and prof == "classic" else reveal) if prof != "quiet" else None            # classic: at the mid-story jolt; otherwise at the reveal; quiet: none
        if sc_ is not None and hit_t is not None:
            put(sc_, hit_t - 0.02, 0.8); px_used.append("scare")
        sw = sfx.pixabay("swell1", 3.0, 0.0, 0.2)
        if sw is not None:                                                         # a ghostly swell on the tape moments (roll, final static)
            for ev in events:
                if ev["kind"] == "roll" or (ev["kind"] == "static" and ev["t"] >= story_end):
                    put(sw, snap(ev["t"] - 0.15), 0.5); px_used.append("swell")
        vp = sfx.pixabay("vocal1", scenes[-1]["dur"] + 1.2, 1.0, 0.5)
        if vp is not None:                                                         # a vocal presence under the monster's line
            put(vp, fstart - 0.2, 0.5); px_used.append("vocal")
        dn = sfx.pixabay_loop("drone", scenes[-1]["dur"] + 1.6)
        if dn is not None:                                                         # a steady, wide dread tone under the whole monster line
            put(dn, fstart - 0.5, 0.45); px_used.append("drone")
        wh = sfx.pixabay("whisper1", 4.2, 0.0, 0.1)
        if wh is not None:                                                         # and a second voice, in each ear in turn
            put(wh, fstart + 0.2, 0.42, 0.9); put(wh, fstart + 0.2 + scenes[-1]["dur"] * 0.45, 0.34, -0.9); px_used.append("whisper")
    if dread:                                                                      # more real recordings: tape glitches on the static, a growl under the thing
        gl = sfx.pixabay("glitch", 0.35, 0.0, 0.03)
        if gl is not None:
            for ev in events:
                if ev["kind"] in ("static", "roll") and ev["t"] < story_end - 1:
                    put(gl, snap(ev["t"]), 0.3, jr.uniform(-0.6, 0.6))
            px_used.append("glitch")
        gw = sfx.pixabay("growl", 3.4, 0.0, 0.6)
        if gw is not None:
            put(gw, fstart - 0.3, 0.5, 0.2); px_used.append("growl")
            if jolt_gapped and jolt:
                put(gw[: int(2.4 * SR)], jolt + 0.2, 0.4, -0.3)                    # it is down there with you, right after the scream
    if dread:                                                                      # your newer recordings
        bed = story.get("bed_sound")
        if bed:                                                                    # a story-specific sound under the whole build-up (SCP-087: a child crying far below)
            span = max(4.0, silence_at - 0.5 - scenes[1]["start"]); bd = sfx.pixabay(bed, min(span, 48.0), 2.0, 3.0)
            if bd is not None:
                put(bd, scenes[1]["start"], 0.22, 0.35); px_used.append(bed)
        vc = sfx.pixabay("voices", 12.0, 3.0, 3.0)
        if vc is not None:                                                         # a crowd of voices far off, rising into the silence
            put(vc, max(0.0, silence_at - 12.5), 0.16, -0.5); px_used.append("crowd")
        rv_ = sfx.pixabay("reverse", None, 0.0, 0.05)
        if rv_ is not None and jolt:                                               # the suck-in just before the scream
            ln_ = 0.9 if ext else 1.6                                              # recorded narration: the suck-in lives inside the stop, it never runs over a word
            tail = rv_[-int(ln_ * SR):].copy(); tail[: int(0.2 * SR)] *= np.linspace(0, 1, int(0.2 * SR))
            put(tail, jolt - ln_ - 0.02, 0.55); px_used.append("reverse")
        st_ = sfx.pixabay("steps", 3.6, 0.0, 0.3)
        if st_ is not None:                                                        # slow heavy footsteps behind you, from one ear
            put(st_, snap(story_end * 0.62), 0.55, 0.9); px_used.append("steps")
        dr_ = sfx.pixabay("door", None, 0.0, 0.01)
        if dr_ is not None:                                                        # a heavy door, cut around its loudest hit
            pk = int(np.argmax(np.abs(dr_))); seg = dr_[max(0, pk - int(0.2 * SR)): pk + int(1.4 * SR)].copy(); k_ = int(0.05 * SR)
            seg[:k_] *= np.linspace(0, 1, k_); seg[-k_:] *= np.linspace(1, 0, k_)
            put(seg, snap(story_end * 0.78), 0.6, -0.8); px_used.append("door")
    put_n(narr_wav, VO)                                                            # the narrator: one continuous take, with real silences where the hits land
    put_n(_wav(scenes[-1]["mp3"]), scenes[-1]["start"] + scenes[-1]["lead"])       # then the whispered finale
    used = 0
    for sc in ([] if ext else scenes):                                             # foley on the spoken word (estimated word times are not exact enough for a recording), sound slightly BEFORE the picture it belongs to
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
    if turn and prof != "quiet":                                                                       # a smaller scare earlier, so the big one is not the only thing to flinch at
        put(sfx.scream_stab(0.4), turn["start"] + turn["lead"] + 0.2, 0.3)
        put(sfx.static_burst(0.18), turn["start"] + turn["lead"] + 0.18, 0.5)
    big = sfx.real_scream(len(story.get('title', ''))) if sfx.real_scream() is not None else sfx.jump_scream()
    if prof == "quiet":
        pass                                                                       # no scream at all: the heartbeat, the silence and the whisper are the scare
    elif prof == "false_calm" and jolt:
        put(big, jolt - 0.02, 0.35)                                                # a small stab that FEELS like the scare...
        put(big, reveal - 0.02, 1.15)                                              # ...then the real one, once you have relaxed
    elif prof == "double" and jolt:
        put(big, jolt - 0.02, 1.0)
        put(sfx.real_scream(len(story.get('title', '')) + 3) if sfx.real_scream() is not None else sfx.jump_scream(), reveal - 0.02, 1.1)
    elif jolt:
        put(big, jolt - 0.02, 1.15)                                                  # THE jump scare: mid-story, right after the heartbeat stops dead
    else:
        put(big, reveal - 0.02, 1.15)                                                # late: it all lands at the reveal
    st = sfx.sting(1.1)                                                            # the ONE sting: its rise ends just before the reveal picture
    put(st, reveal - 1.1 - 0.08, 0.5 if jolt and prof in ("classic", "double") else 0.85)
    fin = story.get("finale_sfx") or ("snap" if story.get("format") == "scp" and "173" in json.dumps(story.get("credit", {})) else "scream")
    voice_end = final["start"] + final["lead"] + final["dur"]
    ft = story.get("finale_type")                                                  # how the last line ends decides what comes right after it (old tapes: always the stab)
    if ft in ("unfinished", "countdown"):
        put(sfx.static_burst(0.3), voice_end + 0.02, 0.9)                          # a hard cut mid-word / mid-number
    elif ft in ("confession", "lullaby", "narrator_is_it"):
        pass                                                                        # nothing: it ends in silence, then the tape dies
    elif fin == "snap":
        put(sfx.snap(), voice_end + 0.06, 1.0)
    elif fin == "scream" or ft in ("taunt", "command", "mimic"):
        put(sfx.scream_stab(), voice_end + 0.06, 0.8)
    put(sfx.tape_stop(0.8), story_end - 0.1, 0.8)
    put(sfx.static_burst(0.6), story_end, 0.5)
    if med:
        put = real_put
        import medina_sfx as ms
        se = story_end; sa = silence_at
        put(shape(ms.night_air(total), [(0, 0), (2.5, 0.30), (sa - 0.3, 0.34), (sa + 0.3, 0.12), (se, 0.1), (se + 0.6, 0)]), 0)                      # the medina at night: wind, far crickets
        gl_ = ms.guembri_line(se, 52.0)
        put(shape(gl_, [(0, 0), (5, 0.0), (11, 0.35), (sa * 0.6, 0.55), (sa - 0.5, 0.75), (sa, 0.0), (se, 0)]), 0)                                   # a slow gnawa bass line that thickens with the dread
        for b in beats:                                                              # the heartbeat is a bendir, on the same beats the picture pulses to
            g_ = 0.3 + 0.7 * min(1.0, b / max(1.0, sa))
            put(ms.bendir("doum"), b, 0.55 * g_, -0.1)
            put(ms.bendir("doum", 0.55), b + 0.24, 0.35 * g_, 0.1)
        q_t0 = max(8.0, se * 0.50); q_span = sa - 0.3 - q_t0
        if q_span > 3:
            q_ = ms.qraqeb(q_span, 0.7); put(shape(q_, [(0, 0), (3, 0.3), (q_span - 0.5, 0.65), (q_span, 0)]), q_t0, 1.0, 0.2)                          # the castanets come in with the dread
        put(ms.ney([0, 1, 2], 1.5, seed=3), snap(se * 0.20), 0.32, 0.35)                                                                              # a lonely flute
        put(ms.ney([4, 3, 2, 1, 0], 1.7, seed=8), snap(se * 0.58), 0.34, -0.35)
        for k_, f_ in enumerate((0.11, 0.33, 0.49, 0.71, 0.86)):
            put(ms.drip(), snap(se * f_), 0.5, 0.8 if k_ % 2 else -0.8)                                                                               # the well, far below
        for frac, pan_, pk_ in ((0.30, -0.95, 0), (0.66, 0.95, 1)):
            bh_ = sfx.pixabay("behind", 6.5, 0.0, 0.6, pick=pk_)
            if bh_ is not None:
                put(bh_, snap(se * frac), 0.6, pan_)
        kg_ = next((i for i, g__ in gaps.items() if g__ == GAP_KNOCK), None)
        if kg_ is not None:
            kn_ = sfx.pixabay("knock", 0.7, 0.0, 0.03)
            put(kn_ if kn_ is not None else sfx.knock(), VO + gap_t[kg_] + 0.28, 1.4, -0.7)
        st2 = sfx.pixabay("steps", 3.6, 0.0, 0.3)
        if st2 is not None:
            put(st2, snap(se * 0.62), 0.5, 0.9)
        if jolt:
            rv2 = sfx.pixabay("reverse", None, 0.0, 0.05)
            if rv2 is not None:
                ln2 = 0.9 if ext else 1.6; tl2 = rv2[-int(ln2 * SR):].copy(); tl2[: int(0.2 * SR)] *= np.linspace(0, 1, int(0.2 * SR)); put(tl2, jolt - ln2 - 0.02, 0.5)
            put(ms.slam(), jolt - 0.02, 1.0)                                                                                                          # the scare: bendir, castanets, guembri
        put(shape(ms.qraqeb(1.1, 1.0), [(0, 0), (1.0, 1.0), (1.1, 0)]), reveal - 1.2, 0.45)                                                           # the rise into the reveal
        put(ms.bendir("doum"), reveal - 0.02, 0.9)
        put(ms.ember_out(), story_end - 0.1, 0.7)                                                                                                     # the end: one low note and a last drip
    st_mix = np.tanh(np.stack([mixL, mixR], axis=1) * 0.9) * 0.85 + np.stack([nL, nR], axis=1)        # effects are soft-limited on their own; the narrator is added clean
    st_mix = st_mix / max(1e-9, np.abs(st_mix).max()) * 0.92
    raw = work / "mix.raw"; raw.write_bytes((st_mix[: int(total * SR)] * 32767).astype(np.int16).tobytes())
    _normalise(raw, work / "audio.wav"); raw.unlink()
    log(f"[horror] {used} foley cues placed on spoken words" + (f"; real recordings: {', '.join(sorted(set(px_used)))}" if px_used else ""))

    # ---- 6. captions + the end card
    rv._captions(scenes, work / "captions.ass", **cap_kw)
    cap = work / "captions.ass"
    extra = ""
    if question:
        import arabic_voice
        q_show = arabic_voice.visual(question) if arabic else question.upper()
        q_style = "\\c&H003CBEFF&\\bord8" if med else ""
        extra += (f"Dialogue: 3,{rv._ass_time(story_end + 0.7)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an5\\pos(540,960)\\fs84\\fad(200,0){q_style}}}{q_show}\n")
    note = (story.get("archivist_note") or "").strip() if SHOW_ARCHIVIST_NOTE else ""
    if note:                                                                        # the archivist thread: "TAPE 07" and a one-line note that gets stranger tape by tape
        extra += (f"Dialogue: 3,{rv._ass_time(story_end + 1.5)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an5\\pos(540,1540)\\fs46\\c&H007090FF&\\bord6\\3c&H00000000&\\shad3\\fad(900,0)}}"
                  + note.replace("  -  ", "\\N") + "\n")
    try:                                                                            # a reason to come back: which tape is next (the queue head at the time this tape is built)
        nxt = json.loads((Path(__file__).parent / "data" / "scp_queue.json").read_text(encoding="utf-8")).get("queue", [])
    except (OSError, json.JSONDecodeError):
        nxt = []
    if nxt and story.get("format") == "scp":
        extra += (f"Dialogue: 3,{rv._ass_time(story_end + 2.2)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an5\\pos(540,1330)\\fs40\\c&H00E6E6E6&\\bord5\\3c&H00000000&\\shad2\\fad(700,0)}}"
                  f"NEXT TAPE  -  SCP-{str(nxt[0]).zfill(3)}\n")
    if story.get("credit"):
        extra += (f"Dialogue: 3,{rv._ass_time(story_end + 0.7)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an2\\pos(540,1840)\\fs30\\c&H00C8C8C8&\\bord3}}{story['credit']['line']}\n")
    if extra:
        cap.write_text(cap.read_text(encoding="utf-8") + extra, encoding="utf-8")
    out = sdir / f"{sdir.name}-HORROR{'' if dread else '-classic'}{'-YT' if yt else ''}.mp4"
    log("[horror] Final render...")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "fx.mp4", "-i", "audio.wav", "-vf", (f"tpad=stop_mode=clone:stop_duration={CARD + 1:.1f},scale=1440:2560:flags=lanczos,subtitles=captions.ass:original_size=1080x1920" if yt
                                                 else f"tpad=stop_mode=clone:stop_duration={CARD + 1:.1f},subtitles=captions.ass"),
                    "-t", f"{total:.2f}", "-c:v", "libx264", "-crf", "20" if yt else "28", "-preset", "medium", "-maxrate", "12M" if yt else "6M", "-bufsize", "24M" if yt else "12M",      # the grain is heavy: bound the bitrate (~40 MB)
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)], cwd=work, check=True)
    shutil.rmtree(work, ignore_errors=True)                                      # ~500 MB of intermediate clips; the result is the video
    log(f"[horror] Done -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("story_dir"); ap.add_argument("--classic", action="store_true", help="the older, simpler cut (no constant dread build-up)"); ap.add_argument("--yt", action="store_true", help="YouTube-quality export: lighter grain, 1440x2560, higher bitrate (bigger file)"); a = ap.parse_args()
    build_horror_video(a.story_dir, dread=not a.classic, yt=a.yt)
