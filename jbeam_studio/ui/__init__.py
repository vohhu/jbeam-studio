"""The JBeam panel, operators, import menu entries, viewport drawing and translations."""

import bpy

from . import operators, overlay, panels, preferences, text_highlight, text_syntax, translations, view

CLASSES = (*view.CLASSES, *preferences.CLASSES, *operators.CLASSES, *panels.CLASSES)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    view.register()
    bpy.types.TOPBAR_MT_file_import.append(operators.menu_import)
    overlay.register()
    text_syntax.register()
    text_highlight.register()
    bpy.app.translations.register(__package__, translations.translations())
    operators.register_keymaps()


def unregister() -> None:
    operators.unregister_keymaps()
    bpy.app.translations.unregister(__package__)
    text_highlight.unregister()
    text_syntax.unregister()
    overlay.unregister()
    bpy.types.TOPBAR_MT_file_import.remove(operators.menu_import)
    view.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
