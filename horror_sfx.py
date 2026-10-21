"""
horror_sfx.py
A small library of synthesized horror sounds (no samples, no licences) - foley cues, beds, stingers - built around what the research says works:
ambiguity, low-frequency unease, silence between sounds, one or two sharp stings, and "sound slightly before picture".
Every function returns a mono float32 array at music.SR (44100 Hz). Layout/mix happens in rules_video.py.
"""

import numpy as np

from music import SR, bell, noise

_rng = np.random.default_rng(404)


def _t(n_seconds: float) -> np.ndarray:
    return np.arange(int(n_seconds * SR)) / SR


def _lp(x: np.ndarray, k: int) -> np.ndarray:
    return np.convolve(x, np.ones(k) / k, mode="same") if k > 1 else x


def reverb(x: np.ndarray, amount: float = 0.35, decay: float = 0.45) -> np.ndarray:
    """A cheap room: a handful of decaying echoes at uneven spacing."""
    out = x.copy()
    for d, g in ((0.037, 0.55), (0.071, 0.45), (0.113, 0.38), (0.171, 0.3), (0.263, 0.22), (0.41, 0.15)):
        n = int(d * SR)
        out[n:] += x[:-n] * g * amount * decay / 0.45
    return out


# ---- foley cues -------------------------------------------------------------------------------------------------------------

def phone_ring(rings: int = 2) -> np.ndarray:
    out = np.zeros(int((rings * 1.0 + 0.6) * SR))
    for r in range(rings):
        t = _t(0.8)
        am = (np.sin(2 * np.pi * 22 * t) > 0).astype(float) * 0.5 + 0.5          # the old two-bell rattle
        tone = np.sin(2 * np.pi * 1180 * t) + 0.6 * np.sin(2 * np.pi * 1420 * t) + 0.3 * np.sin(2 * np.pi * 2360 * t)
        seg = tone * am * np.minimum(1, np.minimum(t * 200, (0.8 - t) * 60))
        i = int(r * 1.0 * SR); out[i:i + len(seg)] += seg
    return reverb(out * 0.35, 0.5)


def elevator_ding() -> np.ndarray:
    t = _t(1.8)
    tone = np.sin(2 * np.pi * 1318 * t) * np.exp(-3.2 * t) + 0.5 * np.sin(2 * np.pi * 1325 * t) * np.exp(-3.0 * t) + 0.25 * np.sin(2 * np.pi * 2637 * t) * np.exp(-6 * t)
    click = np.zeros_like(t); click[:int(0.01 * SR)] = _rng.normal(0, 0.5, int(0.01 * SR))
    return reverb((tone + click) * 0.5, 0.5)


def wet_steps(n: int = 4, gap: float = 0.62) -> np.ndarray:
    out = np.zeros(int((n * gap + 0.8) * SR))
    for k in range(n):
        at = int((k * gap + _rng.uniform(-0.04, 0.04)) * SR + 0.05 * SR)
        thud_t = _t(0.18); thud = np.sin(2 * np.pi * (70 - 25 * thud_t / 0.18) * thud_t) * np.exp(-24 * thud_t)
        sq_t = _t(0.16); squish = _lp(_rng.normal(0, 1, len(sq_t)), 14) * np.exp(-17 * sq_t) * 2.2        # the wet slap
        for seg, g in ((thud, 0.9), (squish, 0.5)):
            out[at:at + len(seg)] += seg * g
    return reverb(out * 0.55, 0.6)


def key_jingle() -> np.ndarray:
    out = np.zeros(int(0.9 * SR))
    for _ in range(9):
        at = int(_rng.uniform(0, 0.55) * SR); f = _rng.uniform(2300, 5400); t = _t(0.09)
        out[at:at + len(t)] += np.sin(2 * np.pi * f * t) * np.exp(-55 * t) * _rng.uniform(0.2, 0.5)
    return reverb(out * 0.5, 0.35)


def knock(n: int = 3, gap: float = 0.24) -> np.ndarray:
    out = np.zeros(int((n * gap + 0.6) * SR))
    for k in range(n):
        at = int(k * gap * SR); t = _t(0.25)
        out[at:at + len(t)] += (np.sin(2 * np.pi * 150 * t) * np.exp(-22 * t) + _lp(_rng.normal(0, 1, len(t)), 5) * np.exp(-70 * t) * 0.6)
    return reverb(out * 0.7, 0.55)


def door_creak(dur: float = 1.6) -> np.ndarray:
    t = _t(dur)
    f = 150 + 140 * np.sin(np.pi * t / dur) ** 2 + 6 * np.sin(2 * np.pi * 7 * t)
    saw = 2 * ((np.cumsum(f) / SR) % 1) - 1
    nz = _lp(_rng.normal(0, 1, len(t)), 3) * 0.4
    return reverb((saw * 0.5 + nz) * np.sin(np.pi * t / dur) ** 1.5 * 0.5, 0.4)


def breath(dur: float = 2.2) -> np.ndarray:
    t = _t(dur); env = np.sin(np.pi * t / dur) ** 2
    return reverb(_lp(_rng.normal(0, 1, len(t)), 22) * env * 1.2, 0.5)


def tape_stop(dur: float = 0.7) -> np.ndarray:
    t = _t(dur); f = 900 * np.exp(-t * 5.0) + 40
    ph = np.cumsum(f) / SR
    return (np.sin(2 * np.pi * ph) * 0.6 + _rng.normal(0, 0.15, len(t))) * np.exp(-t * 2.5)


def static_burst(dur: float = 0.25) -> np.ndarray:
    t = _t(dur)
    return _rng.normal(0, 1, len(t)) * (0.6 + 0.4 * (np.sin(2 * np.pi * 90 * t) > 0)) * np.minimum(1, np.minimum(t * 400, (dur - t) * 200))


