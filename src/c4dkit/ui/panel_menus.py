# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya viewport panel menu bar: View, Shading, Lighting, Show, Renderer, Panels.

Every Maya modelPanel has its own menu bar (research/maya/ui_layout.md:242-244). Menu contents
follow Maya 2022 ``createModelPanelMenu.mel`` (View :1381-1640, Shading :2159-2290, Lighting
:2488-2522, Show :2578-2741, Renderer :509-664) and ``buildPanelPopupMenu.mel:273-427``
(Panels); re-implemented, only labels and order. Design: docs/steps/step_37.md 「계획」.

Only the menu part of the 3D View header changes: ``VIEW3D_MT_editor_menus.draw_collapsible``
(inherited from ``bpy.types.Menu``, called once by ``VIEW3D_HT_header.draw``,
$S\\startup\\bl_ui\\space_view3d.py:915) is overridden while the add-on is enabled; the
mode selector and the right-hand buttons (Maya's panel icon bar) stay Blender's. Blender's
View / Select / Add / Object ... menus stay reachable under 「Blender ▸」.

Item forms (one tuple per row):
``("prop", owner, prop, label)`` check box on ``space`` / ``shading`` / ``overlay``;
``("set", key, label)`` ``allset.panel_set`` (radio / toggle state from ``state``);
``("run", label, op, props)`` an operator run in this view's main region;
``("menu", label, idname)``; ``("grey", label)`` no Blender equivalent; ``("sep", label)``.
"""

import json

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ..operators import view as view_ops

GREY_OP = "allset.menu_unavailable"


# Row tables live in panel_menu_data (bpy-free: menu_count / menu_consistency / notice rules walk them, step 177).
from .panel_menu_data import (_sep, _grey, _run, _tool, _view, VIEW, VIEW_AXIS, CAMERA_TOOLS, SHADING, LIGHTING, SHOW_TYPES, ALL_TYPES,
                              _show_row, SHOW, ISOLATE, RENDERER, PANELS, PANEL_TYPES, LAYOUTS, BAR, item_path)  # noqa: F401


# --- state ---------------------------------------------------------------------------

def _space(context):
    space = context.space_data
    return space if space is not None and space.type == 'VIEW_3D' else None


def _owner(space, context, owner):
    return {"space": space, "shading": space.shading, "overlay": space.overlay}[owner]


def _scene_camera_view(context):
    rv3d = context.region_data or getattr(_space(context), "region_3d", None)
    return rv3d is not None and rv3d.view_perspective == 'CAMERA'


def view_camera(context):
    """The object this view looks through (None: Blender's persp / ortho view, which has no camera object)."""
    space = _space(context)
    if space is None or not _scene_camera_view(context):
        return None
    if space.use_local_camera and space.camera is not None:
        return space.camera
    return context.scene.camera


def camera_locked(ob):
    """Maya Lock Camera (camera -lockTransform): the kit locks the camera's location and rotation channels;
    Blender's camera-view navigation keeps locked channels (measured, step 129)."""
    return all(ob.lock_location) and all(ob.lock_rotation)


# Maya camera display toggles (updateModelPanelBar.mel modelPanelBarDecorationsCallback) -> Blender camera data.
# Blender draws title and action safe areas together (one flag).
CAMERA_DATA = {"FILM_GATE": "show_sensor", "GATE_MASK": "show_passepartout",
               "SAFE_ACTION": "show_safe_areas", "SAFE_TITLE": "show_safe_areas"}
CAMERA_KEYS = {"CAMERA_LOCK", *CAMERA_DATA}

# Toolbar toggles whose Maya off state is another mode (updateModelPanelBar.mel modelPanelBarShadingCallback):
# Wireframe off = smooth shaded, Smooth Shade All off = wireframe, Use All Lights off = default lighting.
TOGGLE_OFF = {"SHADE_WIRE": "SHADE_SMOOTH", "SHADE_SMOOTH": "SHADE_WIRE", "LIGHT_ALL": "LIGHT_DEFAULT"}

# Maya colour management icons (createColorManagementSection.mel: exposure / gamma icon = toggle between the
# default and the last other value, view transform check box = colour management on / off). Blender keeps these per
# scene (view settings); the last values live in Scene ID properties.
EXPOSURE_LAST, GAMMA_LAST, TRANSFORM_LAST = "allset_exposure_last", "allset_gamma_last", "allset_view_transform_last"
RAW = 'Raw'

FAILS = {
    "SELECT_CAMERA": "This view is not looking through a camera object (Blender's persp view has none)",
    "CAMERA_LOCK": "Look through a camera first (Panels > Perspective): Blender's persp view has no camera",
    "ISOLATE": "Select the objects to isolate",
}
for _k in CAMERA_DATA:
    FAILS[_k] = FAILS["CAMERA_LOCK"]

TIPS = {
    "TUMBLE_SELECTION": "Tumble around the selection: Blender's Orbit Around Selection preference "
                        "(opens Preferences > Navigation; the kit doesn't change preferences)",
    "TUMBLE_COI": "Tumble around the center of interest: Orbit Around Selection off "
                  "(opens Preferences > Navigation; the kit doesn't change preferences)",
    "SELECT_CAMERA": "Select camera: the camera this view looks through",
    "CAMERA_LOCK": "Lock Camera: the camera this view looks through can't be moved (Blender: its location and "
                   "rotation channels are locked)",
    "FILM_GATE": "Film gate (Blender: camera sensor frame)",
    "GATE_MASK": "Gate mask (Blender: passepartout)",
    "SAFE_ACTION": "Safe action (Blender draws the action and title safe areas together)",
    "SAFE_TITLE": "Safe title (Blender draws the action and title safe areas together)",
    "GRID": "Grid",
    "SHOW_IMAGE_PLANES": "Image planes (Blender image empties: shown or hidden in every view, like Alt+4)",
    "SHOW_IK_HANDLES": "IK handles (the empties IK constraints follow: shown or hidden in every view)",
    "SHADE_WIRE": "Wireframe",
    "SHADE_SMOOTH": "Smooth shade all",
    "DEFAULT_MATERIAL": "Use default material",
    "HW_TEXTURE": "Textured",
    "LIGHT_ALL": "Use all lights",
    "ISOLATE": "Isolate select",
    "EXPOSURE": "Exposure: switch between 0 and the last exposure",
    "GAMMA": "Gamma: switch between 1 and the last gamma",
    "CM_ENABLE": "Colour management on / off (off = Blender's Raw view transform)",
    "LAYOUT_FOUR": "Four View: top, persp, front and side. " + view_ops.FOUR_VIEW_NOTE,
}


SHOW_HIDDEN = "allset_hidden_by_show"   # IK handles the Show menu hid (view-layer hide; only these come back)


def show_ik_handles(context, on):
    """Maya Show > IK Handles (step 189): Blender has no view filter for these empties, so the kit hides them in
    the view layer (every view) and marks them; showing again un-hides only marked ones."""
    from ..operators import by_type
    for ob in by_type.ik_handles(context.scene):
        try:
            if on and ob.get(SHOW_HIDDEN):
                ob.hide_set(False)
                del ob[SHOW_HIDDEN]
            elif not on and not ob.hide_get():
                ob.hide_set(True)
                ob[SHOW_HIDDEN] = True
        except RuntimeError:       # not in the view layer
            pass


def state(context, key):
    """On/off of a ``set`` row (None: plain command)."""
    space = _space(context)
    if space is None:
        return None
    if key in CAMERA_KEYS:
        ob = view_camera(context)
        if ob is None:
            return False
        if key == "CAMERA_LOCK":
            return camera_locked(ob)
        return ob.type == 'CAMERA' and bool(getattr(ob.data, CAMERA_DATA[key]))
    if key == "ISOLATE":
        return space.local_view is not None
    if key == "CM_ENABLE":
        return context.scene.view_settings.view_transform != RAW
    sh = space.shading
    if key == "SHADE_WIRE":
        return sh.type == 'WIREFRAME'
    if key == "SHADE_SMOOTH":
        return sh.type != 'WIREFRAME'
    if key == "DEFAULT_MATERIAL":
        return sh.color_type == 'SINGLE'
    if key == "HW_TEXTURE":
        return sh.color_type == 'TEXTURE'
    if key == "LIGHT_DEFAULT":
        return sh.type in ('SOLID', 'WIREFRAME') and sh.light != 'FLAT'
    if key == "LIGHT_ALL":
        return (sh.type == 'MATERIAL' and sh.use_scene_lights) or \
            (sh.type == 'RENDERED' and sh.use_scene_lights_render)
    if key == "LIGHT_FLAT":
        return sh.type in ('SOLID', 'WIREFRAME') and sh.light == 'FLAT'
    if key == "RENDER_VP2":
        return sh.type != 'RENDERED'
    if key == "RENDER_ENGINE":
        return sh.type == 'RENDERED'
    if key == "TUMBLE_SELECTION":
        return context.preferences.inputs.use_rotate_around_active
    if key == "TUMBLE_COI":
        return not context.preferences.inputs.use_rotate_around_active
    if key == "GRID":
        from . import maya_grid
        return maya_grid.visible(space)
    if key == "SHOW_IMAGE_PLANES":
        from ..operators import global_keys4
        planes = global_keys4.image_planes(context.scene)
        return not planes or any(getattr(o, f) for o in planes for f in global_keys4.IMAGE_FLAGS)
    if key == "SHOW_IK_HANDLES":
        from ..operators import by_type
        return not any(o.get(SHOW_HIDDEN) for o in by_type.ik_handles(context.scene))
    if key == "LAYOUT_SINGLE":
        return not space.region_quadviews
    if key == "LAYOUT_FOUR":
        return bool(space.region_quadviews)
    return None


RADIO = {"SHADE_WIRE", "SHADE_SMOOTH", "LIGHT_DEFAULT", "LIGHT_ALL", "LIGHT_FLAT", "RENDER_VP2",
         "RENDER_ENGINE", "TUMBLE_SELECTION", "TUMBLE_COI", "LAYOUT_SINGLE", "LAYOUT_FOUR"}
SET_KEYS = [s[1] for menu in (VIEW, SHADING, LIGHTING, SHOW, RENDERER, LAYOUTS) for s in menu
            if s[0] == "set"]
# keys only the panel toolbar uses (ui/panel_toolbar.py)
TOOLBAR_KEYS = ["FILM_GATE", "GATE_MASK", "SAFE_ACTION", "SAFE_TITLE", "ISOLATE", "EXPOSURE", "GAMMA", "CM_ENABLE"]

# Shading / overlay values "Apply Current to All" copies (Maya: current panel's settings to all).
_COPY_SHADING = ("type", "light", "color_type", "show_xray", "show_backface_culling", "show_shadows",
                 "use_dof", "use_scene_lights", "use_scene_world")
_COPY_OVERLAY = ("show_wireframes", "show_xray_bone", "show_floor", "show_ortho_grid", "grid_lines", "show_text",
                 "show_outline_selected", "show_object_origins", "show_motion_paths")


def main_region(area):
    """The area's WINDOW region whose view is ``space.region_3d`` (quad views: the user view)."""
    space = area.spaces.active
    wins = [r for r in area.regions if r.type == 'WINDOW']
    rv3d = getattr(space, "region_3d", None)
    return next((r for r in wins if r.data == rv3d), wins[-1] if wins else None)


_before_render = {}   # 3D View space pointer -> shading type before Rendered (IPR / Renderer menu)


def enter_rendered(space):
    sh = space.shading
    if sh.type != 'RENDERED':
        _before_render[space.as_pointer()] = sh.type
        sh.type = 'RENDERED'


def leave_rendered(space):
    """Back to the shading the view had before Rendered (Maya: stopping IPR keeps the panel's mode, #24)."""
    sh = space.shading
    if sh.type == 'RENDERED':
        sh.type = _before_render.pop(space.as_pointer(), 'SOLID')


def apply(context, key):
    space = _space(context)
    if space is None:
        return False
    sh = space.shading
    if key == "SHADE_WIRE":
        sh.type = 'WIREFRAME'
    elif key == "SHADE_SMOOTH":
        sh.type = 'SOLID'
    elif key == "DEFAULT_MATERIAL":
        sh.color_type = 'MATERIAL' if sh.color_type == 'SINGLE' else 'SINGLE'
    elif key == "HW_TEXTURE":
        sh.color_type = 'MATERIAL' if sh.color_type == 'TEXTURE' else 'TEXTURE'
    elif key == "LIGHT_DEFAULT":
        if sh.type not in ('SOLID', 'WIREFRAME'):
            sh.type = 'SOLID'
        sh.light = 'STUDIO'
    elif key == "LIGHT_ALL":
        sh.type = 'MATERIAL'
        sh.use_scene_lights = True
        sh.use_scene_world = False
    elif key == "LIGHT_FLAT":
        if sh.type not in ('SOLID', 'WIREFRAME'):
            sh.type = 'SOLID'
        sh.light = 'FLAT'
    elif key == "RENDER_VP2":
        leave_rendered(space)
    elif key == "RENDER_ENGINE":
        enter_rendered(space)
    elif key in ("TUMBLE_SELECTION", "TUMBLE_COI"):
        # Blender's Orbit Around Selection is a user preference, which the kit never writes (step 130,
        # docs/user_decisions.md #13): the items show it and open Preferences > Navigation to change it.
        try:
            bpy.ops.screen.userpref_show('INVOKE_DEFAULT', section='NAVIGATION')
        except RuntimeError:      # no window (background)
            return False
    elif key == "GRID":
        from . import maya_grid
        maya_grid.toggle(space)
    elif key == "SHOW_IMAGE_PLANES":
        from ..operators import global_keys4
        global_keys4.toggle_show(space, context.scene, 'IMAGE_PLANES')
    elif key == "SHOW_IK_HANDLES":
        show_ik_handles(context, not state(context, key))
    elif key in ("SHOW_ALL", "SHOW_NONE"):
        for t in ALL_TYPES:
            setattr(space, f"show_object_viewport_{t}", key == "SHOW_ALL")
    elif key == "APPLY_ALL":
        for screen in bpy.data.screens:
            for area in screen.areas:
                for other in area.spaces:
                    if other.type != 'VIEW_3D' or other == space:
                        continue
                    for name in _COPY_SHADING:
                        setattr(other.shading, name, getattr(sh, name))
                    for name in _COPY_OVERLAY:
                        setattr(other.overlay, name, getattr(space.overlay, name))
    elif key == "SELECT_CAMERA":
        cam = view_camera(context)
        if cam is None:
            return False
        for ob in context.scene.objects:
            if ob.visible_get():
                ob.select_set(ob == cam)
        context.view_layer.objects.active = cam
    elif key in CAMERA_KEYS:
        ob = view_camera(context)
        if ob is None or (key != "CAMERA_LOCK" and ob.type != 'CAMERA'):
            return False
        if key == "CAMERA_LOCK":
            on = not camera_locked(ob)
            ob.lock_location = (on,) * 3
            ob.lock_rotation = (on,) * 3
        else:
            prop = CAMERA_DATA[key]
            setattr(ob.data, prop, not getattr(ob.data, prop))
    elif key == "ISOLATE":
        area = context.area
        if area is None or area.type != 'VIEW_3D':
            return False
        if space.local_view is None and not any(ob.select_get() for ob in context.view_layer.objects if ob):
            return False
        with context.temp_override(area=area, region=main_region(area)):
            bpy.ops.allset.isolate()        # step 164: isolating a group shows its children
    elif key in ("EXPOSURE", "GAMMA", "CM_ENABLE"):
        _toggle_colour(context.scene, key)
    elif key in ("LAYOUT_SINGLE", "LAYOUT_FOUR"):
        from ..operators import view
        area = context.area
        if bool(space.region_quadviews) != (key == "LAYOUT_FOUR"):
            if space.region_quadviews:
                view.remember_ortho(area, space)
            with context.temp_override(area=area, region=main_region(area)):
                bpy.ops.screen.region_quadview()
            if space.region_quadviews:
                view.maya_ortho_panes(area, space)      # Maya's ortho cameras (step 161)
        # Maya: Single Perspective is always the persp camera, Four View's top right panel is persp (#8)
        view.ensure_persp(area, space)
    else:
        return False
    return True


def _toggle_colour(scene, key):
    vs = scene.view_settings
    if key == "CM_ENABLE":
        if vs.view_transform != RAW:
            scene[TRANSFORM_LAST] = vs.view_transform
            vs.view_transform = RAW
        else:
            try:
                vs.view_transform = scene.get(TRANSFORM_LAST, 'Standard')
            except TypeError:       # a transform of another colour config
                vs.view_transform = 'Standard'
        return
    prop, default, last = ("exposure", 0.0, EXPOSURE_LAST) if key == "EXPOSURE" else ("gamma", 1.0, GAMMA_LAST)
    value = getattr(vs, prop)
    if abs(value - default) > 1e-6:
        scene[last] = value
        setattr(vs, prop, default)
    else:
        setattr(vs, prop, scene.get(last, default))


class ALLSET_OT_panel_set(bpy.types.Operator):
    """Maya panel menu item for this view"""
    bl_idname = "allset.panel_set"
    bl_label = "Panel Menu Item"
    bl_options = {'INTERNAL', 'UNDO'}

    key: EnumProperty(items=[(k, k.title(), "") for k in
                             dict.fromkeys(SET_KEYS + ["SHOW_ALL", "SHOW_NONE"] + TOOLBAR_KEYS)])
    # panel toolbar button: a second click turns a radio-like mode off again (Maya iconTextCheckBox)
    toggle: BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _space(context) is not None

    @classmethod
    def description(cls, context, props):
        return TIPS.get(props.key, "Maya panel menu item for this view")

    def execute(self, context):
        key = self.key
        if self.toggle and key in TOGGLE_OFF and state(context, key):
            key = TOGGLE_OFF[key]
        if not apply(context, key):
            if key in FAILS:
                self.report({'WARNING'}, FAILS[key])
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_panel_run(bpy.types.Operator):
    """Run a Blender operator in this view (Maya panel menu item)"""
    bl_idname = "allset.panel_run"
    bl_label = "Run in This View"
    bl_options = {'INTERNAL'}

    op: StringProperty(options={'SKIP_SAVE'})
    props: StringProperty(default="{}", options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, props):
        try:
            mod, name = props.op.split(".")
            return getattr(getattr(bpy.ops, mod), name).get_rna_type().description
        except (ValueError, AttributeError, KeyError):
            return ""

    def execute(self, context):
        area = context.area
        if area is None or area.type != 'VIEW_3D':
            return {'CANCELLED'}
        mod, name = self.op.split(".")
        try:
            with context.temp_override(window=context.window, area=area, region=main_region(area)):
                getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT', **json.loads(self.props))
        except RuntimeError as ex:  # poll failed etc.
            self.report({'WARNING'}, str(ex).strip())
            return {'CANCELLED'}
        return {'FINISHED'}


# --- drawing --------------------------------------------------------------------------

def draw_rows(layout, context, rows, idname=""):
    space = _space(context)
    for row in rows:
        kind = row[0]
        if kind == "sep":
            if row[1]:
                layout.separator(type='LINE')
                layout.label(text=row[1])
            else:
                layout.separator()
        elif kind == "grey":
            layout.operator(GREY_OP, text=row[1]).item = item_path(idname, row[1])
        elif kind == "prop":
            _k, owner, prop, label = row
            if space is not None:
                layout.prop(_owner(space, context, owner), prop, text=label)
        elif kind == "set":
            _k, key, label = row
            if key == "RENDER_ENGINE":
                label = context.engine.replace("BLENDER_", "").replace("_NEXT", "").title()
            on = state(context, key)
            if on is None:
                icon = 'NONE'
            elif key in RADIO:
                icon = 'RADIOBUT_ON' if on else 'RADIOBUT_OFF'
            else:
                icon = 'CHECKBOX_HLT' if on else 'CHECKBOX_DEHLT'
            layout.operator(ALLSET_OT_panel_set.bl_idname, text=label, icon=icon).key = key
        elif kind == "run":
            _k, label, op, props = row
            p = layout.operator(ALLSET_OT_panel_run.bl_idname, text=label)
            p.op, p.props = op, json.dumps(props)
        elif kind == "menu":
            layout.menu(row[2], text=row[1])


def _menu(idname, label, rows, doc):
    def draw(self, context):
        draw_rows(self.layout, context, rows, idname)
    return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": label, "__doc__": doc,
                                            "draw": draw})


