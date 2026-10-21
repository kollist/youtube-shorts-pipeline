"""
sim_video.py
Satisfying physics-simulation Shorts: a real 2D physics engine (pymunk) runs the scene, the picture is drawn with glow and trails,
and the SOUND comes from the collisions themselves (notes, ticks, risers) - no voice, no AI pictures, no stock footage.
Format chosen from the format study (research/FORMAT_STUDY.md): 15-30 s, a question or claim as the hook, a visible payoff, sound that
makes it satisfying.

    python sim_video.py ode          # 5 balls play Ode to Joy
    python sim_video.py multiply     # every bounce adds a ball
    python sim_video.py jam          # which funnel jams?
    python sim_video.py ode --preview   # low-res, first seconds only

Two passes: (1) simulate everything and record each frame's state + the audio events; (2) render the frames and mix the sound.
"""

import argparse
import math
import random
import subprocess
import colorsys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pymunk
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

import motion_gfx as g
from music import SR, Track, bell, marimba, noise, pluck

W, H, FPS = 1080, 1920, 30
SUB = 4                                    # physics steps per frame (120 Hz)
OUT = Path(__file__).parent / "sim_videos"


def hsv(h: float, s: float = 0.65, v: float = 1.0) -> tuple[int, int, int]:
    r, gg, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(gg * 255), int(b * 255)


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


# ------------------------------------------------------------------ stage: background, sprites, glow, trails, camera

