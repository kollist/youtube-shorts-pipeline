"""
music.py
Background music for every video category, synthesized in code (no downloads, no licences). Each category has its own sound:

    happy   kids' stories      ukulele strum + xylophone melody (story_video.py)
    tense   scary series       drone + heartbeat + music box     (story_video.py)
    fable   parables           slow fingerpicked minor guitar, warm pad, distant bell
    curious 3D / science       light marimba arpeggios, pizzicato bass, soft ticks
    eerie   creepy chat/mystery sparse detuned bells, ticking clock, dissonant pad, reverse swells
    upbeat  explainers         lo-fi beat: soft kick/snare/hats, electric-piano 7th chords, bass

make(mood, total_seconds, out_path, seed) is called by story_video.synthesize_music. The seed (a hash of the video's title) shifts
the key and tempo a little, so two videos in the same category are related but not identical.
"""

import zlib
from pathlib import Path

import numpy as np

SR = 44100
CATEGORY_MOOD = {"kids story": "happy", "scary series": "tense", "parable": "fable", "3d explainer": "curious",
                 "creepy motion graphics": "eerie", "explainer": "upbeat"}
NEW_MOODS = ("fable", "curious", "eerie", "upbeat")


def seed_from(text: str) -> int:
    return zlib.crc32((text or "").encode("utf-8"))


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


class Track:
    def __init__(self, total: float):
        self.n = int((total + 3) * SR)
        self.buf = np.zeros(self.n)
        self.total = total

    def place(self, sound: np.ndarray, at: float, gain: float = 1.0) -> None:
        i = int(at * SR)
        if 0 <= i < self.n:
            seg = sound[: self.n - i]
            self.buf[i:i + len(seg)] += seg * gain

    def echo(self, delay: float, feedback: float, mix: float) -> None:
        d = int(delay * SR)
        wet = np.zeros(self.n)
        tap = self.buf.copy()
        for _ in range(5):
            tap = np.concatenate([np.zeros(d), tap[:-d]]) * feedback
            wet += tap
        self.buf += wet * mix


def _t(length: float) -> np.ndarray:
    return np.arange(int(length * SR)) / SR


def pluck(freq: float, length: float = 1.2, decay: float = 4.0, bright: float = 0.4) -> np.ndarray:
    t = _t(length)
    tone = np.sin(2 * np.pi * freq * t) + bright * np.sin(2 * np.pi * freq * 2 * t) + 0.12 * np.sin(2 * np.pi * freq * 3.01 * t)
    return tone * np.exp(-decay * t) * np.minimum(1, t * 600)


def marimba(freq: float, length: float = 0.5, decay: float = 11.0) -> np.ndarray:
    t = _t(length)
    tone = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 4.0 * t) * np.exp(-30 * t)
    return tone * np.exp(-decay * t) * np.minimum(1, t * 800)


def bell(freq: float, length: float = 3.0, decay: float = 1.6) -> np.ndarray:
    t = _t(length)
    parts = (1.0, 2.76, 5.40, 8.93)
    tone = sum(a * np.sin(2 * np.pi * freq * p * t + i) * np.exp(-(decay + i * 1.2) * t) for i, (a, p) in enumerate(zip((1, 0.5, 0.25, 0.12), parts)))
    return tone * np.minimum(1, t * 500)


def pad(freqs, length: float, attack: float = 1.2, release: float = 1.5) -> np.ndarray:
    t = _t(length)
    tone = sum(np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.004 * t) + 0.2 * np.sin(2 * np.pi * f * 2 * t) for f in freqs)
    env = np.minimum(1, t / attack) * np.minimum(1, np.maximum(0, (length - t) / release))
    return tone * env


def epiano(freq: float, length: float = 2.0, decay: float = 2.2) -> np.ndarray:
    t = _t(length)
    tone = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-3 * t) + 0.08 * np.sin(2 * np.pi * freq * 6 * t) * np.exp(-9 * t)
    tremolo = 1 + 0.12 * np.sin(2 * np.pi * 5 * t)
    return tone * tremolo * np.exp(-decay * t) * np.minimum(1, t * 300)