def _cameras(context, ortho):
    return [ob for ob in context.scene.objects
            if ob.type == 'CAMERA' and (ob.data.type == 'ORTHO') == ortho]


class ALLSET_OT_panel_look_through(bpy.types.Operator):
    """Look through this camera in this view"""
    bl_idname = "allset.panel_look_through"
    bl_label = "Look Through Camera"
    bl_options = {'INTERNAL'}

    camera: StringProperty(options={'SKIP_SAVE'})   # empty: the active object (Maya Look Through Selected)

    def execute(self, context):
        ob = context.scene.objects.get(self.camera) if self.camera else context.active_object
        area = context.area
        if ob is None or area is None or area.type != 'VIEW_3D':
            if ob is None:
                self.report({'WARNING'}, "Select an object to look through")
            return {'CANCELLED'}
        space = area.spaces.active
        space.camera = ob
        space.use_local_camera = ob != context.scene.camera
        space.region_3d.view_perspective = 'CAMERA'
        # Maya: navigating a view that looks through a camera moves the camera (#9)
        space.lock_camera = True
        return {'FINISHED'}


def _draw_camera_list(layout, context, ortho):
    for ob in _cameras(context, ortho):
        layout.operator(ALLSET_OT_panel_look_through.bl_idname, text=ob.name,
                        icon='OUTLINER_OB_CAMERA').camera = ob.name


