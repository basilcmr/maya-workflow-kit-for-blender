# SPDX-License-Identifier: GPL-3.0-or-later
"""Step 140 Maya option windows: rigging, skinning, deformers and constraints (issue #32, Aim / Pole Vector of #35).

Same spec as operators/option_windows.py (``F`` fields, ``Window`` = one ``allset.opt_<key>`` operator); labels and
factory defaults read from Maya 2022 (research/maya/re/option_boxes_140.md, shots research/maya/screens/options140/).
option_windows.py appends ``WINDOWS`` to its own list, so this module only imports ``F`` / ``Window`` / helpers from it.

Maya tool boxes (Create Joints, Create IK Handle, Create IK Spline Handle, Paint Skin Weights) open Tool Settings,
not a window (option_boxes_140.md:15-17): here they are the same kind of window titled with the tool name, whose
button starts the tool with the values (docs/steps/step_140.md 「설계」). Fields Blender can't honour are only listed
(``missing``), never faked.
"""

import bpy
from bpy.props import StringProperty
from mathutils import Vector

from .option_windows import F, Window, _constraint, _last_constraint  # noqa: F401  (imported by option_windows)


class FText(F):
    """A Maya text field (``kind`` "text")."""

    def __init__(self, name, label, default=""):
        super().__init__(name, label, "text", default)

    def prop(self):
        return StringProperty(name=self.label.rstrip(":"), default=self.default)


# --- run helpers ------------------------------------------------------------------------------------

_SOLVER = {"Rotate-Plane Solver": "RP", "Single-Chain Solver": "SC"}
_NORMALIZE = {"None": "NONE", "Off": "NONE", "Interactive": "INTERACTIVE", "Post": "POST"}


def _ik_fields(prefix=""):
    # IK Handle Settings (option_boxes_140.md:208-211): Current solver RP, Solver enable on, Weight 1
    return [F(prefix + "solver", "Current solver:", "enum", "Rotate-Plane Solver",
              items=("Single-Chain Solver", "Rotate-Plane Solver")),
            F(prefix + "solver_enable", "", "bool", True, text="Solver enable"),
            F(prefix + "weight", "Weight:", "float", 1.0, lo=0.01, hi=1.0)]


_IK_MISSING = ("Autopriority", "Snap enable (Blender's handle is a free empty)", "Sticky", "Priority",
               "POWeight")


def joint_tool_props(v):
    """Window values -> ``allset.joint_tool`` properties."""
    return dict(secondary_axis="NONE" if v["secondary_axis"] == "None" else v["secondary_axis"],
                secondary_world=v["secondary_world"], secondary_sign=v["secondary_sign"],
                create_ik=v["create_ik"], ik_solver=_SOLVER[v["ik_solver"]],
                ik_solver_enable=v["ik_solver_enable"], ik_weight=v["ik_weight"])


def _run_joint_tool(context, v):
    props = joint_tool_props(v)
    if props["secondary_axis"] == "X":
        raise RuntimeError("Secondary axis must differ from the primary axis (X)")
    return bpy.ops.allset.joint_tool('INVOKE_DEFAULT', **props)


def _run_ik_handle(context, v):
    return bpy.ops.allset.ik_handle('INVOKE_DEFAULT', solver=_SOLVER[v["solver"]], solver_enable=v["solver_enable"],
                                    weight=v["weight"])


def _run_ik_spline(context, v):
    return bpy.ops.allset.ik_spline_handle(
        'INVOKE_DEFAULT', root_on_curve=v.get("root_on_curve", True), parent_curve=v.get("parent_curve", True),
        snap_curve=v.get("snap_curve", False), create_curve=v.get("create_curve", True),
        spans=int(v.get("spans", "1")))


