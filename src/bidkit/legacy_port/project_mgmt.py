"""
CLI commands for project management and migration.

Provides utilities to:
- List all projects
- Initialize new projects from docs/
- Migrate legacy single-project workspace
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .data_store import ProjectDataStore, initialize_project_data
from .project_schema import (
    ContractorInfo,
    ProjectConfig,
    ProjectEstimateConfig,
    ProjectMetadata,
    discover_projects,
    find_workspace_root,
)


def list_projects(workspace_root: Path | None = None) -> list[ProjectConfig]:
    """List all available projects in the workspace."""
    projects = discover_projects(workspace_root)

    if not projects:
        print("No projects found in projects/ directory.")
        print("Use 'bidkit init-project' to create a new project.")
        return []

    print(f"\n{'Project ID':<30} {'Name':<40} {'Owner':<30}")
    print("=" * 100)

    for project in projects:
        print(
            f"{project.metadata.project_id:<30} "
            f"{project.metadata.project_name:<40} "
            f"{project.metadata.owner:<30}"
        )

    print(f"\nTotal: {len(projects)} projects")
    return projects


def init_project(
    project_id: str,
    project_name: str,
    owner: str,
    location: str,
    workspace_root: Path | None = None,
) -> ProjectConfig:
    """Initialize a new project with default structure."""

    if workspace_root is None:
        workspace_root = find_workspace_root()

    projects_dir = workspace_root / "projects"
    project_root = projects_dir / project_id

    if project_root.exists():
        raise FileExistsError(f"Project {project_id} already exists at {project_root}")

    # Create project structure
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "sources").mkdir(exist_ok=True)
    (project_root / "data").mkdir(exist_ok=True)
    (project_root / "output").mkdir(exist_ok=True)

    # Create project configuration
    metadata = ProjectMetadata(
        project_id=project_id,
        project_name=project_name,
        owner=owner,
        location=location,
        disciplines=[],
        source_files_glob="*.pdf",
        keywords={},
    )

    contractor = ContractorInfo()
    estimate_config = ProjectEstimateConfig()

    config = ProjectConfig(
        metadata=metadata,
        contractor=contractor,
        estimate_config=estimate_config,
        root=project_root,
    )

    config.save_to_file()

    # Initialize data files
    initialize_project_data(project_root)

    print(f"✓ Created project: {project_id}")
    print(f"  Location: {project_root}")
    print(f"  Structure:")
    print(f"    {project_root / 'project.json'}")
    print(f"    {project_root / 'sources/'} ← Place source PDFs here")
    print(f"    {project_root / 'data/'}")
    print(f"    {project_root / 'output/'}")

    return config


def migrate_legacy_project(
    workspace_root: Path | None = None,
    project_id: str = "legacy-project-001",
    contractor_source: str | Path | dict | None = None,
    compliance_source: str | Path | dict | list | None = None,
) -> ProjectConfig:
    """Migrate a legacy single-project workspace to the multi-project structure."""

    if workspace_root is None:
        workspace_root = find_workspace_root()

    projects_dir = workspace_root / "projects"
    project_root = projects_dir / project_id

    if project_root.exists():
        print(f"Project {project_id} already exists. Skipping migration.")
        return ProjectConfig.load_from_file(project_root)

    print(f"Migrating legacy project to {project_root}...")

    # Create structure
    project_root.mkdir(parents=True, exist_ok=True)
    sources_dir = project_root / "sources"
    sources_dir.mkdir(exist_ok=True)

    # Copy legacy PDFs from workspace root to sources/
    legacy_pdfs = list(workspace_root.glob("*.pdf"))

    if legacy_pdfs:
        print(f"  Copying {len(legacy_pdfs)} source PDFs...")
        for pdf in legacy_pdfs:
            dest = sources_dir / pdf.name
            if not dest.exists():
                shutil.copy2(pdf, dest)
                print(f"    ✓ {pdf.name}")

    from ..contractor import load_compliance_requirements, load_contractor_identity

    identity = load_contractor_identity(contractor_source)
    compliance_reqs = load_compliance_requirements(compliance_source)

    # Create project.json
    metadata = ProjectMetadata(
        project_id=project_id,
        project_name="TO_BE_FILLED",
        owner="TO_BE_FILLED",
        location="TO_BE_FILLED",
        bid_number="TO_BE_FILLED",
        project_number="TO_BE_FILLED",
        disciplines=["roofing", "architectural"],
        description="Migrated project",
        bid_opening_date="2026-10-29",
        bid_opening_time="14:00",
        procurement_status="active",
        source_files_glob="*.pdf",
        keywords={
            "instructions_to_bidders": ["00 21 00", "INSTRUCTIONS TO BIDDERS"],
            "bid_form": ["00 41 00", "BID FORM"],
            "bid_security": ["00 43 13", "BID SECURITY"],
            "responsibility_detail": ["00 45 13", "RESPONSIBILITY DETAIL"],
            "standing_seam": ["07 41 00", "PREFORMED METAL STANDING SEAM"],
            "allowance": ["ALLOWANCE", "UNFORESEEN"],
            "sales_tax": ["SALES TAX", "10.5%", "10.50%"],
            "bid_deadline": ["BID OPENING", "OCTOBER 29, 2026", "2:00 PM"],
            "addendum": ["ADDENDUM", "ADDENDA"],
            "substitution": ["SUBSTITUTION", "APPROVED EQUAL"],
        },
        specifications_files=["project_specs.pdf"],
        drawings_files=["project_drawings.pdf"],
    )

    contractor = ContractorInfo(
        legal_name=identity.legal_name,
        location_city=identity.location_city,
        location_state=identity.location_state,
        wa_ubi=identity.wa_ubi,
        contractor_registration=identity.contractor_registration,
        classification=identity.classification,
        registration_status=identity.registration_status,
    )

    estimate_config = ProjectEstimateConfig(
        tax_rate=0.105,
        tax_rate_status="VERIFIED BID FORM",
        tax_rate_source="project_specs.pdf | 00 41 00 p. 1",
        allowance=25000.0,
        allowance_status="VERIFIED BID FORM",
        allowance_source="project_specs.pdf | 00 41 00 p. 1",
    )

    config = ProjectConfig(
        metadata=metadata,
        contractor=contractor,
        estimate_config=estimate_config,
        root=project_root,
    )

    config.save_to_file()
    print(f"  ✓ Created project.json")

    try:
        from ..records import AMENDMENTS, REQUIREMENTS, RISKS, TAKEOFF

        store = ProjectDataStore(project_root)
        store.save_requirements(REQUIREMENTS)
        store.save_amendments(AMENDMENTS)
        store.save_risks(RISKS)
        store.save_takeoff(TAKEOFF)
        print(f"  ✓ Migrated legacy data records")

        compliance_records = [
            {
                "requirement_name": req.requirement_name,
                "category": req.category,
                "status": req.status,
                "evidence_file": req.evidence_file,
                "notes": req.notes,
            }
            for req in compliance_reqs
        ]
        store.save_compliance_requirements(compliance_records)
        print(f"  ✓ Migrated compliance requirements")

    except ImportError:
        print("  ⚠ Could not import legacy data (already refactored?)")
        initialize_project_data(project_root)

    # Copy legacy data/ and output/ directories
    legacy_data = workspace_root / "data"
    legacy_output = workspace_root / "output"

    if legacy_data.exists():
        dest_data = project_root / "data"
        if not dest_data.exists() or not list(dest_data.iterdir()):
            shutil.copytree(legacy_data, dest_data, dirs_exist_ok=True)
            print(f"  ✓ Copied legacy data/ directory")

    if legacy_output.exists():
        dest_output = project_root / "output"
        if not dest_output.exists() or not list(dest_output.iterdir()):
            shutil.copytree(legacy_output, dest_output, dirs_exist_ok=True)
            print(f"  ✓ Copied legacy output/ directory")

    print(f"\n✓ Migration complete: {project_id}")
    print(f"  Location: {project_root}")

    return config


def auto_discover_projects_from_docs(
    workspace_root: Path | None = None,
) -> list[ProjectConfig]:
    """Auto-discover projects from docs/ directory and create project stubs."""

    if workspace_root is None:
        workspace_root = find_workspace_root()

    docs_dir = workspace_root / "docs"

    if not docs_dir.exists():
        print("No docs/ directory found.")
        return []

    discovered = []

    # Expected project mappings
    project_mappings = {
        "Gonyea Playfield": {
            "id": "gonyea-playfield",
            "name": "Gonyea Playfield",
            "owner": "Pierce County",
            "location": "Pierce County, WA",
            "bid_number": "2026-MPW-244",
        },
        "Orangegate Park Phase 1": {
            "id": "orangegate-park-phase-1",
            "name": "Orangegate Park Phase 1 Site Improvements",
            "owner": "Pierce County",
            "location": "Pierce County, WA",
            "bid_number": "2026-MPW-241",
            "project_number": "P-111031",
        },
        "REBID - Meridian": {
            "id": "meridian-rebid",
            "name": "Meridian Play Area Renovation & ADA Meridian RR Design",
            "owner": "City of Seattle",
            "location": "Seattle, WA",
            "bid_number": "PW2025-037",
            "description": "RE-BID",
        },
        "W Seattle Junction Landbank Park": {
            "id": "west-seattle-junction",
            "name": "West Seattle Junction Landbank Park",
            "owner": "City of Seattle",
            "location": "Seattle, WA",
            "bid_number": "PW2019-094",
            "description": "Historical project (2019) - verify if still active",
        },
    }

    for folder in docs_dir.iterdir():
        if not folder.is_dir():
            continue

        folder_name = folder.name
        mapping = project_mappings.get(folder_name)

        if not mapping:
            print(f"⚠ Unknown docs folder: {folder_name}")
            continue

        project_id = mapping["id"]
        projects_dir = workspace_root / "projects"
        project_root = projects_dir / project_id

        if project_root.exists():
            print(f"  Project {project_id} already exists. Skipping.")
            continue

        # Initialize project
        try:
            config = init_project(
                project_id=project_id,
                project_name=mapping["name"],
                owner=mapping["owner"],
                location=mapping["location"],
                workspace_root=workspace_root,
            )

            # Update metadata with additional fields
            config.metadata.bid_number = mapping.get("bid_number")
            config.metadata.project_number = mapping.get("project_number")
            config.metadata.description = mapping.get("description", "")
            config.save_to_file()

            # Create symlink or note about source docs
            sources_readme = config.source_root / "README.md"
            sources_readme.write_text(
                f"# Source Documents\n\n"
                f"Original documents are in: `../../docs/{folder_name}/`\n\n"
                f"Copy PDFs here or process them directly from docs/.\n",
                encoding="utf-8",
            )

            discovered.append(config)
            print(f"  ✓ Initialized {project_id} from docs/{folder_name}/")

        except Exception as e:
            print(f"  ✗ Failed to initialize {project_id}: {e}")

    return discovered
