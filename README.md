# JBeam Studio

A Blender add-on for editing BeamNG.drive vehicles: import a whole vehicle from its part config (`.pc`) or a single part of a `.jbeam` file, edit nodes, beams, triangles and quads with Blender's modelling tools, and write the changes back. Only the edited values and rows change in the files; formatting, comments and everything else stay as they were.

This is an unofficial rewrite of BeamNG's [Blender JBeam Editor](https://github.com/BeamNG/Blender-JBeam-Editor). It is not affiliated with or endorsed by BeamNG GmbH. BeamNG is a trademark of BeamNG GmbH.

## Install

Blender 4.5 LTS or 5.2 LTS.

1. Download `jbeam_studio-<version>.zip` from Releases (or build it, see below).
2. In Blender: *Edit > Preferences > Get Extensions*, the menu in the top right corner, *Install from Disk...*, choose the zip.
3. In the add-on's preferences, set *Unpacked game vehicles* to the `vehicles` folder of unpacked game content. The add-on can unpack it for you: set *Game vehicle archives* to `BeamNG.drive/content/vehicles`, choose a folder in *Unpack into*, press *Unpack Vehicles*. Mods are then assembled with the game's common parts.

## Use

- *File > Import > JBeam Vehicle (.pc)* or *JBeam Part (.jbeam)*, or the buttons in the *JBeam* tab of the 3D viewport sidebar (N).
- Everything goes into the *JBeam* collection, with a collection for each `.jbeam` file holding an object for each of its parts. A vehicle gets an object for every part that has nodes, beams or faces; all of them are selected after the import, so Tab opens the whole vehicle in Edit Mode, each part in its own object.
- An object shows the nodes, beams and faces of its part. Nodes of other parts that its beams and faces use are shown in orange and cannot be moved or deleted there; *All vehicle nodes* (the button next to the part's name) shows every node of the vehicle in orange, to join new beams of the part to any of them. Whatever is added in an object goes to its part, and an edit in one part shows up in the other objects right away.
- Every vertex is a node, every edge a beam, every face with three or four corners a triangle or quad. Move, add, extrude, duplicate, subdivide, delete and flip (*Flip Faces*) in Edit Mode; each edit is written to the files in memory as soon as the tool finishes (*Editing > Apply right away*), and the mesh is rebuilt from them when you leave Edit Mode.
- A new node is named after the node it was extruded or copied from, or the node it is joined to: the same prefix, the next number and the side letter of its position (extruding `e3l` gives `e5l`, `e5r` on the other side, `e5` at the centre). Nodes without neighbours are named with the *New node prefix* and a number.
- *Editing > Where new rows go*: at the end of the table, after the resets (default); next to the row they come from, with its group and values (an extruded node after its source node, its beam after the beams of that node, a copied beam after the original); or into a chosen node group (a new `{"group":...}` block when the part has no such group).
- Mirroring: *Tools > Mirror Selected Nodes* copies the selected nodes, with the beams, triangles and quads that use them, to the other side of a plane across X, Y or Z through the origin, the 3D cursor or the active node, with mirrored names (`e3l`/`e3r` across X, `e3f`/`e3b` across Y, `rp3t`/`rp3d` across Z; the letters are set in the preferences); counterparts that exist are moved to the mirrored place. *Mirror Moves X/Y/Z* (Blender's mesh symmetry) moves the counterpart of a node with it while you edit.
- Modifier leaks: the game reads the rows of all parts as one table, so a modifier such as `{"group":"rotor"}` left at the end of one part also applies to the parts after it. Diagnostics report where that happens, and *Add Resets* (in *Tools*, or the fix button of the problem) adds a row that sets those keys back to the game's defaults.
- *Editing > Moving nodes*: *Overwrite coordinates* (default) writes plain numbers; *Keep expressions* keeps variables and `$=` expressions and adds the shift to them.
- Ctrl+Z and Ctrl+Shift+Z undo and redo the JBeam edits together with the mesh.
- *Save* writes the changed files. The first save of a file keeps the original next to it as `<name>.bak`. If a file was changed on disk by another program, the panel says so and offers *Reload Changed Files* or *Save Anyway*.
- *Auto* next to *Save* saves the files after every edit, rename, undo and redo, so the files on disk always match what you see. It is kept in the add-on preferences, so undo does not turn it off. Files changed on disk by another program are never overwritten automatically.
- With a file open in Blender's text editor (*Text Editor > Show Text*), the rows of the selection are highlighted: nodes in vertex select mode, beams in edge mode, triangles and quads in face mode. *Follow selection* scrolls to the row of the active element and opens its file. The other way round, *Select from text*: clicking the row of a node, beam or face in the text selects it in Edit Mode, in the matching select mode.
- JBeam files in the text editor are coloured (parts, sections, keys, strings, `$variables`, `$=` expressions, numbers, comments). Syntax errors are underlined as you type and problems found when assembling the vehicle are underlined too; the message is shown after the line and, for the line of the cursor, in the editor's footer.
- *Tools*: rename a node with every reference to it, rename the selected nodes with a prefix and numbers, select the nodes of the active part. *Text Editor*: show a file in Blender's text editor with unsaved edits, apply edits made there, and the switches of highlighting, following and colours.
- *Selection* shows the properties of what is selected, by select mode: nodes in vertex mode, beams in edge mode, triangles and quads in face mode, with the common value or "mixed" and links to the BeamNG documentation. The pencil button or *Set Property* changes a property of all of them (in its column, or in the options of each row); *Select by Property* selects, for example, every beam with `beamType` `|SUPPORT`.
- *Groups* lists the node groups of the active part (or of all parts): select, hide and show, and rename a group in every part together with the flexbodies that use it.
- *Hydros and Rails*: hydros, torsion bars, rails and slide nodes are drawn in the viewport (hydros light blue, torsion bars yellow, torsion hydros orange, rails and slide nodes pink) and listed (when nodes are selected, only those that use them): select their nodes or delete them. In Edit Mode, add a hydro from two selected nodes, a torsion bar from four (in the order they were selected; it twists about the second and third), a rail through the selected nodes in order, or slide nodes on a rail. A deleted rail takes its slide nodes with it. The arrow of an entry shows its properties, such as `inputSource` and `factor` of a hydro or `looped` of a rail, each with an edit button. *Mirror* copies them too (a mirrored rail is named with the other side letter, `boxside_R` from `boxside_L`), and clicking their row in the text editor selects their nodes. A new slide node copies the other cells of a full row of its table.
- *Diagnostics* lists problems found while assembling the vehicle. Some have a fix button, and buttons above the list fix all problems of a kind as one undo step: mark rows that reference missing nodes `"optional": true`, delete repeated beams (the first row of each stays), and add resets to parts that leak modifiers. Rows with missing nodes are never deleted: the node may come from a part of another configuration or from a mod the add-on does not see, and with `optional` the game skips the row silently while the node is missing and uses it when it exists.
- Nodes of other parts that a single imported part uses are shown in orange and cannot be edited there.
- *Display* (in the sidebar, and under *JBeam* in the header of the 3D viewport): what is drawn over the objects, on all JBeam objects, the selected ones or only the active part, with the others dimmed or hidden. Every colour, size and switch can be changed, and *Reset Display Settings* (the arrow) sets them back; they are kept in the add-on preferences, so they last between Blender sessions.
  - *Beams*: by type (`|SUPPORT` orange, `|BOUNDED` blue, `|ANISOTROPIC` purple, `|LBEAM` green, `|PRESSURED` cyan, types the game does not know, such as `"| BOUNDED"`, red), by `beamSpring`, `beamDamp`, `beamDeform` or `beamStrength` on a gradient (rainbow, cool to warm, viridis, heat or two colours of your own), or a colour for each `breakGroup`, `deformGroup` or part. *Normal beams* draws the beams without a colour of their own too. Values a row does not set come from the vehicle's options or the game's defaults, as in the game.
  - *Nodes*: one colour, by group, by part or by `nodeWeight`, and the nodes of other parts in orange.
  - *Hydros and Rails*: which are drawn, their colours and width.
  - *Selection and Problems*: in Edit Mode the selected beams and nodes are drawn over the colours; repeated beams, flat triangles and quads, and nodes whose beams lead to nodes that do not exist are marked in red.
  - *Node Names*, *Centre of Mass*: a cross at the centre of mass of the active vehicle or part and, in Edit Mode, one at the centre of all selected nodes, each with its mass.
  - The legend in the viewport shows what the colours mean.
- Faces hide what is drawn behind them, except in X-ray and wireframe; the button in the header of the 3D viewport (*Through faces*) shows it through faces with one click. What is drawn is kept on the GPU, so moving the view stays smooth with a whole vehicle open part by part.
- The panel shows the mass of the vehicle and of the part (the sum of `nodeWeight`; wheels the game adds are not counted), and *Selection* the mass of the selected nodes.
- Subdividing a face replaces its row with the rows of the new faces, which keep its properties; the faces around it, which Blender gives a point on their edge, stay as they were.
- Importing: several `.pc` or `.jbeam` files can be chosen at once (Shift or Ctrl in the file browser). For `.jbeam` files a list of all their parts follows: tick the parts (dragging over the boxes ticks several), or *All parts*, which leaves out parts without nodes, beams or faces.
- Parts imported on their own from the same files share their edits: the other parts take an edit when editing pauses (those that show what changed) or before they are edited themselves, joining it line by line with their own edits, and saving one does not make the others report the file as changed on disk.

## Develop

- `jbeam_studio/core`: plain Python, no Blender. SJSON parser that keeps the text, vehicle assembly that mirrors the game's loader, edit sessions, mesh matching.
- `jbeam_studio/blender`: meshes, object settings, undo and file handlers. `jbeam_studio/ui`: panel, operators, drawing, Russian translation.
- Tests: `python -m pytest` (core and ported scenarios of the original add-on); with `JBS_VEHICLES_DIR` set to unpacked game vehicles, `python -m pytest tests/corpus` checks every stock file and config; `blender -b --factory-startup --python tests/blender/run.py` runs the Blender tests (pytest from `.blender-pytest`, filled with `python -m pip install --target .blender-pytest pytest`).
- Build: `scripts/build.ps1` builds and validates `dist/jbeam_studio-<version>.zip` with Blender's extension tools.

## Credits

- [Blender JBeam Editor](https://github.com/BeamNG/Blender-JBeam-Editor) by BeamNG GmbH and Angelo Matteo.
- [JBeam Editor for VS Code](https://github.com/BeamNG/vscode-jbeam-editor) by BeamNG GmbH and Thomas Fischer, the source of the key documentation.

MIT License, see `LICENSE.txt`.