class Stage:
    def __init__(self, top=(14, 16, 38), bottom=(3, 4, 12), scale: float = 1.0):
        self.scale = scale
        self.w, self.h = int(W * scale), int(H * scale)
        t = np.linspace(0, 1, self.h, dtype=np.float32)[:, None, None]
        grad = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
        grad = np.repeat(grad, self.w, axis=1)
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        d = np.sqrt(((xx - self.w / 2) / (self.w / 2)) ** 2 + ((yy - self.h / 2) / (self.h / 2)) ** 2)
        grad *= (1 - 0.35 * np.clip(d - 0.5, 0, 1))[..., None]
        self.bg = Image.fromarray(np.clip(grad, 0, 255).astype(np.uint8), "RGB")
        self.gw, self.gh = self.w // 4, self.h // 4
        self.trail = Image.new("RGB", (self.gw, self.gh))
        self.glow = None
        self.img = None
        self.gd = None

    def begin(self, trail_decay: float = 0.86) -> Image.Image:
        self.img = self.bg.copy()
        self.glow = Image.new("RGB", (self.gw, self.gh))
        self.gd = ImageDraw.Draw(self.glow)
        self.trail = ImageEnhance.Brightness(self.trail).enhance(trail_decay)
        self.td = ImageDraw.Draw(self.trail)
        return self.img

    def s(self, v: float) -> float:
        return v * self.scale

    @lru_cache(maxsize=2048)
    def _sprite(self, r: int, rgb: tuple) -> Image.Image:
        k = 4
        big = Image.new("RGBA", (r * 2 * k + 8, r * 2 * k + 8), (0, 0, 0, 0))
        d = ImageDraw.Draw(big)
        c = (big.width // 2, big.height // 2)
        d.ellipse([c[0] - r * k, c[1] - r * k, c[0] + r * k, c[1] + r * k], fill=rgb + (255,))
        light = tuple(min(255, int(v + (255 - v) * 0.55)) for v in rgb)
        rr = int(r * k * 0.62)
        d.ellipse([c[0] - rr - r * k // 5, c[1] - rr - r * k // 4, c[0] + rr - r * k // 5, c[1] + rr - r * k // 4], fill=light + (150,))
        d.ellipse([c[0] - r * k, c[1] - r * k, c[0] + r * k, c[1] + r * k], outline=tuple(int(v * 0.55) for v in rgb) + (255,), width=max(2, k))
        return big.resize((big.width // k, big.height // k), Image.LANCZOS)

    def ball(self, x: float, y: float, r: float, rgb: tuple, glow: float = 1.0, trail: bool = True):
        x, y, r = x * self.scale, y * self.scale, max(2, int(round(r * self.scale)))
        sp = self._sprite(r, rgb)
        self.img.paste(sp, (int(x - sp.width / 2), int(y - sp.height / 2)), sp)
        gr = r * 1.9 / 4
        if glow > 0:
            col = tuple(int(v * 0.55 * glow) for v in rgb)
            self.gd.ellipse([x / 4 - gr, y / 4 - gr, x / 4 + gr, y / 4 + gr], fill=col)
        if trail:
            tr = r * 0.8 / 4
            self.td.ellipse([x / 4 - tr, y / 4 - tr, x / 4 + tr, y / 4 + tr], fill=tuple(int(v * 0.5) for v in rgb))

    def rect(self, x0, y0, x1, y1, rgb, radius=14, glow=0.8, outline=None):
        s = self.scale
        d = ImageDraw.Draw(self.img)
        d.rounded_rectangle([x0 * s, y0 * s, x1 * s, y1 * s], radius=radius * s, fill=rgb, outline=outline)
        if glow:
            self.gd.rounded_rectangle([x0 * s / 4, y0 * s / 4, x1 * s / 4, y1 * s / 4], radius=radius * s / 4, fill=tuple(int(v * 0.5 * glow) for v in rgb))

    def line(self, p0, p1, rgb, width=8, glow=0.8):
        s = self.scale
        d = ImageDraw.Draw(self.img)
        d.line([p0[0] * s, p0[1] * s, p1[0] * s, p1[1] * s], fill=rgb, width=max(1, int(width * s)), joint="curve")
        for p in (p0, p1):
            d.ellipse([p[0] * s - width * s / 2, p[1] * s - width * s / 2, p[0] * s + width * s / 2, p[1] * s + width * s / 2], fill=rgb)
        if glow:
            self.gd.line([p0[0] * s / 4, p0[1] * s / 4, p1[0] * s / 4, p1[1] * s / 4], fill=tuple(int(v * 0.6 * glow) for v in rgb), width=max(1, int(width * s / 4 * 2.2)))

    def text(self, label, kind, size, color, x, y, alpha=1.0, max_w=W - 120, stroke=0, scale_pop=1.0):
        lay = g.text_layer(label, kind, int(size * self.scale), color, int(max_w * self.scale), "center", stroke, (0, 0, 0))
        g.paste_layer(self.img, lay, x * self.scale, y * self.scale, alpha, scale_pop, center=True) if self.img.mode == "RGBA" else \
            self._paste_text(lay, x, y, alpha, scale_pop)

    def _paste_text(self, lay, x, y, alpha, pop):
        if pop != 1.0:
            lay = lay.resize((max(1, int(lay.width * pop)), max(1, int(lay.height * pop))), Image.BILINEAR)
        if alpha < 1.0:
            lay = lay.copy(); lay.putalpha(lay.getchannel("A").point(lambda v: int(v * alpha)))
        self.img.paste(lay, (int(x * self.scale - lay.width / 2), int(y * self.scale - lay.height / 2)), lay)

    def finish(self, zoom: float = 1.0, shake=(0, 0)) -> Image.Image:
        wide = ImageChops.add(self.trail, self.glow).filter(ImageFilter.GaussianBlur(4))
        up = wide.resize((self.w, self.h), Image.BICUBIC)
        out = ImageChops.add(self.img, up)
        if abs(zoom - 1) > 1e-4 or shake != (0, 0):
            out = out.transform((self.w, self.h), Image.AFFINE,
                                (1 / zoom, 0, self.w / 2 - self.w / (2 * zoom) + shake[0], 0, 1 / zoom, self.h / 2 - self.h / (2 * zoom) + shake[1]), Image.BILINEAR)
        return out


def ease_out(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


# ------------------------------------------------------------------ scenes

class Scene:
    """A scene simulates itself (pass 1) and draws a recorded frame (pass 2)."""
    name = "scene"
    title = ""
    duration = 20.0
    top, bottom = (14, 16, 38), (3, 4, 12)
    loud = 1.0

    def __init__(self, seed: int = 1):
        self.rng = random.Random(seed)
        self.events: list[tuple] = []          # (time, kind, a, b) for the sound
        self.t = 0.0

    def simulate(self) -> list:
        raise NotImplementedError

    def draw(self, st: Stage, frame, t: float) -> tuple[float, tuple]:
        """Draws one recorded frame; returns (zoom, shake)."""
        raise NotImplementedError

    def audio(self, tr: Track) -> None:
        raise NotImplementedError

    def hook(self, st: Stage, t: float, line1: str, line2: str = "", sub: str = "") -> None:
        """Big hook text that is readable at once, then settles into the top corner."""
        settle = ease_out((t - 3.2) / 0.8)
        y = 330 - 150 * settle
        size = int(104 - 36 * settle)
        a = 1.0
        pop = 1.0 + 0.12 * max(0, 1 - t / 0.25) if t < 0.25 else 1.0
        st.text(line1, "impact", size, (255, 255, 255), W / 2, y, a, stroke=6, scale_pop=pop)
        if line2:
            st.text(line2, "impact", size, (255, 214, 64), W / 2, y + size * 1.15, a, stroke=6, scale_pop=pop)
        if sub and t < 3.6:
            st.text(sub, "sans_bold", 40, (200, 205, 225), W / 2, y + size * 2.1 + 20, 1 - ease_out((t - 2.6) / 0.8))


# --- A: five balls play Ode to Joy (each ball lands on a note bar at the exact beat) -------------------------------------------

class OdeToJoy(Scene):
    name = "ode_to_joy"
    COLS = {"C": 60, "D": 62, "E": 64, "F": 65, "G": 67}
    ORDER = ["C", "D", "E", "F", "G"]
    BAR_Y, SPAWN_Y, G_ = 1500, -60, 3000.0
    LEAD, BPM = 2.2, 112

    def __init__(self, seed=1):
        super().__init__(seed)
        a = "EEFGGFEDCCDEEDD"; b = "EEFGGFEDCCDEDCC"
        beats = ([1] * 12 + [1.5, 0.5, 2]) * 2
        self.notes = list(zip(a + b, beats))
        self.duration = self.LEAD + sum(beats) * 60 / self.BPM + 3.0
        self.title = "5 BALLS PLAY ODE TO JOY"

    def bar_x(self, n: str) -> float:
        return 140 + self.ORDER.index(n) * 200

    def _fall_time(self) -> float:
        sp = pymunk.Space(); sp.gravity = (0, self.G_)
        bar = pymunk.Segment(sp.static_body, (0, self.BAR_Y), (W, self.BAR_Y), 6); bar.elasticity = 0.4; bar.collision_type = 3
        body = pymunk.Body(1, pymunk.moment_for_circle(1, 0, 34)); body.position = (500, self.SPAWN_Y)
        ball = pymunk.Circle(body, 34); ball.elasticity = 0.4; ball.collision_type = 1
        sp.add(bar, body, ball); hit = []
        sp.on_collision(1, 3, begin=lambda arb, s, d: hit.append(n_steps[0] / 120))
        n_steps = [0]
        while not hit and n_steps[0] < 600:
            sp.step(1 / 120); n_steps[0] += 1
        return hit[0]

    def simulate(self):
        fall = self._fall_time()
        sp = pymunk.Space(); sp.gravity = (0, self.G_); sp.damping = 1.0
        for n in self.ORDER:
            x = self.bar_x(n); seg = pymunk.Segment(sp.static_body, (x - 58, self.BAR_Y), (x + 58, self.BAR_Y), 7)
            seg.elasticity = 0.45; seg.friction = 0.6; seg.collision_type = 3; seg.note = n; sp.add(seg)
        plan, t = [], self.LEAD
        for n, beats in self.notes:
            plan.append((t - fall, n, t)); t += beats * 60 / self.BPM
        plan.sort()
        self.note_plan = [(hit, n) for _, n, hit in plan]
        balls, frames, pi, kicks = [], [], 0, []
        for_ball_note = {}
        flashes = {n: -9 for n in self.ORDER}
        sparks = []                                          # (x, y, vx, vy, born, rgb)
        first_hit = set()

        def on_hit(arb, space, data):
            # the first thing each ball touches - the bar, or a ball already resting on it - is its note
            for ball in [s for s in arb.shapes if s.collision_type == 1]:
                if id(ball) in first_hit or ball.body.velocity.y < 350:
                    continue
                first_hit.add(id(ball))
                note = ball.note
                self.events.append((self.t, "note", note, ball.body.velocity.length))
                flashes[note] = self.t
                kicks.append((ball, 1 if self.ORDER.index(note) < 3 else -1))
                for _ in range(10):
                    ang = self.rng.uniform(math.pi, 2 * math.pi); sp_ = self.rng.uniform(150, 520)
                    sparks.append((ball.body.position.x, self.BAR_Y - 10, math.cos(ang) * sp_, math.sin(ang) * sp_, self.t, hsv(self.ORDER.index(note) / 5)))
        sp.on_collision(1, 3, begin=on_hit)
        sp.on_collision(1, 1, begin=on_hit)
        total = int(self.duration * FPS)
        for f in range(total):
            for _ in range(SUB):
                self.t = f / FPS
                while pi < len(plan) and plan[pi][0] <= self.t:
                    _, n, hit_t = plan[pi]; pi += 1
                    body = pymunk.Body(1, pymunk.moment_for_circle(1, 0, 34)); body.position = (self.bar_x(n) + self.rng.uniform(-6, 6), self.SPAWN_Y)
                    body.velocity = (self.rng.uniform(-60, 60), 0)
                    sh = pymunk.Circle(body, 34); sh.elasticity = 0.45; sh.friction = 0.5; sh.collision_type = 1; sh.color = self.ORDER.index(n); sh.note = n
                    sp.add(body, sh); balls.append(sh)
                sp.step(1 / (FPS * SUB))
            while kicks:                                      # a little hop sideways, so balls leave the bar instead of piling up
                ball, d = kicks.pop()
                ball.body.velocity = (d * self.rng.uniform(420, 560), -self.rng.uniform(300, 420))
            for sh in [b for b in balls if b.body.position.y > H + 120]:
                sp.remove(sh.body, sh); balls.remove(sh)
            sparks[:] = [s for s in sparks if self.t - s[4] < 0.6]
            frames.append({"balls": [(b.body.position.x, b.body.position.y, b.color) for b in balls], "flash": dict(flashes),
                           "sparks": [(s[0] + s[2] * (self.t - s[4]), s[1] + s[3] * (self.t - s[4]) + 900 * (self.t - s[4]) ** 2, s[5], 1 - (self.t - s[4]) / 0.6) for s in sparks]})
        return frames

    def draw(self, st, fr, t):
        img = st.begin(0.84)
        for i, n in enumerate(self.ORDER):
            x = self.bar_x(n); col = hsv(i / 5.0); age = t - fr["flash"][n]
            lift = max(0, 1 - age / 0.35); bright = tuple(min(255, int(c + (255 - c) * 0.7 * lift)) for c in col)
            st.rect(x - 62, self.BAR_Y - 4 + 6 * lift, x + 62, self.BAR_Y + 22 + 6 * lift, bright, 12, glow=0.6 + 1.2 * lift)
            st.text(n, "impact", 64, tuple(int(c * 0.9) for c in col), x, self.BAR_Y + 96, 0.95)
            if age < 0.5:
                r = 40 + age * 500
                st.gd.ellipse([x / 4 * st.scale - r / 8, self.BAR_Y / 4 * st.scale - r / 16, x / 4 * st.scale + r / 8, self.BAR_Y / 4 * st.scale + r / 16],
                              outline=tuple(int(c * (1 - age / 0.5)) for c in col), width=2)
        # the melody so far: one dot per note of the song, lit as each one plays
        total = len(self.note_plan); step = 940 / (total - 1)
        for k, (tn, n) in enumerate(self.note_plan):
            col = hsv(self.ORDER.index(n) / 5.0); on = t >= tn; age = t - tn
            rr = 9 + (9 * max(0, 1 - age / 0.3) if on else 0)
            st.ball(70 + k * step, 1790, rr, col if on else tuple(int(c * 0.22) for c in col), 0.8 if on else 0, trail=False)
        for x, y, c in fr["balls"]:
            st.ball(x, y, 34, hsv(c / 5.0), 1.0)
        for x, y, col, life in fr["sparks"]:
            st.ball(x, y, 5, col, 1.2 * life, trail=False)
        self.hook(st, t, "5 BALLS PLAY", "ODE TO JOY", "pure physics - no editing")
        pulse = max((max(0, 1 - (t - v) / 0.18) for v in fr["flash"].values()), default=0)
        return 1.0 + 0.012 * pulse + 0.01 * (t / self.duration), (0, 0)

    def audio(self, tr):
        for t, kind, n, vel in self.events:
            m = self.COLS[n]
            tr.place(marimba(midi_hz(m + 12), 0.9, 6.0), t, 0.55)
            tr.place(marimba(midi_hz(m), 1.0, 5.0), t, 0.25)
            tr.place(bell(midi_hz(m + 24), 1.4, 3.2), t, 0.05)
        tr.echo(0.28, 0.32, 0.4)


# --- B: every wall bounce adds a ball -----------------------------------------------------------------------------------------------

class Multiply(Scene):
    name = "multiply"
    ARENA = (60, 470, 1020, 1800)
    R, SPEED, CAP = 17, 520.0, 420
    P_SPAWN, COOLDOWN = 0.55, 0.4
    loud = 0.72

    def __init__(self, seed=3):
        super().__init__(seed)
        self.duration = 24.0
        self.title = "EVERY BOUNCE ADDS A BALL"

    def simulate(self):
        sp = pymunk.Space(); sp.gravity = (0, 0); sp.iterations = 14
        x0, y0, x1, y1 = self.ARENA
        for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
            s = pymunk.Segment(sp.static_body, a, b, 8); s.elasticity = 1.0; s.friction = 0; s.collision_type = 2; sp.add(s)
        balls, spawn, frames = [], [], []
        flash = []

        def new_ball(x, y, ang):
            body = pymunk.Body(1, pymunk.moment_for_circle(1, 0, self.R)); body.position = (x, y)
            body.velocity = (math.cos(ang) * self.SPEED, math.sin(ang) * self.SPEED)
            sh = pymunk.Circle(body, self.R); sh.elasticity = 1.0; sh.friction = 0; sh.collision_type = 1; sh.idx = len(balls); sh.born = self.t
            sp.add(body, sh); balls.append(sh); return sh

        new_ball((x0 + x1) / 2, (y0 + y1) / 2, self.rng.uniform(0, 6.28))

        def on_wall(arb, space, data):
            ball = [s for s in arb.shapes if s.collision_type == 1][0]
            self.events.append((self.t, "wall", len(balls), ball.body.velocity.length))
            if len(balls) + len(spawn) < self.CAP and self.t - getattr(ball, "last", -9) > self.COOLDOWN and (len(balls) < 10 or self.rng.random() < self.P_SPAWN):
                ball.last = self.t
                spawn.append((ball.body.position.x, ball.body.position.y, 0))
            flash.append((self.t, ball.body.position.x, ball.body.position.y))
        sp.on_collision(1, 2, begin=on_wall)
        self.full_at = None
        for f in range(int(self.duration * FPS)):
            for _ in range(SUB):
                self.t = f / FPS
                sp.step(1 / (FPS * SUB))
                for b in balls:
                    v = b.body.velocity; l = v.length
                    if l > 1e-6: b.body.velocity = v * (self.SPEED / l)
            while spawn:
                x, y, _ = spawn.pop()
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; dx, dy = cx - x, cy - y; dl = math.hypot(dx, dy) or 1
                nx, ny = x + dx / dl * 2.4 * self.R, y + dy / dl * 2.4 * self.R          # appears just inside, not inside the parent
                new_ball(nx, ny, self.rng.uniform(0, 6.28))
            if len(balls) >= self.CAP and self.full_at is None:
                self.full_at = self.t
            flash[:] = [e for e in flash if self.t - e[0] < 0.25]
            frames.append({"n": len(balls), "balls": [(b.body.position.x, b.body.position.y, b.idx) for b in balls], "flash": list(flash)})
        return frames

    def draw(self, st, fr, t):
        img = st.begin(0.9)
        x0, y0, x1, y1 = self.ARENA
        edge = (90, 150, 255)
        st.rect(x0 - 14, y0 - 14, x1 + 14, y1 + 14, edge, 30, glow=0.9)
        st.rect(x0 - 4, y0 - 4, x1 + 4, y1 + 4, (7, 9, 22), 24, glow=0)
        for tt, x, y in fr["flash"]:
            a = 1 - (t - tt) / 0.25
            st.ball(x, y, 26 + 30 * (1 - a), (255, 255, 255), 0.0, trail=False) if False else None
        for x, y, i in fr["balls"]:
            st.ball(x, y, self.R, hsv(i * 0.0173 + 0.55, 0.62, 1.0), 0.9)
        n = fr["n"]
        pop = 1.0 + 0.2 * max(0, 1 - (t - self._last_milestone(fr, t)) / 0.25) if n > 1 else 1.0
        st.text(f"{n}", "impact", 190, (255, 255, 255), W / 2, 395, ease_out((t - 3.0) / 0.5), stroke=7, scale_pop=pop) if t > 3.0 else None
        st.text("balls", "sans_bold", 44, (170, 180, 210), W / 2, 505, 0.9) if False else None
        self.hook(st, t, "EVERY BOUNCE", "ADDS A BALL", "")
        if self.full_at is not None and t > self.full_at:
            st.text("SCREEN FULL", "impact", 96, (255, 214, 64), W / 2, 1100, min(1, (t - self.full_at) / 0.4), stroke=6)
        return 1.0 + 0.02 * (t / self.duration), (0, 0)

    def _last_milestone(self, fr, t):
        n = fr["n"]
        return t if n & (n - 1) == 0 else 0

    def audio(self, tr):
        scale = [0, 2, 4, 7, 9]                                     # major pentatonic: every combination sounds consonant
        by_frame = {}
        for t, kind, n, vel in self.events:
            by_frame.setdefault(int(t * FPS), []).append((t, n))
        for f, evs in by_frame.items():
            evs = evs[:5]                                           # a crowd of hits becomes a shimmer, not a wall of noise
            gain = 0.5 / math.sqrt(len(evs))
            for t, n in evs:
                step = int(math.log2(max(2, n)) * 2.2) + self.rng.randrange(0, 3)
                midi = 60 + scale[step % 5] + 12 * (step // 5)
                tr.place(pluck(midi_hz(min(midi, 96)), 0.5, 11.0, 0.3), t, gain)
        tr.echo(0.22, 0.3, 0.35)
        # a quiet low pad that rises with the ball count gives the whole video a direction
        for i in range(int(self.duration)):
            tr.place(__import__("music").pad([midi_hz(36 + (i // 4) * 2), midi_hz(43 + (i // 4) * 2)], 1.6, 0.6, 0.8), i, 0.03 + 0.012 * i / self.duration)


# --- C: which funnel jams? ---------------------------------------------------------------------------------------------------------

class Jam(Scene):
    name = "jam"
    R, N_BALLS, OPEN_AT = 11, 130, 2.6
    GAPS = [2.25, 2.35, 2.45]                                      # exit width, in ball widths - jamming has a sharp threshold near 2.3
    CX = [190, 540, 890]
    TOP_Y, NECK_Y, SPOUT_Y = 660, 1230, 1330

    def __init__(self, seed=6):
        super().__init__(seed)
        self.duration = 11.0
        self.title = "WHICH ONE JAMS?"
        self.escaped = [0, 0, 0]

    def simulate(self):
        sp = pymunk.Space(); sp.gravity = (0, 1700); sp.iterations = 20
        gates = []
        for k, (cx, gap_n) in enumerate(zip(self.CX, self.GAPS)):
            half = gap_n * self.R / 1.0
            top_half = 158
            for a, b in (((cx - top_half, self.TOP_Y), (cx - half, self.NECK_Y)), ((cx + top_half, self.TOP_Y), (cx + half, self.NECK_Y)),
                         ((cx - half, self.NECK_Y), (cx - half, self.SPOUT_Y)), ((cx + half, self.NECK_Y), (cx + half, self.SPOUT_Y))):
                s = pymunk.Segment(sp.static_body, a, b, 5); s.friction = 0.35; s.elasticity = 0.15; sp.add(s)
            gate = pymunk.Segment(sp.static_body, (cx - half, self.NECK_Y + 20), (cx + half, self.NECK_Y + 20), 5); gate.friction = 0.5; sp.add(gate); gates.append(gate)
        balls, frames = [], []
        for k, cx in enumerate(self.CX):
            for i in range(self.N_BALLS):
                row, col = divmod(i, 11)
                body = pymunk.Body(1, pymunk.moment_for_circle(1, 0, self.R)); body.position = (cx - 100 + col * 20 + self.rng.uniform(-3, 3), self.TOP_Y - 20 - row * 22)
                sh = pymunk.Circle(body, self.R); sh.elasticity = 0.15; sh.friction = 0.35; sh.col = k; sh.collision_type = 1
                sp.add(body, sh); balls.append(sh)
        opened = False; self.jam_at = [None] * 3; last_esc = [0.0] * 3; done_at = [None] * 3
        def on_hit(arb, space, data):
            sh = arb.shapes[0]
            if self.rng.random() < 0.16:
                self.events.append((self.t, "tick", sh.col, sh.body.velocity.length))
        sp.on_collision(1, None, begin=on_hit)
        sp.on_collision(1, 1, begin=on_hit)
        for f in range(int(self.duration * FPS)):
            self.t = f / FPS
            if not opened and self.t >= self.OPEN_AT:
                for gt in gates: sp.remove(gt)
                opened = True; self.events.append((self.t, "open", 0, 0))
            for _ in range(SUB):
                sp.step(1 / (FPS * SUB))
            for k in range(3):
                self.escaped[k] = sum(1 for b in balls if b.col == k and b.body.position.y > self.SPOUT_Y)
                if self.escaped[k] != last_esc[k] if False else False:
                    pass
            # a funnel is "jammed" once balls remain above the neck but nothing has left for 1.5 s
            for k in range(3):
                if opened and self.jam_at[k] is None and done_at[k] is None:
                    remaining = sum(1 for b in balls if b.col == k and b.body.position.y < self.NECK_Y)
                    if remaining == 0:
                        done_at[k] = self.t; self.events.append((self.t, "clear", k, 0))
                    else:
                        if self.escaped[k] != last_esc[k] or not hasattr(self, "_stamp"):
                            pass
            if f % 5 == 0:
                if not hasattr(self, "_hist"): self._hist = {}
                for k in range(3):
                    self._hist.setdefault(k, []).append((self.t, self.escaped[k]))
                    if opened and self.jam_at[k] is None and done_at[k] is None:
                        h = [e for t_, e in self._hist[k] if self.t - t_ <= 1.6]
                        if self.t > self.OPEN_AT + 1.8 and len(h) >= 5 and max(h) == min(h):
                            self.jam_at[k] = self.t - 1.6; self.events.append((self.t - 1.6, "jam", k, 0))
            frames.append({"balls": [(b.body.position.x, b.body.position.y, b.col) for b in balls], "esc": list(self.escaped), "opened": opened,
                           "jam": list(self.jam_at), "done": list(done_at)})
        self.final = {"jam": list(self.jam_at), "done": list(done_at), "esc": list(self.escaped)}
        return frames

    def draw(self, st, fr, t):
        st.begin(0.86)
        cols = [(255, 120, 150), (255, 200, 90), (110, 230, 190)]
        for k, (cx, gap_n) in enumerate(zip(self.CX, self.GAPS)):
            half = gap_n * self.R; edge = (140, 160, 230)
            st.line((cx - 158, self.TOP_Y), (cx - half, self.NECK_Y), edge, 9); st.line((cx + 158, self.TOP_Y), (cx + half, self.NECK_Y), edge, 9)
            st.line((cx - half, self.NECK_Y), (cx - half, self.SPOUT_Y), edge, 9); st.line((cx + half, self.NECK_Y), (cx + half, self.SPOUT_Y), edge, 9)
            if not fr["opened"]:
                st.line((cx - half, self.NECK_Y + 20), (cx + half, self.NECK_Y + 20), (255, 255, 255), 8)
            st.text(f"{gap_n:g}x", "impact", 84, cols[k], cx, 1470, 1.0, stroke=5)
            st.text("exit width", "sans_bold", 30, (170, 180, 210), cx, 1540, 0.9)
            esc = fr["esc"][k]
            st.text(f"{esc} / {self.N_BALLS}", "sans_bold", 46, (255, 255, 255), cx, 1630, 1.0)
            if fr["jam"][k] is not None and t >= fr["jam"][k] + 1.6:
                st.text("JAMMED", "impact", 70, (255, 80, 80), cx, 1750, min(1, (t - fr["jam"][k] - 1.6) / 0.3), stroke=5)
            elif fr["done"][k] is not None:
                st.text("CLEAR", "impact", 70, (110, 255, 160), cx, 1750, min(1, (t - fr["done"][k]) / 0.3), stroke=5)
        for x, y, k in fr["balls"]:
            if y < self.SPOUT_Y + 50:                       # balls that have dropped out of a funnel just disappear (they're counted below)
                st.ball(x, y, self.R, cols[k], 0.6, trail=False)
        if t < self.OPEN_AT:
            n = int(self.OPEN_AT - t) + 1
            st.text(str(n), "impact", 220, (255, 255, 255), W / 2, 880, 0.35 + 0.65 * (1 - ((self.OPEN_AT - t) % 1)), stroke=8)
        self.hook(st, t, "WHICH ONE", "JAMS?", "same balls, same gravity - exits differ by 4%")
        return 1.0, (0, 0)

    def audio(self, tr):
        scale = [0, 3, 5, 7, 10]
        seen_frames = {}
        for t, kind, a, b in self.events:
            if kind == "tick":
                f = int(t * FPS)
                if seen_frames.get(f, 0) >= 2:                      # at most two patters per frame, so it stays a soft rain, not static
                    continue
                seen_frames[f] = seen_frames.get(f, 0) + 1
                tr.place(marimba(midi_hz(72 + scale[(int(t * 97) + a) % 5] + 12 * (a % 2)), 0.28, 16), t, 0.06)
            elif kind == "open":
                tr.place(noise(1.0, 3.0, np.random.default_rng(7), 18) * np.linspace(0.2, 1, int(SR * 1.0)), t, 0.3)
            elif kind == "jam":
                tr.place(pluck(midi_hz(41), 1.2, 3.0, 0.5), t + 1.6, 0.8); tr.place(pluck(midi_hz(34), 1.5, 2.5, 0.5), t + 1.7, 0.8)
            elif kind == "clear":
                for i, m in enumerate((72, 76, 79, 84)):
                    tr.place(bell(midi_hz(m), 1.8, 2.0), t + i * 0.09, 0.22)
        for i, tt in enumerate((0.5, 1.2, 1.9)):
            tr.place(pluck(midi_hz(76), 0.25, 14, 0.2), tt, 0.5)
        tr.echo(0.3, 0.3, 0.3)


SCENES = {"ode": OdeToJoy, "multiply": Multiply, "jam": Jam}


# ------------------------------------------------------------------ rendering

def render(scene: Scene, out_path: Path, preview: bool = False, log=print) -> Path:
    out_path = Path(out_path); out_path.parent.mkdir(parents=True, exist_ok=True)
    scale = 0.5 if preview else 1.0
    log(f"[sim] simulating '{scene.name}' ({scene.duration:.0f}s)...")
    frames = scene.simulate()
    if preview:
        frames = frames[: int(FPS * 6)]
    tr = Track(scene.duration)
    scene.audio(tr)
    log(f"[sim] {len(scene.events)} sound events; rendering {len(frames)} frames...")
    wav = out_path.with_suffix(".wav")
    buf = tr.buf[: int(scene.duration * SR)]
    buf = buf / max(1e-9, float(np.sqrt((buf ** 2).mean()))) * 0.2 * scene.loud          # same average loudness for every scene (about -14 dB)
    buf = np.tanh(buf * 1.1)                                               # soft-limit the peaks instead of clipping them
    buf = buf / max(1e-9, np.abs(buf).max()) * 0.9
    fade = int(0.05 * SR); buf[:fade] *= np.linspace(0, 1, fade); buf[-fade * 6:] *= np.linspace(1, 0, fade * 6)
    raw = out_path.with_suffix(".raw"); raw.write_bytes((np.repeat(buf[:, None], 2, 1) * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw), str(wav)], check=True); raw.unlink()
    st = Stage(scene.top, scene.bottom, scale)
    w, h = st.w, st.h
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-i", str(wav),
           "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for i, fr in enumerate(frames):
            zoom, shake = scene.draw(st, fr, i / FPS)
            proc.stdin.write(st.finish(zoom, shake).tobytes())
            if i % 90 == 0:
                log(f"[sim] frame {i}/{len(frames)}")
        proc.stdin.close(); proc.wait()
    finally:
        if proc.poll() is None: proc.kill()
    wav.unlink(missing_ok=True)
    log(f"[sim] Done -> {out_path}")
    return out_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", choices=list(SCENES))
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--seed", type=int)
    a = ap.parse_args()
    sc = SCENES[a.scene](a.seed) if a.seed is not None else SCENES[a.scene]()
    render(sc, OUT / f"{a.scene}{'_preview' if a.preview else ''}.mp4", a.preview)
