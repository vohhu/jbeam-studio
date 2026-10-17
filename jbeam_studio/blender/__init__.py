"""The bridge between edit sessions and Blender data: meshes, object settings, undo and file handlers."""

from . import handlers, props


def register() -> None:
    props.register()
    handlers.register()


def unregister() -> None:
    handlers.unregister()
    props.unregister()
