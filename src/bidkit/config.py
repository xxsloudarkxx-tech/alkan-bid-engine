from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .contractor import (
    ComplianceRequirement,
    ContractorIdentity,
    load_compliance_requirements,
    load_contractor_identity,
)
from .data_store import read_json


def project_id(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    project_name: str | None = None
    contractor_source: str | Path | dict[str, Any] | None = None
    compliance_source: str | Path | dict[str, Any] | list[Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())
        if not self.project_name:
            raise ValueError("Seleccione un proyecto explícitamente con --project; no existe proyecto por defecto.")
        if self.project_name not in list_projects(self.root):
            matches = [n for n in list_projects(self.root) if project_id(n) == self.project_name]
            if len(matches) != 1:
                raise ValueError(f"Proyecto desconocido: {self.project_name}")
            object.__setattr__(self, "project_name", matches[0])
        if not self.source_root.resolve().is_relative_to((self.root / "docs").resolve()):
            raise ValueError("El expediente debe estar dentro de docs/.")
        if sum(project_id(n) == self.id for n in list_projects(self.root)) != 1:
            raise ValueError("Identificador de proyecto ambiguo.")

    @property
    def id(self) -> str:
        return project_id(self.project_name)

    @property
    def source_root(self) -> Path:
        return self.root / "docs" / self.project_name

    @property
    def project_dir(self) -> Path:
        return self.root / "projects" / self.id

    @property
    def data_dir(self) -> Path:
        return self.root / "data" / "projects" / self.id

    @property
    def audit_dir(self) -> Path:
        return self.data_dir / "audit"

    @property
    def output_dir(self) -> Path:
        return self.root / "output" / self.id

    @property
    def source_files(self) -> list[Path]:
        return sorted(p for p in self.source_root.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")

    @property
    def source_assets(self) -> list[Path]:
        return sorted(p for p in self.source_root.rglob("*") if p.is_file())

    @property
    def metadata(self) -> dict:
        path = self.project_dir / "project.json"
        data = read_json(path) if path.exists() else {"id": self.id, "name": self.project_name, "contractor": None}
        if data.get("id") != self.id or data.get("name") != self.project_name:
            raise ValueError("La configuración pertenece a otro proyecto.")
        return data

    @property
    def contractor_identity(self) -> ContractorIdentity:
        """Resolves the contractor identity from explicit source, project.json, or placeholder."""
        if self.contractor_source is not None:
            return load_contractor_identity(self.contractor_source)
        contractor_file = self.project_dir / "contractor.json"
        if contractor_file.exists():
            return load_contractor_identity(contractor_file)
        meta_contractor = self.metadata.get("contractor")
        if isinstance(meta_contractor, (dict, str)):
            return load_contractor_identity(meta_contractor)
        return load_contractor_identity(None)

    @property
    def compliance_requirements(self) -> list[ComplianceRequirement]:
        """Resolves compliance requirements from explicit source, project dir, or generic placeholder."""
        if self.compliance_source is not None:
            return load_compliance_requirements(self.compliance_source)
        compliance_file = self.project_dir / "compliance.json"
        if compliance_file.exists():
            return load_compliance_requirements(compliance_file)
        meta_compliance = self.metadata.get("compliance")
        if meta_compliance is not None:
            return load_compliance_requirements(meta_compliance)
        return load_compliance_requirements(None)


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError("No se encontró pyproject.toml; ejecute desde la raíz del proyecto.")


def list_projects(root: Path) -> list[str]:
    docs = root / "docs"
    return sorted(p.name for p in docs.iterdir() if p.is_dir() and any(f.suffix.lower() == ".pdf" for f in p.rglob("*"))) if docs.exists() else []
