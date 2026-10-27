"""
picture_styles.py
The look of an episode's pictures. Each style is a different KIND of scary footage (a security camera, a thermal camera, an on-camera-flash photo, a flooded basement...),
so a viewer who has seen five tapes still can't tell what the next one will look like. The writer gets the chosen style's shot menu; the picture model gets its look string.

Used by scp_story.py (`pick_style`, `rules_text`) - one style per episode, the least recently used first, so the same one never appears twice in a row.
Add or remove styles freely: the only keys that matter are name / style / shots / sample.
"""

import json
import random
import zlib
from pathlib import Path

DATA = Path(__file__).parent / "data"
STATE = DATA / "picture_style_state.json"
DISABLED = DATA / "picture_styles_disabled.json"          # {"disabled": ["thermal", ...]} - styles you don't want in the rotation

NO_TEXT = "absolutely no text, no letters, no numbers, no timestamps, no watermarks, vertical composition"

STYLES = {
    "cctv": {
        "name": "Security camera (black and white)",
        "style": f"grainy black-and-white CCTV security camera frame from a high corner, fisheye wide angle, low resolution, scanlines, crushed blacks, photorealistic, {NO_TEXT}",
        "shots": ("a wide empty room or corridor seen from a high corner, the entity tiny and perfectly still far from the camera; the same room again, the entity slightly closer; "
                  "a doorway with the door ajar; a figure at the edge of the frame partly cut off; the entity directly under the camera, only the top of its head visible"),
        "sample": "grainy black-and-white CCTV frame from a high corner of an empty concrete corridor, a tall pale thin humanoid figure standing perfectly motionless at the far end, head tilted",
    },
    "flashlight": {
        "name": "Flashlight point of view",
        "style": f"found-footage photograph, one flashlight beam cutting through haze, everything outside the beam pitch black, desaturated, heavy 35mm film grain, photorealistic, {NO_TEXT}",
        "shots": ("the viewer's point of view walking down a dark corridor, the beam finding something at the far end; the beam on a wall with wrong marks; the beam sweeping across a door; "
                  "the beam catching a pale face for one frame at the edge of the light; the beam shaking, the entity very close and half out of focus"),
        "sample": "point of view down a dark narrow corridor, a flashlight beam through haze, at the far end of the beam a pale tall figure with an unnaturally long neck half swallowed by darkness",
    },
    "shoulder": {
        "name": "Over the shoulder",
        "style": f"cinematic found-footage horror photograph, over-the-shoulder composition, shallow depth of field, one cold light source, heavy film grain, photorealistic, {NO_TEXT}",
        "shots": ("the back of a person's head out of focus in the foreground and something standing in a dark doorway ahead; the same framing with it nearer; "
                  "a hand reaching toward a door handle; the person frozen, the entity lit by one red light behind them; the entity out of focus right behind their shoulder, never touching"),
        "sample": "over-the-shoulder shot, the back of a man's head out of focus in the left foreground, in a dark doorway ahead a tall pale figure lit only from below by a red emergency light",
    },
    "thermal": {
        "name": "Thermal camera",
        "style": f"thermal imaging camera footage, FLIR false-colour heat map, cold deep blue and purple background, warm orange-white human heat signatures, low resolution, noise, photorealistic, {NO_TEXT}",
        "shots": ("a room full of warm orange human shapes and one shape that is COLD and black, a hole in the heat map; the cold shape closer; the warm shapes turning to face it; "
                  "a corridor where footprints glow warm and lead to a cold black figure; the cold black shape filling the doorway, no heat at all"),
        "sample": "thermal imaging view of a dark corridor, glowing orange-white warm human silhouettes of two guards in the foreground, and behind them one tall completely cold black humanoid shape that gives off no heat",
    },
    "nightvision": {
        "name": "Night vision",
        "style": f"green night-vision infrared camera footage, glowing white eyes reflecting the infrared light, grainy, bloom, vignette, photorealistic, {NO_TEXT}",
        "shots": ("a dark room in green night vision, two points of reflected light where eyes should not be; a bed or desk with someone asleep and the room wrong; the same room, the eyes nearer; "
                  "a face blown out white by the infrared; the glowing eyes right at the lens"),
        "sample": "green night-vision camera view of a dark bedroom doorway, a very tall thin figure standing in the doorway with two glowing white reflective eyes, grainy infrared look",
    },
    "flashphoto": {
        "name": "Harsh flash photograph",
        "style": f"harsh direct on-camera flash photograph at night, red-eye effect, overexposed foreground, pitch black background beyond the flash, evidence photo, film grain, photorealistic, {NO_TEXT}",
        "shots": ("a flash-lit empty room with one wrong detail, the dark behind it unlit; a flash photo of a wall with something dragged along it; a flash photo showing a pale shape at the edge of the dark; "
                  "a flash photo where a face has appeared in the black background; a flash photo taken too close, the entity half in frame, lit white and flat"),
        "sample": "harsh on-camera flash photograph of a messy abandoned room at night, deep black beyond the flash, in the dark at the edge of the flash a pale tall figure stands very still with red-eye glowing eyes",
    },
    "camcorder": {
        "name": "90s camcorder / VHS",
        "style": f"1990s handheld camcorder VHS home video freeze frame shot at night in a dark house, lit only by the small camcorder light, low resolution, tracking distortion, washed-out colours, blown highlights, tape smear, deep black shadows, photorealistic, {NO_TEXT}",
        "shots": ("a family-video style room, bright and ordinary, a dark shape in the background nobody mentions; the same room, the shape nearer; the camera turning away too late; "
                  "a freeze-frame where something stands in the doorway; tracking lines tearing across the entity's face"),
        "sample": "1990s VHS camcorder freeze frame at night in a dark suburban hallway lit only by the camcorder light, tracking lines, at the far end in the dark doorway a very tall pale thin figure in dark clothes stands motionless, head too high",
    },
    "monitorwall": {
        "name": "Wall of monitors",
        "style": f"dark control room lit only by a wall of security monitors, each screen showing a different grainy camera view, cold screen glow, photorealistic, {NO_TEXT}",
        "shots": ("a wall of monitors, every screen an empty corridor except one with a tiny figure; the same wall, the figure now on two screens; a close view of one screen with the entity closer; "
                  "a guard's silhouette in front of the screens, one screen showing the guard from behind with something standing there; every screen showing the same face"),
        "sample": "a dark security control room, wall of grainy monitors showing empty corridors, on one central screen a tall pale figure stands close to the camera, a seated guard silhouette in front",
    },
    "trailcam": {
        "name": "Trail camera in the woods",
        "style": f"infrared trail camera night photograph in a deep dark forest, flash-lit trees, glowing eyes in the dark, wide angle, grainy, photorealistic, {NO_TEXT}",
        "shots": ("a forest clearing at night, two glowing eyes between the trees; the same clearing, eyes closer; a path with the shape of something tall between trunks; "
                  "a tree with something wrong in its branches; the entity close to the camera, face smeared by the infrared flash"),
        "sample": "infrared trail camera photograph of a dark forest at night, flash-lit trees, between the trunks a very tall thin pale figure with glowing eyes standing among the trees, grainy",
    },
    "flooded": {
        "name": "Flooded basement",
        "style": f"flooded concrete basement, knee-deep black water like a mirror, one caged bare bulb, ripples, dripping pipes, deep shadows, photorealistic, {NO_TEXT}",
        "shots": ("a basement full of black water with one ripple in the middle; footprints in wet concrete that end at the water; the bulb flickering and a shape under the surface; "
                  "a reflection in the water that does not match what is above it; a pale hand at the water's edge"),
        "sample": "flooded concrete basement, black mirror-like water, one caged bare light bulb, in the reflection and in the dark at the far end a tall pale figure standing waist-deep in the water, photorealistic",
    },
    "hospital": {
        "name": "Abandoned hospital",
        "style": f"abandoned hospital hallway, peeling green paint, overturned wheelchair, flickering fluorescent light, deep shadows, dust in the air, photorealistic found photograph, {NO_TEXT}",
        "shots": ("a long hospital corridor with a flickering light and an overturned wheelchair; a ward door ajar with something in the dark; a gurney in the wrong place; "
                  "a window in a door with a pale face behind it; the entity at the far end of the corridor, lit by the flicker"),
        "sample": "long abandoned hospital corridor, peeling green paint, overturned wheelchair, one flickering fluorescent tube, at the far end a tall thin pale figure standing at the edge of the light",
    },
    "liminal": {
        "name": "Liminal office (backrooms)",
        "style": f"endless empty office rooms with damp yellow carpet and humming fluorescent lights, no windows, wrong proportions, liminal space, photorealistic, {NO_TEXT}",
        "shots": ("an empty office floor going on too far; a doorway into another identical room; a stain on the carpet in the shape of footprints; "
                  "far away between the cubicles a pale figure that is always the same distance; the same figure suddenly much closer"),
        "sample": "endless empty office floor with damp yellow carpet and humming fluorescent lights, far away between cubicle walls a very tall pale figure stands perfectly still, liminal space",
    },
    "elevator": {
        "name": "Stuck elevator",
        "style": f"inside a stuck elevator, brushed metal walls, flickering light, doors half open onto darkness between floors, photorealistic, {NO_TEXT}",
        "shots": ("the elevator interior with the doors half open onto black; the light flickering and the doorway different each flicker; a hand on the edge of the doors; "
                  "the buttons all lit; the entity filling the gap in the doors, lit by the flicker"),
        "sample": "inside a stuck elevator, brushed steel walls, flickering light, the doors half open onto pitch darkness, in the gap a tall pale figure stands very close to the doors",
    },
    "film16": {
        "name": "Archive film (1970s)",
        "style": f"scratched black-and-white 16mm archival film frame, heavy grain, dust and hair, light leak, 1970s documentary look, photorealistic, {NO_TEXT}",
        "shots": ("an archival shot of a laboratory or corridor, staff in 1970s clothing, one figure in the background that is wrong; the same footage, the figure nearer; "
                  "a scratched frame where the figure is in the foreground; the film burning at the edge as the entity turns to the lens"),
        "sample": "scratched black-and-white 16mm archive film frame of a 1970s laboratory corridor, grain and dust, researchers in lab coats and behind them a very tall thin pale figure that is wrong",
    },
    "whiteout": {
        "name": "Polar whiteout",
        "style": f"polar research base in a whiteout storm, blowing snow, one red beacon, silhouettes at the edge of visibility, cold blue, grain, photorealistic, {NO_TEXT}",
        "shots": ("a base at night in blowing snow with one red light; a line of footprints in the snow leading away; a silhouette at the edge of visibility; "
                  "the silhouette nearer, taller than a person; the entity just inside the storm, lit red by the beacon"),
        "sample": "polar research base in a whiteout blizzard at night, one red beacon light, blowing snow, at the edge of visibility a very tall dark silhouette standing among the drifts",
    },
    "mirror": {
        "name": "Mirror",
        "style": f"bathroom mirror at night lit by one bare bulb, slightly cracked glass, the reflection subtly wrong, every person fully clothed in dark coats, faces in shadow, photorealistic, {NO_TEXT}",
        "shots": ("a person at a mirror and the reflection a moment late; the reflection with something standing behind it that is not in the room; the mirror fogged with a handprint on the inside; "
                  "the reflection turning while the person does not; the entity standing right behind the reflection's shoulder"),
        "sample": "bathroom mirror at night with one bare bulb, in the cracked mirror the reflection shows a tall thin figure in a long dark coat standing close behind the viewer, face hidden in shadow, who is not in the real room",
    },
}


