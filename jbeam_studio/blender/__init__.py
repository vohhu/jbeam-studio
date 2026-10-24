"""The bridge between edit sessions and Blender data: meshes, object settings, undo and file handlers."""

from . import handlers, props, selection


def register() -> None:
    props.register()
    handlers.register()
    selection.register()


def unregister() -> None:
    selection.unregister()
    handlers.unregister()
    props.unregister()