class ALLSET_MT_panel_perspective(bpy.types.Menu):
    """Maya Panels > Perspective: the persp view and perspective cameras"""
    bl_idname = "ALLSET_MT_panel_perspective"
    bl_label = "Perspective"

    def draw(self, context):
        draw_rows(self.layout, context, [_view("persp", 'PERSP')])
        _draw_camera_list(self.layout, context, False)


class ALLSET_MT_panel_orthographic(bpy.types.Menu):
    """Maya Panels > Orthographic: top, front, side and orthographic cameras"""
    bl_idname = "ALLSET_MT_panel_orthographic"
    bl_label = "Orthographic"

    def draw(self, context):
        draw_rows(self.layout, context, [_view("top", 'TOP'), _view("front", 'FRONT'), _view("side", 'RIGHT')])
        _draw_camera_list(self.layout, context, True)


class ALLSET_MT_panel_panel(bpy.types.Menu):
    """Maya Panels > Panel: turn this pane into another editor"""
    bl_idname = "ALLSET_MT_panel_panel"
    bl_label = "Panel"

    def draw(self, context):
        for label, ui_type in PANEL_TYPES:
            self.layout.operator("allset.hb_pane", text=label).ui_type = ui_type


class ALLSET_MT_panel_blender(bpy.types.Menu):
    """Blender's own 3D View menus (View, Select, Add, Object ...)"""
    bl_idname = "ALLSET_MT_panel_blender"
    bl_label = "Blender"

    def draw(self, context):
        bpy.types.VIEW3D_MT_editor_menus.draw(self, context)


