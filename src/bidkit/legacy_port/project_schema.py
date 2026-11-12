"""
Project configuration schema and validation.

Defines the structure of project.json files and provides
utilities for loading, validating, and managing project configurations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass
class ProjectMetadata:
    """Core project identification and metadata."""

    project_id: str
    project_name: str
    owner: str
    location: str
    bid_number: str | None = None
    project_number: str | None = None
    disciplines: list[str] = field(default_factory=list)
    description: str = ""

    # Dates
    bid_opening_date: str | None = None
    bid_opening_time: str | None = None
    procurement_status: Literal["active", "closed", "archived", "unknown"] = "unknown"

    # Source configuration
    source_files_glob: str = "*.pdf"
    keywords: dict[str, list[str]] = field(default_factory=dict)
    specifications_files: list[str] = field(default_factory=list)
    drawings_files: list[str] = field(default_factory=list)


@dataclass
class ContractorInfo:
    """Contractor identity for this specific project."""

    legal_name: str = "CONTRACTOR_NOT_ASSIGNED"
    location_city: str = ""
    location_state: str = ""
    wa_ubi: str | None = None
    contractor_registration: str | None = None
    classification: str = ""
    registration_status: str = "PENDING"

    def format_full_location(self) -> str:
        """Returns 'City, State' format."""
        if self.location_city and self.location_state:
            return f"{self.location_city}, {self.location_state}"
        return ""

    def format_legal_header(self) -> str:
        """Returns formatted name and location for bid documents."""
        location = self.format_full_location()
        if location:
            return f"{self.legal_name}\n{location}"
        return self.legal_name


@dataclass
class ProjectEstimateConfig:
    """Estimate-specific configuration for a project."""

    tax_rate: float = 0.0
    tax_rate_status: str = "PENDING"
    tax_rate_source: str | None = None

    allowance: float = 0.0
    allowance_status: str = "PENDING"
    allowance_source: str | None = None

    overhead_rate: float = 0.0
    profit_rate: float = 0.0

    estimate_basis: str = "unit_price"  # or "lump_sum", "time_and_materials"


@dataclass
class ProjectConfig:
    """Complete project configuration."""

    metadata: ProjectMetadata
    contractor: ContractorInfo = field(default_factory=ContractorInfo)
    estimate_config: ProjectEstimateConfig = field(default_factory=ProjectEstimateConfig)

    # File paths (resolved at runtime)
    root: Path = field(default_factory=Path)

    @property
    def source_root(self) -> Path:
        """Root directory containing project PDFs."""
        return self.root / "sources"

    @property
    def data_dir(self) -> Path:
        """Data directory for intermediate processing."""
        return self.root / "data"

    @property
    def output_dir(self) -> Path:
        """Output directory for generated documents."""
        return self.root / "output"

    @property
    def audit_dir(self) -> Path:
        """Audit directory for document inventories."""
        return self.data_dir / "audit"

    @property
    def takeoff_dir(self) -> Path:
        """Takeoff directory for quantity records."""
        return self.data_dir / "takeoff"

    @property
    def estimate_dir(self) -> Path:
        """Estimate directory for cost data."""
        return self.data_dir / "estimate"

    @property
    def source_files(self) -> list[Path]:
        """Discover project source PDFs using glob pattern."""
        pattern = self.metadata.source_files_glob
        source_root = self.source_root

        if not source_root.exists():
            return []

        files = sorted(source_root.glob(pattern))
        return files

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON export."""
        return {
            "metadata": {
                "project_id": self.metadata.project_id,
                "project_name": self.metadata.project_name,
                "owner": self.metadata.owner,
                "location": self.metadata.location,
                "bid_number": self.metadata.bid_number,
                "project_number": self.metadata.project_number,
                "disciplines": self.metadata.disciplines,
                "description": self.metadata.description,
                "bid_opening_date": self.metadata.bid_opening_date,
                "bid_opening_time": self.metadata.bid_opening_time,
                "procurement_status": self.metadata.procurement_status,
                "source_files_glob": self.metadata.source_files_glob,
                "keywords": self.metadata.keywords,
                "specifications_files": self.metadata.specifications_files,
                "drawings_files": self.metadata.drawings_files,
            },
            "contractor": {
                "legal_name": self.contractor.legal_name,
                "location_city": self.contractor.location_city,
                "location_state": self.contractor.location_state,
                "wa_ubi": self.contractor.wa_ubi,
                "contractor_registration": self.contractor.contractor_registration,
                "classification": self.contractor.classification,
                "registration_status": self.contractor.registration_status,
            },
            "estimate_config": {
                "tax_rate": self.estimate_config.tax_rate,
                "tax_rate_status": self.estimate_config.tax_rate_status,
                "tax_rate_source": self.estimate_config.tax_rate_source,
                "allowance": self.estimate_config.allowance,
                "allowance_status": self.estimate_config.allowance_status,
                "allowance_source": self.estimate_config.allowance_source,
                "overhead_rate": self.estimate_config.overhead_rate,
                "profit_rate": self.estimate_config.profit_rate,
                "estimate_basis": self.estimate_config.estimate_basis,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], root: Path) -> ProjectConfig:
        """Deserialize from dictionary (loaded from JSON)."""
        meta = data.get("metadata", {})
        metadata = ProjectMetadata(
            project_id=meta["project_id"],
            project_name=meta["project_name"],
            owner=meta["owner"],
            location=meta["location"],
            bid_number=meta.get("bid_number"),
            project_number=meta.get("project_number"),
            disciplines=meta.get("disciplines", []),
            description=meta.get("description", ""),
            bid_opening_date=meta.get("bid_opening_date"),
            bid_opening_time=meta.get("bid_opening_time"),
            procurement_status=meta.get("procurement_status", "unknown"),
            source_files_glob=meta.get("source_files_glob", "*.pdf"),
            keywords=meta.get("keywords", {}),
            specifications_files=meta.get("specifications_files", []),
            drawings_files=meta.get("drawings_files", []),
        )

        contr = data.get("contractor", {})
        contractor = ContractorInfo(
            legal_name=contr.get("legal_name", "CONTRACTOR_NOT_ASSIGNED"),
            location_city=contr.get("location_city", ""),
            location_state=contr.get("location_state", ""),
            wa_ubi=contr.get("wa_ubi"),
            contractor_registration=contr.get("contractor_registration"),
            classification=contr.get("classification", ""),
            registration_status=contr.get("registration_status", "PENDING"),
        )

        est = data.get("estimate_config", {})
        estimate_config = ProjectEstimateConfig(
            tax_rate=est.get("tax_rate", 0.0),
            tax_rate_status=est.get("tax_rate_status", "PENDING"),
            tax_rate_source=est.get("tax_rate_source"),
            allowance=est.get("allowance", 0.0),
            allowance_status=est.get("allowance_status", "PENDING"),
            allowance_source=est.get("allowance_source"),
            overhead_rate=est.get("overhead_rate", 0.0),
            profit_rate=est.get("profit_rate", 0.0),
            estimate_basis=est.get("estimate_basis", "unit_price"),
        )

        return cls(
            metadata=metadata,
            contractor=contractor,
            estimate_config=estimate_config,
            root=root,
        )

    @classmethod
    def load_from_file(cls, project_root: Path) -> ProjectConfig:
        """Load project configuration from project.json."""
        config_file = project_root / "project.json"

        if not config_file.exists():
            raise FileNotFoundError(
                f"No project.json found in {project_root}. "
                f"Create one with project metadata first."
            )

        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            return cls.from_dict(data, project_root)
        except Exception as e:
            raise ValueError(f"Failed to load {config_file}: {e}")

    def save_to_file(self) -> None:
        """Save project configuration to project.json."""
        config_file = self.root / "project.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)

        config_file.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )


