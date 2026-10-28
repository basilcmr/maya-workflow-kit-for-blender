# Cinema 4D Workflow Kit for Blender (C4D-Kit)
## Vibe Coding Roadmap & Module Blueprint

This document outlines the step-by-step strategy for transforming the **Maya Workflow Kit (`allset`)** codebase into a **Cinema 4D Workflow Kit for Blender** using Gemini 3.8 Flash in Antigravity.

---

## 1. Architectural Strategy & Philosophy

The Maya kit is over 50,000 lines of code because Maya differs drastically from Blender in its graph architecture, multiple attribute editors, and complex marking menus.

**Cinema 4D is much closer to Blender.** Therefore, the goal is **NOT** to blindly port every single Maya file, but to:
1. **Reuse the Rock-Solid Core Infrastructure**: Clean on/off state switching (`switch.py`), keymap isolation & patching (`patch.py`), version compatibility (`compat.py`), and preferences persistence.
2. **Prune Maya Specifics**: Strip out `maya.cmds` shims, Space-hold Hotbox, DAG path emulations, and Channel Box/Attribute Editor dual-pane duplication.
3. **Build C4D Muscle Memory**: Navigation (`1`/`2`/`3`), transform hotkeys (`E`/`R`/`T`), C4D layout (Object Manager + Attributes Manager + Material Manager), and signature tools like the `Shift + C` Commander.

---

## 2. Target File Structure

```text
src/c4dkit/
├── __init__.py                 # Add-on entry point & registration
├── blender_manifest.toml       # Blender 4.5+ extension manifest
├── compat.py                   # Blender version compatibility shims (keep from allset)
├── switch.py                   # On/Off switch between Blender Mode and C4D Mode
├── preferences.py              # User preferences & customization settings
│
├── keymap/                     # --- KEYMAP & INPUT SYSTEM ---
│   ├── __init__.py             # Keymap registration / unregistration hooks
│   ├── patch.py                # Non-destructive keymap patching engine
│   ├── mapping.py              # Active C4D keybindings table
│   └── navigation.py           # 1/2/3 navigation & Alt navigation modal handlers
│
├── ui/                         # --- LAYOUT & INTERFACE ---
│   ├── __init__.py
│   ├── workspaces.py           # C4D Standard Layout (Object/Attr/Material layout)
│   ├── commander.py            # Shift + C fuzzy search palette
│   ├── v_menu.py               # 'V' key contextual radial/popup menu
│   ├── status_bar.py           # Bottom info, coordinates, & take/mode display
│   └── outliner_tags.py        # Outliner tweaks (C4D-style visibility/material tags)
│
└── operators/                  # --- C4D BEHAVIORS & OPERATORS ---
    ├── __init__.py
    ├── generator_parent.py     # Alt-click on generators (SubD, Array) to auto-parent
    ├── selection_modes.py      # Points, Edges, Polygons, Model mode toggles
    └── primitive_helpers.py    # C4D-style parametric primitives & naming
```

---

## 3. Module-by-Module Execution Steps

Follow these phases sequentially with Gemini in Antigravity.

### Phase 1: Core Foundation & Rebranding
**Goal**: Create a clean, bootable fork of the extension that can be enabled in Blender without errors.

- [ ] **Step 1.1: Extension Manifest & Identity**
  - **Files**: `blender_manifest.toml`, `src/allset/__init__.py` $\to$ `src/c4dkit/__init__.py`
  - **Task**: Update extension metadata (id: `c4d_workflow_kit`, title: `Cinema 4D Workflow Kit`, author, tags).
  - *Gemini Prompt*: *"Update `blender_manifest.toml` and root `__init__.py` to rebrand `allset` into `c4dkit`. Set clean entry points."*

- [ ] **Step 1.2: Pruning Unnecessary Maya Systems**
  - **Task**: Safely strip out:
    - `src/allset/command_line/` (Maya MEL / `maya.cmds` shims)
    - `src/allset/marking/` (Maya multi-zone Space Hotbox)
    - Redundant Maya panels (`channel_box.py`, `attribute_editor.py` dual stack)
  - *Gemini Prompt*: *"Clean up imports in `switch.py` and preferences to remove all references to `command_line` and `marking` modules so the switch only manages keymaps and UI layouts."*

- [ ] **Step 1.3: Verify Mode Switcher (`switch.py`)**
  - **Files**: `switch.py`, `preferences.py`
  - **Task**: Ensure the top-bar button says **"Cinema 4D | Blender"** and toggles cleanly without leaving residual keymaps.

---

### Phase 2: Navigation & Keymap (The Muscle Memory)
**Goal**: Match Cinema 4D's essential keyboard & mouse interactions.

