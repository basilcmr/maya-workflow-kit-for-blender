# SPDX-License-Identifier: GPL-3.0-or-later
"""Cinema 4D Workflow Kit: make Blender feel like Cinema 4D (keymap, navigation, layout, tools).

Shipped as a Blender 4.5+ extension.
Core modules manage preferences and state switching.
Mode modules register C4D-specific keymaps, workspaces, and operators when C4D mode is active.
"""

from . import preferences, switch, welcome, operators, ui, first_start, keymap

# Always registered: preferences, state switch, welcome/opt-in.
CORE = (preferences, switch, welcome)

# Registered while C4D mode is active:
MODE = (operators, ui, first_start, keymap)


def register():
    for mod in CORE:
        mod.register()
    if switch.is_on():
        switch.register_mode()
        switch._registered[0] = True


def unregister():
    if switch._registered[0]:
        switch.unregister_mode()
        switch._registered[0] = False
    for mod in reversed(CORE):
        mod.unregister()
