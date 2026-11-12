"""Local append-only project revisions. No database or remote side effects."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
import re
import os
import tempfile

from .data_store import fingerprint, read_json


def utcnow():
    return datetime.now(UTC).isoformat()


class RevisionConflict(ValueError):
    pass


class DossierStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def directory(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,90}", project_id):
            raise ValueError("Identificador de proyecto inválido")
        path = self.root / "projects" / project_id / "intelligence"
        if not path.resolve().is_relative_to(self.root / "projects"):
            raise ValueError("Ruta fuera del expediente")
        return path

    def child(self, project_id, folder, name=""):
        base=self.directory(project_id).resolve()
        path=base/folder/name
        if not path.resolve().is_relative_to(base): raise ValueError("Ruta fuera del expediente")
        return path

    @contextmanager
    def locked(self, project_id):
        folder = self.directory(project_id)
        folder.mkdir(parents=True, exist_ok=True)
        lock = folder / ".write-lock"
        try:
            handle = lock.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise RevisionConflict("Expediente ocupado; recargue antes de guardar") from exc
        try:
            handle.write(utcnow()); handle.close()
            yield
        finally:
            lock.unlink()

    def history(self, project_id):
        folder = self.child(project_id,"revisions")
        rows, previous = [], None
        for index, path in enumerate(sorted(folder.glob("*.json")), 1):
            row = read_json(path)
            digest = row.pop("sha256", None)
            if (row["revision"] != index or row["project_id"] != project_id
                    or row["previous_sha256"] != previous or fingerprint(row) != digest):
                raise ValueError("Historial modificado o incompleto")
            row["sha256"] = digest
            rows.append(row); previous = digest
        return rows

    def load(self, project_id):
        rows = self.history(project_id)
        if not rows:
            raise FileNotFoundError("Expediente V2 no encontrado")
        return deepcopy(rows[-1])

    def append(self, project_id, state, expected_revision, actor, action):
        # Caller holds the project lock across read/validate/write, including upload.
        rows = self.history(project_id)
        current = rows[-1] if rows else None
        if expected_revision != (current["revision"] if current else 0):
            raise RevisionConflict("El expediente cambió. Recargue antes de guardar.")
        if not str(actor or "").strip():
            raise ValueError("Responsable de revisión obligatorio")
        row = {"project_id": project_id, "revision": expected_revision + 1,
               "previous_sha256": current["sha256"] if current else None,
               "created_at": utcnow(), "actor": actor, "action": action, "state": state}
        row["sha256"] = fingerprint(row)
        folder = self.child(project_id,"revisions")
        folder.mkdir(exist_ok=True)
        import json
        raw=json.dumps(row,ensure_ascii=False,indent=2,allow_nan=False)
        fd, staged=tempfile.mkstemp(dir=folder,suffix=".staged")
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as fp:
                fp.write(raw);fp.flush();os.fsync(fp.fileno())
            os.link(staged,folder/f"{row['revision']:06d}.json")  # Exclusive, complete-file publication.
        finally: Path(staged).unlink(missing_ok=True)
        return row
