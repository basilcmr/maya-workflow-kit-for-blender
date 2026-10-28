# SPDX-License-Identifier: GPL-3.0-or-later
"""Cinema 4D Viewport Navigation Operators.

Binds:
- '1' + LMB Drag -> Pan / Track 3D View
- '2' + LMB Drag -> Dolly / Zoom 3D View
- '3' + LMB Drag -> Tumble / Orbit 3D View
"""

import bpy


class C4DKIT_OT_nav_pan(bpy.types.Operator):
    """C4D Pan/Track View (Key 1 + LMB)"""
    bl_idname = "c4dkit.nav_pan"
    bl_label = "C4D Viewport Pan"
    bl_options = {'BLOCKING', 'GRAB_CURSOR'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            return bpy.ops.view3d.move('INVOKE_DEFAULT')
        return {'PASS_THROUGH'}


class C4DKIT_OT_nav_zoom(bpy.types.Operator):
    """C4D Zoom/Dolly View (Key 2 + LMB)"""
    bl_idname = "c4dkit.nav_zoom"
    bl_label = "C4D Viewport Zoom"
    bl_options = {'BLOCKING', 'GRAB_CURSOR'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            return bpy.ops.view3d.zoom('INVOKE_DEFAULT')
        return {'PASS_THROUGH'}


class C4DKIT_OT_nav_orbit(bpy.types.Operator):
    """C4D Orbit/Tumble View (Key 3 + LMB)"""
    bl_idname = "c4dkit.nav_orbit"
    bl_label = "C4D Viewport Orbit"
    bl_options = {'BLOCKING', 'GRAB_CURSOR'}

    def invoke(self, context, event):
        if context.space_data.type == 'VIEW_3D':
            return bpy.ops.view3d.rotate('INVOKE_DEFAULT')
        return {'PASS_THROUGH'}


classes = (
    C4DKIT_OT_nav_pan,
    C4DKIT_OT_nav_zoom,
    C4DKIT_OT_nav_orbit,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

