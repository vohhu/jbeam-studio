"""JBeam Studio: editing BeamNG.drive vehicles and parts in Blender.

Blender modules are imported only in `register`, so `jbeam_studio.core` also works in plain Python.
"""


def register() -> None:
    from . import blender, ui

    blender.register()
    ui.register()


def unregister() -> None:
    from . import blender, ui

    ui.unregister()
    blender.unregister()