def _run_bind(context, v):
    res = bpy.ops.allset.bind_skin('EXEC_DEFAULT', bind_to='SELECTED' if v["bind_to"] == "Selected joints" else
                                   'HIERARCHY', max_influences=v["max_influences"],
                                   bind_method='HEAT_MAP' if v.get("bind_method") == "Heat Map" else
                                   'CLOSEST_DISTANCE',
                                   normalize=_NORMALIZE[v["normalize"]], remove_unused=v["remove_unused"],
                                   colorize=v["colorize"])
    if res == {'FINISHED'}:
        for ob in context.selected_objects:
            for md in getattr(ob, "modifiers", ()):
                if md.type == 'ARMATURE':
                    md.use_deform_preserve_volume = v["skinning"] == "Dual quaternion"
    return res


def _run_unbind(context, v):
    history = {"Delete history": "DELETE", "Keep history": "KEEP", "Bake history": "BAKE"}[v["history"]]
    return bpy.ops.allset.unbind_skin('EXEC_DEFAULT', history=history, remove_colors=v["remove_colors"])


_SURFACE = {"Closest point on surface": "CLOSEST_POINT", "Ray cast": "RAY_CAST",
            "Closest component": "CLOSEST_COMPONENT"}
_INFLUENCE = {"Closest joint": "CLOSEST_JOINT", "Closest bone": "CLOSEST_BONE", "One to one": "ONE_TO_ONE",
              "Name": "NAME", "None": "NONE"}


def _run_copy_weights(context, v):
    return bpy.ops.allset.copy_skin_weights('EXEC_DEFAULT', surface=_SURFACE[v["surface"]],
                                            influence1=_INFLUENCE[v["influence1"]],
                                            influence2=_INFLUENCE[v["influence2"]],
                                            influence3=_INFLUENCE[v["influence3"]], normalize=v["normalize"])


_PAINT_OPS = {"Replace": "REPLACE", "Add": "ADD", "Scale": "SCALE", "Smooth": "SMOOTH"}
_PROFILES = {"Gaussian": "GAUSSIAN", "Soft": "SOFT", "Solid": "SOLID"}


def _run_paint(context, v):
    return bpy.ops.allset.paint_skin_weights(
        'EXEC_DEFAULT', settings=True, operation=_PAINT_OPS[v["operation"]], profile=_PROFILES[v["profile"]],
        normalize=_NORMALIZE[v["normalize"]], opacity=v["opacity"], value=v["value"], radius=v["radius"],
        screen_projection=v["screen_projection"], show_wireframe=v["show_wireframe"], xray_joints=v["xray_joints"])


def _run_blend_shape(context, v):
    return bpy.ops.allset.blend_shape('EXEC_DEFAULT', node_name=v["node_name"].strip(),
                                      origin=v["origin"].upper(), check_topology=v["check_topology"],
                                      delete_targets=v["delete_targets"])


def _run_aim(context, v):
    from . import rig_tools
    world_up = v["world_up_type"]
    if world_up == "Vector":
        up = Vector(v["world_up_vector"])
        if up.length < 1e-9 or (up.normalized() - Vector((0.0, 1.0, 0.0))).length > 1e-6:
            raise RuntimeError("Blender's Track To turns the up vector towards the scene up only: World up vector "
                               "must be 0 1 0 (Maya Y)")
    # check the vectors before anything is added (rig_tools.aim raises on vectors Blender can't take)
    bone = context.mode == 'POSE'
    if rig_tools.axis_of(rig_tools.local_axis(v["aim_vector"], bone)) is None:
        raise RuntimeError("Blender aims along an axis: the aim vector must be +-X, +-Y or +-Z")
    if world_up != "None":
        a = rig_tools.axis_of(rig_tools.local_axis(v["aim_vector"], bone))
        u = rig_tools.axis_of(rig_tools.local_axis(v["up_vector"], bone))
        if u is None or u[1] < 0 or u[0] == a[0]:
            raise RuntimeError("Blender's Track To needs an up vector along a positive axis other than the aim "
                               "vector's")
    res = bpy.ops.allset.constrain('EXEC_DEFAULT', type='TRACK_TO')
    con = _last_constraint(context)
    if res != {'FINISHED'} or con is None:
        return res
    owner = context.active_pose_bone if bone else context.active_object
    cons = owner.constraints
    if (tuple(v["aim_vector"]), tuple(v["up_vector"]), world_up) != (rig_tools.AIM_VECTOR, rig_tools.UP_VECTOR,
                                                                    rig_tools.WORLD_UP):
        # the operator made Maya's factory aim; redo it with the window's vectors on a fresh Track To
        target, sub, name = con.target, getattr(con, "subtarget", ""), con.name
        cons.remove(con)
        con = cons.new('TRACK_TO')
        con.name, con.target = name, target
        if sub:
            con.subtarget = sub
        con = rig_tools.aim(cons, con, v["aim_vector"], v["up_vector"], world_up, bone=bone)
    con.influence = v["weight"]
    return res