- [ ] **Step 2.1: 1 / 2 / 3 Viewport Navigation**
  - **Files**: `keymap/navigation.py`, `keymap/mapping.py`
  - **C4D Actions**:
    - `1` + LMB drag $\to$ Pan / Track view
    - `2` + LMB drag $\to$ Dolly / Zoom view
    - `3` + LMB drag $\to$ Tumble / Orbit view
    - Also support `Alt + MMB` (Pan), `Alt + RMB` (Zoom), `Alt + LMB` (Orbit).
  - *Gemini Prompt*: *"In `keymap/navigation.py`, implement modal key handlers for holding keys 1, 2, and 3 while dragging LMB to pan, zoom, and rotate the 3D viewport, mirroring Cinema 4D."*

- [ ] **Step 2.2: Standard C4D Transform & Selection Keys**
  - **Files**: `keymap/mapping.py`
  - **Keybindings**:
    - `Space`: Toggle between current tool and Selection tool (Live Selection).
    - `E`: Move tool (`builtin.move`).
    - `R`: Rotate tool (`builtin.rotate`).
    - `T`: Scale tool (`builtin.scale`).
    - `Ctrl + R`: Render Active View (`render.render`).
    - `O`: Frame Selected (`view3d.view_selected` / Outliner sync).
    - `H`: Frame All (`view3d.view_all`).

- [ ] **Step 2.3: Component Selection Modes**
  - **Files**: `operators/selection_modes.py`, `keymap/mapping.py`
  - **C4D Actions**:
    - Point Mode (Vertex edit mode)
    - Edge Mode (Edge edit mode)
    - Polygon Mode (Face edit mode)
    - Model / Object Mode (Object mode)
    - Key mappings: C4D uses `Enter` to toggle between Object / Element modes, or custom side toolbar buttons.

---

### Phase 3: Layout & Workspaces
**Goal**: Recreate the iconic Cinema 4D Standard layout inside Blender.

- [ ] **Step 3.1: The C4D Standard Workspace**
  - **Files**: `ui/workspaces.py`
  - **Layout Configuration**:
    - **Center**: Large 3D Viewport.
    - **Top Right**: Outliner (emulating C4D's **Object Manager**).
    - **Bottom Right**: Properties Editor (emulating C4D's **Attribute Manager**).
    - **Bottom Area**: Material List / Asset Browser (emulating C4D's **Material Manager**).
    - **Left Toolbar**: Clean single-column active tools (Select, Move, Rotate, Scale, Points, Edges, Polys).
  - *Gemini Prompt*: *"Rewrite `ui/workspaces.py` to construct a new workspace layout named 'C4D Standard' with an Outliner top-right, Properties bottom-right, and Material panel bottom-center."*

- [ ] **Step 3.2: Coordinate & Status Bar**
  - **Files**: `ui/status_bar.py`
  - **C4D Feature**: Bottom-right coordinate manager (Position, Size, Rotation X/Y/Z) for quick numeric transformations.

---

### Phase 4: Signature C4D Power Features
**Goal**: Add the quality-of-life tools that make C4D feel uniquely fast.

- [ ] **Step 4.1: The `Shift + C` Commander**
  - **Files**: `ui/commander.py`
  - **C4D Feature**: Floating search bar centered under the mouse that does instant fuzzy search across all commands, modifiers, objects, and materials.
  - *Gemini Prompt*: *"Create a floating popup search dialog in `ui/commander.py` triggered by `Shift+C` that allows fuzzy searching and executing Blender operators, adding modifiers, and creating primitives."*

- [ ] **Step 4.2: The 'V' Radial / Context Menu**
  - **Files**: `ui/v_menu.py`
  - **C4D Feature**: Pressing `V` opens a fast radial pie menu containing top-level C4D categories (Select, Tools, Modes, Snap, Workplanes, View).

- [ ] **Step 4.3: Generator Auto-Parenting (Alt-Click Workflow)**
  - **Files**: `operators/generator_parent.py`
  - **C4D Behavior**: In C4D, holding `Alt` while clicking a Generator (like Subdivision Surface, Array, or Boole) automatically makes the selected object a child of that generator.
  - *Implementation in Blender*: An operator that either adds the corresponding Modifier directly to the active object or groups it into a Collection/Geometry Node setup.

---

## 4. Best Practices for Vibe Coding with Gemini in Antigravity

1. **One Focus File per Turn**:
   - Don't ask Gemini to update the keymap, workspaces, and operators in a single prompt.
   - Keep tasks focused: *"Today we are working strictly on `keymap/navigation.py` to get `1/2/3` keys working."*
2. **Immediate In-App Testing**:
   - Have Blender open in the background. After modifying a file, reload scripts in Blender (`F3` $\to$ `Reload Scripts` or restart) to test the change right away.
3. **Use Git Commits as Save Points**:
   - Commit after completing each sub-phase (e.g., `git commit -m "feat: c4d 1/2/3 navigation implemented"`). If an experiment breaks, you can instantly roll back.
4. **Leverage Existing Code**:
   - When asking Gemini for an operator, point to an existing pattern: *"Look at how `src/allset/keymap/patch.py` registers modal operators and follow the exact same pattern for C4D."*