def kick() -> np.ndarray:
    t = _t(0.35)
    return np.sin(2 * np.pi * (45 * t + 60 * (1 - np.exp(-t * 30)) / 30 * 1.0)) * np.exp(-9 * t)


def noise(length: float, decay: float, rng, smooth: int = 1) -> np.ndarray:
    t = _t(length)
    x = rng.normal(0, 1, len(t))
    if smooth > 1:
        x = np.convolve(x, np.ones(smooth) / smooth, mode="same")
    return x * np.exp(-decay * t)


def snare(rng) -> np.ndarray:
    t = _t(0.25)
    return noise(0.25, 18, rng, 3) * 0.7 + np.sin(2 * np.pi * 190 * t) * np.exp(-22 * t) * 0.5


def hat(rng) -> np.ndarray:
    x = noise(0.08, 55, rng)
    return np.diff(x, prepend=0) * 0.9           # crude high-pass: brighter, "tssk"


def _finish(tr: Track, out: Path) -> None:
    from story_video import _write_wav
    _write_wav(tr.buf[: int(tr.total * SR)], Path(out), SR)


# ------------------------------------------------------------------ moods

def fable(total: float, out: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    root = [57, 62, 64, 55][seed % 4]                         # A, D, E, G (minor key)
    bpm = 66 + seed % 9
    beat = 60 / bpm
    tr = Track(total)
    prog = [(0, [0, 3, 7]), (-4, [0, 4, 7]), (3, [0, 4, 7]), (-2, [0, 4, 7])]     # i - VI - III - VII
    bar = beat * 4
    for b in range(int(total / bar) + 2):
        shift, chord = prog[(b // 2) % 4]
        r = root + shift
        t0 = b * bar
        tones = [r + c for c in chord]
        tr.place(pluck(hz(r - 12), 1.6, 3.0, 0.3), t0, 0.5)
        if b % 2 == 0:
            tr.place(pad([hz(m) for m in tones], bar * 2 + 0.5), t0, 0.05)
        pattern = [0, 2, 1, 2, 1, 2, 1, 0] if b % 4 else [0, 1, 2, 1, 2, 1, 0, 2]
        for i, k in enumerate(pattern):
            swing = 0.012 * (rng.random() - 0.5)
            tr.place(pluck(hz(tones[k] + (12 if k == 2 else 0)), 1.0, 5.0, 0.55), t0 + i * beat / 2 + swing, 0.20 if i % 2 == 0 else 0.15)
        if b % 4 == 0 and b:
            tr.place(bell(hz(tones[2] + 24), 3.5), t0 + beat * 1.5, 0.09)
    tr.echo(beat * 0.75, 0.4, 0.45)
    _finish(tr, out)


def curious(total: float, out: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    root = [60, 62, 65, 67][seed % 4]                         # C, D, F, G major
    bpm = 100 + seed % 13
    beat = 60 / bpm
    tr = Track(total)
    prog = [(0, [0, 4, 7]), (7, [0, 4, 7]), (9, [0, 3, 7]), (5, [0, 4, 7])]       # I - V - vi - IV
    pent = [0, 2, 4, 7, 9, 12, 14, 16]
    bar = beat * 4
    for b in range(int(total / bar) + 2):
        shift, chord = prog[b % 4]
        r = root + shift
        t0 = b * bar
        tr.place(pluck(hz(r - 24), 0.5, 9.0, 0.2), t0, 0.7)
        tr.place(pluck(hz(r - 24 + 7), 0.5, 9.0, 0.2), t0 + beat * 2, 0.5)
        for i in range(8):                                                           # marimba arpeggio, little melodic hops
            tone = r + [c for c in chord][i % 3] + (12 if i % 4 == 3 else 0)
            tr.place(marimba(hz(tone + 12), 0.5), t0 + i * beat / 2, 0.20 if i % 2 == 0 else 0.13)
            tr.place(hat(rng), t0 + i * beat / 2 + beat / 4, 0.012)
        if b % 8 == 7:                                                               # a little "wonder" run upward
            for j, step in enumerate(pent[:6]):
                tr.place(marimba(hz(root + 12 + step), 0.6), t0 + beat * 2 + j * beat / 3, 0.17)
    tr.echo(beat / 2, 0.3, 0.25)
    _finish(tr, out)


def eerie(total: float, out: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    root = [33, 31, 35, 34][seed % 4]                         # low A, G, B, A#
    tr = Track(total)
    t = _t(total + 3)
    swell = 0.55 + 0.45 * np.sin(2 * np.pi * 0.06 * t + seed % 7)
    drone = np.sin(2 * np.pi * hz(root) * t) + 0.7 * np.sin(2 * np.pi * hz(root) * 1.006 * t) + 0.35 * np.sin(2 * np.pi * hz(root + 1) * t + 1)
    tr.buf[: len(drone)] += drone * swell * 0.25
    scale = [0, 1, 3, 5, 6, 8, 10]                                                   # phrygian-ish: dark, unresolved
    at = 2.0
    while at < total:
        note = root + 36 + int(rng.choice(scale)) + 12 * int(rng.integers(0, 2))
        tr.place(bell(hz(note), 4.0, 1.3), at, 0.16)
        at += float(rng.uniform(2.4, 5.2))
    k = 0.0
    while k < total:                                                                 # clock tick, a little uneven
        tr.place(noise(0.03, 120, rng, 6) * 0.5, k, 0.06)
        k += 1.0 + 0.02 * float(rng.normal())
    sw = 6.0
    while sw < total:                                                                # reverse swell leading into silence
        s = noise(3.0, 0, rng, 12) * np.linspace(0, 1, int(3.0 * SR)) ** 3
        tr.place(s, sw, 0.12)
        sw += float(rng.uniform(9, 14))
    tr.place(pad([hz(root + 24), hz(root + 25), hz(root + 31)], total + 1, 6, 4), 0, 0.04)
    tr.echo(0.55, 0.5, 0.55)
    _finish(tr, out)


def upbeat(total: float, out: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    root = [48, 50, 53, 55][seed % 4]
    bpm = 84 + seed % 9
    beat = 60 / bpm
    tr = Track(total)
    prog = [(0, [0, 4, 7, 11]), (9, [0, 3, 7, 10]), (2, [0, 3, 7, 10]), (7, [0, 4, 7, 10])]   # Imaj7 vi7 ii7 V7
    bar = beat * 4
    kk, sn = kick(), None
    for b in range(int(total / bar) + 2):
        shift, chord = prog[b % 4]
        r = root + shift
        t0 = b * bar
        for c in chord:
            tr.place(epiano(hz(r + c + 12), bar + 0.4), t0 + 0.01 * rng.random(), 0.075)
        tr.place(pluck(hz(r - 12), 0.9, 4.0, 0.15), t0, 0.5)
        tr.place(pluck(hz(r - 12 + 7), 0.7, 5.0, 0.15), t0 + beat * 2.5, 0.35)
        for beat_i in (0, 2):
            tr.place(kk, t0 + beat_i * beat, 0.85)
        tr.place(kk, t0 + beat * 2.75, 0.35)
        for beat_i in (1, 3):
            tr.place(snare(rng), t0 + beat_i * beat + 0.012, 0.28)
        for i in range(8):
            swing = beat / 6 if i % 2 else 0
            tr.place(hat(rng), t0 + i * beat / 2 + swing, 0.035 if i % 2 else 0.022)
    tr.echo(beat * 0.75, 0.25, 0.2)
    _finish(tr, out)


MOODS = {"fable": fable, "curious": curious, "eerie": eerie, "upbeat": upbeat}


def make(mood: str, total: float, out: Path, seed: int = 0) -> None:
    MOODS[mood](total, out, seed)


if __name__ == "__main__":
    import sys
    out_dir = Path(__file__).parent / "music_samples"
    out_dir.mkdir(exist_ok=True)
    length = float(sys.argv[1]) if len(sys.argv) > 1 else 24
    for m in MOODS:
        make(m, length, out_dir / f"{m}.wav", seed=seed_from("demo"))
        print("wrote", out_dir / f"{m}.wav")
