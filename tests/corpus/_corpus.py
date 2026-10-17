import os
from pathlib import Path

VEHICLES = Path(os.environ["JBS_VEHICLES_DIR"]) if os.environ.get("JBS_VEHICLES_DIR") else None
CONFIGS_MODE = os.environ.get("JBS_CORPUS_CONFIGS", "first")


def source_files() -> list[Path]:
    if VEHICLES is None:
        return []
    return sorted(p for p in VEHICLES.rglob("*") if p.suffix.lower() in (".jbeam", ".pc"))


def configs() -> list[tuple[Path, Path | None]]:
    """(model folder, part config) pairs: the first config of every model, or all with JBS_CORPUS_CONFIGS=all."""
    if VEHICLES is None:
        return []
    result = []
    for model_dir in sorted(d for d in VEHICLES.iterdir() if d.is_dir() and d.name.lower() != "common"):
        pcs = sorted(model_dir.glob("*.pc"))
        if not pcs:
            result.append((model_dir, None))
        else:
            result.extend((model_dir, pc) for pc in (pcs if CONFIGS_MODE == "all" else pcs[:1]))
    return result


def path_id(value) -> str:
    if value is None:
        return "default"
    return value.relative_to(VEHICLES).as_posix()
