"""
Project data records management.

Provides utilities to load and save project-specific data records
(requirements, amendments, takeoff, risks, compliance) from JSON files
instead of hardcoded Python constants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ProjectDataStore:
    """Manages project-specific data records stored in JSON files."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.data_dir = project_root / "data"

    def _load_json(self, filename: str) -> dict[str, Any]:
        """Load a JSON file from the project data directory."""
        path = self.data_dir / filename

        if not path.exists():
            return

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ValueError(f"Failed to load {path}: {e}")

    def _save_json(self, filename: str, data: dict[str, Any]) -> None:
        """Save data to a JSON file in the project data directory."""
        path = self.data_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def load_requirements(self) -> list[dict[str, Any]]:
        """Load bid requirements checklist."""
        data = self._load_json("requirements.json")
        return data.get("requirements", [])

    def save_requirements(self, requirements: list[dict[str, Any]]) -> None:
        """Save bid requirements checklist."""
        self._save_json("requirements.json", {"requirements": requirements})

    def load_amendments(self) -> list[dict[str, Any]]:
        """Load addenda and amendments."""
        data = self._load_json("amendments.json")
        return data.get("amendments", [])

    def save_amendments(self, amendments: list[dict[str, Any]]) -> None:
        """Save addenda and amendments."""
        self._save_json("amendments.json", {"amendments": amendments})

    def load_takeoff(self) -> list[dict[str, Any]]:
        """Load takeoff records."""
        data = self._load_json("takeoff_records.json")
        return data.get("records", [])

    def save_takeoff(self, records: list[dict[str, Any]]) -> None:
        """Save takeoff records."""
        self._save_json("takeoff_records.json", {"records": records})

    def load_risks(self) -> list[dict[str, Any]]:
        """Load risk and clarification register."""
        data = self._load_json("risks.json")
        return data.get("risks", [])

    def save_risks(self, risks: list[dict[str, Any]]) -> None:
        """Save risk and clarification register."""
        self._save_json("risks.json", {"risks": risks})

    def load_compliance_requirements(self) -> list[dict[str, Any]]:
        """Load compliance requirements for this project."""
        data = self._load_json("compliance.json")
        return data.get("compliance_requirements", [])

    def save_compliance_requirements(self, requirements: list[dict[str, Any]]) -> None:
        """Save compliance requirements for this project."""
        self._save_json("compliance.json", {"compliance_requirements": requirements})

    def load_estimate_rows(self) -> list[dict[str, Any]]:
        """Load estimate line items."""
        data = self._load_json("estimate_rows.json")
        return data.get("rows", [])

    def save_estimate_rows(self, rows: list[dict[str, Any]]) -> None:
        """Save estimate line items."""
        self._save_json("estimate_rows.json", {"rows": rows})


def source(document: str, page: int | str, confidence: str = "HIGH") -> dict[str, Any]:
    """Helper function to create a source reference dictionary."""
    return {"document": document, "page": page, "confidence": confidence}


# Template data structures for new projects

def get_default_requirements_template() -> list[dict[str, Any]]:
    """Get a template for bid requirements."""
    return [
        {
            "id": "BID-001",
            "phase": "with_bid",
            "requirement": "Complete and submit official bid form",
            "status": "PENDING",
            "source": source("specifications.pdf", "TBD"),
        },
        {
            "id": "BID-002",
            "phase": "with_bid",
            "requirement": "Acknowledge all addenda",
            "status": "PENDING",
            "source": source("specifications.pdf", "TBD"),
        },
        {
            "id": "BID-003",
            "phase": "with_bid",
            "requirement": "Provide bid security (bond or check)",
            "status": "BLOCKING",
            "source": source("specifications.pdf", "TBD"),
        },
    ]


def get_default_amendments_template() -> list[dict[str, Any]]:
    """Get a template for addenda tracking."""
    return [
        {
            "addendum": "01",
            "date": "YYYY-MM-DD",
            "change": "Description of changes",
            "precedence": "active",
            "source": source("addendum_01.pdf", 1),
        },
    ]


def get_default_risks_template() -> list[dict[str, Any]]:
    """Get a template for risk register."""
    return [
        {
            "id": "R-01",
            "status": "PENDING",
            "risk": "Risk description",
            "action": "Required action or mitigation",
            "source": source("specifications.pdf", "TBD"),
        },
    ]


def get_default_takeoff_template() -> list[dict[str, Any]]:
    """Get a template for takeoff records."""
    return [
        {
            "building": "Building or Area Name",
            "item": "Work item description",
            "unit": "EA",
            "quantity": None,
            "quantity_status": "PENDIENTE DE MEDICIÓN",
            "basis": "Measurement basis or calculation",
            "source": source("drawings.pdf", "Sheet No."),
        },
    ]


def initialize_project_data(project_root: Path) -> None:
    """Initialize default data files for a new project."""
    store = ProjectDataStore(project_root)

    # Only create files if they don't exist
    if not (store.data_dir / "requirements.json").exists():
        store.save_requirements(get_default_requirements_template())

    if not (store.data_dir / "amendments.json").exists():
        store.save_amendments(get_default_amendments_template())

    if not (store.data_dir / "risks.json").exists():
        store.save_risks(get_default_risks_template())

    if not (store.data_dir / "takeoff_records.json").exists():
        store.save_takeoff(get_default_takeoff_template())

    if not (store.data_dir / "compliance.json").exists():
        store.save_compliance_requirements([])

    if not (store.data_dir / "estimate_rows.json").exists():
        store.save_estimate_rows([])