def draw_bar(layout, context):
    for label, idname in BAR:
        layout.menu(idname, text=label)
    layout.menu(ALLSET_MT_panel_blender.bl_idname, text="Blender")


class ALLSET_MT_panel_bar(bpy.types.Menu):
    """The Maya panel menus folded into one menu (header menus collapsed)"""
    bl_idname = "ALLSET_MT_panel_bar"
    bl_label = "Panel Menus"

    def draw(self, context):
        draw_bar(self.layout, context)


_generated = [
    _menu("ALLSET_MT_panel_view", "View", VIEW, "Maya panel View menu"),
    _menu("ALLSET_MT_panel_view_axis", "View Along Axis", VIEW_AXIS, "Look along a world axis"),
    _menu("ALLSET_MT_panel_camera_tools", "Camera Tools", CAMERA_TOOLS, "Maya camera tools"),
    _menu("ALLSET_MT_panel_shading", "Shading", SHADING, "Maya panel Shading menu"),
    _menu("ALLSET_MT_panel_lighting", "Lighting", LIGHTING, "Maya panel Lighting menu"),
    _menu("ALLSET_MT_panel_show", "Show", SHOW, "Maya panel Show menu"),
    _menu("ALLSET_MT_panel_isolate", "Isolate Select", ISOLATE, "Maya Isolate Select"),
    _menu("ALLSET_MT_panel_renderer", "Renderer", RENDERER, "Maya panel Renderer menu"),
    _menu("ALLSET_MT_panel_panels", "Panels", PANELS, "Maya panel Panels menu"),
    _menu("ALLSET_MT_panel_layouts", "Layouts", LAYOUTS, "Maya panel layouts"),
]

