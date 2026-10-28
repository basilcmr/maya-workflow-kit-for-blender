# SPDX-License-Identifier: GPL-3.0-or-later
"""The opt-in: nothing changes until the user asks for Maya (docs/steps/step_115.md).

Part of CORE (registered whenever the extension is enabled, also in Blender mode). Enabling the extension only adds
the Maya | Blender switch, an Edit menu item, Ctrl+Alt+Shift+M and, once in a GUI session, this welcome dialog. Its
confirm button "Make Blender feel like Maya" (also in the add-on preferences) turns on Maya mode and Make Blender
Maya (``first_start.make``: start in the Maya layout, the layout shown now). Cancelling changes nothing. Blender's
preferences are never written (step 130).

Not in background runs; GUI tests and tools set ``ALLSET_NO_WELCOME=1`` (the dialog would eat simulated events).
"""

import os

import bpy

from . import preferences

# Square art made by tools/make_splash.py (icons are square; the 2:1 splash would letterbox).
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), "welcome.png")
_previews = None


def _splash_icon():
    global _previews
    if not os.path.isfile(WELCOME_IMAGE):
        return 0
    if _previews is None:
        import bpy.utils.previews
        _previews = bpy.utils.previews.new()
    if "splash" not in _previews:
        _previews.load("splash", WELCOME_IMAGE, 'IMAGE')
    return _previews["splash"].icon_id


def _window():
    wm = bpy.context.window_manager
    return wm.windows[0] if wm and wm.windows else None


def opt_in(open_layout=True):
    """Everything "Make Blender feel like Maya" does. Runs from a timer (switching registers the Maya mode
    modules, which an operator of theirs must not do while it runs; docs/steps/step_42.md)."""
    from . import switch
    switch.set_mode(True, layout=False)
    from . import first_start
    first_start.make(bpy.context, open_layout=False)
    if open_layout:
        # an untouched new file: a new Maya scene; the user's file: the layout workspace appended, data kept
        first_start.show_layout(_window())


# Body text, wrapped to the measured room left of the icon: fixed lines were cut ("the Maya colou...") at 125 %
# UI scale (step 124).
PARAGRAPHS = (
    "The whole Maya workflow in Blender, in one install.",
    "Nothing has changed yet. Make Blender feel like Maya turns on the Maya-style keys: Alt+mouse, QWER, Space "
    "hotbox, marking menus; the Maya layout, menus, Channel Box and shelf.",
    "Your Blender preferences are never changed: the Maya | Blender switch at the top right or Ctrl+Alt+Shift+M "
    "goes back to plain Blender at any time.",
    # step 141 (B6): the kit may not raise Blender's undo depth itself
    "Tip: Maya's undo is unlimited, Blender keeps 32 steps by default. Raise Edit > Preferences > System > Undo "
    "Steps to 256 if you like Maya's long undo.",
)
DIALOG_WIDTH = 640      # unscaled px
ICON_SCALE = 7.0        # template_icon scale = 20 px units
ICON_FACTOR = (ICON_SCALE * 20 + 16) / DIALOG_WIDTH     # icon column share of the split
TEXT_PAD = 40           # dialog margins + label padding, unscaled px (generous: a cut word is worse than a short line)


def text_room(with_icon=True):
    """Unscaled px a body line may take."""
    return DIALOG_WIDTH * ((1.0 - ICON_FACTOR) if with_icon else 1.0) - TEXT_PAD


def text_width(text, size):
    import blf
    blf.size(0, size)
    return blf.dimensions(0, text)[0]


def wrap(text, width, size, measure=text_width):
    """Words of ``text`` in lines no wider than ``width`` px at font ``size`` (a word longer than a line stays whole)."""
    lines, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}" if cur else word
        if cur and measure(cand, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


class ALLSET_OT_welcome(bpy.types.Operator):
    """Turn on the Maya-style keys, layout and menus (asks first). Blender's preferences are not changed;
    Ctrl+Alt+Shift+M or the Maya / Blender switch turns it off again"""
    bl_idname = "allset.welcome"
    bl_label = "Make Blender feel like Maya"
    bl_options = {'INTERNAL'}

    open_layout: bpy.props.BoolProperty(name="Open Maya Layout", default=True, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        preferences.get(context).welcome_done = True    # asked once, never again
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, title="Welcome to Maya Workflow Kit", confirm_text="Make Blender feel like Maya")

    def draw(self, context):
        icon = _splash_icon()
        if icon:    # a plain row halves the dialog (measured): give the icon only its own width
            row = self.layout.split(factor=ICON_FACTOR)
            row.template_icon(icon_value=icon, scale=ICON_SCALE)
        else:
            row = self.layout.row()
        col = row.column()
        col.label(text="Maya Workflow Kit")
        scale = context.preferences.system.ui_scale or 1.0      # 0 in background
        size = context.preferences.ui_styles[0].widget.points * scale
        width = text_room(bool(icon)) * scale
        for k, para in enumerate(PARAGRAPHS):
            if k:
                col.separator()
            for line in wrap(para, width, size):
                col.label(text=line)

    def execute(self, context):
        preferences.get(context).welcome_done = True
        open_layout = self.open_layout
        bpy.app.timers.register(lambda: opt_in(open_layout), first_interval=0.0)
        return {'FINISHED'}


def _show_welcome():
    try:
        prefs = preferences.get()
    except KeyError:
        return None
    if prefs.welcome_done or prefs.maya_mode:
        return None
    win = _window()
    if win is None:
        return 0.5
    with bpy.context.temp_override(window=win, screen=win.screen):
        bpy.ops.allset.welcome('INVOKE_DEFAULT')
    return None


classes = (ALLSET_OT_welcome,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background and os.environ.get("ALLSET_NO_WELCOME") != "1":
        bpy.app.timers.register(_show_welcome, first_interval=0.5)


def unregister():
    global _previews
    if bpy.app.timers.is_registered(_show_welcome):
        bpy.app.timers.unregister(_show_welcome)
    if _previews is not None:
        bpy.utils.previews.remove(_previews)
        _previews = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
