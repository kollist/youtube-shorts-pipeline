"""
medina_sfx.py
The sound of the "Khbir" (الخبير) series: night in a Moroccan medina, built from instruments you hear in gnawa and in the street - all synthesised
here (no samples, no licences):

  guembri   the three-string gnawa bass lute: a low plucked note with a skin thump and the buzz of its metal rattle; a sparse slow ostinato
  bendir    the frame drum with a snare string: a low "doum", a high "tak", a buzzing roll - used as the heartbeat and the scare
  qraqeb    the iron castanets: bright metallic clatter in the gnawa 6/8 groove; it only enters when the dread does
  ney       the breathy end-blown flute, in a Hijaz-like mode (the minor second then the augmented second), for the lonely phrases
  night     wind through a riad courtyard, far crickets, a dripping well with a long echo

Everything returns a mono float array at music.SR. horror_video.py places them when a story says "design": "medina".
"""

import numpy as np

from music import SR

_rng = np.random.default_rng(11)


def _t(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def _lp(x: np.ndarray, k: int) -> np.ndarray:
    return np.convolve(x, np.ones(k) / k, mode="same") if k > 1 else x


def _echo(x: np.ndarray, taps=((0.13, 0.42), (0.29, 0.3), (0.51, 0.2), (0.83, 0.12))) -> np.ndarray:
    out = x.copy()
    for d, g in taps:
        n = int(d * SR)
        if n < len(x):
            out[n:] += x[:-n] * g
    return out


# ---------------------------------------------------------------- instruments
def guembri(freq: float = 55.0, dur: float = 1.8, hard: float = 1.0) -> np.ndarray:
    """A plucked low string (Karplus-Strong) with the dull skin thump of the body and the faint buzz of the iron rattles."""
    n = int(dur * SR); p = max(2, int(SR / freq))
    buf = _rng.uniform(-1, 1, p) * 0.9
    buf = _lp(buf, 4)                                               # a dark pluck
    out = np.zeros(n)
    for i in range(n):
        j = i % p
        out[i] = buf[j]
        buf[j] = 0.5 * (buf[j] + buf[(j + 1) % p]) * 0.9972
    t = _t(dur)
    thump = np.sin(2 * np.pi * (freq * 1.5 - 14 * np.minimum(t, 0.1) * 5) * t) * np.exp(-t * 22) * 0.9
    buzz = np.convolve(_rng.normal(0, 1, n), np.ones(3) / 3, mode="same") * np.exp(-t * 9) * 0.07 * hard
    out = out * np.exp(-t * 0.9) + thump + buzz
    k = int(0.004 * SR); out[:k] *= np.linspace(0, 1, k)
    return out / max(1e-9, np.abs(out).max()) * 0.9


def bendir(kind: str = "doum", power: float = 1.0) -> np.ndarray:
    """kind: doum (low centre hit), tak (high rim hit), roll (the buzzing snare string, a quick tremble)."""
    if kind == "doum":
        t = _t(0.55)
        body = np.sin(2 * np.pi * (96 - 40 * np.minimum(t / 0.12, 1)) * t) * np.exp(-t * 11)
        skin = _lp(_rng.normal(0, 1, len(t)), 6) * np.exp(-t * 55) * 0.35
        snare = (_rng.normal(0, 1, len(t)) - _lp(_rng.normal(0, 1, len(t)), 5)) * np.exp(-t * 28) * 0.1
        x = body + skin + snare
    elif kind == "tak":
        t = _t(0.25)
        x = np.sin(2 * np.pi * 210 * t) * np.exp(-t * 38) * 0.6 + (_rng.normal(0, 1, len(t)) - _lp(_rng.normal(0, 1, len(t)), 4)) * np.exp(-t * 34) * 0.45
    else:
        t = _t(0.7)
        rattle = (_rng.normal(0, 1, len(t)) - _lp(_rng.normal(0, 1, len(t)), 6)) * (0.5 + 0.5 * np.sin(2 * np.pi * 26 * t)) ** 2 * np.exp(-t * 4)
        x = rattle * 0.55 + np.sin(2 * np.pi * 88 * t) * np.exp(-t * 8) * 0.4
    return x * power / max(1e-9, np.abs(x).max()) * 0.95


def heartbeat(dur: float, bpm0: float = 52, bpm1: float = 128) -> np.ndarray:
    """The heartbeat, played on the bendir: a doum, then a softer one just after it; it speeds up. The schedule is the same as horror_sfx.heartbeat_times."""
    out = np.zeros(int(dur * SR)); t0 = 0.0
    doum, soft = bendir("doum"), bendir("doum", 0.55)
    while t0 < dur:
        for off, snd, g in ((0.0, doum, 1.0), (0.24, soft, 0.7)):
            i = int((t0 + off) * SR)
            if i + len(snd) < len(out):
                out[i:i + len(snd)] += snd * g
        t0 += 60.0 / (bpm0 + (bpm1 - bpm0) * min(1, t0 / dur))
    return out * 0.9


def qraqeb(dur: float, intensity: float = 1.0) -> np.ndarray:
    """Iron castanets in the 6/8 gnawa groove: pairs of bright clashes, then a gap. intensity 0..1 controls how many hits are played."""
    out = np.zeros(int(dur * SR)); beat = 0.31; pat = [1, 0.5, 0.8, 1, 0.5, 0.0]
    t0, k = 0.0, 0
    while t0 < dur - 0.2:
        g = pat[k % 6]
        if g > 0 and _rng.random() < 0.35 + 0.65 * intensity:
            n = int(0.14 * SR); tt = np.arange(n) / SR
            hit = _rng.normal(0, 1, n)
            hit = (hit - _lp(hit, 3)) * np.exp(-tt * 40)
            ring = (np.sin(2 * np.pi * 6200 * tt) + 0.7 * np.sin(2 * np.pi * 8700 * tt) + 0.5 * np.sin(2 * np.pi * 4300 * tt)) * np.exp(-tt * 70)
            snd = (hit * 0.6 + ring * 0.35) * g
            i = int(t0 * SR)
            if i + n < len(out):
                out[i:i + n] += snd
        t0 += beat; k += 1
    return out * 0.55


# the Hijaz-like mode on D: D Eb F# G A Bb C (the augmented second between Eb and F# is the sound that reads as "Arab")
_HIJAZ = [293.66, 311.13, 369.99, 392.0, 440.0, 466.16, 523.25]


def ney(notes: list[int], note_len: float = 1.6, gap: float = 0.25, seed: int = 3) -> np.ndarray:
    """A breathy end-blown flute phrase. notes are degrees of the Hijaz-like mode (0 = D). Slow breath attack, a late vibrato, air noise."""
    rng = np.random.default_rng(seed)
    parts = []
    for d in notes:
        f = _HIJAZ[d % 7] * (2 if d >= 7 else 1) * 0.5
        t = _t(note_len)
        vib = 1 + 0.006 * np.sin(2 * np.pi * 5.2 * t) * np.clip((t - 0.4) / 0.5, 0, 1)
        ph = 2 * np.pi * np.cumsum(f * vib) / SR
        tone = np.sin(ph) + 0.28 * np.sin(2 * ph) + 0.08 * np.sin(3 * ph)
        air = _lp(rng.normal(0, 1, len(t)), 3) - _lp(rng.normal(0, 1, len(t)), 40)
        env = np.minimum(t / 0.22, 1) * np.exp(-np.maximum(t - note_len * 0.55, 0) * 2.8)
        parts.append((tone * 0.7 + air * 0.35) * env)
        parts.append(np.zeros(int(gap * SR)))
    x = np.concatenate(parts)
    return _echo(x * 0.5)


# ---------------------------------------------------------------- phrases and beds
def guembri_line(dur: float, bpm: float = 54.0, seed: int = 5, root: float = 55.0) -> np.ndarray:
    """A sparse gnawa-style ostinato: the root, a minor third, the fourth - never fast, with long holes. Gains come from the caller's envelope."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(dur * SR)); step = 60.0 / bpm / 2
    cycle = [(1.0, 1.0), (1.0, 0.0), (1.0, 0.55), (1.189, 0.0), (1.0, 0.8), (1.335, 0.0), (1.0, 0.5), (1.0, 0.0)]
    t0, k = 0.0, 0
    while t0 < dur - 0.5:
        ratio, g = cycle[k % len(cycle)]
        if g > 0 and rng.random() < 0.9:
            snd = guembri(root * ratio, 1.6)
            i = int(t0 * SR)
            if i + len(snd) < len(out):
                out[i:i + len(snd)] += snd * g
        t0 += step; k += 1
    return out * 0.8


def night_air(dur: float, seed: int = 2) -> np.ndarray:
    """A medina at night: wind that moves through the courtyard, a few far crickets, nothing else."""
    rng = np.random.default_rng(seed)
    t = _t(dur); n = len(t)
    wind = _lp(rng.normal(0, 1, n), 60) - _lp(rng.normal(0, 1, n), 900)
    wind *= (0.55 + 0.45 * np.sin(2 * np.pi * 0.09 * t + 1.3)) ** 2 * 2.2
    cr = np.zeros(n)
    for _ in range(max(1, int(dur / 7))):                                    # a cricket: a train of tiny 4.3 kHz pulses, fading in and out
        s = int(rng.uniform(0, max(1, dur - 3)) * SR); L = int(rng.uniform(1.5, 3.2) * SR)
        tt = np.arange(min(L, n - s)) / SR
        pulses = (np.sin(2 * np.pi * 14 * tt) > 0.55) * np.sin(2 * np.pi * 4300 * tt)
        cr[s:s + len(tt)] += pulses * np.sin(np.pi * tt / max(tt[-1], 1e-6)) * 0.05
    return wind * 0.5 + cr


def drip(dur: float = 2.8) -> np.ndarray:
    """A drop falling into the well far below: a short falling blip, then a long cave echo."""
    t = _t(0.09)
    blip = np.sin(2 * np.pi * np.cumsum(1500 * np.exp(-t * 18) + 380) / SR) * np.exp(-t * 55)
    x = np.zeros(int(dur * SR)); x[: len(blip)] = blip
    return _echo(x, ((0.21, 0.55), (0.43, 0.38), (0.71, 0.27), (1.1, 0.18), (1.6, 0.1))) * 0.8


def slam(power: float = 1.0) -> np.ndarray:
    """The scare: a huge bendir doum, a gnawa crash of qraqeb, a guembri note slammed at the bottom, a short reversed swell into it."""
    L = int(2.2 * SR); out = np.zeros(L)
    d = bendir("doum"); out[: len(d)] += d * 1.3
    out[: len(d)] += bendir("roll")[: len(d)] * 0.4
    q = qraqeb(1.2, 1.0); out[: len(q)] += q * 1.1
    g = guembri(41.2, 2.0, hard=2.0); out[: len(g)] += g * 0.9
    return np.tanh(out * 1.1) * power


def ember_out(dur: float = 1.8) -> np.ndarray:
    """The end: one low guembri note, a last drip. Nothing else."""
    x = np.zeros(int(dur * SR))
    g = guembri(46.0, dur); x[: len(g)] += g * 0.9
    d = drip(1.8); i = int(0.9 * SR); x[i:i + len(d)] += d[: len(x) - i] * 0.5
    return x
