# Changelog

**English** · [Русский](CHANGELOG.ru.md)

Versions 0.1–0.12 were released before this repository was created.

## 0.19.0

- **Placement at text cursor**: new *At text cursor* option and toggle to insert newly created nodes, beams, and triangles/quads right where the text editor cursor is positioned.
- **Graceful mismatch handling**: if the text cursor is in a section different from what is being added (e.g. cursor is in `nodes` while adding `beams`), the action is never restricted or cancelled; elements are placed at the end of their table with an informative, dismissible UI warning.
- **Default display out of the box**: nodes, normal beams, and through-faces are now enabled by default so JBeam structures are immediately visible in color through faces upon importing.
- **UI layout & grouping overhaul**:
  - Reorganized main action bar into a clean 2x2 grid (`Apply`, `Save`, `Auto Save`, `At Cursor`) that never gets truncated.
  - Regrouped `Tools` panel into 3 distinct sections: *Edit & Clipboard*, *Symmetry & Mirror*, and *Mesh Operations*, with full-width live mesh symmetry controls (`X`, `Y`, `Z`).
  - Improved `Display`, `Editing`, and `Text Editor` panels with dedicated cards and 2-column alignments avoiding text truncation in narrow sidebars.
- **Extended clipboard and hotkeys**: `Copy`, `Cut`, and `Delete` (`Ctrl+C`, `Ctrl+X`, `Delete`) work seamlessly for beams and faces as well as nodes, both in 3D Viewport and Text Editor selections.
- **Safer node deletion**: deleting nodes in vertex select mode preserves dependent beams and faces rather than cascading deletions.
- **Selection raycast occlusion**: new *Only Visible* filter option preventing accidental selection of nodes occluded behind solid faces.
- **Horizontal scrolling**: added support for mouse horizontal scroll in the text editor.
- **Blender 4.x / 5.2 compatibility & fixes**: fixed `icon="CUT"` crash by replacing with `icon="REMOVE"`, and fixed black shading / matcap normals artifact after text edits.

## 0.18.1

- The warning about nodes that other imported parts also have is gone, with its red marks: it also marked the nodes of parts that are never fitted together, such as variants of one wing.

## 0.18.0

- The first full release, no longer a preview, with the repository public.

## 0.17.1

- The warning about nodes that other parts in the scene already have is clearer and fits the panel.
- The README shows every display setting: beams by type, through faces or not, every gradient, break and deform groups, parts, nodes by flags, group and weight, node names, hydros, torsion bars and rails, dimmed and hidden parts, the popover, the panels, a part with the nodes of other parts and the warning about shared node names; the Russian README with the Russian interface.

## 0.17.0

- The default colours are those of the game's debug view: beam types (`|NORMAL` green, `|SUPPORT` magenta, `|BOUNDED` yellow, `|ANISOTROPIC` orange, `|LBEAM` grey, `|PRESSURED` cyan), nodes by their flags (`fixed`, `selfCollision`, `collision: false`), hydros blue, torsion bars as two triangles with an orange axis, a colour for each rail with its slide nodes, break and deform groups in the game's contrast colours, values from white to red with `FLT_MAX` in magenta, node names in magenta and a red centre of mass.
- Nodes that two imported parts both define, such as a new node of the front door named like a node of the rear door, are reported in the panel and marked in red. Alternative parts of one slot do not count.
- A new README in English and Russian with screenshots of the ETK 800, a changelog, contribution notes and issue templates; `scripts/screenshots.py` takes the screenshots again.

## 0.16.0

- Speed with a whole vehicle imported part by part: moving a node with Auto took a minute or more and now takes a fraction of a second. Parts that share edited files take the edit when editing pauses, joining it line by line with their own edits.
- Moving the view no longer lags: what is drawn over objects is kept on the GPU and worked out again only when something changes. Names of all nodes draw about four times faster.
- Display settings for everything, in the sidebar and under the JBeam button in the viewport header: where the colours are shown (all, selected, active, with the others dimmed), every colour, size and width, gradients, break and deform groups, parts; kept between Blender sessions.
- The selection is drawn over the colours in Edit Mode; problems are marked in red; a centre of mass for the selected nodes.
- The panels are regrouped: Display and Text Editor have their own panels.
- Subdividing a face no longer turns the faces around it into flat quads.
- *All parts* leaves out parts without nodes, beams or faces.

## 0.14.0

- Faces hide the coloured beams, nodes, hydros, rails and node names behind them, except in X-ray, in wireframe and with the new *Through faces* button.
- Several files at once, with a list of their parts to tick.
- Parts of one `.jbeam` file imported on their own share their edits.
- Line width and opacity, beams by `beamSpring`, `beamDamp`, `beamDeform` or `beamStrength`, nodes by `nodeWeight`.
- The mass of the vehicle, the part and the selection, and the centre of mass.

## 0.13.0

- A vehicle becomes an object for each part, in a collection for each `.jbeam` file under one JBeam collection; Tab opens them all, and parts edited together are applied together.
- Nodes of other parts used by a part are shown in orange; *All vehicle nodes* shows every node of the vehicle.

## 0.12.0

- First release in this repository, the same add-on as 0.12.0 before the move.

## 0.11.0

- Rows that reference a missing node are marked `"optional": true` instead of being deleted.

## 0.10.0

- Hydros, torsion bars, torsion hydros, rails and slide nodes: drawn, listed, added from selected nodes and deleted.

## 0.9.0

- Fix buttons in Diagnostics: missing nodes, repeated beams, resets for parts that leak modifiers.

## 0.8.0

- Clicking a row in the text editor selects it in the viewport.

## 0.7.0

- Beams of special types and node groups in colour, with a legend.

## 0.6.0

- Properties of the selection with edit buttons and documentation links, *Set Property*, *Select by Property*, node groups.

## 0.5.0

- Where new rows go, modifier leaks and *Add Resets*, mirroring across X, Y or Z.

## 0.4.0

- *Mirror Selected Nodes* and mirrored moves.

## 0.3.0 – 0.3.2

- Edits applied right away in Edit Mode, with undo; JBeam syntax colours and problems in the text editor; new nodes named after their neighbours.

## 0.2.0

- *Auto* save and highlighting of the selection in the text editor.

## 0.1.0

- First preview: import vehicles and parts, edit nodes, beams, triangles and quads, save.
