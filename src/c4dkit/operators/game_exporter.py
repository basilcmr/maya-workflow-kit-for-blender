# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya File > Game Exporter (step 225, Issue #135; ATTACH_PLAN L24): the Model / Animation export window with
Maya's Animation Clips list, written with the kit's Maya FBX preset (operators/file_io.py, step 222 rig post-process).

Maya 2026 (mayapy, research/scripts/maya_anim225/game_exporter.py; ``$M/others/gameFbxExporter*.mel``):

- settings live on a ``gameFbxExporter`` node; factory values (createNode, ``FACTORY``): Export All, Model tab,
  one file, Bake Animation on, Skinning / Blend Shapes on, Smoothing Groups / Tangents and Binormals on, Triangulate /
  Move to Origin / Embed Media / Include Children / Input Connections off, Up Axis Y, Cameras / Lights on;
- a new clip (``gameExp_AddNewAnimationClip``) starts with the playback range, an empty name, export on; a typed name
  that exists gets the next number (``gameExp_ProvideUniqueName``: walk -> walk1, run09 -> run10);
- clips export as FBX takes (``FBXExportSplitAnimationIntoTakes`` name start end): **one file** = the file name
  (``.fbx`` added) with a take per exported clip; **a file per clip** = file name used as a prefix + clip name +
  ``.fbx`` (``gameExp_GenerateClipFilenameList``). Maya's files also carry the FBX plug-in's own ``Take 001`` and its
  per-clip loop never clears the take list, so a later clip file repeats the earlier clips' takes (measured) — the
  kit writes only the clip's own takes (delegated: engines would import those extra clips).

