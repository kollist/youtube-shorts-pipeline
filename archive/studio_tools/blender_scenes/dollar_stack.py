"""
How tall is a stack of dollar bills? Six composed shots, one per narration beat, each built at its own scale.
Numbers: a US bill is 0.0043 in = 0.109 mm thick -> 1 thousand = 0.109 m, 1 million = 109 m, 1 billion = 109 km,
1 trillion = 109,000 km. References: Statue of Liberty with pedestal 93 m, Everest 8.85 km, airliner cruise ~11 km,
Karman line 100 km, Moon 384,400 km. In the km-scale shots the stack is drawn wider than real (a real one is 15 cm wide).
"""
import blender_kit as k

BILL_MM = 0.109
PAPER = (0.25, 0.62, 0.32)
GOLD = (1.0, 0.82, 0.25)
RED = (1.0, 0.38, 0.33)
WHITE = (0.95, 0.96, 1.0)
DAY, DUSK, SPACE = (0.5, 0.72, 0.95), (0.08, 0.14, 0.3), (0.005, 0.008, 0.025)


def build(t):
    k.reset(sky=DAY, width=720, height=1280)
    km = 109.0   # one billion bills, in km

    # 1. hook - a needle of bills rising into space (1 unit = 1 km; drawn wider than real so it can be seen)
    with k.shot(t[0], cam=(70, -150, 15), cam_end=(45, -105, 70), look=(0, 0, 55), look_end=(0, 0, 75), sky=DUSK):
        k.disc(radius=900, color=(0.22, 0.38, 0.22))
        k.box(size=(5, 5, km), loc=(0, 0, km / 2), color=PAPER)
        k.ring(14, loc=(0, 0, 100), thickness=0.5, color=RED)
        k.text("SPACE", size=9, loc=(-22, 0, 100), color=RED, align="RIGHT")
        k.text("ONE BILLION $1 BILLS", size=8, loc=(0, 0, km + 12), color=GOLD)

    # 2. one bill is 0.109 mm thick (1 unit = 1 cm)
    with k.shot(t[1], cam=(0, -62, 40), cam_end=(0, -46, 30), look=(0, 0, 4), look_end=(0, 0, 3), sky=(0.82, 0.84, 0.88)):
        k.disc(radius=200, color=(0.86, 0.85, 0.82))
        k.box(size=(15.6, 6.6, 0.0109), loc=(0, 0, 0.0055), color=PAPER)
        k.text("ONE BILL", size=3.4, loc=(0, 0, 14), color=(0.15, 0.2, 0.15))
        k.text("0.109 mm thick", size=2.6, loc=(0, 0, 9), color=(0.1, 0.4, 0.15))

    # 3. one million bills = 109 m, next to the Statue of Liberty (93 m with pedestal) and a person (1 unit = 1 m)
    with k.shot(t[2], cam=(0, -215, 30), cam_end=(0, -165, 55), look=(0, 0, 52), look_end=(0, 0, 56), sky=DAY):
        k.disc(radius=1500, color=(0.3, 0.52, 0.3))
        k.box(size=(8, 8, 109), loc=(0, 0, 54.5), color=PAPER)
        k.text("1 MILLION BILLS", size=11, loc=(0, 0, 128), color=GOLD)
        k.text("109 m", size=10, loc=(0, 0, 114), color=WHITE)
        # statue stand-in: pedestal + figure
        k.box(size=(18, 18, 47), loc=(-26, 0, 23.5), color=(0.7, 0.68, 0.62))
        k.cylinder(radius=5, height=44, loc=(-26, 0, 69), color=(0.38, 0.62, 0.55))
        k.sphere(4, loc=(-26, 0, 94), color=(0.38, 0.62, 0.55))
        k.text("STATUE", size=6, loc=(-26, 0, 112), color=WHITE)
        k.text("OF LIBERTY 93 m", size=5, loc=(-26, 0, 104), color=WHITE)
        k.sphere(1.6, loc=(24, 0, 1.6), color=(0.95, 0.55, 0.2), emission=1.0)
        k.text("YOU (1.75 m)", size=5, loc=(24, 0, 9), color=(0.95, 0.55, 0.2))

    # 4. one billion: past Everest and the airliners (1 unit = 1 km)
    with k.shot(t[3], cam=(0, -215, 45), cam_end=(0, -160, 62), look=(0, 0, 52), look_end=(0, 0, 60), sky=DUSK):
        k.disc(radius=1500, color=(0.25, 0.3, 0.27))
        k.box(size=(4, 4, km), loc=(0, 0, km / 2), color=PAPER)
        k.cone(radius=14, height=8.85, loc=(-38, 0, 4.4), color=(0.72, 0.74, 0.8), name="everest")
        k.text("EVEREST", size=7, loc=(-38, 0, 20), color=WHITE)
        k.text("8.9 km", size=7, loc=(-38, 0, 12), color=WHITE)
        k.ring(9, loc=(0, 0, 11), thickness=0.3, color=(0.7, 0.88, 1.0))
        k.text("AIRLINERS", size=7, loc=(24, 0, 20), color=(0.7, 0.88, 1.0))
        k.text("11 km", size=7, loc=(24, 0, 12), color=(0.7, 0.88, 1.0))
        k.text("1 BILLION BILLS", size=9, loc=(0, 0, km + 20), color=GOLD)
        k.text("109 km", size=9, loc=(0, 0, km + 8), color=WHITE)

    # 5. the Karman line, where space begins, at 100 km (1 unit = 1 km)
    with k.shot(t[4], cam=(60, -230, 92), cam_end=(40, -170, 99), look=(0, 0, 98), look_end=(0, 0, 101), sky=SPACE):
        k.disc(radius=1500, color=(0.18, 0.3, 0.55))
        k.box(size=(4, 4, km), loc=(0, 0, km / 2), color=PAPER)
        k.ring(22, loc=(0, 0, 100), thickness=0.6, color=RED)
        k.text("SPACE BEGINS", size=8, loc=(0, 0, 118), color=RED)
        k.text("100 km", size=8, loc=(0, 0, 108), color=WHITE)
        k.text("THE STACK: 109 km", size=7, loc=(0, 0, 128), color=GOLD)

    # 6. a trillion bills: 109,000 km, over a quarter of the way to the Moon (1 unit = 1 km, true sizes)
    with k.shot(t[5], cam=(0, -680_000, 192_000), cam_end=(0, -600_000, 192_000), look=(0, 0, 192_000), sky=SPACE, last=True):
        k.sphere(6371, loc=(0, 0, 0), color=(0.2, 0.45, 0.85))
        k.sphere(1737, loc=(0, 0, 384_400), color=(0.75, 0.75, 0.78))
        k.cylinder(radius=3000, height=109_000, loc=(0, 0, 54_500), color=GOLD, emission=1.0)
        k.text("EARTH", size=52_000, loc=(40_000, 0, 0), color=WHITE, align="LEFT")
        k.text("MOON", size=52_000, loc=(40_000, 0, 384_400), color=WHITE, align="LEFT")
        k.text("1 TRILLION BILLS", size=46_000, loc=(-30_000, 0, 85_000), color=GOLD, align="RIGHT")
        k.text("109,000 km", size=46_000, loc=(-30_000, 0, 40_000), color=WHITE, align="RIGHT")
        k.text("28% OF THE WAY", size=46_000, loc=(0, 0, 230_000), color=GOLD)
    k.set_range(t[-1][1])
