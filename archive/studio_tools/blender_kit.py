"""
blender_kit.py
Small helper library that scene scripts use INSIDE Blender (it imports bpy, so it only runs under `blender -b -P`).
It turns "make a clean 3D explainer scene" into a few readable calls, so the scene scripts - written by hand or by Claude -
stay short and hard to get wrong. blender_video.py runs the scripts and assembles the finished video.

A scene script looks like:

    import blender_kit as k
    def build(t):                 # t = [(start_s, end_s), ...] one entry per narration scene
        k.reset(sky=(0.55, 0.75, 0.95))
        ground = k.disc(radius=400, color=(0.3, 0.5, 0.25))
        k.camera_path([(0, (5, -8, 2), (0, 0, 2)), (t[-1][1], (5, -8, 90), (0, 0, 80))])
"""

import math
import sys

import bpy
from mathutils import Vector

FPS = 30
CAPTION_SHIFT = -0.045    # negative = the picture moves up in frame, leaving a clear band at the bottom for captions
_mats = {}
_state = {"fps": FPS, "cam": None, "target": None, "world_node": None}


def args() -> list[str]:
    """Arguments after `--` on the blender command line."""
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def reset(sky=(0.55, 0.75, 0.95), width=720, height=1280, fps=FPS, samples=24, strength=1.0):
    """Empty scene with sensible, clean render settings (soft EEVEE look, true colors)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    _state["fps"] = fps
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = width, height, 100
    sc.render.fps = fps
    for attr, val in (("taa_render_samples", samples),):
        try:
            setattr(sc.eevee, attr, val)
        except Exception:
            pass
    try:
        sc.view_settings.view_transform = "Standard"
    except Exception:
        pass
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*sky, 1)
    bg.inputs[1].default_value = strength
    sc.world = world
    _state["world_node"] = bg
    sc.render.film_transparent = False
    sun(strength=2.0)
    return sc


import contextlib


def _interp(kind: str):
    """New keyframes use this interpolation (CONSTANT = hold until the next key, used for hard cuts)."""
    bpy.context.preferences.edit.keyframe_new_interpolation_type = kind


def _key_cam_pos(seconds, cam_loc, look_at, cut_after=False):
    cam, target = _state["cam"], _state["target"]
    _interp("CONSTANT" if cut_after else "BEZIER")
    cam.location, target.location = cam_loc, look_at
    cam.keyframe_insert("location", frame=f(seconds))
    target.keyframe_insert("location", frame=f(seconds))
    _interp("BEZIER")


@contextlib.contextmanager
def shot(span, cam, cam_end=None, look=(0, 0, 0), look_end=None, sky=None, lens=35, last=False):
    """One composed shot lasting span=(start_s, end_s). Everything created inside the `with` block exists only during the
    shot (hard cut in, hard cut out). The camera goes from `cam` to `cam_end` (smoothly) looking at `look` -> `look_end`.
    sky=(r, g, b) sets the background for the shot. Build every shot at a scale where its subject is clearly visible."""
    start, end = span
    if _state["cam"] is None:
        _make_camera(lens)
    before = set(bpy.data.objects.keys())
    yield
    new = [bpy.data.objects[n] for n in bpy.data.objects.keys() if n not in before]
    _interp("CONSTANT")
    for o in new:
        for prop in ("hide_render", "hide_viewport"):
            setattr(o, prop, True)
            o.keyframe_insert(prop, frame=1)
            setattr(o, prop, False)
            o.keyframe_insert(prop, frame=f(start))
            setattr(o, prop, True)
            o.keyframe_insert(prop, frame=f(end) - 1 if not last else f(end) + 5)
    if sky is not None:         # held (constant) so the colour doesn't drift between shots
        bg = _state["world_node"]
        bg.inputs[0].default_value = (*sky, 1)
        bg.inputs[0].keyframe_insert("default_value", frame=f(start))
        bg.inputs[0].keyframe_insert("default_value", frame=f(end) - 1)      # hold the same colour to the end of the shot
    _interp("BEZIER")
    _state["cam"].data.lens = lens
    _key_cam_pos(start, cam, look)
    _key_cam_pos(end - 0.04, cam_end or cam, look_end or look, cut_after=True)


def _make_camera(lens=35, clip=(0.05, 2_000_000)):
    sc = bpy.context.scene
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    cam.data.lens = lens
    cam.data.clip_start, cam.data.clip_end = clip
    cam.data.shift_y = CAPTION_SHIFT      # lifts the whole scene up so the caption band at the bottom stays clear
    sc.camera = cam
    bpy.ops.object.empty_add(type="PLAIN_AXES")
    target = bpy.context.object
    tr = cam.constraints.new("TRACK_TO")
    tr.target, tr.track_axis, tr.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    _state["cam"], _state["target"] = cam, target


def earth(radius=6371, loc=(0, 0, 0)):
    return sphere(radius, loc, (0.15, 0.4, 0.75), 0.8)


def f(seconds: float) -> int:
    return int(round(seconds * _state["fps"])) + 1


def sky_keys(keys):
    """keys = [(seconds, (r, g, b)), ...] - the background colour over time (e.g. blue sky -> black space)."""
    bg = _state["world_node"]
    for s, col in keys:
        bg.inputs[0].default_value = (*col, 1)
        bg.inputs[0].keyframe_insert("default_value", frame=f(s))


def mat(color, rough=0.55, metallic=0.0, emission=0.0):
    key = (tuple(round(c, 3) for c in color), rough, metallic, emission)
    if key not in _mats:
        m = bpy.data.materials.new(f"m{len(_mats)}")
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*color, 1)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metallic
        if emission:
            b.inputs["Emission Color"].default_value = (*color, 1)
            b.inputs["Emission Strength"].default_value = emission
        _mats[key] = m
    return _mats[key]


def _finish(obj, color, rough=0.55, emission=0.0, name=None):
    if name:
        obj.name = name
    obj.data.materials.append(mat(color, rough, emission=emission))
    return obj


def box(size=(1, 1, 1), loc=(0, 0, 0), color=(0.8, 0.8, 0.8), rough=0.55, name=None, emission=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.scale = size
    return _finish(o, color, rough, emission, name)


def cylinder(radius=1, height=1, loc=(0, 0, 0), color=(0.8, 0.8, 0.8), rough=0.55, name=None, verts=48, emission=0.0):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height, location=loc, vertices=verts)
    return _finish(bpy.context.object, color, rough, emission, name)


def disc(radius=10, loc=(0, 0, 0), color=(0.4, 0.6, 0.3), rough=0.9, name=None):
    return cylinder(radius, 0.02, loc, color, rough, name, verts=96)


def sphere(radius=1, loc=(0, 0, 0), color=(0.8, 0.8, 0.8), rough=0.5, name=None, emission=0.0):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=loc, segments=48, ring_count=24)
    o = bpy.context.object
    bpy.ops.object.shade_smooth()
    return _finish(o, color, rough, emission, name)


def cone(radius=1, height=1, loc=(0, 0, 0), color=(0.5, 0.5, 0.5), name=None):
    bpy.ops.mesh.primitive_cone_add(radius1=radius, radius2=0, depth=height, location=loc, vertices=6)
    return _finish(bpy.context.object, color, 0.9, 0.0, name)


def person(loc=(0, 0, 0), height=1.75, color=(0.95, 0.55, 0.2)):
    """A clean stylised figure (capsule body + round head), feet at loc."""
    body_h = height * 0.78
    bpy.ops.mesh.primitive_cylinder_add(radius=height * 0.12, depth=body_h, location=(loc[0], loc[1], loc[2] + body_h / 2), vertices=32)
    body = bpy.context.object
    bpy.ops.object.shade_smooth()
    body.data.materials.append(mat(color))
    head = sphere(height * 0.11, (loc[0], loc[1], loc[2] + body_h + height * 0.1), (0.96, 0.8, 0.66))
    head.parent = body
    head.matrix_parent_inverse = body.matrix_world.inverted()
    return body


def sun(strength=3.0, rotation=(0.9, 0.2, 0.7)):
    bpy.ops.object.light_add(type="SUN")
    s = bpy.context.object
    s.data.energy = strength
    s.rotation_euler = rotation
    try:
        s.data.angle = 0.08
    except Exception:
        pass
    return s


def text(label, size=1.0, loc=(0, 0, 0), color=(1, 1, 1), face_camera=True, align="CENTER", extrude=0.0):
    """Floating 3D text. Emissive so it stays readable against any sky; faces the camera when asked."""
    bpy.ops.object.text_add(location=loc)
    o = bpy.context.object
    o.data.body = label
    o.data.size = size
    o.data.align_x = align
    o.data.extrude = extrude
    o.data.materials.append(mat(color, 0.5, emission=1.0))
    if face_camera and _state["cam"] is not None:
        c = o.constraints.new("COPY_ROTATION")
        c.target = _state["cam"]
    return o


def ring(radius, loc=(0, 0, 0), thickness=0.05, color=(1, 1, 1), emission=1.0):
    bpy.ops.mesh.primitive_torus_add(major_radius=radius, minor_radius=thickness, location=loc, major_segments=96, minor_segments=12)
    return _finish(bpy.context.object, color, 0.4, emission)


def camera_path(keys, lens=35, clip=(0.05, 2_000_000), ease=True):
    """keys = [(seconds, (x, y, z) camera, (x, y, z) look-at), ...]. The camera always looks at an animated target,
    and moves smoothly (ease in/out) between keys."""
    sc = bpy.context.scene
    bpy.ops.object.camera_add()
    cam = bpy.context.object
    cam.data.lens = lens
    cam.data.clip_start, cam.data.clip_end = clip
    sc.camera = cam
    bpy.ops.object.empty_add(type="PLAIN_AXES")
    target = bpy.context.object
    tr = cam.constraints.new("TRACK_TO")
    tr.target, tr.track_axis, tr.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
    for s, cp, tp in keys:
        cam.location, target.location = cp, tp
        cam.keyframe_insert("location", frame=f(s))
        target.keyframe_insert("location", frame=f(s))
    if ease:
        for ob in (cam, target):
            for fc in (ob.animation_data.action.fcurves if hasattr(ob.animation_data.action, "fcurves") else []):
                for kp in fc.keyframe_points:
                    kp.interpolation = "BEZIER"
    _state["cam"], _state["target"] = cam, target
    return cam, target


def animate(obj, seconds_values, prop="location"):
    """seconds_values = [(seconds, value), ...] for location / scale / rotation_euler."""
    for s, v in seconds_values:
        setattr(obj, prop, v)
        obj.keyframe_insert(prop, frame=f(s))


def set_range(seconds: float):
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, f(seconds)


def render_frames(out_dir: str, seconds: float, first: int | None = None, last: int | None = None):
    """Writes PNG frames out_dir/f0001.png ... (optionally only a frame range, for quick previews)."""
    sc = bpy.context.scene
    set_range(seconds)
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = f"{out_dir}/f"
    if first or last:
        sc.frame_start, sc.frame_end = first or 1, last or sc.frame_end
    bpy.ops.render.render(animation=True)