def _run_scale(context, v):
    res = _constraint('COPY_SCALE')(context, {**v, "maintain_offset": False})
    con = _last_constraint(context)
    if res != {'FINISHED'} or con is None or con.type != 'COPY_SCALE':
        return res
    owner = context.active_pose_bone if context.mode == 'POSE' else context.active_object
    # Maya: driven scale = target scale x offset (Maya Y = Blender Z). Blender's Copy Scale with Offset multiplies
    # the owner's own scale in, so the owner's scale channels become the offset (option_boxes_140.md:190-192).
    offset = Vector((v["offset"][0], v["offset"][2], v["offset"][1]))
    if v["maintain_offset"]:
        target = con.target
        ts = target.pose.bones[con.subtarget].matrix.to_scale() if con.subtarget else target.matrix_world.to_scale()
        own = owner.scale.copy()
        offset = Vector([own[i] / ts[i] if abs(ts[i]) > 1e-9 else 1.0 for i in range(3)])
    if (offset - Vector((1.0, 1.0, 1.0))).length > 1e-9:
        con.use_offset = True
        owner.scale = offset
    return res


def _run_pole_vector(context, v):
    if abs(v["weight"] - 1.0) > 1e-9:
        raise RuntimeError("Blender's IK pole target has no weight: the pole vector always counts fully (Weight 1)")
    return bpy.ops.allset.pole_vector('EXEC_DEFAULT')


# --- the windows (labels / defaults: research/maya/re/option_boxes_140.md) --------------------------

_ANIM_LAYER = ("Animation Layer", "Set layer to override")