def enabled() -> list[str]:
    try:
        off = set(json.loads(DISABLED.read_text(encoding="utf-8")).get("disabled", []))
    except (OSError, json.JSONDecodeError):
        off = set()
    return [k for k in STYLES if k not in off]


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def pick_style(seed_text: str = "", remember: bool = True) -> str:
    """The least recently used enabled style, ties broken by a seed (so the same episode gets the same style if asked twice). Never the previous one."""
    keys = enabled() or list(STYLES)
    st = _state(); last = st.get("history", [])
    rng = random.Random(zlib.crc32(seed_text.encode()))
    recent = last[-len(keys) + 1:] if len(keys) > 1 else []
    pool = [k for k in keys if k not in recent] or [k for k in keys if k != (last[-1] if last else None)] or keys
    choice = rng.choice(pool)
    if remember:
        st["history"] = (last + [choice])[-40:]
        DATA.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(st), encoding="utf-8")
    return choice


CORE_RULES = """PICTURES - the fear comes from what you almost see. This episode's look is: {name}. These are PHOTOGRAPHS / FOOTAGE, never illustrations, and NEVER a portrait of a person facing the camera.
Shot ideas in this look (use a different one for every scene): {shots}.
Order: scene 1 (the poster) = wide and dark, a faint shape far away, a large empty dark area at the top for the title. Scenes 2-4: the entity absent or tiny, only signs of it. Scenes 5-6: far away,
partly hidden. Scene 7: closer than before, still mostly dark. Scene 8: the entity very close but in darkness, lit by ONE light, partly out of focus - never a bright, sharp, full-body close-up, never touching anyone.
Every prompt: ONE strong light source, 40 words max, photorealistic, ending with {{style}}. Describe the entity ONLY with traits from the article and repeat its key physical traits in every prompt that shows it
(the picture model forgets). "entity_look" = 25 words: shape, skin, face (hidden or not), size, what is wrong with it. "hero_look" = hair colour and a dark Foundation jacket, 12 words, no face.
Use {{Hero}} only for the back of a head ("the back of {{Hero}}"), and only if the look has people in it.
"""


def rules_text(key: str) -> str:
    s = STYLES[key]
    return CORE_RULES.format(name=s["name"], shots=s["shots"])


def style_string(key: str) -> str:
    return STYLES[key]["style"]
