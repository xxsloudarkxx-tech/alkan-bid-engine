from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from bidkit.audit import audit
from bidkit.config import ProjectConfig
from bidkit.data_store import write_json


@pytest.fixture
def project_factory(tmp_path):
    def make(name="Alpha", quantity=7):
        root = tmp_path / "workspace"
        path = root / "docs" / name / "schedule.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(path), invariant=1)
        pdf.drawString(50, 750, f"{name} schedule: {quantity} benches. Insurance required. Sales tax pending.")
        pdf.save()
        config = ProjectConfig(root, name)
        manifest = audit(config)
        ref = {"document": "schedule.pdf", "page": 1, "sha256": manifest["documents"][0]["sha256"], "excerpt": f"{name} schedule: {quantity} benches."}
        data = {"schema_version": 1, "project_id": config.id, "scope_status": "PARTIAL_TEST_SCOPE", "coverage": "Independent fixture", "quantities": [{"id": "Q1", "package": "Base", "pricing_scope": "base", "item": "Benches", "unit": "EA", "quantity": quantity, "quantity_status": "DOCUMENT_QUANTITY", "basis": "Explicit document schedule", "sources": [ref]}], "materials": [{"id": "M1", "description": "Bench assembly", "unit": "EA", "quantity_id": "Q1", "specification": "As scheduled", "sources": [ref]}], "requirements": [{"id": "REQ1", "status": "PENDING_EVIDENCE", "requirement": "Insurance", "sources": [ref]}], "amendments": [], "risks": [], "pending": [{"id": "P1", "issue": "Prices pending", "action": "Obtain supported quote"}], "tax_rate": None, "allowance": None}
        write_json(config.project_dir / "project.json", config.metadata)
        write_json(config.project_dir / "analysis.json", data)
        return config
    return make
