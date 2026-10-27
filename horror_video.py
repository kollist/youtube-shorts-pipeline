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


async def _voice(text: str, who: dict, mp3: Path, whisper: bool, damage: float = 0.0):
    words = await rv._tts(text, who["voice"], who.get("rate", "+0%"), who.get("pitch", "+0Hz"), mp3)
    toks = text.split()
    if len(toks) == len(words):
        words = [(a, b, tk) for (a, b, _), tk in zip(words, toks)]
    if not whisper:                                                      # an old training tape: narrow band, a little wobble, squashed
        tmp = mp3.with_suffix(".t.mp3"); mp3.rename(tmp)
        run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-af", (f"highpass=f=170,lowpass=f={int(4800 - 1500 * damage)},vibrato=f=4.6:d={0.025 + 0.02 * damage:.3f},"            # every tape the narrator is a little worse: darker, wobblier, a faint echo of someone else
                      + (f"aecho=0.8:0.5:{int(25 + 55 * damage)}:{0.10 + 0.22 * damage:.2f}," if damage > 0.15 else "") + "acompressor=threshold=-20dB:ratio=3:makeup=3"), str(mp3)]); tmp.unlink()
    if whisper:                                                          # the finale: not a quiet voice - a VOICE WITH SOMETHING UNDER IT
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


def _wav(mp3: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


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
    words = asyncio.run(_voice(" ".join(texts), narr, main_mp3, False, damage))
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
                       "badge": (sc["label"] if sc.get("label") else "" if story.get("format") == "scp" else f"RULE {sc['rule_no']}" if sc.get("kind") in ("rule", "twist") and sc.get("rule_no") and not any(s["kind"] == "twist" for s in scenes if sc.get("kind") == "twist") else "")})
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
    turn0 = next((s for s in scenes if s["kind"] == "twist" and not s["final"]), None)
    jolt = (turn0["start"] + 0.45) if (dread and turn0 and prof in ("classic", "false_calm", "double")) else None
    events = []
    for sc in scenes:
        if sc["kind"] == "rule" and sc["rule_no"] >= 3:
            events.append({"t": sc["start"], "dur": 0.07, "kind": "static"})
        if sc["kind"] == "rule" and sc["rule_no"] == 4:
            events.append({"t": sc["start"] + 1.4, "dur": 0.07, "kind": "flash", "image": "twist"})                    # one subliminal frame
        if sc["kind"] == "rule" and sc["rule_no"] == 5:
            events.append({"t": sc["start"] + 2.2, "dur": 0.4, "kind": "roll"})
    events += [{"t": final["start"] - SILENCE_BEFORE_FINAL, "dur": 0.28, "kind": "freeze"},
               ({"t": jolt, "dur": 0.34, "kind": "slam"} if jolt else {"t": reveal, "dur": 0.34, "kind": "slam"}),
               {"t": story_end, "dur": 0.6, "kind": "static"}, {"t": story_end + 0.45, "dur": 0.15, "kind": "black"}]
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
    horror_fx.process(str(work / "silent.mp4"), str(fxv), curve, events, label, {"twist": str(final["image"])}, log=log, beats=beats, soft=yt)

    # ---- 5. sound
    log("[horror] Sound design...")
    n = int((total + 1) * SR); mixL = np.zeros(n); mixR = np.zeros(n); px_used = []
    def put(sound, at, gain=1.0, pan=0.0):                                         # pan -1 (left ear) .. +1 (right ear)
        i = int(max(0, at) * SR)
        if i < n:
            seg = sound[: n - i] * gain; ang = (pan + 1) * np.pi / 4
            mixL[i:i + len(seg)] += seg * np.cos(ang) * 1.414; mixR[i:i + len(seg)] += seg * np.sin(ang) * 1.414
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
        for frac, snd, pan, g in ((jt(0.30), _slot(0), -0.95, 0.8), (jt(0.43), sfx.door_creak, 0.9, 0.45), (knock_frac, sfx.knock, -1.0, 1.5), (jt(0.66), _slot(1), 0.95, 0.8), (jt(0.78), sfx.door_creak, -0.9, 0.5)):
            put(snd(), story_end * frac, g, pan)                                   # sounds from behind you, in one ear, on no word
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
                    put(sw, ev["t"] - 0.15, 0.5); px_used.append("swell")
        vp = sfx.pixabay("vocal1", scenes[-1]["dur"] + 1.2, 1.0, 0.5)
        if vp is not None:                                                         # a vocal presence under the monster's line
            put(vp, fstart - 0.2, 0.5); px_used.append("vocal")
        dn = sfx.pixabay_loop("drone", scenes[-1]["dur"] + 1.6)
        if dn is not None:                                                         # a steady, wide dread tone under the whole monster line
            put(dn, fstart - 0.5, 0.45); px_used.append("drone")
        wh = sfx.pixabay("whisper1", 4.2, 0.0, 0.1)
        if wh is not None:                                                         # and a second voice, in each ear in turn
            put(wh, fstart + 0.2, 0.42, 0.9); put(wh, fstart + 0.2 + scenes[-1]["dur"] * 0.45, 0.34, -0.9); px_used.append("whisper")
    narr = _wav(main_mp3).copy()
    if dread:                                                                      # the narrator dips for the knock so nothing covers it
        k0 = int((story_end * knock_frac - 0.05 - VO) * SR); k1 = k0 + int(1.0 * SR)
        duck = np.ones(len(narr)); a_, b_ = max(0, k0), min(len(narr), k1)
        if a_ < b_:
            duck[a_:b_] = 0.4; r_ = int(0.06 * SR)
            duck[max(0, a_ - r_):a_] = np.linspace(1, 0.4, len(duck[max(0, a_ - r_):a_])); duck[b_:b_ + r_] = np.linspace(0.4, 1, len(duck[b_:b_ + r_]))
            narr *= duck
    put(narr, VO, 1.0)                                                             # the narrator: one continuous take
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
    st_mix = np.tanh(np.stack([mixL, mixR], axis=1) * 0.9)
    st_mix = st_mix / max(1e-9, np.abs(st_mix).max()) * 0.92
    raw = work / "mix.raw"; raw.write_bytes((st_mix[: int(total * SR)] * 32767).astype(np.int16).tobytes())
    run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw), "-af", "loudnorm=I=-15:TP=-1.5:LRA=11", str(work / "audio.wav")]); raw.unlink()
    log(f"[horror] {used} foley cues placed on spoken words" + (f"; real recordings: {', '.join(sorted(set(px_used)))}" if px_used else ""))

    # ---- 6. captions + the end card
    rv._captions(scenes, work / "captions.ass")
    cap = work / "captions.ass"
    extra = ""
    if question:
        extra += (f"Dialogue: 3,{rv._ass_time(story_end + 0.7)},{rv._ass_time(total)},Cap,,0,0,0,,{{\\an5\\pos(540,960)\\fs84\\fad(200,0)}}{question.upper().replace('?', '?')}\n")
    note = (story.get("archivist_note") or "").strip()
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
