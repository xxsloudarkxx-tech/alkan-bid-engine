"""Safely remove V3.1 code changes while preserving all dossier data.

The default mode is a dry run.  ``--apply`` first verifies every changed file
against the release manifest, archives the current files, then restores the
pre-V3.1 bytes from the audited code archive.  Project revisions, originals,
exports and audit evidence are outside the restore set.
"""
from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import argparse
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "data" / "v31_audit"
PRESERVED = {"projects", "data", "output", "ENTREGAS"}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def safe_target(relative: str) -> Path:
    target = (ROOT / relative).resolve()
    if not target.is_relative_to(ROOT):
        raise ValueError(f"Ruta fuera del proyecto: {relative}")
    if target.relative_to(ROOT).parts and target.relative_to(ROOT).parts[0] in PRESERVED:
        raise ValueError(f"La reversión no puede tocar datos del expediente: {relative}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="aplicar después de verificar el manifiesto")
    args = parser.parse_args()
    baseline = json.loads((AUDIT / "baseline.json").read_text(encoding="utf-8"))
    archive = AUDIT / "before_v31_code.zip"
    if sha256(archive.read_bytes()).hexdigest() != baseline["archive_sha256"]:
        raise ValueError("El respaldo de código V3.1 no coincide con su hash auditado")
    before_rows = json.loads((AUDIT / "before_v31_manifest.json").read_text(encoding="utf-8"))
    before = {row["path"]: row["sha256"] for row in before_rows}
    release = json.loads((AUDIT / "release_manifest.json").read_text(encoding="utf-8"))
    changed = [row for row in release["files"] if row["status"] in {"modified", "added"}]
    for row in changed:
        target = safe_target(row["path"])
        if row["status"] == "added":
            if target.exists() and digest(target) != row["sha256"]:
                raise ValueError(f"Archivo añadido cambió después del cierre: {row['path']}")
        elif not target.exists() or digest(target) != row["sha256"]:
            raise ValueError(f"Trabajo posterior detectado; no se sobrescribe: {row['path']}")
    print(f"Archivos de código V3.1 verificados: {len(changed)}")
    if not args.apply:
        for row in changed:
            print(row["status"], row["path"])
        print("Dry run: no se modificó ningún archivo. Use --apply con el servidor detenido.")
        return
    saved = AUDIT / ("before_rollback_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f"))
    saved.mkdir(parents=True)
    with ZipFile(archive) as backup:
        for row in changed:
            target = safe_target(row["path"])
            if target.exists():
                destination = saved / row["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, destination)
            if row["path"] in before:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(backup.read(row["path"]))
            elif target.exists():
                target.unlink()
    print("Código anterior restaurado; expedientes, documentos originales, revisiones y exportaciones conservados.")
    print(f"Copia de los cambios aplicada en: {saved}")


if __name__ == "__main__":
    main()