# ---- the stings: sound arrives BEFORE the picture, then a heavy hit as it lands ---------------------------------------------

def sting(rise: float = 1.1) -> np.ndarray:
    """Returns rise + hit. The hit is at index len(rise); place so the HIT lands on (or just before) the visual."""
    t = _t(rise); f = 180 + 1500 * (t / rise) ** 2.2
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * (t / rise) ** 1.6 * 0.45
    swell = _lp(_rng.normal(0, 1, len(t)), 6) * (t / rise) ** 3 * 0.8
    hit_t = _t(1.6)
    hit = (np.sin(2 * np.pi * (44 - 10 * hit_t / 1.6) * hit_t) * np.exp(-2.6 * hit_t) * 1.2
           + sum(bell(m, 2.0, 1.4)[: len(hit_t)] * 0.12 for m in (1568, 1661, 2349))                  # cold dissonant cluster
           + _rng.normal(0, 0.25, len(hit_t)) * np.exp(-30 * hit_t))
    return np.concatenate([tone + swell, hit])


# ---- beds -------------------------------------------------------------------------------------------------------------------

def drone(dur: float) -> np.ndarray:
    t = _t(dur)
    lfo = 0.65 + 0.35 * np.sin(2 * np.pi * 0.07 * t)
    return (np.sin(2 * np.pi * 41 * t) + 0.55 * np.sin(2 * np.pi * 41.9 * t) + 0.35 * np.sin(2 * np.pi * 82.3 * t) + 0.12 * np.sin(2 * np.pi * 123.6 * t + np.sin(0.3 * t))) * lfo * 0.35


def room_tone(dur: float) -> np.ndarray:
    return _lp(_rng.normal(0, 1, int(dur * SR)), 45) * 1.6


def heartbeat(dur: float, bpm0: float = 62, bpm1: float = 118) -> np.ndarray:
    out = np.zeros(int(dur * SR)); t0 = 0.0
    while t0 < dur:
        for off, g in ((0.0, 1.0), (0.26, 0.7)):
            tt = _t(0.3); thump = np.sin(2 * np.pi * (58 - 18 * tt / 0.3) * tt) * np.exp(-16 * tt)
            i = int((t0 + off) * SR)
            if i + len(thump) < len(out): out[i:i + len(thump)] += thump * g
        bpm = bpm0 + (bpm1 - bpm0) * min(1, t0 / dur)
        t0 += 60.0 / bpm
    return out * 0.9


def whisper_bed(dur: float) -> np.ndarray:
    """Formant-ish breathy noise that sits just below intelligibility - the 'something is speaking' feeling."""
    n = int(dur * SR); x = _rng.normal(0, 1, n)
    bands = _lp(x, 6) - _lp(x, 30)
    env = (0.5 + 0.5 * np.sin(2 * np.pi * 0.31 * _t(dur) + 1.0)) ** 2
    return bands * env * 1.5


def snap() -> np.ndarray:
    """A dry, sharp crack with a short low thud under it - the sound of a neck. Hard transient, no tail."""
    t = _t(0.35)
    crack = _rng.normal(0, 1, len(t)) * np.exp(-t * 90) * 1.6
    body = np.sin(2 * np.pi * (170 - 90 * t / 0.35) * t) * np.exp(-t * 28) * 0.9
    return crack + body


def scream_stab(dur: float = 0.55) -> np.ndarray:
    """An implied scream: a harsh, rising, distorted shriek that is CUT OFF mid-breath (the research: show less, cut earlier)."""
    t = _t(dur)
    f = 520 + 900 * np.minimum(1, t / 0.18) + 55 * np.sin(2 * np.pi * 9 * t)
    ph = np.cumsum(f) / SR
    saw = 2 * (ph % 1) - 1
    vowel = np.sin(2 * np.pi * 1150 * t) * 0.4 + np.sin(2 * np.pi * 2300 * t) * 0.25                      # a crude "ah" resonance
    x = np.tanh((saw * 0.8 + vowel) * 3.2) * 0.7 + _lp(_rng.normal(0, 1, len(t)), 3) * 0.18
    return reverb(x * np.minimum(1, t * 120), 0.35) * (t < dur - 0.004)


def jump_scream(dur: float = 1.2) -> np.ndarray:
    """The jump-scare: four detuned harsh voices that leap upward, a vowel resonance, heavy distortion, grit and a sub hit under it.
    Instant attack (no build-up - the build-up is the silence before it) and a short ragged tail."""
    t = _t(dur)
    x = np.zeros_like(t)
    for base, g in ((620, 1.0), (880, 0.75), (1290, 0.55), (410, 0.7)):
        f = base * (1 + 0.85 * np.minimum(1, t / 0.10)) + 80 * np.sin(2 * np.pi * (9 + base % 7) * t) + 25 * _rng.normal(0, 1, len(t)).cumsum() / 400
        ph = np.cumsum(f) / SR
        x += (2 * (ph % 1) - 1) * g
    vowel = np.sin(2 * np.pi * 1150 * t) * 0.5 + np.sin(2 * np.pi * 2450 * t) * 0.3 + np.sin(2 * np.pi * 3400 * t) * 0.15
    x = np.tanh((x * 0.55 + vowel) * 5.0) * 0.8 + _lp(_rng.normal(0, 1, len(t)), 2) * 0.35
    x += np.sin(2 * np.pi * (38 - 8 * t / dur) * t) * np.exp(-t * 2.2) * 1.3
    env = np.minimum(1, t * 1500) * np.where(t < dur * 0.62, 1.0, np.exp(-(t - dur * 0.62) * 9))
    return reverb(x * env, 0.3)
