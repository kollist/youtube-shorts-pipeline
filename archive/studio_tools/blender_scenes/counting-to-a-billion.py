'''
How long to count to one billion? Six shots, one per narration beat.
Numbers (counting one number per second):
 1 year = 365.25 d x 86,400 s = 31,557,600 s
 1 million = 1,000,000 s / 86,400 = 11.57 days
 1 billion = 1,000,000,000 / 31,557,600 = 31.69 years (= 1,000 millions x 11.57 d = 11,574 d)
 8 h/day = 28,800 s/day -> 1e9 / 28,800 = 34,722 days / 365.25 = 95.06 years
 Today 2026-10-20 + 31.69 y = late June 2058.
Shot 1: 31 blocks of 1 year (0.5 unit each) + one red block of 0.7 year (0.35 unit).
Shot 2: 11 full day blocks + one 0.57-wide block = 11.57 days.
Shot 3: 25 x 40 = 1,000 blocks, each one million (11.6 days); first block in red.
Shot 4: bar scale 0.17 unit per year: 31.69 y = 5.39, 63.37 y more = 10.77, total 95.06 y = 16.16.
Shot 5: timeline scale 0.3 unit per year: 31.69 y = 9.5 units.
'''
import blender_kit as k

GOLD = (1.0, 0.82, 0.25)
ORANGE = (1.0, 0.5, 0.2)
WHITE = (0.95, 0.96, 1.0)
RED = (1.0, 0.38, 0.33)
NIGHT = (0.03, 0.05, 0.13)


def build(t):
    k.reset(sky=NIGHT, width=720, height=1280)

    # 1. hook: 31.7 one-year blocks stacked (1 block = 1 year)
    with k.shot(t[0], cam=(0, -32, 16), cam_end=(0, -30, 16), look=(0, 0, 16), sky=NIGHT):
        for i in range(31):
            k.box(size=(4, 1.5, 0.46), loc=(0, 0, 8 + 0.5 * i + 0.23), color=GOLD if i % 2 == 0 else ORANGE, emission=0.4)
        k.box(size=(4, 1.5, 0.35), loc=(0, 0, 8 + 15.5 + 0.175), color=RED, emission=0.4)
        k.text('ONE BILLION', size=2.3, loc=(0, 0, 28.5), color=WHITE)
        k.text('31.7 YEARS', size=2.4, loc=(0, 0, 26), color=GOLD)

    # 2. one million = 11.6 days (1 block = 1 day)
    with k.shot(t[1], cam=(0, -14, 8.5), cam_end=(0, -13, 8.5), look=(0, 0, 8.5), sky=NIGHT):
        for i in range(12):
            r, c = divmod(i, 3)
            x = (c - 1) * 1.2
            z = 10.4 - 1.2 * r
            if i < 11:
                k.box(size=(1, 0.3, 1), loc=(x, 0, z), color=GOLD, emission=0.4)
            else:
                w = 0.57
                k.box(size=(w, 0.3, 1), loc=(x - 0.5 + w / 2, 0, z), color=RED, emission=0.4)
        k.text('1 MILLION', size=1.2, loc=(0, 0, 14), color=WHITE)
        k.text('11.6 DAYS', size=1.2, loc=(0, 0, 12.4), color=GOLD)

    # 3. one billion = 1,000 millions (1 block = 1 million = 11.6 days)
    with k.shot(t[2], cam=(0, -38, 22), cam_end=(0, -34, 22), look=(0, 0, 22), sky=NIGHT):
        for r in range(40):
            for c in range(25):
                first = (r == 0 and c == 0)
                k.box(size=(0.4, 0.2, 0.36), loc=((c - 12) * 0.5, 0, 30.5 - 0.45 * r), color=RED if first else GOLD, emission=0.4)
        k.text('1,000 MILLIONS', size=2.0, loc=(0, 0, 36.2), color=WHITE)
        k.text('31.7 YEARS', size=2.8, loc=(0, 0, 33.4), color=GOLD)

    # 4. eight hours a day = 95 years (0.17 unit per year)
    with k.shot(t[3], cam=(0, -34, 18), cam_end=(0, -31, 18), look=(0, 0, 18), sky=NIGHT):
        k.box(size=(4, 2, 5.39), loc=(2, 0, 9 + 2.695), color=GOLD, emission=0.4)
        k.box(size=(4, 2, 10.77), loc=(2, 0, 9 + 5.39 + 5.385), color=ORANGE, emission=0.4)
        k.text('NONSTOP', size=1.7, loc=(-0.3, 0, 12.8), color=GOLD, align='RIGHT')
        k.text('31.7 YEARS', size=1.5, loc=(-0.3, 0, 10.8), color=GOLD, align='RIGHT')
        k.text('8 HOURS', size=1.7, loc=(-0.3, 0, 21), color=ORANGE, align='RIGHT')
        k.text('A DAY', size=1.7, loc=(-0.3, 0, 19), color=ORANGE, align='RIGHT')
        k.text('95 YEARS', size=2.6, loc=(1.5, 0, 28.5), color=WHITE)

    # 5. timeline: start 2026, finish mid 2058 (0.3 unit per year)
    with k.shot(t[4], cam=(0, -26, 15), cam_end=(0, -23, 15), look=(0, 0, 15), sky=NIGHT):
        k.cylinder(radius=0.12, height=9.5, loc=(0, 0, 14.25), color=WHITE, emission=0.6)
        k.sphere(0.6, loc=(0, 0, 9.5), color=GOLD, emission=0.6)
        k.sphere(0.6, loc=(0, 0, 19), color=RED, emission=0.6)
        k.text('2026', size=2.4, loc=(1.4, 0, 10.6), color=GOLD, align='LEFT')
        k.text('START', size=1.6, loc=(1.4, 0, 8.7), color=WHITE, align='LEFT')
        k.text('2058', size=2.4, loc=(1.4, 0, 20.4), color=RED, align='LEFT')
        k.text('FINISH', size=1.6, loc=(1.4, 0, 18.4), color=WHITE, align='LEFT')
        k.text('31.7', size=2.2, loc=(-1.0, 0, 15.2), color=GOLD, align='RIGHT')
        k.text('YEARS', size=1.6, loc=(-1.0, 0, 13.4), color=GOLD, align='RIGHT')

    # 6. big numbers take longer to say, so the real time is more
    with k.shot(t[5], cam=(0, -16, 9), cam_end=(0, -14.5, 9), look=(0, 0, 9), sky=NIGHT, last=True):
        k.text('1,000,000,000', size=1.0, loc=(0, 0, 14.5), color=GOLD)
        k.text('BIG NUMBERS', size=1.2, loc=(0, 0, 12.3), color=WHITE)
        k.text('TAKE LONGER', size=1.2, loc=(0, 0, 10.7), color=WHITE)
        k.text('OVER 31.7', size=1.4, loc=(0, 0, 8.5), color=ORANGE)
        k.text('YEARS', size=1.4, loc=(0, 0, 6.9), color=ORANGE)
    k.set_range(t[-1][1])
