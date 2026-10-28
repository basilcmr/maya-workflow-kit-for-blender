# SPDX-License-Identifier: GPL-3.0-or-later
"""Maya UV workflow on Blender's UV Editor (docs/steps/step_66.md 「계획」 1, 3).

- Opening the UV Editor (Maya UV > UV Editor) enters edit mode with UV Sync Selection on, so the object's UVs show at once
  (research/maya/workflows/uv.md:14-19, :60-63). Maya's UV / UV Shell components are UVs picked apart from the mesh
  vertices: Blender needs sync off for that (and then draws only the selected faces' UVs, so every face is selected).
- UV Shell = Blender UV island (uv.md:130). Blender's island operators group UVs by shared coordinates and ignore seams
  (measured, step 66: pack_islands / average_islands_scale), only unwrap reads seams. So Cut = seam + the smaller side moved
  2e-4 off the cut (a real split that still looks in place), Sew = seam cleared + the smaller shell moved onto the edge.
- Unfold = Blender Unwrap (Minimum Stretch) on the chosen shells with their borders kept as seams, each shell put back where
  it was; Layout = Pack Islands with Maya's shell padding in pixels of the map; Texel Density = px per Maya unit (uv.md:141-142).
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty
from mathutils import Vector

from .. import results
from .. import undo_steps
from . import units
from .. import compat

EPS = 1e-5           # UVs closer than this are one UV
NUDGE = 2e-4         # how far Cut moves the smaller side (0.2 px on a 1024 map)
MAYA_MAP_SIZE = 1024
MAYA_SHELL_PADDING = 2   # px [K] (uv.md:140)
NOTICE_UNFOLD = "Unfold uses Blender Unwrap (Minimum Stretch), not Unfold3D: shapes can differ from Maya."


class ALLSET_PG_uv(bpy.types.PropertyGroup):
    map_size: IntProperty(name="Map Size", default=MAYA_MAP_SIZE, min=1, soft_max=8192,
                          description="Texture size in pixels for Texel Density and Layout padding")
    texel_density: FloatProperty(name="Texel Density", default=0.0, min=0.0, precision=3,
                                 description="Pixels per Maya unit (px/cm in the Maya Workflow Kit template)")
    shell_padding: FloatProperty(name="Shell Padding", default=MAYA_SHELL_PADDING, min=0.0, soft_max=64.0,
                                 description="Pixels between UV shells (Layout)")


def settings(context):
    return context.scene.allset_uv


def register_props():
    bpy.utils.register_class(ALLSET_PG_uv)
    bpy.types.Scene.allset_uv = PointerProperty(type=ALLSET_PG_uv)


def unregister_props():
    del bpy.types.Scene.allset_uv
    bpy.utils.unregister_class(ALLSET_PG_uv)


# --- selection and islands (bmesh) ------------------------------------------------------------------

def _same(a, b):
    return abs(a.x - b.x) <= EPS and abs(a.y - b.y) <= EPS


def _uv_at(face, vert, uv):
    for loop in face.loops:
        if loop.vert is vert:
            return loop[uv].uv
    return None


def islands(bm, uv, faces=None, seams=False):
    """Lists of faces that share UVs across their edges (Blender's islands; ``seams``: a seam also splits)."""
    faces = list(bm.faces if faces is None else faces)
    index = {f: i for i, f in enumerate(faces)}
    parent = list(range(len(faces)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for e in {e for f in faces for e in f.edges}:
        if seams and e.seam:
            continue
        fs = [f for f in e.link_faces if f in index]
        for i in range(1, len(fs)):
            a, b = fs[0], fs[i]
            if all(_same(_uv_at(a, v, uv), _uv_at(b, v, uv)) for v in e.verts):
                ra, rb = find(index[a]), find(index[b])
                if ra != rb:
                    parent[rb] = ra
    groups = {}
    for f, i in index.items():
        groups.setdefault(find(i), []).append(f)
    return list(groups.values())


def sync(context):
    return context.scene.tool_settings.use_uv_select_sync


def selected_faces(bm, uv, synced):
    if synced:
        return [f for f in bm.faces if f.select and not f.hide]
    return [f for f in bm.faces if f.select and not f.hide and all(compat.uv_vert_selected(l, uv) for l in f.loops)]


def selected_edges(bm, uv, synced):
    if synced:
        return [e for e in bm.edges if e.select and not e.hide]
    out = set()
    for f in bm.faces:
        if f.hide or not f.select:
            continue
        for loop in f.loops:
            if compat.uv_edge_selected(loop, uv):
                out.add(loop.edge)
    return list(out)


def target_islands(bm, uv, synced):
    """Shells touched by the selection (faces, else any selected UV), or every shell."""
    every = islands(bm, uv, [f for f in bm.faces if not f.hide])
    if synced:
        picked = {f for f in bm.faces if f.select}
    else:
        picked = {f for f in bm.faces if f.select and any(compat.uv_vert_selected(l, uv) for l in f.loops)}
    chosen = [isl for isl in every if picked & set(isl)]
    return chosen or every


def _island_loops(island):
    return [loop for f in island for loop in f.loops]


def uv_centre(island, uv):
    loops = _island_loops(island)
    return sum((l[uv].uv for l in loops), Vector((0.0, 0.0))) / max(len(loops), 1)


def uv_bounds(island, uv):
    us = [l[uv].uv for l in _island_loops(island)]
    lo = Vector((min(u.x for u in us), min(u.y for u in us)))
    hi = Vector((max(u.x for u in us), max(u.y for u in us)))
    return lo, hi


# --- Cut / Sew ---------------------------------------------------------------------------------------

def cut(bm, uv, edges):
    """Maya Cut UVs: seams on ``edges``; where that splits a shell, the smaller side moves NUDGE off the cut.
    Returns the number of edges that now separate two shells."""
    for e in edges:
        e.seam = True
    groups = islands(bm, uv, [f for f in bm.faces if not f.hide], seams=True)
    owner = {f: i for i, isl in enumerate(groups) for f in isl}
    moved = set()
    split = 0
    for e in edges:
        fs = [f for f in e.link_faces if f in owner]
        if len(fs) != 2 or owner[fs[0]] == owner[fs[1]]:
            continue
        split += 1
        small = min(fs, key=lambda f: len(groups[owner[f]]))
        isl = groups[owner[small]]
        centre = uv_centre(isl, uv)
        for v in e.verts:
            key = (owner[small], v.index)
            if key in moved:
                continue
            moved.add(key)
            c = _uv_at(small, v, uv).copy()
            d = centre - c
            d = d.normalized() * NUDGE if d.length > 1e-9 else Vector((NUDGE, 0.0))
            for loop in _island_loops(isl):
                if loop.vert is v and _same(loop[uv].uv, c):
                    loop[uv].uv = c + d
    return split


def sew(bm, uv, edges):
    """Maya Sew UVs: clear the seams; a shell on the other side of an edge is moved (rotated, scaled) onto it,
    the smaller shell onto the bigger one. Returns the number of edges sewn."""
    for e in edges:
        e.seam = False
    sewn = 0
    for e in edges:
        fs = [f for f in e.link_faces if not f.hide]
        if len(fs) != 2:
            continue
        groups = islands(bm, uv, [f for f in bm.faces if not f.hide])
        where = {f: i for i, isl in enumerate(groups) for f in isl}
        a, b = fs
        v, w = e.verts
        if where[a] == where[b]:
            shell = set(groups[where[a]])
            for vert in (v, w):     # a slit inside one shell: weld the two sides half-way
                pa, pb = _uv_at(a, vert, uv).copy(), _uv_at(b, vert, uv).copy()
                mid = (pa + pb) / 2
                for loop in vert.link_loops:
                    if loop.face in shell and (_same(loop[uv].uv, pa) or _same(loop[uv].uv, pb)):
                        loop[uv].uv = mid.copy()
            sewn += 1
            continue
        big, small = (a, b) if len(groups[where[a]]) >= len(groups[where[b]]) else (b, a)
        p_v, p_w = _uv_at(small, v, uv).copy(), _uv_at(small, w, uv).copy()
        q_v, q_w = _uv_at(big, v, uv).copy(), _uv_at(big, w, uv).copy()
        zp, zq = complex(*(p_w - p_v)), complex(*(q_w - q_v))
        k = zq / zp if abs(zp) > 1e-12 else 1.0
        for loop in _island_loops(groups[where[small]]):
            z = complex(*(loop[uv].uv - p_v)) * k
            loop[uv].uv = q_v + Vector((z.real, z.imag))
        for vert, q in ((v, q_v), (w, q_w)):
            for loop in vert.link_loops:
                if loop.face in set(groups[where[small]]) and (loop[uv].uv - q).length < 1e-4:
                    loop[uv].uv = q.copy()
        sewn += 1
    return sewn


# --- Unfold / Layout (Blender operators with the selection set up) -----------------------------------

def _with_faces(context, ob, faces, call):
    """Run ``call`` with UV sync on and exactly ``faces`` selected (Blender's unwrap / pack use that), then put the
    selection and sync back."""
    ts = context.scene.tool_settings
    bm = bmesh.from_edit_mesh(ob.data)
    old_sync = ts.use_uv_select_sync
    for seq in (bm.verts, bm.edges, bm.faces):
        seq.index_update()
    old = [[el.index for el in seq if el.select] for seq in (bm.verts, bm.edges, bm.faces)]
    old_mode = tuple(ts.mesh_select_mode)
    want = {f.index for f in faces}
    ts.use_uv_select_sync = True
    for f in bm.faces:
        f.select_set(False)
    for f in bm.faces:
        if f.index in want:
            f.select_set(True)
    bmesh.update_edit_mesh(ob.data)
    try:
        return call()
    finally:
        bm = bmesh.from_edit_mesh(ob.data)
        for seq, keep in zip((bm.verts, bm.edges, bm.faces), old):
            seq.ensure_lookup_table()
            for el in seq:
                el.select = False
            for i in keep:
                if i < len(seq):
                    seq[i].select = True
        ts.mesh_select_mode = old_mode
        ts.use_uv_select_sync = old_sync
        bmesh.update_edit_mesh(ob.data)


def mark_shell_borders(bm, uv, faces):
    """Seams on the borders of the shells of ``faces`` (keeps them apart through an unwrap)."""
    where = {f: i for i, isl in enumerate(islands(bm, uv, [f for f in bm.faces if not f.hide])) for f in isl}
    fs = set(faces)
    for e in {e for f in faces for e in f.edges}:
        linked = [f for f in e.link_faces if not f.hide]
        if len(linked) == 2 and (where[linked[0]] != where[linked[1]] or (linked[0] in fs) != (linked[1] in fs)):
            e.seam = True


def unfold(context, ob):
    """Maya Unfold on the target shells of ``ob``: Blender Unwrap (Minimum Stretch), each shell back in its place."""
    bm = bmesh.from_edit_mesh(ob.data)
    uv = bm.loops.layers.uv.verify()
    bm.faces.index_update()
    shells = target_islands(bm, uv, sync(context))
    faces = [f for isl in shells for f in isl]
    mark_shell_borders(bm, uv, faces)
    # Maya Unfold (Unfold3D) keeps each shell's UV area and the mean of its UVs (research/maya/re/uv_shells_155.md §4
    # Unfold); its solver turn can't be reproduced, Blender's unwrap orientation stays.
    before = [([f.index for f in isl], _point_mean(isl, uv), sum(_uv_area(f, uv) for f in isl)) for isl in shells]
    bmesh.update_edit_mesh(ob.data)
    _with_faces(context, ob, faces, lambda: bpy.ops.uv.unwrap(method='MINIMUM_STRETCH', margin=0.0))
    bm = bmesh.from_edit_mesh(ob.data)
    uv = bm.loops.layers.uv.verify()
    bm.faces.ensure_lookup_table()
    # one factor for all unfolded shells: the measured rule keeps the *total* area (one-shell cases), and a common
    # factor keeps the even texel density Blender's unwrap gives the shells (sweep M66-3: Unfold then Layout)
    area = sum(a for _i, _m, a in before)
    now = sum(_uv_area(bm.faces[i], uv) for idx, _m, _a in before for i in idx)
    k = math.sqrt(area / now) if now > 1e-12 and area > 1e-12 else 1.0
    for idx, mean, _area in before:
        isl = [bm.faces[i] for i in idx]
        c = _point_mean(isl, uv)
        for loop in _island_loops(isl):
            loop[uv].uv = mean + (loop[uv].uv - c) * k
    bmesh.update_edit_mesh(ob.data)
    return len(shells)


def _point_mean(island, uv):
    """Mean of the shell's UV positions, each UV (vertex + coordinate) once."""
    pts = []
    for loop in _island_loops(island):
        p = loop[uv].uv
        if not any(v is loop.vert and _same(q, p) for v, q in pts):
            pts.append((loop.vert, p.copy()))
    return sum((q for _v, q in pts), Vector((0.0, 0.0))) / max(len(pts), 1)


def layout(context, ob, padding_px, map_size):
    bm = bmesh.from_edit_mesh(ob.data)
    uv = bm.loops.layers.uv.verify()
    shells = target_islands(bm, uv, sync(context))
    faces = [f for isl in shells for f in isl]
    margin = padding_px / max(map_size, 1)
    _with_faces(context, ob, faces, lambda: bpy.ops.uv.pack_islands(
        rotate=True, margin_method='FRACTION', margin=margin))
    return len(shells)


# --- Automatic / Contour Stretch (step 139, research/maya/re/edit_mesh_139_uv.md) -------------------

def auto_planes(count):
    """Projection directions of Maya's Automatic mapping (object space). 3 and 6 = the six axis planes (Maya 3 planes
    also gives 6 shells on a cube / sphere, measured); 4 / 8 / 12 = tetrahedron / octahedron / dodecahedron faces,
    5 = top, bottom and three around (delegated: only 6 is compared with Maya). Order = Maya X, Y, Z (Blender X, Z, -Y):
    a face that ties goes to the earlier plane (a Maya cylinder's 45-degree sides go to X, measured)."""
    count = int(count)
    if count in (3, 6):
        return [Vector(d) for d in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, -1, 0), (0, 1, 0))]
    if count == 4:
        return [Vector(d).normalized() for d in ((1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1))]
    if count == 5:
        ring = [Vector((math.cos(a), math.sin(a), 0.0)) for a in (0.0, 2 * math.pi / 3, 4 * math.pi / 3)]
        return [Vector((0, 0, 1)), Vector((0, 0, -1))] + ring
    if count == 8:
        return [Vector((x, y, z)).normalized() for x in (1, -1) for z in (1, -1) for y in (-1, 1)]
    g = (1 + math.sqrt(5)) / 2       # 12: icosahedron vertices = dodecahedron face normals
    dirs = []
    for a, b in ((1, g), (-1, g), (1, -g), (-1, -g)):
        dirs += [Vector((0, a, b)), Vector((a, b, 0)), Vector((b, 0, a))]
    return [d.normalized() for d in dirs]


def _basis(d):
    """(U, V) of a projection plane seen from outside along ``-d``: V = up (Blender Z, Y for the top / bottom)."""
    up = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((0, 1, 0)) * (1 if d.z > 0 else -1)
    u = (-d).cross(up).normalized()
    return u, d.cross(u).normalized()


def _shelf(rects, scale, gap):
    """Shelf layout of ``rects`` (w, h) at ``scale`` in 0-1 with ``gap`` around and between them; (positions, fits)."""
    x = y = gap
    row = 0.0
    pos = [None] * len(rects)
    for i in sorted(range(len(rects)), key=lambda i: -rects[i][1]):
        w, h = rects[i][0] * scale, rects[i][1] * scale
        if x > gap and x + w + gap > 1.0 + 1e-9:
            x, y, row = gap, y + row + gap, 0.0
        pos[i] = (x, y)
        x += w + gap
        row = max(row, h)
    return pos, y + row + gap <= 1.0 + 1e-9 and all(w * scale + 2 * gap <= 1.0 + 1e-9 for w, _h in rects)


def pack_uniform(rects, gap):
    """Positions and one scale for every rect so the shells fit 0-1 (Maya Automatic: uniform scale, square layout)."""
    big = max((max(w, h) for w, h in rects), default=0.0)
    if big <= 1e-12:
        return [(gap, gap)] * len(rects), 1.0
    lo, hi = 0.0, (1.0 - 2 * gap) / big
    best = _shelf(rects, lo, gap)[0]
    for _ in range(40):
        mid = (lo + hi) / 2
        pos, fits = _shelf(rects, mid, gap)
        if fits:
            lo, best = mid, pos
        else:
            hi = mid
    return best, lo


def auto_project(bm, uv, faces, planes=6, spacing=0.2):
    """Maya polyAutoProjection on ``faces`` (object space, -ws 0): every face goes to the plane its normal faces most,
    connected faces of one plane are one shell projected on it, shells are laid out in 0-1 at one scale with
    ``spacing`` percent between them (factory 6 planes / 0.2 %, performPolyAutoProj.mel:23-51). Returns the shell count."""
    dirs = auto_planes(planes)
    faces = [f for f in faces if not f.hide]
    which = {}
    for f in faces:
        dots = [f.normal.dot(d) for d in dirs]
        top = max(dots)
        which[f] = next(i for i, x in enumerate(dots) if x >= top - 1e-6)
    seen, shells = set(), []
    for f in faces:
        if f in seen:
            continue
        seen.add(f)
        group, todo = [], [f]
        while todo:
            g = todo.pop()
            group.append(g)
            for e in g.edges:
                for n in e.link_faces:
                    if n not in seen and n in which and which[n] == which[f]:
                        seen.add(n)
                        todo.append(n)
        shells.append((which[f], group))
    flat, rects = [], []
    for k, group in shells:
        u, v = _basis(dirs[k])
        pts = {lp: Vector((lp.vert.co.dot(u), lp.vert.co.dot(v))) for g in group for lp in g.loops}
        lo = Vector((min(p.x for p in pts.values()), min(p.y for p in pts.values())))
        hi = Vector((max(p.x for p in pts.values()), max(p.y for p in pts.values())))
        flat.append((pts, lo))
        rects.append((hi.x - lo.x, hi.y - lo.y))
    pos, scale = pack_uniform(rects, max(0.0, spacing) / 100.0)
    for (pts, lo), (x, y) in zip(flat, pos):
        for lp, p in pts.items():
            lp[uv].uv = ((p.x - lo.x) * scale + x, (p.y - lo.y) * scale + y)
    return len(shells)


def fit_unit(loops, uv):
    """Stretch the UVs of ``loops`` to fill 0-1 (Maya Contour Stretch: a strip of faces fills the square, measured)."""
    pts = [lp[uv].uv.copy() for lp in loops]
    if not pts:
        return
    x0, y0 = min(p.x for p in pts), min(p.y for p in pts)
    w = (max(p.x for p in pts) - x0) or 1.0
    h = (max(p.y for p in pts) - y0) or 1.0
    for lp, p in zip(loops, pts):
        lp[uv].uv = ((p.x - x0) / w, (p.y - y0) / h)


class _ObjectFaces:
    """From object mode: the selected meshes in edit mode with every face selected (Maya converts an object selection
    to its faces for UV projections, performPolyProjectionArgList.mel:621-634, performPolyAutoProj.mel:460-464), back to
    object mode afterwards. In edit mode: nothing."""

    def __init__(self, context):
        self.context = context
        self.entered = False

    def __enter__(self):
        context = self.context
        if context.mode == 'EDIT_MESH':
            return [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
        meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if not meshes:
            return []
        if context.view_layer.objects.active not in meshes:
            context.view_layer.objects.active = meshes[0]
        bpy.ops.object.mode_set(mode='EDIT')
        self.entered = True
        bpy.ops.mesh.select_mode(type='FACE')
        bpy.ops.mesh.select_all(action='SELECT')
        return [o for o in bpy.context.objects_in_mode_unique_data if o.type == 'MESH']

    def __exit__(self, *exc):
        if self.entered:
            bpy.ops.object.mode_set(mode='OBJECT')
        return False


def _mesh_poll(context):
    if context.mode == 'EDIT_MESH':
        return True
    return context.mode == 'OBJECT' and any(o.type == 'MESH' for o in context.selected_objects)


PLANE_ITEMS = [(n, n, f"{n} projection planes") for n in ("3", "4", "5", "6", "8", "12")]


class ALLSET_OT_uv_automatic(bpy.types.Operator):
    """Project UVs from several planes at once (Maya UV > Automatic): the selected faces, or every face of the
    selected meshes in object mode"""
    bl_idname = "allset.uv_automatic"
    bl_label = "Automatic"
    bl_options = {'REGISTER', 'UNDO'}

    planes: EnumProperty(name="Planes", items=PLANE_ITEMS, default="6")
    spacing: FloatProperty(name="Percentage Space", default=0.2, min=0.0, max=5.0)

    poll = classmethod(lambda cls, context: _mesh_poll(context))

    def execute(self, context):
        n = 0
        with _ObjectFaces(context) as obs:
            for ob in obs:
                bm = bmesh.from_edit_mesh(ob.data)
                uv = bm.loops.layers.uv.verify()
                faces = [f for f in bm.faces if f.select and not f.hide]
                if faces:
                    n += auto_project(bm, uv, faces, self.planes, self.spacing)
                    bmesh.update_edit_mesh(ob.data)
        if not n:
            self.report({'WARNING'}, "Select faces (or a mesh) to project.")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_uv_contour(bpy.types.Operator):
    """Lay the selected faces out along their quad grid and stretch them to fill 0-1 (Maya UV > Contour Stretch;
    Blender Follow Active Quads): every face of the selected meshes in object mode"""
    bl_idname = "allset.uv_contour"
    bl_label = "Contour Stretch"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(lambda cls, context: _mesh_poll(context))

    def execute(self, context):
        done = 0
        with _ObjectFaces(context) as obs:
            for ob in obs:
                bm = bmesh.from_edit_mesh(ob.data)
                uv = bm.loops.layers.uv.verify()
                faces = [f for f in bm.faces if f.select and not f.hide]
                quads = [f for f in faces if len(f.verts) == 4]
                if not quads:
                    continue
                if bm.faces.active not in quads:
                    bm.faces.active = quads[0]
                bmesh.update_edit_mesh(ob.data)
                with context.temp_override(active_object=ob, object=ob, edit_object=ob,
                                           objects_in_mode=[ob], objects_in_mode_unique_data=[ob]):
                    try:
                        _with_faces(context, ob, faces, lambda: bpy.ops.uv.follow_active_quads(mode='LENGTH_AVERAGE'))
                    except RuntimeError:
                        continue
                bm = bmesh.from_edit_mesh(ob.data)
                uv = bm.loops.layers.uv.verify()
                fit_unit([lp for f in bm.faces if f.select and not f.hide for lp in f.loops], uv)
                bmesh.update_edit_mesh(ob.data)
                done += 1
        if not done:
            self.report({'WARNING'}, "Select quad faces (or a mesh) for Contour Stretch.")
            return {'CANCELLED'}
        return {'FINISHED'}


# --- Texel Density -----------------------------------------------------------------------------------

def _uv_area(face, uv):
    pts = [l[uv].uv for l in face.loops]
    return abs(sum(pts[i].x * pts[i - 1].y - pts[i - 1].x * pts[i].y for i in range(len(pts)))) / 2


def _world_area(face, mw):
    pts = [mw @ v.co for v in face.verts]
    area = Vector()
    for i in range(1, len(pts) - 1):
        area += (pts[i] - pts[0]).cross(pts[i + 1] - pts[0])
    return area.length / 2


def density(faces, uv, mw, map_size, unit):
    """Pixels per Maya unit of ``faces``: sqrt(UV area * map^2 / world area in Maya units^2)."""
    uva = sum(_uv_area(f, uv) for f in faces)
    wa = sum(_world_area(f, mw) for f in faces) / (unit * unit)
    return math.sqrt(uva * map_size * map_size / wa) if wa > 1e-12 and uva > 0 else 0.0


def scale_island(island, uv, factor):
    c = uv_centre(island, uv)
    for loop in _island_loops(island):
        loop[uv].uv = c + (loop[uv].uv - c) * factor


def _edit_meshes(context):
    return [o for o in getattr(context, "objects_in_mode_unique_data", ()) if o.type == 'MESH']


# --- operators ---------------------------------------------------------------------------------------

def _uv_poll(context):
    return context.mode == 'EDIT_MESH'


@undo_steps.no_redo_panel      # step 147: no Adjust Last Operation (Maya has none)
class ALLSET_OT_uv_cut(bpy.types.Operator):
    """Cut the UVs along the selected edges (Maya Cut UV Edges): a seam, and the shells separate in place"""
    bl_idname = "allset.uv_cut"
    bl_label = "Cut UV Edges"
    bl_options = {'REGISTER', 'UNDO'}

    # 3D Cut and Sew tool x (step 79): the edges selected in the 3D View, whatever the UV sync setting
    mesh_select: BoolProperty(name="3D View Edges", default=False, options={'SKIP_SAVE'})

    poll = classmethod(lambda cls, context: _uv_poll(context))

    def execute(self, context):
        done = 0
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            edges = selected_edges(bm, uv, sync(context) or self.mesh_select)
            if edges:
                cut(bm, uv, edges)
                bmesh.update_edit_mesh(ob.data)
                done += len(edges)
        if not done:
            self.report({'WARNING'}, "Select edges to cut")
            return {'CANCELLED'}
        return {'FINISHED'}


@undo_steps.no_redo_panel      # step 147: no Adjust Last Operation (Maya has none)
class ALLSET_OT_uv_sew(bpy.types.Operator):
    """Sew the UVs along the selected edges (Maya Sew UV Edges): the smaller shell moves onto the bigger one"""
    bl_idname = "allset.uv_sew"
    bl_label = "Sew UV Edges"
    bl_options = {'REGISTER', 'UNDO'}

    mesh_select: BoolProperty(name="3D View Edges", default=False, options={'SKIP_SAVE'})   # step 79 tool s

    poll = classmethod(lambda cls, context: _uv_poll(context))

    def execute(self, context):
        done = 0
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            edges = selected_edges(bm, uv, sync(context) or self.mesh_select)
            if edges:
                done += sew(bm, uv, edges)
                bmesh.update_edit_mesh(ob.data)
        if not done:
            self.report({'WARNING'}, "Select edges between UV shells to sew")
            return {'CANCELLED'}
        return {'FINISHED'}


class ALLSET_OT_uv_unfold(bpy.types.Operator):
    """Unfold the selected UV shells (all when none are selected), keeping their borders and places
    (Maya Unfold; Blender Unwrap, Minimum Stretch)"""
    bl_idname = "allset.uv_unfold"
    bl_label = "Unfold"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(lambda cls, context: _uv_poll(context))

    def execute(self, context):
        n = sum(unfold(context, ob) for ob in _edit_meshes(context))
        if not n:
            return {'CANCELLED'}
        results.result(self, NOTICE_UNFOLD)
        return {'FINISHED'}


@undo_steps.no_redo_panel      # step 147: no Adjust Last Operation (Maya has none)
class ALLSET_OT_uv_layout(bpy.types.Operator):
    """Lay the selected UV shells (all when none are selected) out in 0-1 (Maya Layout; Blender Pack Islands)"""
    bl_idname = "allset.uv_layout"
    bl_label = "Layout"
    bl_options = {'REGISTER', 'UNDO'}

    shell_padding: FloatProperty(name="Shell Padding (px)", default=MAYA_SHELL_PADDING, min=0.0, soft_max=64.0)
    map_size: IntProperty(name="Map Size", default=MAYA_MAP_SIZE, min=1)

    poll = classmethod(lambda cls, context: _uv_poll(context))

    def invoke(self, context, event):
        s = settings(context)
        self.shell_padding, self.map_size = s.shell_padding, s.map_size
        return self.execute(context)

    def execute(self, context):
        n = sum(layout(context, ob, self.shell_padding, self.map_size) for ob in _edit_meshes(context))
        return {'FINISHED'} if n else {'CANCELLED'}


class ALLSET_OT_uv_texel_get(bpy.types.Operator):
    """Measure the texel density of the selected UV shells (all when none are selected): pixels per Maya unit"""
    bl_idname = "allset.uv_texel_get"
    bl_label = "Get Texel Density"
    bl_options = {'REGISTER', 'INTERNAL'}

    poll = classmethod(lambda cls, context: _uv_poll(context))

    def execute(self, context):
        s = settings(context)
        unit = units.maya_unit(context.scene)
        uva = wa = 0.0
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            faces = [f for isl in target_islands(bm, uv, sync(context)) for f in isl]
            uva += sum(_uv_area(f, uv) for f in faces)
            wa += sum(_world_area(f, ob.matrix_world) for f in faces) / (unit * unit)
        if wa <= 1e-12:
            return {'CANCELLED'}
        s.texel_density = math.sqrt(uva * s.map_size ** 2 / wa)
        results.result(self, f"Texel density {s.texel_density:.3f} px per unit (map {s.map_size})")
        return {'FINISHED'}


class ALLSET_OT_uv_texel_set(bpy.types.Operator):
    """Scale the selected UV shells (all when none are selected) to the texel density (pixels per Maya unit)"""
    bl_idname = "allset.uv_texel_set"
    bl_label = "Set Texel Density"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(lambda cls, context: _uv_poll(context))

    def execute(self, context):
        s = settings(context)
        if s.texel_density <= 0:
            self.report({'WARNING'}, "Get a texel density first (or type one)")
            return {'CANCELLED'}
        unit = units.maya_unit(context.scene)
        done = 0
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            uv = bm.loops.layers.uv.verify()
            for isl in target_islands(bm, uv, sync(context)):
                d = density(isl, uv, ob.matrix_world, s.map_size, unit)
                if d > 0:
                    scale_island(isl, uv, s.texel_density / d)
                    done += 1
            bmesh.update_edit_mesh(ob.data)
        return {'FINISHED'} if done else {'CANCELLED'}


# --- UV Editor and UV components --------------------------------------------------------------------

COMPONENTS = (('VERTEX', "Vertex", "Mesh vertices (UV Sync Selection on)"),
              ('EDGE', "Edge", "Mesh edges (UV Sync Selection on)"),
              ('FACE', "Face", "Mesh faces (UV Sync Selection on)"),
              ('UV', "UV", "UVs picked apart from the mesh (UV Sync Selection off)"),
              ('SHELL', "UV Shell", "Whole UV shells = Blender UV islands (UV Sync Selection off)"),
              ('OPEN', "Open", "Only open the UV Editor"))


def find_uv_editor(context):
    for win in context.window_manager.windows:
        for area in win.screen.areas:
            if area.ui_type == 'UV':
                return win, area
    return None, None


def prepare(context):
    """Edit mode on the active mesh with UV Sync Selection on (the UVs show in the UV Editor at once)."""
    ob = context.view_layer.objects.active
    if ob is None or ob.type != 'MESH':
        return False
    if ob.mode != 'EDIT':
        if not ob.select_get():
            ob.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
    context.scene.tool_settings.use_uv_select_sync = True
    return True


# Maya keeps each component type's selection: F12 (UV) and back to F9 / F10 / F11 shows the vertices / edges / faces
# selected before. Kit UV mode selects every face (sync off draws only selected faces' UVs), so the mesh selection
# from before it is kept here and put back when a mesh component mode comes back (issue #80).
_MESH_SELECTION = {}     # object name -> ((verts, edges, faces) counts, selected vert / edge / face indices)


def _counts(bm):
    return len(bm.verts), len(bm.edges), len(bm.faces)


def remember_mesh_selection(context):
    _MESH_SELECTION.clear()
    for ob in _edit_meshes(context):
        bm = bmesh.from_edit_mesh(ob.data)
        _MESH_SELECTION[ob.name] = (_counts(bm), [v.index for v in bm.verts if v.select],
                                    [e.index for e in bm.edges if e.select], [f.index for f in bm.faces if f.select])


def forget_mesh_selection():
    _MESH_SELECTION.clear()


def leave_uv_mode(context):
    """Maya F9 / F10 / F11 after F12 / Alt+F12: UV Sync Selection back on and the mesh selection from before UV mode
    back (when the mesh still has the same element counts)."""
    ts = context.scene.tool_settings
    if ts.use_uv_select_sync:
        return
    ts.use_uv_select_sync = True
    for ob in _edit_meshes(context):
        saved = _MESH_SELECTION.get(ob.name)
        bm = bmesh.from_edit_mesh(ob.data)
        if saved is None or saved[0] != _counts(bm):
            continue
        seqs = (bm.verts, bm.edges, bm.faces)
        for seq in seqs:      # all off first: a face's / edge's ``select = False`` also drops its vertices
            for el in seq:
                el.select = False
        for seq, chosen in zip(seqs, saved[1:]):
            seq.ensure_lookup_table()
            for i in chosen:
                seq[i].select = True
        bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)
    _MESH_SELECTION.clear()


def set_component(context, mode):
    ts = context.scene.tool_settings
    if mode in ('VERTEX', 'EDGE', 'FACE'):
        leave_uv_mode(context)
        ts.mesh_select_mode = (mode == 'VERTEX', mode == 'EDGE', mode == 'FACE')
    elif mode in ('UV', 'SHELL'):
        ts.use_uv_select_sync = False
        compat.set_uv_island_mode(ts, mode == 'SHELL')
        # without sync Blender draws only the selected faces' UVs: Maya shows them all
        for ob in _edit_meshes(context):
            bm = bmesh.from_edit_mesh(ob.data)
            for f in bm.faces:
                if not f.hide:
                    f.select_set(True)
            bmesh.update_edit_mesh(ob.data)


class ALLSET_OT_uv_component(bpy.types.Operator):
    """Maya UV components: open the UV Editor (once) and pick Vertex / Edge / Face / UV / UV Shell there.
    Blender picks UVs in the UV Editor only"""
    bl_idname = "allset.uv_component"
    bl_label = "UV Component"
    bl_options = {'UNDO'}

    mode: EnumProperty(items=COMPONENTS, name="Component", default='UV')

    @classmethod
    def poll(cls, context):
        ob = context.view_layer.objects.active if context.view_layer else None
        target = getattr(context.window_manager, "allset_mm_target", "")
        return (ob is not None and ob.type == 'MESH') or bool(target)

    def execute(self, context):
        target = bpy.data.objects.get(getattr(context.window_manager, "allset_mm_target", "") or "")
        if target is not None and target.type == 'MESH' and context.mode == 'OBJECT':
            for o in context.selected_objects:
                if o is not target:
                    o.select_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
        ts = context.scene.tool_settings
        # coming from a mesh component mode (or object mode): keep its selection for F9 / F10 / F11 (#80)
        remember = self.mode in ('UV', 'SHELL') and (context.mode != 'EDIT_MESH' or ts.use_uv_select_sync)
        if self.mode in ('VERTEX', 'EDGE', 'FACE') and context.mode == 'EDIT_MESH':
            leave_uv_mode(context)     # before prepare() turns UV Sync Selection on
        if not prepare(context):
            self.report({'WARNING'}, "Select a mesh")
            return {'CANCELLED'}
        if remember:
            remember_mesh_selection(context)
        # open the editor first: its prepare() turns UV Sync Selection on, which undid F12's UV mode the first time
        # (issue #80)
        if find_uv_editor(context)[1] is None and context.window is not None and not bpy.app.background:
            bpy.ops.allset.open_editor(ui_type='UV')
        if self.mode != 'OPEN':
            set_component(context, self.mode)
        return {'FINISHED'}


classes = (ALLSET_OT_uv_cut, ALLSET_OT_uv_sew, ALLSET_OT_uv_unfold, ALLSET_OT_uv_layout, ALLSET_OT_uv_texel_get,
           ALLSET_OT_uv_texel_set, ALLSET_OT_uv_component, ALLSET_OT_uv_automatic, ALLSET_OT_uv_contour)
