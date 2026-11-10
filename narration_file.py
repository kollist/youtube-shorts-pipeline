"""Narration that was recorded elsewhere (an ElevenLabs mp3, your own voice): cut into the story's lines, every word gets a time.
No recogniser: the words are spread over the SPEECH time (silences removed) by letter count, and each line starts where its voice starts."""
import re
import subprocess
from pathlib import Path

import numpy as np

SR = 16000


def _marks(s: str) -> str:
    return re.sub("[ً-ْٰ]", "", s)


def _load(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _segments(a: np.ndarray, merge: float = 0.12, thr: float = 0.03) -> list[list[float]]:
    fr = int(0.02 * SR); n = len(a) // fr
    env = np.abs(a[: n * fr]).reshape(n, fr).max(axis=1); act = env > thr * env.max()
    segs, i = [], 0
    while i < n:
        if act[i]:
            j = i
            while j < n and act[j]:
                j += 1
            segs.append([i * 0.02, j * 0.02]); i = j
        else:
            i += 1
    out = []
    for s in segs:
        if out and s[0] - out[-1][1] < merge:
            out[-1][1] = s[1]
        else:
            out.append(list(s))
    return out


def align(path: Path, lines: list[str]):
    """-> (words per line [(start, end, token)], line start times, speech end) - seconds in the file."""
    segs = _segments(_load(path))
    cum = np.concatenate([[0.0], np.cumsum([e - s for s, e in segs])])             # speech time at the start of every segment

    def s2r(x: float, later: bool) -> float:                                       # speech time -> real time (at a segment edge: its end, or the start of the next one)
        for k, (s, e) in enumerate(segs):
            if x < cum[k + 1] - 1e-9 or (not later and x <= cum[k + 1] + 1e-9):
                return s + max(0.0, x - cum[k])
        return segs[-1][1]

    def r2s(t: float) -> float:
        for k, (s, e) in enumerate(segs):
            if t <= e:
                return cum[k] + max(0.0, t - s)
        return cum[-1]

    toks = [ln.split() for ln in lines]
    wt = [[max(1, len(re.sub(r"\W", "", _marks(w)))) + 1.5 for w in tl] for tl in toks]
    tot_w = sum(sum(w) for w in wt); done = 0.0; est = []
    for w in wt:
        est.append(s2r(cum[-1] * done / tot_w, True)); done += sum(w)
    onsets = [s for s, _ in segs]; starts = []
    for i, t in enumerate(est):
        if i == 0:
            starts.append(onsets[0]); continue
        near = min((o for o in onsets if o > starts[-1] + 0.5), key=lambda o: abs(o - t), default=t)
        starts.append(near if abs(near - t) <= 0.7 else t)
    out = []
    for i, (tl, w) in enumerate(zip(toks, wt)):
        a0 = r2s(starts[i]); a1 = r2s(starts[i + 1]) if i + 1 < len(starts) else cum[-1]
        edges = a0 + np.concatenate([[0.0], np.cumsum(w)]) / sum(w) * (a1 - a0)
        out.append([(s2r(edges[k], True), s2r(edges[k + 1], False), tl[k]) for k in range(len(tl))])
    return out, starts, segs[-1][1]


def prepare(path: Path, lines: list[str], work: Path, question: str = ""):
    """The last line is the whispered finale: it gets its own file. -> (main_file, main_words, final_file, final_words).
    question: the end-card question, if the recording speaks it after the finale - it is timed but cut off (the scare is the last thing heard)."""
    n = len(lines)
    words, starts, end = align(path, lines + ([question] if question else []))
    if question:
        end = words[n - 1][-1][1]
    segs = _segments(_load(path))
    t0 = max(0.0, segs[0][0] - 0.05)
    st = starts[n - 1]
    prev_end = max((e for s, e in segs if e <= st + 0.01), default=st - 0.1)
    cut = (prev_end + st) / 2 if st - prev_end > 0.08 else st - 0.03
    t1 = end + 0.15
    main_f, fin_f = work / "ext_main.mp3", work / "ext_final.mp3"
    for f, a, b in ((main_f, t0, cut), (fin_f, cut, t1)):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(path), "-ar", "44100", "-ac", "1", "-b:a", "192k", str(f)], check=True)
    main_words = [(a - t0, b - t0, w) for ln in words[: n - 1] for a, b, w in ln]
    fin_words = [(a - cut, b - cut, w) for a, b, w in words[n - 1]]
    return main_f, main_words, fin_f, fin_words