Blender: a take = an NLA strip in the FBX writer (``bake_anim_use_nla_strips``); the kit adds a temporary track per
clip on every animated object (strip = the object's action over the clip range), writes, then removes them, and
merges takes of the same name written by several objects into one take and moves each take to the clip's own
frames (``finalize_takes``).
"""

import os
import re

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, \
    StringProperty

from .. import results

TRACK = "allset_game_clip"

FACTORY = {"export_type": 'MODEL', "export_set": 'ALL', "model_file_mode": 'SINGLE', "file_split": 'SINGLE',
           "bake_animation": True, "skinning": True, "blendshapes": True, "smoothing_groups": True,
           "tangents": True, "triangulate": False, "move_to_origin": False, "embed_media": False,
           "include_children": False, "input_connections": False, "up_axis": 'Y', "include_cameras": True,
           "include_lights": True}


class ALLSET_PG_game_clip(bpy.types.PropertyGroup):
    name: StringProperty(name="Clip Name")
    start: FloatProperty(name="Start", default=1.0)
    end: FloatProperty(name="End", default=24.0)
    export: BoolProperty(name="Export", default=True)


class ALLSET_PG_game_exporter(bpy.types.PropertyGroup):
    export_type: EnumProperty(name="Export", items=[('MODEL', "Model", "Export the models (no animation)"),
                                                  ('ANIMATION', "Animation Clips", "Export the animation clips")],
                              default='MODEL')
    export_set: EnumProperty(name="Export", items=[('ALL', "Export All", ""), ('SELECTION', "Export Selection", "")],
                             default='ALL')
    model_file_mode: EnumProperty(name="File Type", items=[('SINGLE', "Single File", ""),
                                                          ('PER_ROOT', "Multiple Files", "A file per root object")],
                                  default='SINGLE')
    file_split: EnumProperty(name="File Type", items=[('SINGLE', "Multiple Clips to Single File", ""),
                                                     ('PER_CLIP', "Clips to Multiple Files", "")], default='SINGLE')
    clips: CollectionProperty(type=ALLSET_PG_game_clip)
    clip_index: IntProperty(default=0)
    bake_animation: BoolProperty(name="Bake Animation", default=True)
    skinning: BoolProperty(name="Skinning", default=True)
    blendshapes: BoolProperty(name="Blend Shapes", default=True)
    smoothing_groups: BoolProperty(name="Smoothing Groups", default=True)
    tangents: BoolProperty(name="Tangents and Binormals", default=True)
    triangulate: BoolProperty(name="Triangulate", default=False)
    move_to_origin: BoolProperty(name="Move to Origin", default=False)
    embed_media: BoolProperty(name="Embed Media", default=False)
    include_children: BoolProperty(name="Include Children", default=False)
    input_connections: BoolProperty(name="Input Connections", default=False)
    up_axis: EnumProperty(name="Up Axis", items=[('Y', "Y", ""), ('Z', "Z", "")], default='Y')
    include_cameras: BoolProperty(name="Cameras", default=True)
    include_lights: BoolProperty(name="Lights", default=True)
    export_path: StringProperty(name="Path", subtype='DIR_PATH')
    export_filename: StringProperty(name="File Name")


def settings(context):
    return context.scene.allset_game_exporter


# --- clips -------------------------------------------------------------------------------------------------------

def playback_range(scene):
    """Maya's playback range = the kit's preview range when it is on, else the scene range (step 20)."""
    if scene.use_preview_range:
        return float(scene.frame_preview_start), float(scene.frame_preview_end)
    return float(scene.frame_start), float(scene.frame_end)


def add_clip(scene):
    s = scene.allset_game_exporter
    clip = s.clips.add()
    clip.name = ""
    clip.start, clip.end = playback_range(scene)
    clip.export = True
    s.clip_index = len(s.clips) - 1
    return clip


def unique_name(name, taken):
    """Maya gameExp_ProvideUniqueName: count up a trailing number (keeping its zeros), else append 1."""
    while name in taken:
        m = re.search(r"\d+$", name)
        if m:
            digits = m.group(0)
            number = int(digits) + 1
            width = len(digits) if len(str(number)) <= len(digits) else len(str(number))
            name = name[:m.start()] + str(number).zfill(width)
        else:
            name = name + "1"
    return name


def clip_files(s, folder):
    """[(path, [clips])] Maya writes for the exported clips (gameExp_GenerateClipFilenameList)."""
    clips = [c for c in s.clips if c.export]
    stem = s.export_filename
    if s.file_split == 'SINGLE':
        name = stem if os.path.splitext(stem)[1] else stem + ".fbx"
        return [(os.path.join(folder, name), clips)] if clips and stem else []
    base = stem[:-4] if stem.lower().endswith(".fbx") else stem
    out = []
    for c in clips:
        name = base + c.name
        out.append((os.path.join(folder, name if os.path.splitext(name)[1] else name + ".fbx"), [c]))
    return out


def model_files(s, folder, roots):
    stem = s.export_filename
    if s.model_file_mode == 'SINGLE':
        return [(os.path.join(folder, stem if os.path.splitext(stem)[1] else stem + ".fbx"), roots)] if stem else []
    base = stem[:-4] if stem.lower().endswith(".fbx") else stem
    return [(os.path.join(folder, base + r.name + ".fbx"), [r]) for r in roots]


# --- FBX ---------------------------------------------------------------------------------------------------------

def fbx_args(context, s, selection):
    from . import file_io, units
    _op, args = file_io.export_args('FBX', units.maya_unit(context.scene), selection)
    types = {'MESH', 'EMPTY', 'OTHER'}
    if s.skinning:
        types.add('ARMATURE')
    if s.include_cameras:
        types.add('CAMERA')
    if s.include_lights:
        types.add('LIGHT')
    args.update(object_types=types, mesh_smooth_type='FACE' if s.smoothing_groups else 'OFF',
                use_tspace=s.tangents, use_triangles=s.triangulate,
                axis_up=s.up_axis, axis_forward='-Z' if s.up_axis == 'Y' else 'Y')
    if s.embed_media:
        args.update(embed_textures=True, path_mode='COPY')
    return args


KTIME = 46186158000            # FBX ticks per second


def finalize_takes(path, clips, fps):
    """Maya's takes from Blender's: one take per clip name and Maya's clip times.

    Blender's writer makes a take per NLA strip, so a clip on two objects gives two takes of the same name (with the
    same ids: the elements are written twice) — they become one; and it starts every take at time 0 while Maya writes
    the clip's own frames (frame f = f / fps seconds, game_exporter.json: walk 1-10, run 11-24), so each take's keys and
    LocalTime / ReferenceTime move by the clip start. Returns the take names in order."""
    from . import fbx_rig
    tree, version = fbx_rig.load(path)
    objects = tree.first(b"Objects")
    conns = tree.first(b"Connections")
    seen, elems = set(), []
    for e in objects.elems:                       # the same take written twice: keep one copy
        if e.id in (b"AnimationStack", b"AnimationLayer"):
            if e.props[0] in seen:
                continue
            seen.add(e.props[0])
        elems.append(e)
    objects.elems = elems
    seen_c, keep_c = set(), []
    for c in conns.elems:
        key = tuple(c.props)
        if key in seen_c:
            continue
        seen_c.add(key)
        keep_c.append(c)
    conns.elems = keep_c
    stacks = objects.find(b"AnimationStack")
    stack_ids = {st.props[0]: st for st in stacks}
    layer_stack = {c.props[1]: c.props[2] for c in conns.elems if c.props[0] == b"OO" and c.props[2] in stack_ids}
    node_layer = {c.props[1]: c.props[2] for c in conns.elems if c.props[0] == b"OO" and c.props[2] in layer_stack}
    curve_node = {c.props[1]: c.props[2] for c in conns.elems if c.props[0] in (b"OO", b"OP")
                  and c.props[2] in node_layer}
    by_name = {c.name: c for c in clips}
    offsets = {}
    for st in stacks:
        clip = by_name.get(fbx_rig.name_of(st))
        if clip is None:
            continue
        off = int(round(clip.start / fps * KTIME))
        offsets[st.props[0]] = off
        p70 = fbx_rig._p70(st)
        props = {p.props[0]: p for p in p70.elems if p.props}
        stop = int(props[b"LocalStop"].props[4]) if b"LocalStop" in props else 0
        for name, value in ((b"LocalStart", off), (b"LocalStop", stop + off), (b"ReferenceStart", off),
                            (b"ReferenceStop", stop + off)):
            if name in props:
                props[name].props[4] = value
            else:
                p70.elems.append(fbx_rig.Elem(b"P", [name, b"KTime", b"Time", b"", value], b"SSSSL"))
    import array
    for e in objects.find(b"AnimationCurve"):
        node = curve_node.get(e.props[0])
        st = layer_stack.get(node_layer.get(node)) if node is not None else None
        off = offsets.get(st)
        kt = e.first(b"KeyTime")
        if off and kt is not None:
            kt.props[0] = array.array('q', [t + off for t in kt.props[0]])
    takes = tree.first(b"Takes")
    if takes is not None:
        names, keep = set(), []
        for t in takes.elems:
            if t.id == b"Take":
                nm = t.props[0].decode("utf-8", "replace") if isinstance(t.props[0], bytes) else t.props[0]
                if nm in names:
                    continue
                names.add(nm)
                clip = by_name.get(nm)
                if clip is not None:
                    off = int(round(clip.start / fps * KTIME))
                    for sub in t.elems:
                        if sub.id in (b"LocalTime", b"ReferenceTime"):
                            sub.props = [sub.props[0] + off, sub.props[1] + off]
            keep.append(t)
        takes.elems = keep
    fbx_rig.save(path, tree, version)
    out = []
    for st in stacks:
        if fbx_rig.name_of(st) not in out:
            out.append(fbx_rig.name_of(st))
    return out


class _Clips:
    """Temporary NLA tracks: a strip per clip on every animated object (the writer's takes)."""

    def __init__(self, obs, clips):
        self.obs = [o for o in obs if o.animation_data is not None and o.animation_data.action is not None]
        self.clips = clips
        self.made = []

    def __enter__(self):
        for ob in self.obs:
            ad = ob.animation_data
            action = ad.action
            for c in self.clips:
                track = ad.nla_tracks.new()
                track.name = TRACK
                strip = track.strips.new(c.name or "clip", int(round(c.start)), action)
                strip.name = c.name or "clip"
                strip.action_frame_start, strip.action_frame_end = c.start, c.end
                strip.frame_start, strip.frame_end = c.start, c.end
                self.made.append((ob, track))
        return self

    def __exit__(self, *exc):
        for ob, track in self.made:
            ad = ob.animation_data
            if ad is not None and track.name in ad.nla_tracks:
                ad.nla_tracks.remove(track)


def export(context, s):
    """Write the files; returns [(path, take names)]."""
    from . import file_io, dag, units
    folder = bpy.path.abspath(s.export_path) or ""
    if not folder:
        raise ValueError("The file path is empty")            # Maya kGameExporterFilePathEmpty
    if not os.path.isdir(folder):
        raise ValueError(f"The directory doesn't exist: {folder}")
    selection = s.export_set == 'SELECTION'
    view_layer = context.view_layer
    obs = list(context.selected_objects) if selection else [o for o in context.scene.objects
                                                            if o.name in view_layer.objects]
    if selection and not obs:
        raise ValueError("Nothing selected to export.")
    k = units.maya_unit(context.scene)
    run = bpy.ops.export_scene.fbx
    out = []
    if s.export_type == 'ANIMATION':
        files = clip_files(s, folder)
        if not files:
            raise ValueError("The file name is empty or no clip is checked for export")
        names = [c.name for c in s.clips if c.export]
        if any(not n for n in names) or len(set(names)) != len(names):
            raise ValueError("Every exported clip needs a unique name")
        for path, clips in files:
            args = dict(fbx_args(context, s, selection), bake_anim=True, bake_anim_use_nla_strips=True,
                        bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True)
            with _Clips(obs, clips):
                if selection and s.include_children:
                    with dag.selected_hierarchy(context):
                        file_io.write(context, 'FBX', path, "export_scene.fbx", args, True, k)
                else:
                    file_io.write(context, 'FBX', path, "export_scene.fbx", args, True, k)
            fps = context.scene.render.fps / (context.scene.render.fps_base or 1.0)
            out.append((path, finalize_takes(path, clips, fps)))
        return out
    roots = [o for o in obs if o.parent is None or o.parent not in obs]
    files = model_files(s, folder, roots)
    if not files:
        raise ValueError("The file name is empty")               # Maya kGameExporterFilenameEmpty
    for path, part in files:
        args = dict(fbx_args(context, s, True), bake_anim=False)
        keep = list(context.selected_objects)
        try:
            for o in context.selected_objects:
                o.select_set(False)
            for r in part:
                for o in [r, *r.children_recursive]:
                    if o in obs and o.name in view_layer.objects:
                        o.select_set(True)
            file_io.write(context, 'FBX', path, "export_scene.fbx", args, True, k)
        finally:
            for o in context.selected_objects:
                o.select_set(False)
            for o in keep:
                o.select_set(True)
        out.append((path, []))
    return out


# --- window ------------------------------------------------------------------------------------------------------

class ALLSET_UL_game_clips(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index=0):
        row = layout.row(align=True)
        row.prop(item, "export", text="")
        row.prop(item, "name", text="", emboss=True, placeholder="Clip Name")
        row.prop(item, "start", text="")
        row.prop(item, "end", text="")


class ALLSET_OT_game_clip(bpy.types.Operator):
    """Add a clip with the playback range, or delete the picked clip"""
    bl_idname = "allset.game_clip"
    bl_label = "Animation Clip"
    bl_options = {'INTERNAL', 'UNDO'}

    action: EnumProperty(items=[('ADD', "Add", ""), ('REMOVE', "Delete", "")], options={'SKIP_SAVE'})

    def execute(self, context):
        s = settings(context)
        if self.action == 'ADD':
            add_clip(context.scene)
        elif 0 <= s.clip_index < len(s.clips):
            s.clips.remove(s.clip_index)
            s.clip_index = max(0, min(s.clip_index, len(s.clips) - 1))
        return {'FINISHED'}


class ALLSET_OT_game_exporter(bpy.types.Operator):
    """Maya Game Exporter: export models or animation clips (one FBX take per clip) for a game engine"""
    bl_idname = "allset.game_exporter"
    bl_label = "Game Exporter"
    bl_options = {'UNDO'}

    def invoke(self, context, event):
        s = settings(context)
        if not s.export_path:
            from . import project
            s.export_path = project.current_root(context)
        return context.window_manager.invoke_props_dialog(self, width=560, title="Game Exporter",
                                                          confirm_text="Export")

    def draw(self, context):
        s = settings(context)
        layout = self.layout
        layout.row().prop(s, "export_type", expand=True)
        box = layout.box()
        box.row().prop(s, "export_set", expand=True)
        if s.export_type == 'MODEL':
            box.row().prop(s, "model_file_mode", expand=True)
        else:
            box.label(text="Animation Clips")
            row = box.row()
            row.template_list("ALLSET_UL_game_clips", "", s, "clips", s, "clip_index", rows=4)
            col = row.column(align=True)
            col.operator("allset.game_clip", text="", icon='ADD').action = 'ADD'
            col.operator("allset.game_clip", text="", icon='REMOVE').action = 'REMOVE'
            box.row().prop(s, "file_split", expand=True)
            box.prop(s, "bake_animation")
        col = layout.box().column(align=True)
        col.label(text="Export Settings")
        grid = col.grid_flow(columns=2, align=True)
        for name in ("skinning", "blendshapes", "smoothing_groups", "tangents", "triangulate", "move_to_origin",
                     "embed_media", "include_children", "include_cameras", "include_lights"):
            sub = grid.row()
            sub.enabled = name not in {"blendshapes", "move_to_origin"}
            sub.prop(s, name)
        col.row().prop(s, "up_axis", expand=True)
        box = layout.box()
        box.label(text="Path")
        box.prop(s, "export_path")
        box.prop(s, "export_filename")
        folder = bpy.path.abspath(s.export_path)
        files = clip_files(s, folder) if s.export_type == 'ANIMATION' else []
        for path, clips in files[:4]:
            box.label(text=os.path.basename(path) + ("   " + ", ".join(c.name for c in clips) if clips else ""),
                      icon='FILE')

    def execute(self, context):
        try:
            done = export(context, settings(context))
        except (ValueError, RuntimeError) as ex:
            self.report({'ERROR'}, str(ex).strip().splitlines()[-1])
            return {'CANCELLED'}
        results.result(self, "Exported " + ", ".join(os.path.basename(p) for p, _t in done))
        return {'FINISHED'}


classes = (ALLSET_PG_game_clip, ALLSET_PG_game_exporter, ALLSET_UL_game_clips, ALLSET_OT_game_clip,
           ALLSET_OT_game_exporter)


def register_props():
    bpy.types.Scene.allset_game_exporter = PointerProperty(type=ALLSET_PG_game_exporter)


def unregister_props():
    del bpy.types.Scene.allset_game_exporter
