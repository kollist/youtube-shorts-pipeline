"""The narrator's own voice for the Arabic series: Chatterbox (venv-clone, MIT) clones data/voice/expert_ref.wav and reads the fully vocalised (tashkeel) text.
It gives no word timings, so each sentence is generated separately and its words are spread over that sentence's measured speech by letter count.
Returns the words WITHOUT the vowel marks (they are what the captions show)."""
import hashlib
import json
import re
import subprocess
from pathlib import Path

import numpy as np

BASE = Path(__file__).parent
CACHE = BASE / "data" / "voice_cache"
REF = BASE / "data" / "voice" / "expert_ref.wav"
PY = BASE / "venv-clone" / "bin" / "python"
SR = 24000
_MARKS = re.compile("[ً-ٰٟۖ-ۭـ]")


def strip_marks(s: str) -> str:
    return _MARKS.sub("", s)


def visual(text: str) -> str:
    """Arabic text as the subtitle renderer needs it: marks removed, letters joined (presentation forms) and reordered left-to-right for drawing."""
    from arabic_reshaper import reshape
    from bidi.algorithm import get_display
    out = get_display(reshape(strip_marks(text)))
    return re.sub("([\uFEDD-\uFEE0])([\uFE82\uFE84\uFE88\uFE8E])", "\\1\u200C\\2", out)    # drawn left-to-right a lam followed by an alef-final is read by the font as the lam-alef ligature (a box, and the letters swapped): a joiner-breaker between them


def _chunks(text: str) -> list[str]:
    parts = re.split(r"(?<=[.؟?!:])\s+", text.strip())
    return [p for p in parts if re.search(r"\w", p)]


def _gap(chunk: str) -> float:
    return 0.6 if chunk.rstrip().endswith("...") else 0.18 if chunk.rstrip().endswith((":", "،", ",")) else 0.3


def _trim(a: np.ndarray) -> np.ndarray:
    frame = int(0.02 * SR); n = len(a) // frame
    if n < 3:
        return a
    env = np.abs(a[: n * frame]).reshape(n, frame).max(axis=1)
    on = np.where(env > 0.03 * env.max())[0]
    return a[max(0, (on[0] - 1) * frame): min(len(a), (on[-1] + 2) * frame)] if len(on) else a


def synth(text: str, out_mp3: Path, exaggeration: float = 0.5, cfg: float = 0.5, log=print) -> list[tuple[float, float, str]]:
    import soundfile as sf
    if not REF.exists() or not PY.exists():
        raise RuntimeError("The voice clone isn't set up (data/voice/expert_ref.wav + venv-clone).")
    CACHE.mkdir(parents=True, exist_ok=True)
    chunks = _chunks(text)
    paths = []
    for c in chunks:
        key = hashlib.sha1(f"{c}|{exaggeration}|{cfg}|{REF.stat().st_size}".encode()).hexdigest()[:16]
        paths.append(CACHE / f"{key}.wav")
    todo = [{"text": c, "out": str(p), "exaggeration": exaggeration, "cfg": cfg} for c, p in zip(chunks, paths) if not p.exists()]
    if todo:
        job = CACHE / "job.json"; job.write_text(json.dumps({"ref": str(REF), "items": todo}, ensure_ascii=False), encoding="utf-8")
        log(f"[voice] cloning your voice: {len(todo)} sentence(s) to generate (about a minute each)...")
        r = subprocess.run([str(PY), str(BASE / "clone_worker.py"), str(job)], text=True, capture_output=True)
        if r.returncode != 0 or not all(p.exists() for _, p in zip(chunks, paths)):
            raise RuntimeError("The voice clone failed:\n" + (r.stderr or r.stdout)[-800:])
    audio, words, t = [], [], 0.0
    for c, p in zip(chunks, paths):
        a, sr = sf.read(str(p), dtype="float32")
        a = _trim(a.reshape(-1))
        toks = c.split(); plain = [strip_marks(w) for w in toks]
        weights = np.array([max(1, len(re.sub(r"\W", "", w))) + 1.5 for w in plain], dtype=float)
        edges = np.concatenate([[0], np.cumsum(weights)]) / weights.sum() * (len(a) / SR)
        for i, w in enumerate(plain):
            words.append((t + float(edges[i]), t + float(edges[i + 1]), w))
        audio.append(a); t += len(a) / SR
        gap = _gap(c); audio.append(np.zeros(int(gap * SR), dtype=np.float32)); t += gap
    wav = np.concatenate(audio)
    tmp = Path(out_mp3).with_suffix(".clone.wav"); sf.write(str(tmp), wav, SR)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), str(out_mp3)], check=True); tmp.unlink()
    return words
