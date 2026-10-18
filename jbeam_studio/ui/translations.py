"""Russian translation of the interface; Blender switches to it when its interface language is Russian."""

from __future__ import annotations

RUSSIAN = {
    # panel
    "JBeam Studio": "JBeam Studio",
    "Vehicle (.pc)": "Машина (.pc)",
    "Parts (.jbeam)": "Части (.jbeam)",
    "Import a vehicle or a part to edit it": "Импортируйте машину или часть, чтобы редактировать её",
    "This object is a copy of a JBeam object, so it is not linked to the files.":
        "Этот объект — копия JBeam-объекта, поэтому он не связан с файлами.",
    "The JBeam files of this object are not loaded.": "JBeam-файлы этого объекта не загружены.",
    "Edits are applied when leaving Edit Mode": "Правки применяются при выходе из режима редактирования",
    "The mesh has edits that are not applied": "В меше есть неприменённые правки",
    "Mesh edits were not applied": "Правки меша не применены",
    "Unsaved files: {files}": "Несохранённые файлы: {files}",
    "Changed on disk: {files}": "Изменены на диске: {files}",
    "Save": "Сохранить",
    "Save Anyway": "Всё равно сохранить",
    "Editing": "Правка",
    "Selection": "Выделение",
    "Tools": "Инструменты",
    "Diagnostics": "Диагностика",
    "View": "Вид",
    "Select nodes and beams in Edit Mode": "Выделяйте ноды и балки в режиме редактирования",
    "Nothing selected": "Ничего не выделено",
    "{count} nodes selected": "Выделено нод: {count}",
    "Node of another part, shown for reference": "Нода другой части, показана для справки",
    "Part: {part}": "Часть: {part}",
    "Position from: {expressions}": "Позиция задана: {expressions}",
    "{count} beams between these nodes": "Балок между этими нодами: {count}",
    "Apply {name}": "Применить {name}",
    "No problems found": "Проблем не найдено",
    "Show all {count}": "Показать все ({count})",
    "{nodes} nodes, {beams} beams, {triangles} triangles, {quads} quads":
        "нод: {nodes}, балок: {beams}, треугольников: {triangles}, квадов: {quads}",
    "{} nodes of other parts were moved back": "Ноды других частей возвращены на место: {}",
    "{} nodes of other parts were restored": "Ноды других частей восстановлены: {}",
    "{} faces with more than four corners were dropped": "Отброшены грани больше чем с четырьмя углами: {}",
    "The mesh was built from a state of the files that the edit history no longer has. "
    "Rebuild the mesh to continue; its unapplied edits are lost.":
        "Меш построен из состояния файлов, которого уже нет в истории правок. Перестройте меш, чтобы "
        "продолжить; неприменённые правки меша пропадут.",
    # operators
    "Import JBeam Vehicle": "Импорт JBeam-машины",
    "All vehicle nodes": "Все ноды машины",
    "Show every node of the vehicle in this part's mesh, the nodes of other parts in orange, so new beams and faces "
    "of this part can join any of them":
        "Показать в меше этой части все ноды машины, ноды других частей — оранжевыми, чтобы новые балки и грани "
        "части могли идти к любой из них",
    "Assemble a vehicle from a part config (.pc) and show each of its parts as an object, in a collection of its "
    ".jbeam file under the JBeam collection; several files give several vehicles":
        "Собрать машину по конфигу (.pc) и показать каждую её часть отдельным объектом в коллекции её файла .jbeam "
        "внутри коллекции JBeam; несколько файлов дают несколько машин",
    "Import JBeam Parts": "Импорт JBeam-частей",
    "Choose the parts of the .jbeam files to import": "Выбрать части файлов .jbeam для импорта",
    "Show parts of .jbeam files as objects, with the nodes of other parts they use; with several parts, choose "
    "which ones":
        "Показать части файлов .jbeam объектами вместе с нодами других частей, которые они используют; если частей "
        "несколько — выбрать, какие",
    "All parts": "Все части",
    "Import every part of the chosen files": "Импортировать все части выбранных файлов",
    "{count} of {total} parts": "Выбрано частей: {count} из {total}",
    "Choose the parts to import": "Выберите части для импорта",
    "None of the parts has nodes, beams or faces": "Ни в одной части нет нод, балок и граней",
    "{count} parts without nodes, beams or faces left out": "частей без нод, балок и граней пропущено: {count}",
    "Loaded {count} parts from {files} files; {errors} errors, {warnings} warnings":
        "Загружено частей: {count} из файлов: {files}; ошибок {errors}, предупреждений {warnings}",
    "JBeam Vehicle (.pc)": "JBeam-машина (.pc)",
    "JBeam Parts (.jbeam)": "JBeam-части (.jbeam)",
    "Apply Mesh Edits": "Применить правки меша",
    "Write the edits of the mesh into the JBeam files in memory": "Записать правки меша в JBeam-файлы в памяти",
    "Save JBeam Files": "Сохранить JBeam-файлы",
    "Apply the mesh edits and write the changed files; the first save keeps the original as .bak":
        "Применить правки меша и записать изменённые файлы; при первом сохранении оригинал остаётся как .bak",
    "Rebuild Mesh": "Перестроить меш",
    "Build the mesh again from the JBeam files in memory, dropping mesh edits that were not applied":
        "Построить меш заново из JBeam-файлов в памяти; неприменённые правки меша пропадут",
    "Reload Changed Files": "Перечитать изменённые файлы",
    "Read the files that changed on disk again; unsaved edits of these files and the undo history are lost":
        "Прочитать заново файлы, изменённые на диске; несохранённые правки этих файлов и история отмены пропадут",
    "Find New Files": "Найти новые файлы",
    "Take in .jbeam files added to the vehicle folders since loading; the undo history is cleared":
        "Подхватить файлы .jbeam, добавленные в папки машины после загрузки; история отмены очищается",
    "Load from Files": "Загрузить из файлов",
    "Open the JBeam files of this object again and rebuild its mesh":
        "Снова открыть JBeam-файлы этого объекта и перестроить его меш",
    "Make Plain Mesh": "Сделать обычным мешем",
    "Turn this object into a plain mesh that is not linked to JBeam files":
        "Превратить объект в обычный меш без связи с JBeam-файлами",
    "Rename Node": "Переименовать ноду",
    "Rename the active node and every beam, triangle and other reference to it":
        "Переименовать активную ноду и все балки, треугольники и другие ссылки на неё",
    "New name": "Новое имя",
    'Node "{node}"': 'Нода "{node}"',
    "References renamed with it: {count}": "Ссылок, которые переименуются вместе с ней: {count}",
    "Equal strings that stay as they are: {count}": "Совпадающих строк, которые останутся как есть: {count}",
    "Rename Selected Nodes": "Переименовать выделенные ноды",
    "Give the selected nodes names made of a prefix, a number and a suffix, in the order of selection":
        "Дать выделенным нодам имена из префикса, номера и суффикса в порядке выделения",
    "Prefix": "Префикс",
    "First number": "Первый номер",
    "Suffix": "Суффикс",
    "and {count} more groups": "и ещё групп: {count}",
    "Draw beams in colour, by what Colour by says": "Рисовать балки цветом по выбранному признаку",
    "Colour beams by": "Цвет балок по",
    "Beams of special types: SUPPORT, BOUNDED, ANISOTROPIC, LBEAM, PRESSURED; types the game does not know in red":
        "Балки особых типов: SUPPORT, BOUNDED, ANISOTROPIC, LBEAM, PRESSURED; неизвестные игре типы — красным",
    "Stiffness, from blue (low) to red (high)": "Жёсткость: от синего (мало) до красного (много)",
    "Damping, from blue (low) to red (high)": "Демпфирование: от синего (мало) до красного (много)",
    "Force that bends a beam for good, from blue (low) to red (high)":
        "Сила, при которой балка гнётся насовсем: от синего (мало) до красного (много)",
    "Force that breaks a beam, from blue (low) to red (high)":
        "Сила, при которой балка рвётся: от синего (мало) до красного (много)",
    "Draw nodes in colour, by what Colour by says": "Рисовать ноды цветом по выбранному признаку",
    "Colour nodes by": "Цвет нод по",
    "A colour for each node group": "Свой цвет у каждой группы нод",
    "Weight, from blue (light) to red (heavy)": "Весу: от синего (лёгкие) до красного (тяжёлые)",
    "Kinds": "Виды",
    "Draw hydros": "Рисовать гидравлику",
    "Draw torsion bars and torsion hydros": "Рисовать торсионы и торсионную гидравлику",
    "Draw rails and the slide nodes on them": "Рисовать рельсы и скользящие ноды на них",
    "Through faces": "Сквозь грани",
    "Draw coloured beams and nodes, hydros, rails and node names of JBeam objects through faces; otherwise faces "
    "hide them, except in X-ray and wireframe":
        "Рисовать цветные балки и ноды, гидравлику, рельсы и имена нод JBeam-объектов сквозь грани; иначе грани их "
        "закрывают, кроме режимов X-ray и каркаса",
    "Line width": "Толщина линий",
    "Width of coloured beams, hydros, torsion bars and rails, in pixels":
        "Толщина цветных балок, гидравлики, торсионов и рельсов в пикселях",
    "Opacity of coloured beams, nodes, hydros, torsion bars and rails":
        "Непрозрачность цветных балок, нод, гидравлики, торсионов и рельсов",
    "Centre of mass": "Центр масс",
    "Mark the centre of mass of the vehicle, from the weights of its nodes":
        "Отмечать центр масс машины по весам её нод",
    "Mass: {mass} kg": "Масса: {mass} кг",
    "Mass: {mass} kg, this part {part} kg": "Масса: {mass} кг, эта часть {part} кг",
    "Mass of the selection: {mass} kg": "Масса выделенного: {mass} кг",
    "Legend": "Легенда",
    "Show what the colours mean in the viewport": "Показывать во вьюпорте, что означают цвета",
    "Set Property": "Задать свойство",
    "Set a property on the selected nodes, beams or faces: in its column when the table has one, otherwise in "
    "the options of each row":
        "Задать свойство выделенным нодам, балкам или граням: в колонке, если она есть в таблице, иначе в опциях "
        "каждой строки",
    "Of": "Для",
    "Nodes": "Ноды",
    "Beams": "Балки",
    "Triangles and quads": "Треугольники и квады",
    "Key": "Ключ",
    "Value": "Значение",
    'A number, true, false, or text such as |NORMAL or "name"': 'Число, true, false или текст, например |NORMAL или "name"',
    "Select what to change and give a key": "Выделите, что менять, и укажите ключ",
    "{key} = {value} on {count} rows": "{key} = {value} у строк: {count}",
    "Select by Property": "Выделить по свойству",
    "Select the nodes, beams or faces whose property has a value, such as beamType = |SUPPORT":
        "Выделить ноды, балки или грани с заданным значением свойства, например beamType = |SUPPORT",
    "Leave empty to select everything that has the key": "Оставьте пустым, чтобы выделить всё, где ключ задан",
    "Extend": "Добавить к выделению",
    "Add to the selection": "Добавить к текущему выделению",
    "Selected {count}": "Выделено: {count}",
    "Select Group": "Выделить группу",
    "Select the nodes of this group; with Shift, add them to the selection":
        "Выделить ноды этой группы; с Shift — добавить к выделению",
    "Hide or Show Group": "Скрыть или показать группу",
    "Hide the nodes of this group in Edit Mode, or show them again":
        "Скрыть ноды этой группы в режиме редактирования или снова показать",
    "Rename Group": "Переименовать группу",
    "Rename a node group in every part, together with the flexbodies that use it":
        "Переименовать группу нод во всех частях вместе с flexbodies, которые её используют",
    "Renamed {count} places": "Переименовано мест: {count}",
    "Groups": "Группы",
    "No node groups": "Групп нод нет",
    "Groups of all parts": "Группы всех частей",
    "List the node groups of every part, not only of the active part": "Показывать группы нод всех частей, а не только активной",
    "mixed": "разные",
    "{count} beams selected": "Выделено балок: {count}",
    "{count} triangles and quads selected": "Выделено треугольников и квадов: {count}",
    "Where new rows go": "Куда добавлять",
    "End of table": "В конец таблицы",
    "After the last row and the resets, with the default values": "После последней строки и сбросов, со значениями по умолчанию",
    "Next to the source": "Рядом с источником",
    "Right after the row of the node, beam or face they come from, with its group and values":
        "Сразу после строки ноды, балки или грани, от которой они происходят, с её группой и значениями",
    "Into a group": "В группу",
    "At the end of the rows of the chosen node group, with its values": "В конец строк выбранной группы нод, с её значениями",
    "Group": "Группа",
    "Node group that new nodes, and beams and faces between its nodes, join":
        "Группа нод, в которую попадают новые ноды, а также балки и грани между её нодами",
    "Add Resets": "Добавить сбросы",
    "Add a row at the end of each table of the part that sets the modifiers it changes, such as group or beamType, "
    "back to their defaults, so the rows of parts after it do not get them":
        "Добавить в конец каждой таблицы части строку, которая возвращает изменённые частью модификаторы (например "
        "group или beamType) к значениям по умолчанию, чтобы их не получали строки следующих частей",
    'Part "{part}" already resets what it changes': 'Часть "{part}" уже сбрасывает всё, что меняет',
    "Added resets: {resets}": "Добавлены сбросы: {resets}",
    "Fix": "Исправить",
    "Fix this problem in the JBeam files in memory": "Исправить эту проблему в JBeam-файлах в памяти",
    "This problem has no automatic fix": "У этой проблемы нет автоматического исправления",
    'Mark this row "optional": true. The row stays: the game skips it without a warning while the node is missing, '
    "and uses it when another part or mod provides the node":
        'Пометить строку "optional": true. Строка остаётся: пока ноды нет, игра пропускает её без предупреждения, '
        "а когда ноду даёт другая часть или мод — использует",
    "Delete this copy of the beam; the row it repeats stays": "Удалить этот повтор балки; исходная строка останется",
    "Add a row at the end of each table of the part that sets the modifiers it changes back to their defaults":
        "Добавить в конец каждой таблицы части строку, возвращающую изменённые ею модификаторы к значениям по умолчанию",
    "Mark Optional ({count})": "Пометить optional ({count})",
    'Mark every row that references a missing node "optional": true; the rows stay for the parts and mods that '
    "provide those nodes":
        'Пометить "optional": true все строки со ссылками на несуществующие ноды; строки остаются для частей и '
        "модов, которые дают эти ноды",
    "{count} rows marked optional": "помечено optional строк: {count}",
    "Delete Duplicate Beams ({count})": "Удалить повторы балок ({count})",
    "Delete every repeated beam; the first row of each stays": "Удалить все повторы балок; первая строка каждой останется",
    "Add Resets to Parts ({count})": "Добавить сбросы в части ({count})",
    "Add resets to every part that leaves modifiers set for the parts after it":
        "Добавить сбросы во все части, которые оставляют модификаторы для частей после них",
    "The problem is gone": "Проблемы уже нет",
    "{count} rows deleted": "удалено строк: {count}",
    "resets added to {parts}": "сбросы добавлены в {parts}",
    "Fixed: {done}": "Исправлено: {done}",
    "Nothing to fix": "Нечего исправлять",
    "Mirror Selected Nodes": "Отразить выделенные ноды",
    "Copy the selected nodes, and the beams, triangles and quads that use them, to the other side of X = 0 with "
    "mirrored names (e3l to e3r); counterparts that exist are moved to the mirrored place":
        "Скопировать выделенные ноды и их балки, треугольники и квады на другую сторону от X = 0 с зеркальными "
        "именами (e3l в e3r); если пара уже есть, она переносится в зеркальное положение",
    "Mirror Moves": "Зеркалить перемещения",
    "Mirror axis": "Ось отражения",
    "Mirror left and right (l and r)": "Отражать лево и право (l и r)",
    "Mirror front and back (f and b)": "Отражать перед и зад (f и b)",
    "Mirror top and down (t and d)": "Отражать верх и низ (t и d)",
    "Mirror plane": "Плоскость отражения",
    "Origin": "Начало координат",
    "The plane through 0 of the vehicle": "Плоскость через 0 машины",
    "3D Cursor": "3D-курсор",
    "The plane through the 3D cursor": "Плоскость через 3D-курсор",
    "Active node": "Активная нода",
    "The plane through the active node, such as the mast of a rotor": "Плоскость через активную ноду, например мачту ротора",
    "Select the node the mirror plane goes through last": "Выделите последней ноду, через которую идёт плоскость",
    "Side letters across X": "Буквы сторон по X",
    "Side letters across Y": "Буквы сторон по Y",
    "Side letters across Z": "Буквы сторон по Z",
    "Letters at the end of node ids that mirroring across X swaps": "Буквы в конце имён нод, которые меняет отражение по X",
    "Letters at the end of node ids that mirroring across Y swaps": "Буквы в конце имён нод, которые меняет отражение по Y",
    "Letters at the end of node ids that mirroring across Z swaps": "Буквы в конце имён нод, которые меняет отражение по Z",
    "Copy the selected nodes, and the beams, triangles and quads that use them, to the other side of the mirror "
    "plane with mirrored names (e3l to e3r); counterparts that exist are moved to the mirrored place":
        "Скопировать выделенные ноды и их балки, треугольники и квады на другую сторону плоскости отражения с "
        "зеркальными именами (e3l в e3r); если пара уже есть, она переносится в зеркальное положение",
    "The selection is already mirrored": "Выделенное уже отражено",
    "Mirrored: {added} nodes added, {moved} moved, {beams} beams, {faces} faces, {extras} hydros, torsion bars, "
    "slide nodes and rails":
        "Отражено: добавлено нод {added}, перенесено {moved}, балок {beams}, граней {faces}, гидравлики, "
        "торсионов, скользящих нод и рельсов {extras}",
    "Flip Faces": "Развернуть грани",
    "Reverse the winding of the selected triangles and quads; written when the mesh edits are applied":
        "Развернуть порядок обхода выделенных треугольников и квадов; записывается при применении правок меша",
    "Select Part": "Выделить часть",
    "Add the nodes of the active part to the selection": "Добавить ноды активной части к выделению",
    "Show Text": "Показать текст",
    "Open the file in Blender's text editor as it is in memory, with unsaved edits":
        "Открыть файл в текстовом редакторе Blender таким, каким он сейчас в памяти, с несохранёнными правками",
    "Apply Text": "Применить текст",
    "Replace the file in memory with the text edited in Blender's text editor":
        "Заменить файл в памяти текстом, отредактированным в текстовом редакторе Blender",
    "Unpack Vehicles": "Распаковать машины",
    "Copy the .jbeam, .pc and info.json files out of the game's vehicle archives":
        "Скопировать файлы .jbeam, .pc и info.json из архивов машин игры",
    # reports
    "Loaded {name}: {summary}; {errors} errors, {warnings} warnings":
        "Загружено {name}: {summary}; ошибок: {errors}, предупреждений: {warnings}",
    "{name} has no parts": "В {name} нет частей",
    'Part "{part}" is not in {name}': 'Части "{part}" нет в {name}',
    "Nothing to apply": "Применять нечего",
    "All changes are saved (saved at {time}: {files})": "Все изменения сохранены (в {time}: {files})",
    "There are no changes to save": "Изменений для сохранения нет",
    "Text edits in {names} are not applied, so they were not saved":
        "Текстовые правки в {names} не применены, поэтому не сохранены",
    "Text edits in {name} are not applied yet": "Текстовые правки в {name} ещё не применены",
    "Apply": "Применить",
    "Discard": "Отменить",
    "Discard Text Edits": "Отменить текстовые правки",
    "Show the file as it is in memory again, dropping the edits made in the text editor":
        "Снова показать файл таким, каким он сейчас в памяти, отбросив правки из текстового редактора",
    "Saved at {time}: {files}": "Сохранено в {time}: {files}",
    "Saved {files}": "Сохранено: {files}",
    "{error}. Reload them, or save anyway to overwrite them":
        "{error}. Перечитайте их или сохраните всё равно, чтобы перезаписать",
    "{count} new files": "Новых файлов: {count}",
    "Select a node": "Выделите ноду",
    "Select nodes": "Выделите ноды",
    "Choose the active part": "Выберите активную часть",
    "Set the game vehicle archives and the folder to unpack into":
        "Укажите архивы машин игры и папку для распаковки",
    "No .zip archives in {folder}": "В {folder} нет архивов .zip",
    "Unpacked {count} files into {folder}": "Распаковано файлов: {count} в {folder}",
    "moved {} nodes": "перемещено нод: {}",
    "added {} nodes": "добавлено нод: {}",
    "deleted {} nodes": "удалено нод: {}",
    "added {} beams": "добавлено балок: {}",
    "deleted {} beams": "удалено балок: {}",
    "added {} faces": "добавлено граней: {}",
    "deleted {} faces": "удалено граней: {}",
    "flipped {} faces": "развёрнуто граней: {}",
    # object settings
    "Source": "Источник",
    "Vehicle": "Машина",
    "Part": "Часть",
    "Active part": "Активная часть",
    "Part that new nodes, beams, triangles and quads are added to when they do not come from a node of a part; "
    "a node extruded or copied from a node goes to that node's part":
        "Часть, в которую добавляются новые ноды, балки, треугольники и квады, если они не происходят от ноды "
        "какой-то части; нода, выдавленная или скопированная из ноды, попадает в часть этой ноды",
    "New node prefix": "Префикс новых нод",
    "New nodes without neighbours are named with this prefix and a number":
        "Новые ноды без соседей получают имя из этого префикса и номера",
    "Name new nodes after their neighbours": "Называть новые ноды по соседям",
    "Name a new node like the node it was extruded or copied from, or the node it is joined to: the same prefix, "
    "the next number and the side letter of its position, as e3l gives e5l or e5r":
        "Называть новую ноду как ноду, из которой её выдавили или скопировали, или с которой она соединена: тот же "
        "префикс, следующий номер и буква стороны по положению, например из e3l получится e5l или e5r",
    "Moving nodes": "Перемещение нод",
    "Overwrite coordinates": "Перезаписывать координаты",
    "Write the new position as plain numbers, replacing variables and expressions":
        "Записывать новую позицию числами вместо переменных и выражений",
    "Keep expressions": "Сохранять выражения",
    "Keep variables and expressions and add the shift to them": "Оставлять переменные и выражения, добавляя к ним сдвиг",
    "Edit shared rows": "Править общие строки",
    "Allow edits of rows that also define entries in other slots, which then change too":
        "Разрешить правку строк, которые задают элементы и в других слотах; те тоже изменятся",
    "Edits are applied right away": "Правки применяются сразу",
    "Apply right away": "Применять сразу",
    "Write mesh edits to the JBeam files in memory after every operation in Edit Mode, so the text and, with Auto, "
    "the files follow the mesh as you edit":
        "Записывать правки меша в JBeam-файлы в памяти после каждой операции в режиме редактирования, чтобы текст, "
        "а с «Авто» и файлы, сразу следовали за мешем",
    "Save after changes": "Сохранять после изменений",
    "Write the changed files to disk after every applied edit, rename, undo and redo":
        "Записывать изменённые файлы на диск после каждой применённой правки, переименования, отмены и повтора",
    "Auto": "Авто",
    "Files were not saved": "Файлы не сохранены",
    "Line {line}: {message}": "Строка {line}: {message}",
    "JBeam colours": "Цвета JBeam",
    "Colour parts, sections, keys, strings, variables, expressions, numbers and comments of JBeam files in the "
    "text editor":
        "Раскрашивать части, секции, ключи, строки, переменные, выражения, числа и комментарии JBeam-файлов в "
        "текстовом редакторе",
    "Show problems": "Показывать проблемы",
    "Underline problems of JBeam files in the text editor and describe them after the line: syntax errors as you "
    "type, and problems found when assembling the vehicle":
        "Подчёркивать проблемы JBeam-файлов в текстовом редакторе и писать их после строки: ошибки синтаксиса "
        "по мере набора и проблемы, найденные при сборке машины",
    "Highlight in text": "Подсветка в тексте",
    "Highlight the rows of the selection in the text editor: nodes in vertex select mode, beams in edge mode, "
    "triangles and quads in face mode":
        "Подсвечивать строки выделенного в текстовом редакторе: ноды в режиме вершин, балки в режиме рёбер, "
        "треугольники и квады в режиме граней",
    "Hydros and rails": "Гидравлика и рельсы",
    "Draw hydros, torsion bars, rails and slide nodes, which are not mesh edges":
        "Рисовать гидравлику, торсионы, рельсы и скользящие ноды, которых нет среди рёбер меша",
    "Hydros": "Гидравлика",
    "Torsion bars": "Торсионы",
    "Torsion hydros": "Торсионная гидравлика",
    "Rails": "Рельсы",
    "Slide nodes": "Скользящие ноды",
    "hydro": "гидравлика",
    "torsion bar": "торсион",
    "torsion hydro": "торсионная гидравлика",
    "rail": "рельс",
    "slide node": "скользящая нода",
    "Add Hydro or Torsion Bar": "Добавить гидравлику или торсион",
    "Hydro": "Гидравлика",
    "Torsion Bar": "Торсион",
    "Add a hydro between the two selected nodes, to the active part":
        "Добавить гидравлику между двумя выделенными нодами в активную часть",
    "Add a torsion bar through the four selected nodes in the order they were selected, to the active part; it "
    "twists about the second and third":
        "Добавить торсион через четыре выделенные ноды в порядке выделения в активную часть; ось кручения — "
        "вторая и третья",
    "Select {count} nodes, in order": "Выделите ноды по порядку: {count}",
    "Added {what}": "Добавлено: {what}",
    "Add Rail": "Добавить рельс",
    "Add a rail through the selected nodes in the order they were selected, to the active part; slide nodes can "
    "then slide along it":
        "Добавить рельс через выделенные ноды в порядке выделения в активную часть; по нему смогут скользить "
        "скользящие ноды",
    "Looped": "Замкнутый",
    "The rail closes from its last node back to the first": "Рельс замыкается от последней ноды к первой",
    "Capped": "С упорами",
    "Slide nodes cannot leave the rail at its ends": "Скользящие ноды не сходят с концов рельса",
    "Select at least two nodes, in order": "Выделите по порядку хотя бы две ноды",
    "Add Slide Nodes": "Добавить скользящие ноды",
    "Make the selected nodes slide along a rail, in the active part":
        "Сделать выделенные ноды скользящими по рельсу (в активной части)",
    "The vehicle has no rails yet; add one first": "У машины ещё нет рельсов; сначала добавьте рельс",
    "Select the nodes that slide, and a rail": "Выделите скользящие ноды и выберите рельс",
    "Select Nodes": "Выделить ноды",
    "Select the nodes this joins; with Shift, add them to the selection":
        "Выделить ноды, которые это соединяет; с Shift — добавить к выделению",
    "Delete this row from the JBeam file; a rail takes the slide nodes on it with it":
        "Удалить эту строку из JBeam-файла; вместе с рельсом удаляются скользящие ноды на нём",
    "Deleted {what}": "Удалено: {what}",
    "Hydros and Rails": "Гидравлика и рельсы",
    "Slide Nodes": "Скользящие ноды",
    "Add them from selected nodes in Edit Mode": "Добавляются из выделенных нод в режиме редактирования",
    "No hydros, torsion bars or rails": "Нет гидравлики, торсионов и рельсов",
    "Using the selected nodes: {count}": "С выделенными нодами: {count}",
    "All: {count}": "Все: {count}",
    "Rail": "Рельс",
    "Show Properties": "Показать свойства",
    "Show or hide the properties of this entry": "Показать или скрыть свойства этой записи",
    "Set a property of this hydro, torsion bar, slide node or rail: in its column when the table has one, "
    "otherwise in the options of its row":
        "Задать свойство этой гидравлики, торсиона, скользящей ноды или рельса: в колонке, если она есть в "
        "таблице, иначе в параметрах строки",
    'A number, true, false, a list such as ["n1", "n2"], or text such as steering':
        'Число, true, false, список вроде ["n1", "n2"] или текст, например steering',
    "Give a key": "Укажите ключ",
    "This entry no longer exists": "Этой записи больше нет",
    "and {count} more": "и ещё {count}",
    "Select from text": "Выделять из текста",
    "Putting the text cursor on the row of a node, beam or face selects it in Edit Mode":
        "Курсор на строке ноды, балки или грани выделяет её в режиме редактирования",
    "Follow selection": "Следовать за выделением",
    "Scroll the text editor to the row of the active element and open its file":
        "Прокручивать текстовый редактор к строке активного элемента и открывать его файл",
    "Apply when leaving Edit Mode": "Применять при выходе из режима редактирования",
    "Write mesh edits to the JBeam files in memory when leaving Edit Mode":
        "Записывать правки меша в JBeam-файлы в памяти при выходе из режима редактирования",
    # view settings
    "Node names": "Имена нод",
    "Selected": "Выделенные",
    "All": "Все",
    "None": "Нет",
    "Show the names of selected nodes in Edit Mode": "Показывать имена выделенных нод в режиме редактирования",
    "Show the names of all nodes": "Показывать имена всех нод",
    "Hide node names": "Скрыть имена нод",
    "Text size": "Размер текста",
    "Mark nodes of other parts": "Отмечать ноды других частей",
    "Draw nodes that belong to other parts, which cannot be edited here, in orange":
        "Рисовать оранжевым ноды других частей, которые здесь нельзя редактировать",
    "Show": "Показать",
    "Errors": "Ошибки",
    "Warnings": "Предупреждения",
    "Messages": "Сообщения",
    "Show all": "Показать все",
    # display
    "Show on": "Показывать на",
    "Colour every JBeam object": "Раскрашивать все JBeam-объекты",
    "Colour the selected JBeam objects": "Раскрашивать выделенные JBeam-объекты",
    "Colour only the active object, the part being edited": "Раскрашивать только активный объект — редактируемую часть",
    "Dim the others": "Приглушать остальные",
    "Draw the colours of the other JBeam objects faintly instead of hiding them":
        "Рисовать цвета остальных JBeam-объектов бледно, а не прятать их",
    "Their opacity": "Их непрозрачность",
    "Opacity of the colours of the other JBeam objects": "Непрозрачность цветов остальных JBeam-объектов",
    "Opacity of everything drawn over the objects": "Непрозрачность всего, что рисуется поверх объектов",
    "Stiffness, on the gradient from low to high": "Жёсткость, по градиенту от низкой к высокой",
    "Damping, on the gradient from low to high": "Демпфирование, по градиенту от низкого к высокому",
    "Force that bends a beam for good, on the gradient from low to high":
        "Сила, при которой балка гнётся навсегда, по градиенту от низкой к высокой",
    "Force that breaks a beam, on the gradient from low to high":
        "Сила, при которой балка ломается, по градиенту от низкой к высокой",
    "A colour for each break group": "Свой цвет для каждой breakGroup",
    "A colour for each deform group": "Свой цвет для каждой deformGroup",
    "A colour for each part": "Свой цвет для каждой части",
    "Other beams": "Остальные балки",
    "Also draw the beams that Colour by gives no colour, such as beams of the normal type, in their own colour":
        "Рисовать своим цветом и балки, которым «Цвет по» не даёт цвета, например балки обычного типа",
    "Colour of other beams": "Цвет остальных балок",
    "Unknown type": "Неизвестный тип",
    'Beam types the game does not know, such as "| BOUNDED"': 'Типы балок, которых игра не знает, например "| BOUNDED"',
    "Width of coloured beams, in pixels": "Толщина цветных балок в пикселях",
    "Rainbow": "Радуга",
    "Blue, cyan, green, yellow, red": "Синий, голубой, зелёный, жёлтый, красный",
    "Cool to warm": "Холодный — тёплый",
    "Blue, grey, red": "Синий, серый, красный",
    "Purple, teal, yellow; easy to read for colour-blind people":
        "Фиолетовый, бирюзовый, жёлтый; хорошо читается при дальтонизме",
    "Heat": "Тепло",
    "Dark red, orange, yellow, white": "Тёмно-красный, оранжевый, жёлтый, белый",
    "From the low colour to the high colour": "От цвета низких значений к цвету высоких",
    "Values such as FLT_MAX, which do not fit a gradient": "Значения вроде FLT_MAX, которые не помещаются в градиент",
    "One colour": "Один цвет",
    "Every node in the node colour": "Все ноды цветом нод",
    "A colour for each node group; nodes without one in the node colour":
        "Свой цвет для каждой группы нод; ноды без группы — цветом нод",
    "Weight, on the gradient from light to heavy": "Вес, по градиенту от лёгких к тяжёлым",
    "Node colour": "Цвет нод",
    "Size of nodes, in pixels": "Размер нод в пикселях",
    "Nodes of other parts": "Ноды других частей",
    "Mark nodes that belong to other parts, which cannot be edited here":
        "Отмечать ноды других частей, которые здесь нельзя редактировать",
    "Colour of nodes of other parts": "Цвет нод других частей",
    "Their size": "Их размер",
    "Width of hydros, torsion bars and rails, in pixels": "Толщина гидравлики, торсионов и рельсов в пикселях",
    "In Edit Mode, draw the selected beams and nodes over the colours":
        "В режиме редактирования рисовать выделенные балки и ноды поверх цветов",
    "Selection colour": "Цвет выделения",
    "Problems": "Проблемы",
    "Mark repeated beams, flat triangles and quads, and nodes whose beams lead to nodes that do not exist":
        "Отмечать повторяющиеся балки, плоские треугольники и квады и ноды, чьи балки ведут к несуществующим нодам",
    "Problem colour": "Цвет проблем",
    "Name colour": "Цвет имён",
    "Names of nodes of other parts": "Имена нод других частей",
    "Mark the centre of mass of the vehicle or part of the active object, from the weights of its nodes":
        "Отмечать центр масс машины или части активного объекта по весам её нод",
    "Colour": "Цвет",
    "Of the selected nodes": "Выделенных нод",
    "In Edit Mode, also mark the centre of mass of all selected nodes":
        "В режиме редактирования также отмечать общий центр масс всех выделенных нод",
    "Colour of the selected nodes' centre": "Цвет центра выделенных нод",
    "Show the mass": "Показывать массу",
    "Write the mass next to the cross": "Писать массу рядом с крестом",
    "Half the length of the arms of the cross": "Половина длины лучей креста",
    "Text Editor": "Текстовый редактор",
    "JBeam Display": "Отображение JBeam",
    "Colour by": "Цвет по",
    "Other parts": "Другие части",
    "Selection and Problems": "Выделение и проблемы",
    "Node Names": "Имена нод",
    "Centre of Mass": "Центр масс",
    "Selected nodes": "Выделенные ноды",
    "Normal beams": "Обычные балки",
    "Without a group": "Без группы",
    "Node groups": "Группы нод",
    "Parts": "Части",
    "Flags": "Флаги",
    "As the game shows nodes: fixed, selfCollision and collision false in their colours, the others in the node colour":
        "Как ноды показывает игра: fixed, selfCollision и collision false своими цветами, остальные — цветом нод",
    "Other nodes": "Остальные ноды",
    'Nodes with "fixed": true': 'Ноды с "fixed": true',
    'Nodes with "selfCollision": true': 'Ноды с "selfCollision": true',
    'Nodes with "collision": false': 'Ноды с "collision": false',
    "BeamNG": "BeamNG",
    "White to red, as the game shows beam values": "От белого к красному, как игра показывает значения балок",
    "The first half: from the first node to the axis": "Первая половина: от первой ноды к оси",
    "Second half": "Вторая половина",
    "From the last node to the axis": "От последней ноды к оси",
    "Axis": "Ось",
    "Between the second and the third node": "Между второй и третьей нодой",
    "Anisotropic": "Анизотропные",
    "Torsion bars with spring2 or damp2: the first half": "Торсионы со spring2 или damp2: первая половина",
    "Anisotropic, second half": "Анизотропные, вторая половина",
    "One for each": "Свой у каждого",
    "A colour for each rail, as in the game; slide nodes in the colour of their rail":
        "Свой цвет у каждого рельса, как в игре; слайд-ноды — цветом своего рельса",
    "Every rail and slide node in the rail colour": "Все рельсы и слайд-ноды цветом рельсов",
    "Rail colour": "Цвет рельсов",
    "Reset Display Settings": "Сбросить настройки отображения",
    "Set every colour, size and switch of the display back to its default":
        "Вернуть все цвета, размеры и переключатели отображения к значениям по умолчанию",
    "Display settings are in the JBeam tab of the sidebar and in the viewport header":
        "Настройки отображения — во вкладке JBeam боковой панели и в шапке вьюпорта",
    # preferences
    "Unpacked game vehicles": "Распакованные машины игры",
    "The vehicles folder of unpacked game content. Mods are assembled with the game's common parts and vehicles from it":
        "Папка vehicles распакованного контента игры. Моды собираются вместе с общими частями и машинами из неё",
    "Game vehicle archives": "Архивы машин игры",
    "The content/vehicles folder of the BeamNG.drive installation": "Папка content/vehicles установленной BeamNG.drive",
    "Unpack into": "Распаковать в",
    "Folder that receives a vehicles folder with the .jbeam, .pc and info.json files":
        "Папка, в которой появится папка vehicles с файлами .jbeam, .pc и info.json",
    "Unpack vehicles from the game": "Распаковка машин из игры",
}


def translations() -> dict:
    table = {}
    for english, russian in RUSSIAN.items():
        for context in ("*", "Operator"):
            table[(context, english)] = russian
    return {"ru_RU": table, "ru": table}
