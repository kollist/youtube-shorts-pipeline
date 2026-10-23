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


def knock(n: int = 3, gap: float = 0.34) -> np.ndarray:
    """Three knuckle raps on a wooden door, from real recordings (assets/sfx/knock_*.wav), a little different each time. Falls back to a synth thump."""
    mine = sorted(c for c in _SFX_DIR.glob("pixabay_knock*") if c.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a"))
    if mine:                                                                   # hand-picked recordings win: used whole, as one cue
        a = _load_wav(mine[int(_rng.integers(len(mine)))])[: int(4.2 * SR)]
        a = a / max(1e-9, np.abs(a).max()); a[-int(0.4 * SR):] *= np.linspace(1, 0, int(0.4 * SR))[: len(a[-int(0.4 * SR):])]
        return reverb(a, 0.1) * 0.95
    clips = sorted(_SFX_DIR.glob("knock_*.wav"))
    if not clips:
        return _knock_synth(n, gap)
    out = np.zeros(int((n * gap + 0.9) * SR))
    for k in range(n):
        a = _load_wav(clips[k % len(clips)]); a = a / max(1e-9, np.abs(a).max()) * (1.0 if k < n - 1 else 0.85)
        at = int(k * gap * SR + (_rng.uniform(-0.015, 0.015) * SR if k else 0)); at = max(0, at)
        out[at:at + len(a)] += a[: len(out) - at]
    return reverb(out, 0.12) * 0.9


def _knock_synth(n: int = 3, gap: float = 0.3) -> np.ndarray:
    """Knuckles on a wooden door: a sharp click, then a few short wood resonances. Mostly dry so it reads even under a voice and on a phone speaker."""
    out = np.zeros(int((n * gap + 0.7) * SR))
    for k in range(n):
        at = int((k * gap + _rng.uniform(-0.02, 0.02)) * SR) if k else 0
        t = _t(0.22); g = _rng.uniform(0.85, 1.0)
        click = _rng.normal(0, 1, len(t)) * np.exp(-420 * t)                                              # the hit itself
        wood = sum(a * np.sin(2 * np.pi * f * t + _rng.uniform(0, 6)) * np.exp(-d * t)
                   for f, a, d in ((190, 1.0, 38), (410, 0.8, 55), (780, 0.5, 80), (1350, 0.3, 110)))   # hollow door panel
        body = np.sin(2 * np.pi * 95 * t) * np.exp(-30 * t) * 0.6                                         # thud behind it
        seg = (click * 0.9 + wood * 0.9 + body) * g
        out[at:at + len(seg)] += seg
    out = out / (np.abs(out).max() + 1e-9)
    return reverb(out * 0.9, 0.18) * 0.9


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
            tt = _t(0.3); thump = np.sin(2 * np.pi * (58 - 18 * tt / 0.3) * tt) * np.exp(-16 * tt) + np.sin(2 * np.pi * 105 * tt) * np.exp(-30 * tt) * 0.5 + _lp(_rng.normal(0, 1, len(tt)), 8) * np.exp(-80 * tt) * 0.35
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


# ---- real scream recordings (CC0, see assets/sfx/CREDITS.md): far more convincing than a synthesized one ------------------

_SFX_DIR = __import__("pathlib").Path(__file__).parent / "assets" / "sfx"


def _load_wav(path) -> np.ndarray:
    import subprocess
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def pixabay(stem: str, seconds: float | None = None, start: float = 0.0, fade: float = 0.3, pick: int = 0) -> np.ndarray | None:
    """A hand-picked Pixabay recording (assets/sfx/pixabay_<stem>*), peak-normalised, sliced and faded. None if the file is not there."""
    files = sorted(c for c in _SFX_DIR.glob(f"pixabay_{stem}*") if c.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a"))
    if not files:
        return None
    a = _load_wav(files[pick % len(files)])[int(start * SR):]
    if seconds:
        a = a[: int(seconds * SR)]
    if not len(a):
        return None
    a = a / max(1e-9, np.abs(a).max()); k = min(int(fade * SR), len(a) // 2)
    if k:
        a[:k] *= np.linspace(0, 1, k); a[-k:] *= np.linspace(1, 0, k)
    return a


def real_scream(seed: int = 0) -> np.ndarray | None:
    """The jump scare from real recordings: a female scream (one of four) with the long horror scream layered just behind it, a sub-bass hit
    under both, a touch of room. Returns None if the files are missing (callers fall back to jump_scream())."""
    clips = sorted(_SFX_DIR.glob("scream_*.wav"))
    if not clips:
        return None
    female = [c for c in clips if c.stem[-1] in "1234"]
    horror = [c for c in clips if c.stem[-1] == "5"]
    a = _load_wav(female[seed % len(female)] if female else clips[0])
    out = np.zeros(len(a) + int(0.4 * SR))
    out[:len(a)] += a / max(1e-9, np.abs(a).max())
    if horror:
        b = _load_wav(horror[0]); n = int(0.09 * SR)
        out[n:n + len(b)] += (b / max(1e-9, np.abs(b).max()) * 0.7)[: len(out) - n]
    t = _t(1.4)
    sub = np.sin(2 * np.pi * (44 - 10 * t / 1.4) * t) * np.exp(-t * 2.4) * 1.4
    out[:len(sub)] += sub[: len(out)]
    return reverb(np.tanh(out * 1.3), 0.22)


def heartbeat_times(dur: float, bpm0: float = 62, bpm1: float = 118) -> list[float]:
    """When each 'lub' of heartbeat() lands (the same schedule), so the picture can pulse in time with it."""
    out, t0 = [], 0.0
    while t0 < dur:
        out.append(t0)
        t0 += 60.0 / (bpm0 + (bpm1 - bpm0) * min(1, t0 / dur))
    return out


def rising_bed(dur: float, f0: float = 70, f1: float = 520) -> np.ndarray:
    """A tone that climbs for the whole story and never reaches anywhere (a Shepard-style unresolved rise): two detuned voices, a slow tremolo that speeds up.
    This is the 'tight chest' layer - the ear keeps waiting for it to stop."""
    t = _t(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    ph = np.cumsum(f) / SR
    trem = 0.6 + 0.4 * np.sin(2 * np.pi * (0.4 + 5.0 * (t / dur) ** 2) * t)
    x = (np.sin(2 * np.pi * ph) + 0.7 * np.sin(2 * np.pi * ph * 1.0145) + 0.25 * np.sin(2 * np.pi * ph * 2.01)) * trem
    return x * 0.5