def find_workspace_root(start: Path | None = None) -> Path:
    """Find the workspace root by looking for pyproject.toml."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError(
        "No se encontró pyproject.toml; ejecute desde la raíz del proyecto."
    )


def discover_projects(workspace_root: Path | None = None) -> list[ProjectConfig]:
    """Discover all projects in the workspace's projects/ directory."""
    if workspace_root is None:
        workspace_root = find_workspace_root()

    projects_dir = workspace_root / "projects"

    if not projects_dir.exists():
        return []

    discovered = []

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        config_file = project_dir / "project.json"
        if not config_file.exists():
            continue

        try:
            config = ProjectConfig.load_from_file(project_dir)
            discovered.append(config)
        except Exception:
            # Skip invalid projects
            continue

    return discovered


def find_project_by_id(
    project_id: str, workspace_root: Path | None = None
) -> ProjectConfig:
    """Locate a project by ID within the workspace."""
    if workspace_root is None:
        workspace_root = find_workspace_root()

    projects_dir = workspace_root / "projects"
    project_path = projects_dir / project_id

    if project_path.exists() and (project_path / "project.json").exists():
        return ProjectConfig.load_from_file(project_path)

    raise FileNotFoundError(
        f"Project '{project_id}' not found in {projects_dir}. "
        f"Expected: {project_path}/project.json"
    )