classes = (ALLSET_OT_panel_set, ALLSET_OT_panel_run, ALLSET_OT_panel_look_through,
           ALLSET_MT_panel_perspective, ALLSET_MT_panel_orthographic, ALLSET_MT_panel_panel,
           ALLSET_MT_panel_blender, ALLSET_MT_panel_bar, *_generated)


# --- header patch -----------------------------------------------------------------------

def _enabled(context):
    from .. import preferences
    try:
        return preferences.get(context).maya_panel_menus
    except KeyError:
        return False


def draw_collapsible(cls, context, layout):
    """Replaces Menu.draw_collapsible for VIEW3D_MT_editor_menus (bpy_types.py:1292-1299)."""
    if not _enabled(context):
        return _ORIG(cls, context, layout)
    if context.area.show_menus:
        draw_bar(layout.row(align=True), context)
    else:
        layout.menu(ALLSET_MT_panel_bar.bl_idname, text="", icon='COLLAPSEMENU')


def _ORIG(cls, context, layout):
    return bpy.types.Menu.draw_collapsible.__func__(cls, context, layout)


def patch_header():
    bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = classmethod(draw_collapsible)


def unpatch_header():
    cls = bpy.types.VIEW3D_MT_editor_menus
    if "draw_collapsible" in cls.__dict__:
        del cls.draw_collapsible


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    patch_header()


def unregister():
    unpatch_header()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