WINDOWS = [
    # Skeleton > Create Joints: Tool Settings "Joint Tool" (option_boxes_140.md:196-206)
    Window("joint_tool", "Joint Tool", "Create Joints", None, [
        F("secondary_axis", "Secondary Axis:", "enum", "Y", items=("X", "Y", "Z", "None")),
        F("secondary_world", "Secondary Axis World Orientation:", "enum", "Y", items=("X", "Y", "Z")),
        F("secondary_sign", "", "enum", "+", items=("+", "-")),
        F("create_ik", "", "bool", False, text="Create IK handle"),
        *_ik_fields("ik_")], _run_joint_tool, paths=("Skeleton/Create Joints",),
        missing=("Degrees of freedom", "Symmetry", "Scale compensate", "Auto joint limits",
                 "Variable Bone Radius Settings / Bone Radius Settings", "Projected Centering",
                 "Orient Joint to World (Blender bones point Y at the child)",
                 "Primary Axis (always the bone's Y = Maya X)") + _IK_MISSING),
    # Skeleton > Create IK Handle: Tool Settings "IK Handle Tool" (option_boxes_140.md:208-211)
    Window("ik_handle_tool", "IK Handle Tool", "Create IK Handle", None, _ik_fields(), _run_ik_handle,
           paths=("Skeleton/Create IK Handle",), missing=_IK_MISSING),
    # Skeleton > Create IK Spline Handle: Tool Settings "IK Spline Handle Tool" (option_boxes_140.md:213-218; Maya
    # 2026 factory values ikSplineHandleCtx, research/maya/re/maya2026_curve_rigs.md:11, step 218)
    Window("ik_spline_tool", "IK Spline Handle Tool", "Create IK Spline Handle", None, [
        F("root_on_curve", "", "bool", True, text="Root on curve"),
        F("parent_curve", "", "bool", True, text="Auto parent curve"),
        F("snap_curve", "", "bool", False, text="Snap curve to root"),
        F("create_curve", "", "bool", True, text="Auto create curve"),
        F("spans", "Number of spans:", "enum", "1", items=("1", "2", "3", "4"))], _run_ik_spline,
        paths=("Skeleton/Create IK Spline Handle",),
        missing=("Auto create root axis", "Auto simplify curve (the kit always fits the curve: on)",
                 "Root twist mode", "Twist type (Linear; Blender's Spline IK has no twist distribution)")),
    # Skin > Bind Skin (option_boxes_140.md:28-46); replaces option_windows "bind_skin"
    Window("bind_skin_maya", "Bind Skin Options", "Apply and Close", ("allset.bind_skin", {}), [
        F("bind_to", "Bind to:", "enum", "Joint hierarchy", items=("Joint hierarchy", "Selected joints")),
        F("bind_method", "Bind method:", "enum", "Closest distance", items=("Closest distance", "Heat Map")),
        F("skinning", "Skinning method:", "enum", "Classic linear", items=("Classic linear", "Dual quaternion")),
        F("normalize", "Normalize weights:", "enum", "Interactive", items=("None", "Interactive", "Post")),
        F("max_influences", "Max influences:", "int", 5, lo=1, hi=30),
        F("remove_unused", "", "bool", True, text="Remove unused influences"),
        F("colorize", "", "bool", True, text="Colorize skeleton")], _run_bind, paths=("Skin/Bind Skin",),
        missing=("Bind to: Object hierarchy", "Bind method: Closest in hierarchy / Geodesic Voxel", "Skinning method: Weight "
                 "blended", "Weight distribution", "Allow multiple bind poses", "Maintain max influences",
                 "Include hidden selections on creation", "Deformer node")),
    # Skin > Unbind Skin: "Detach Skin Options" (option_boxes_140.md:48-51)
    Window("unbind_skin", "Detach Skin Options", "Detach", ("allset.unbind_skin", {}), [
        F("history", "History:", "enum", "Delete history", items=("Delete history", "Keep history", "Bake history")),
        F("remove_colors", "Coloring:", "bool", True, text="Remove joint colors")], _run_unbind,
        paths=("Skin/Unbind Skin",)),
    # Skin > Copy Skin Weights (option_boxes_140.md:53-60)
    Window("copy_skin_weights", "Copy Skin Weights Options", "Copy", ("allset.copy_skin_weights", {}), [
        F("surface", "Surface Association:", "enum", "Closest point on surface",
          items=("Closest point on surface", "Ray cast", "Closest component")),
        F("influence1", "Influence Association 1:", "enum", "Closest joint",
          items=("Closest joint", "Closest bone", "One to one", "Name")),
        F("influence2", "Influence Association 2:", "enum", "None",
          items=("None", "Closest joint", "Closest bone", "One to one", "Name")),
        F("influence3", "Influence Association 3:", "enum", "None",
          items=("None", "Closest joint", "Closest bone", "One to one", "Name")),
        F("normalize", "", "bool", False, text="Normalize")], _run_copy_weights, paths=("Skin/Copy Skin Weights",),
        missing=("Surface Association: UV space", "Influence Association: Label")),
    # Skin > Paint Skin Weights: Tool Settings "Paint Skin Weights Tool" (option_boxes_140.md:220-237)
    Window("paint_skin_weights", "Paint Skin Weights Tool", "Paint Skin Weights", None, [
        F("operation", "Paint operation:", "enum", "Replace", items=("Replace", "Add", "Scale", "Smooth")),
        F("profile", "Profile:", "enum", "Soft", items=("Gaussian", "Soft", "Solid")),
        F("normalize", "Normalize Weights:", "enum", "Interactive", items=("Off", "Interactive", "Post")),
        F("opacity", "Opacity:", "float", 1.0, lo=0.0, hi=1.0), F("value", "Value:", "float", 1.0, lo=0.0, hi=1.0),
        F("radius", "Radius(U):", "float", 1.0, lo=0.0001, hi=1000.0),
        F("screen_projection", "", "bool", False, text="Screen projection"),
        F("show_wireframe", "", "bool", True, text="Show wireframe"),
        F("xray_joints", "", "bool", True, text="XRay Joints")], _run_paint, paths=("Skin/Paint Skin Weights",),
        missing=("Influences sort / filter (the vertex group list)", "Mode: Select / Paint Select", "Weight Type",
                 "Min/Max value", "Gradient / color ramp", "Radius(L)", "Reflection", "Stamp spacing / depth",
                 "Stylus pressure", "Other display options")),
    # Deform > Blend Shape (option_boxes_140.md:125-134)
    Window("blend_shape", "Blend Shape Options", "Create", ("allset.blend_shape", {}), [
        FText("node_name", "BlendShape node:"),
        F("origin", "Origin:", "enum", "Local", items=("Local", "World")),
        F("check_topology", "", "bool", True, text="Check topology"),
        F("delete_targets", "", "bool", False, text="Delete targets")], _run_blend_shape,
        paths=("Deform/Blend Shape",), missing=("Envelope (Blender shape keys have no envelope)",
                                                "Target shape options: In-between")),
    # Constrain > Aim (option_boxes_140.md:169-185): +X at the target, +Y up, world up Vector (0, 1, 0)
    Window("aim_constraint", "Aim Constraint Options", "Add", ("allset.constrain", {"type": 'TRACK_TO'}), [
        F("aim_vector", "Aim vector:", "vec3", (1.0, 0.0, 0.0)), F("up_vector", "Up vector:", "vec3", (0.0, 1.0, 0.0)),
        F("world_up_type", "World up type:", "enum", "Vector", items=("Scene up", "Vector", "None")),
        F("world_up_vector", "World up vector:", "vec3", (0.0, 1.0, 0.0)),
        F("weight", "Weight:", "float", 1.0, lo=0.0, hi=1.0)], _run_aim, paths=("Constrain/Aim",),
        missing=("Maintain offset / Offset (Blender's Track To has none)",) + _ANIM_LAYER +
        ("World up type: Object up / Object rotation up", "World up object", "Constraint axes (always All)")),
    # Constrain > Pole Vector (option_boxes_140.md:187-188): only Weight
    Window("pole_vector", "Pole Vector Constraint Options", "Add", ("allset.pole_vector", {}), [
        F("weight", "Weight:", "float", 1.0, lo=0.0, hi=1.0)], _run_pole_vector, paths=("Constrain/Pole Vector",)),
    # Constrain > Scale (option_boxes_140.md:190-192)
    Window("scale_constraint", "Scale Constraint Options", "Add", ("allset.constrain", {"type": 'COPY_SCALE'}), [
        F("maintain_offset", "Maintain offset:", "bool", False), F("offset", "Offset:", "vec3", (1.0, 1.0, 1.0)),
        F("all", "Constraint axes:", "bool", True, text="All"), F("x", "", "bool", False, text="X"),
        F("y", "", "bool", False, text="Y"), F("z", "", "bool", False, text="Z"),
        F("weight", "Weight:", "float", 1.0, lo=0.0, hi=1.0)], _run_scale, paths=("Constrain/Scale",),
        missing=_ANIM_LAYER),
]

