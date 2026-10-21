"""
blender_runner.py - executed INSIDE Blender by blender_video.py:
    blender -b -P blender_runner.py -- <scene_script.py> <timing.json> <out_dir> [--stills 3,10,20] [--low]
Loads the scene script (it must define build(t)), builds the scene with the narration timings, then renders either the
whole animation as PNG frames or just a few still frames (a quick look before the long render).
"""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402

import blender_kit as k  # noqa: E402

a = k.args()
script, timing_file, out_dir = a[0], a[1], a[2]
stills = [float(x) for x in a[a.index("--stills") + 1].split(",")] if "--stills" in a else []
t = json.load(open(timing_file))["scenes"]
spec = importlib.util.spec_from_file_location("scene_script", script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.build(t)
sc = bpy.context.scene
if "--low" in a:
    sc.render.resolution_x, sc.render.resolution_y = 360, 640
os.makedirs(out_dir, exist_ok=True)
total = t[-1][1]
if stills:
    sc.render.image_settings.file_format = "PNG"
    for s in stills:
        sc.frame_set(k.f(s))
        sc.render.filepath = os.path.join(out_dir, f"still_{s:05.1f}.png")
        bpy.ops.render.render(write_still=True)
    print("STILLS_DONE")
else:
    k.render_frames(out_dir, total)
    print("RENDER_DONE")
