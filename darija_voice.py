"""The narrator for the Moroccan Darija series. Per sentence: Habibi-TTS MAR model (Moroccan accent, venv-habibi) -> voice conversion to the narrator's own voice (Chatterbox VC, venv-clone).
Everything is cached per sentence in data/voice_cache, so changing one word regenerates only that sentence. Same interface as arabic_voice.synth: returns words WITHOUT vowel marks."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from arabic_voice import SR, _chunks, _trim, strip_marks

BASE = Path(__file__).parent
CACHE = BASE / "data" / "voice_cache"
REF_VC = BASE / "data" / "voice" / "expert_ref.wav"                 # the narrator's voice (what the final audio sounds like)
REF_HB = BASE / "data" / "voice" / "habibi_ref.wav"                # what Habibi is shown (any clear voice)
REF_HB_TEXT = "السلام عليكم. أنا الخبير، وهادي هي الملفات اللي ما بغاوش يشوفوها. فاش كنت صغير، جدتي كانت كتقول ليا: إلا سمعتي"
NFE = 32
SPEED = 1.1                                                          # a little faster than the model's calm default: the episode was running about 2:50
RESPELL = BASE / "data" / "darija_respell.json"                      # {"word": "how to write it so the model reads it right"}, applied to the model's text only (captions keep the normal spelling)


def _gap(chunk: str) -> float:
    return 0.55 if chunk.rstrip().endswith("...") else 0.28                      # a narrator breathes between lines (Ghalia reference: ~0.28 s)


def _lines(text: str) -> list[str]:
    """One chunk per written line (a beat of the story), so the model carries the intonation across its sentences."""
    out = []
    for ln in (l.strip() for l in text.splitlines()):
        if not re.search(r"\w", ln):
            continue
        out += [ln] if len(ln.split()) <= 24 else [p for p in re.split(r"(?<=[.؟?!])\s+", ln) if re.search(r"\w", p)]
    return out


def _respell(chunk: str) -> str:
    try:
        rs = json.loads(RESPELL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rs = {}
    for k in sorted((k for k in rs if " " in k), key=len, reverse=True):         # phrases first
        chunk = chunk.replace(k, rs[k])
    out = []
    for tok in chunk.split():
        m = re.match(r"^(\W*)(.*?)(\W*)$", tok)
        if not m:
            out.append(tok); continue
        core = rs.get(m.group(2), m.group(2))
        out.append(m.group(1) + core + m.group(3))
    return " ".join(out)


def _tighten(a, max_pause: float = 0.16):
    """Cut every silence inside a line down to max_pause: the model stalls at each punctuation mark, a narrator does not."""
    import numpy as np
    fr = int(0.02 * SR); n = len(a) // fr
    if n < 3:
        return a
    env = np.abs(a[: n * fr]).reshape(n, fr).max(axis=1)
    quiet = env < 0.02 * max(env.max(), 1e-6)
    keep = np.ones(n, dtype=bool); i = 0; mx = int(max_pause / 0.02)
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i > mx:
                keep[i + mx: j] = False
            i = j
        else:
            i += 1
    return np.concatenate([a[k * fr:(k + 1) * fr] for k in range(n) if keep[k]] + [a[n * fr:]])


def _no_dots(s: str) -> str:
    """The model voices full stops and colons as a sound: it gets only commas (the pauses are ours, see _gap)."""
    s = re.sub(r"\s*(\.{2,}|\u2026)\s*$", "", s.strip())
    s = re.sub(r"\s*[.:]+\s*$", "", s)
    s = re.sub(r"\s*(\.{2,}|\u2026|[.:])\s+", "، ", s)
    return re.sub(r"[.:]", "،", s)


def _run(py: str, worker: str, job: dict, tag: str, log) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    jf = CACHE / f"job_{tag}.json"; jf.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([str(BASE / py / "bin" / "python"), str(BASE / worker), str(jf)], text=True, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"{worker} failed:\n" + (r.stderr or r.stdout)[-900:])


def synth(text: str, out_mp3: Path, exaggeration: float = 0.5, cfg: float = 0.5, log=print) -> list[tuple[float, float, str]]:
    import soundfile as sf
    chunks = [strip_marks(c) for c in _lines(text)]                  # the model reads PLAIN Darija: vowel marks made it unintelligible
    spoken = [_no_dots(_respell(c)) for c in chunks]
    hb, vc = [], []
    for c in spoken:
        key = hashlib.sha1(f"{c}|{NFE}|{SPEED}|{REF_HB.stat().st_size}|{REF_VC.stat().st_size}".encode()).hexdigest()[:16]
        hb.append(CACHE / f"hb_{key}.wav"); vc.append(CACHE / f"vc_{key}.wav")
    todo = [{"text": c, "out": str(p)} for c, p, v in zip(spoken, hb, vc) if not v.exists() and not p.exists()]
    if todo:
        log(f"[voice] Moroccan voice: {len(todo)} sentence(s)...")
        _run("venv-habibi", "habibi_worker.py", {"ref_audio": str(REF_HB), "ref_text": REF_HB_TEXT, "nfe_step": NFE, "speed": SPEED, "items": todo}, "hb", log)
    todo = [{"in": str(p), "out": str(v)} for p, v in zip(hb, vc) if not v.exists()]
    if todo:
        log(f"[voice] converting {len(todo)} sentence(s) to your voice...")
        _run("venv-clone", "vc_worker.py", {"ref": str(REF_VC), "items": todo}, "vc", log)
    audio, words, t = [], [], 0.0
    for c, v in zip(chunks, vc):
        a, sr = sf.read(str(v), dtype="float32")
        a = _tighten(_trim(a.reshape(-1)))
        toks = c.split(); plain = [strip_marks(w) for w in toks]
        weights = np.array([max(1, len(re.sub(r"\W", "", w))) + 1.5 for w in plain], dtype=float)
        edges = np.concatenate([[0], np.cumsum(weights)]) / weights.sum() * (len(a) / SR)
        for i, w in enumerate(plain):
            words.append((t + float(edges[i]), t + float(edges[i + 1]), w))
        audio.append(a); t += len(a) / SR
        g = _gap(c); audio.append(np.zeros(int(g * SR), dtype=np.float32)); t += g
    wav = np.concatenate(audio)
    tmp = Path(out_mp3).with_suffix(".dj.wav"); sf.write(str(tmp), wav, SR)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), str(out_mp3)], check=True)
    tmp.unlink()
    return words
