"""ALKAN Bid Engine — Reciclador y Purgador de Estimados.

Optimiza el almacenamiento eliminando corridas obsoletas, borradores repetidos,
cargas temporales en data/uploads/ y archivos pesados no requeridos una vez
generados los entregables.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("bidkit.recycler")

ACTIVE_STATUSES = {"en cola", "indexando", "estimando"}
FINAL_STATUSES = {"autorizada", "exportada"}
DISCARDABLE_STATUSES = {"cancelada", "interrumpida", "error", "rechazada", "no-go"}


def get_dir_size(path: Path) -> int:
    """Calcula el tamaño total en bytes de un directorio."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat().st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_dir_size(Path(entry.path))
    except (OSError, PermissionError):
        pass
    return total


def purge_superseded_runs(
    base_dir: Path,
    project_key: str | None = None,
    keep_latest_drafts: int = 1,
    purge_failed: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Purga corridas preliminares o repetidas bajo la misma clave de proyecto.

    Reglas:
    1. Si un proyecto tiene una corrida autorizada o exportada, los borradores
       anteriores obsoletos se purgan.
    2. Si hay múltiples borradores preliminares del mismo proyecto, se conservan
       únicamente los `keep_latest_drafts` más recientes y se eliminan los viejos.
    3. Si purge_failed=True, se purgan corridas canceladas, interrumpidas o con error.
    4. Nunca se purga una corrida activa en ejecución ni la corrida autorizada/exportada.
    """
    base_dir = Path(base_dir)
    if not base_dir.exists():
        return {"purged_runs": [], "count": 0, "bytes_freed": 0, "dry_run": dry_run}

    # Agrupar por project key
    by_key: dict[str, list[dict[str, Any]]] = {}
    corrupted_dirs: list[Path] = []

    for item in base_dir.iterdir():
        if not item.is_dir():
            continue
        run_file = item / "run.json"
        if not run_file.exists():
            corrupted_dirs.append(item)
            continue
        try:
            state = json.loads(run_file.read_text(encoding="utf-8"))
            state["_dir"] = str(item)
            key = state.get("key", "").upper()
            if not key:
                key = item.name.split("_")[0].upper()
            by_key.setdefault(key, []).append(state)
        except (OSError, ValueError):
            corrupted_dirs.append(item)

    to_purge: list[dict[str, Any]] = []

    for k, runs in by_key.items():
        if project_key and k != project_key.upper():
            continue

        # Ordenar por fecha de inicio descendente (más reciente primero)
        runs.sort(key=lambda r: r.get("started_at", "") or "", reverse=True)

        has_approved = any((r.get("status") or "").lower() in FINAL_STATUSES for r in runs)
        draft_count = 0

        for r in runs:
            status = (r.get("status") or "").lower()
            run_id = r.get("id") or Path(r["_dir"]).name

            # No tocar corridas en ejecución activa
            if status in ACTIVE_STATUSES:
                continue

            # Preservar corridas aprobadas o exportadas
            if status in FINAL_STATUSES:
                continue

            # Corridas fallidas/canceladas
            if purge_failed and status in DISCARDABLE_STATUSES:
                to_purge.append({"id": run_id, "path": r["_dir"], "key": k, "reason": f"Status descartable: {status}"})
                continue

            # Si ya hay una versión aprobada, los borradores son obsoletos
            if has_approved:
                to_purge.append({"id": run_id, "path": r["_dir"], "key": k, "reason": "Superado por corrida aprobada/exportada"})
                continue

            # Si no hay aprobada, conservar solo los últimos `keep_latest_drafts`
            draft_count += 1
            if draft_count > keep_latest_drafts:
                to_purge.append({"id": run_id, "path": r["_dir"], "key": k, "reason": f"Borrador excedente (se conserva el más reciente)"})

    # Procesar carpetas corruptas
    for cdir in corrupted_dirs:
        to_purge.append({"id": cdir.name, "path": str(cdir), "key": "UNKNOWN", "reason": "Carpeta corrupta sin run.json válido"})

    bytes_freed = 0
    purged_items: list[dict[str, Any]] = []

    for item in to_purge:
        p = Path(item["path"])
        size = get_dir_size(p)
        bytes_freed += size
        purged_items.append({
            "id": item["id"],
            "key": item["key"],
            "reason": item["reason"],
            "bytes": size,
        })
        if not dry_run:
            try:
                shutil.rmtree(p, ignore_errors=True)
            except OSError as err:
                logger.warning("No se pudo eliminar %s: %s", p, err)

    return {
        "purged_runs": purged_items,
        "count": len(purged_items),
        "bytes_freed": bytes_freed,
        "dry_run": dry_run,
    }


def purge_raw_uploads(
    uploads_dir: Path,
    max_age_seconds: float = 3600.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Elimina carpetas temporales de subida en data/uploads tras procesarse o expirar."""
    uploads_dir = Path(uploads_dir)
    if not uploads_dir.exists():
        return {"purged_uploads": [], "count": 0, "bytes_freed": 0, "dry_run": dry_run}

    now = time.time()
    purged: list[dict[str, Any]] = []
    bytes_freed = 0

    for item in uploads_dir.iterdir():
        if not item.is_dir():
            continue
        try:
            mtime = item.stat().st_mtime
            age = now - mtime
            if age >= max_age_seconds:
                size = get_dir_size(item)
                bytes_freed += size
                purged.append({"upload_id": item.name, "bytes": size, "age_hours": round(age / 3600, 2)})
                if not dry_run:
                    shutil.rmtree(item, ignore_errors=True)
        except (OSError, PermissionError):
            continue

    return {
        "purged_uploads": purged,
        "count": len(purged),
        "bytes_freed": bytes_freed,
        "dry_run": dry_run,
    }


def slim_run_artifacts(run_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    """Elimina archivos pesados intermedios (ej. subcarpetas de planos descomprimidos) de una corrida finalizada."""
    run_dir = Path(run_dir)
    if not run_dir.exists():
        return {"freed_bytes": 0, "removed_files": []}

    removed = []
    freed = 0

    # Subcarpetas _zip creadas durante la indexación
    for sub in run_dir.glob("*_zip"):
        if sub.is_dir():
            size = get_dir_size(sub)
            freed += size
            removed.append(str(sub.name))
            if not dry_run:
                shutil.rmtree(sub, ignore_errors=True)

    # Archivos temporales .tmp
    for tmp in run_dir.glob("*.tmp"):
        if tmp.is_file():
            size = tmp.stat().st_size
            freed += size
            removed.append(tmp.name)
            if not dry_run:
                tmp.unlink(missing_ok=True)

    return {"freed_bytes": freed, "removed_files": removed, "dry_run": dry_run}


def delete_single_run(run_dir: Path) -> dict[str, Any]:
    """Elimina una corrida individual de forma segura."""
    run_dir = Path(run_dir)
    if not run_dir.exists():
        raise ValueError("Corrida no encontrada")
    size = get_dir_size(run_dir)
    shutil.rmtree(run_dir, ignore_errors=True)
    return {"id": run_dir.name, "bytes_freed": size, "status": "deleted"}


def recycle_all(
    root_dir: Path,
    project_key: str | None = None,
    keep_latest_drafts: int = 1,
    max_upload_age_seconds: float = 3600.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Ejecuta una pasada completa de reciclaje y purga en el motor."""
    root_dir = Path(root_dir)
    runs_dir = root_dir / "ENTREGAS" / "AGENTE"
    uploads_dir = root_dir / "data" / "uploads"

    runs_res = purge_superseded_runs(
        base_dir=runs_dir,
        project_key=project_key,
        keep_latest_drafts=keep_latest_drafts,
        dry_run=dry_run,
    )

    uploads_res = purge_raw_uploads(
        uploads_dir=uploads_dir,
        max_age_seconds=max_upload_age_seconds,
        dry_run=dry_run,
    )

    total_bytes = runs_res["bytes_freed"] + uploads_res["bytes_freed"]
    return {
        "status": "success",
        "dry_run": dry_run,
        "total_bytes_freed": total_bytes,
        "runs": runs_res,
        "uploads": uploads_res,
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ALKAN Bid Engine — Reciclador de Estimados")
    parser.add_argument("--root", default=".", help="Ruta raíz del repositorio")
    parser.add_argument("--key", default=None, help="Clave de proyecto específico (ej. GONYEA)")
    parser.add_argument("--keep", type=int, default=1, help="Número de borradores recientes a conservar")
    parser.add_argument("--max-upload-age", type=float, default=3600.0, help="Edad máxima de subidas en segundos")
    parser.add_argument("--dry-run", action="store_true", help="Simula sin borrar")
    args = parser.parse_args()

    res = recycle_all(
        root_dir=Path(args.root),
        project_key=args.key,
        keep_latest_drafts=args.keep,
        max_upload_age_seconds=args.max_upload_age,
        dry_run=args.dry_run,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))

