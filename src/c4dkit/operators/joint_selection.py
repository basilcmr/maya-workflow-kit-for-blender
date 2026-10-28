# SPDX-License-Identifier: GPL-3.0-or-later
"""Bridge Maya joint objects to Blender pose bones without a manual mode switch."""

import bpy
import numpy as np

from .. import compat
from .preselect import project, segment_distance


def clear(context):
    """Clear latent bone selections too, so reselecting a rig cannot revive them."""
    from ..ui.channel_box import set_bone_selected
    for ob in context.view_layer.objects:
        if ob is None or ob.type != 'ARMATURE':
            continue
        if ob.mode == 'EDIT':
            for bone in ob.data.edit_bones:
                bone.select = bone.select_head = bone.select_tail = False
            ob.data.edit_bones.active = None
        for pb in ob.pose.bones:
            set_bone_selected(pb, False)
        ob.data.bones.active = None


def _collection_hidden(bone):
    return bool(bone.collections) and not any(c.is_visible_effectively for c in bone.collections)


def root_joints(ob):
    """Pose bones of the skeleton's top joints: shown bones with no shown ancestor, in bone order."""
    out = []
    for pb in ob.pose.bones:
        if compat.bone_hidden(pb) or _collection_hidden(pb.bone):
            continue
        up = pb.bone.parent
        while up is not None and (up.hide or _collection_hidden(up)):
            up = up.parent
        if up is None:
            out.append(pb)
    return out


def select_roots_if_empty(ob):
    """Maya: picking a skeleton picks its root joint (research/maya/re/maya2026_joints.md §4 - the Channel Box shows
    the root's channels, Select > All = every root, lead = the last). When the automatic Pose mode (decision 16) shows
    a rig with no shown bone selected, select its root joints, the last one active. True when it selected."""
    from ..ui.channel_box import bone_selected, set_bone_selected
    if ob is None or ob.type != 'ARMATURE' or ob.pose is None:
        return False
    if any(bone_selected(pb) and not compat.bone_hidden(pb) and not _collection_hidden(pb.bone)
           for pb in ob.pose.bones):
        return False
    roots = root_joints(ob)
    for pb in roots:
        set_bone_selected(pb, True)
    if roots:
        ob.data.bones.active = roots[-1].bone
    return bool(roots)


def pick(context, ob, mouse, radius):
    """Pick a visible, selectable joint, preferring its head over the connecting shaft."""
    from .select_priority import BONE_WIDTH, bone_width
    editing = ob.mode == 'EDIT'
    bones = ob.data.edit_bones if editing else ob.pose.bones
    candidates = []
    persp = np.asarray(context.region_data.perspective_matrix, dtype=np.float64)
    region = context.region
    for item in bones:
        bone = item if editing else item.bone
        hidden = bone.hide if editing else compat.bone_hidden(item)
        if (hidden or bone.hide_select or (bone.collections and
                not any(c.is_visible_effectively for c in bone.collections))):
            continue
        points = np.asarray([ob.matrix_world @ item.head, ob.matrix_world @ item.tail])
        screen, front = project(points, persp, region.width, region.height)
        if not all(front):
            continue
        distance, t = segment_distance(mouse, screen[:1], screen[1:])
        width = BONE_WIDTH * np.linalg.norm(screen[1] - screen[0]) if ob.data.display_type == 'OCTAHEDRAL' else 0
        shaft = max(0.0, float(distance[0] - bone_width(t, width)[0]))
        head = float(np.linalg.norm(screen[0] - mouse))
        if min(head, shaft) <= radius:
            candidates.append((head > radius, head if head <= radius else shaft, item.name))
    return min(candidates)[2] if candidates else None


def select(context, ob, name, shift=False, ctrl=False):
    """Maya replace / toggle / subtract / add on individual joints."""
    from ..ui.channel_box import bone_selected, set_bone_selected
    pb = ob.pose.bones[name]
    selected = bone_selected(pb)
    remove = (ctrl and not shift) or (shift and not ctrl and selected)
    if remove:
        set_bone_selected(pb, False)
        if ob.data.bones.active == pb.bone:
            ob.data.bones.active = next((b.bone for b in ob.pose.bones if bone_selected(b)), None)
        if not any(bone_selected(b) for b in ob.pose.bones):
            if context.active_object == ob and ob.mode == 'POSE':
                bpy.ops.object.mode_set(mode='OBJECT')
            ob.select_set(False)
            if context.view_layer.objects.active == ob:
                context.view_layer.objects.active = next(iter(context.selected_objects), None)
        return False
    if context.mode != 'OBJECT' and context.active_object != ob:
        bpy.ops.object.mode_set(mode='OBJECT')
    if not shift and not ctrl:
        clear(context)
        for other in context.selected_objects:
            if other != ob:
                other.select_set(False)
    ob.select_set(True)
    context.view_layer.objects.active = ob
    if ob.mode != 'POSE':
        bpy.ops.object.mode_set(mode='POSE')
    set_bone_selected(ob.pose.bones[name], True)
    ob.data.bones.active = ob.data.bones[name]
    return True


def leave(context, clear_selection=False):
    if clear_selection:
        clear(context)
    if context.mode != 'OBJECT' and context.active_object is not None:
        bpy.ops.object.mode_set(mode='OBJECT')


def select_object_at(context, mouse, shift=False, ctrl=False):
    """Native object picking after releasing Blender's pose/edit selection lock."""
    leave(context, clear_selection=not (shift or ctrl))
    result = bpy.ops.view3d.select(location=tuple(map(int, mouse)),
                                  deselect_all=not (shift or ctrl),
                                  toggle=shift and not ctrl,
                                  deselect=ctrl and not shift,
                                  extend=shift and ctrl)
    if not context.selected_objects:
        context.view_layer.objects.active = None
    return result
