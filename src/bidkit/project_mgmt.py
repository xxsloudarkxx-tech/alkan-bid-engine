from __future__ import annotations

from pathlib import Path

from .config import ProjectConfig, list_projects, project_id
from .data_store import write_json


def inventory(root: Path) -> dict:
    names = list_projects(root)
    ids = [project_id(name) for name in names]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay nombres de proyecto con identificadores en conflicto.")
    result = {"projects": []}
    for name in names:
        config = ProjectConfig(root, name)
        if not (config.project_dir / "project.json").exists():
            write_json(config.project_dir / "project.json", config.metadata)
        result["projects"].append({"id": config.id, "name": name, "source_dir": config.source_root.relative_to(root).as_posix(), "documents": len(config.source_files), "assets": len(config.source_assets), "data_dir": config.data_dir.relative_to(root).as_posix(), "output_dir": config.output_dir.relative_to(root).as_posix()})
    write_json(root / "data" / "projects_inventory.json", result)
    return result
