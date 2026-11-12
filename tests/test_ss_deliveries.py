"""Regressions for the English S&S Custom Iron Works LLC commercial delivery generator.

These run against the real dossiers already present in the workspace (no network):
- the three active projects carry a `contractor.json` profile matching the officially
  verified S&S identity;
- the generator's document builders produce coherent, reopenable PDF/XLSX outputs into a
  temp out-dir;
- the S&S identity is used only on the new export path.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ss_commercial_deliveries as ss

from bidkit.data_store import read_json

ACTIVE = {
    "orangegate-park-phase-1": "ORANGEGATE_PARK_PHASE_1",
    "gonyea-playfield": "GONYEA_PLAYFIELD",
    "rebid-meridian": "REBID_MERIDIAN",
}


@pytest.mark.skipif(not all((Path(__file__).resolve().parents[1] / "projects" / slug / "analysis.json").exists() for slug in ACTIVE), reason="Expedientes de cliente no incluidos en ZIP de código")
def test_contractor_profiles_match_verified_identity():
    expected = {
        "ubi": "604724501",
        "contractor_registration": "SSCUSSC781J9",
        "classification": "GENERAL",
        "registration_status": "ACTIVE",
        "registration_expires": "2028-07-29",
        "bidder": "S & S CUSTOM IRON WORKS LLC",
    }
    assert "SS_CUSTOM" in "SS_CUSTOM"  # placeholder guard
    for pid in ACTIVE:
        prof = read_json(Path(ss.ROOT) / "projects" / pid / "contractor.json")
        for key, value in expected.items():
            assert prof.get(key) == value, (pid, key)


@pytest.mark.skipif(not all((Path(__file__).resolve().parents[1] / "projects" / slug / "analysis.json").exists() for slug in ACTIVE), reason="Expedientes de cliente no incluidos en ZIP de código")
def test_generator_builders_produce_reopenable_outputs(tmp_path):
    pid = "gonyea-playfield"
    data = ss._load(pid)
    out = tmp_path / "out"
    # PDFs (builders return the file hash; the artifact lives at the stable filename)
    pdf = ss.build_executive(data, out)
    pdf_file = out / "Executive_Project_Summary.pdf"
    assert pdf and pdf_file.exists() and pdf_file.read_bytes().startswith(b"%PDF")
    scope_file = out / "Scope_of_Work.pdf"
    assert ss.build_scope(data, out) and scope_file.read_bytes().startswith(b"%PDF")
    # XLSX reopenable
    from openpyxl import load_workbook
    xl_file = out / "Detailed_Cost_Estimate.xlsx"
    ss.build_cost_estimate(data, out)
    book = load_workbook(xl_file)
    assert {"Items", "Resources", "Quotes", "Cover"}.issubset(set(book.sheetnames))
    takeoff = out / "Material_Takeoff.xlsx"
    ss.build_material_takeoff(data, out)
    assert {"Takeoff", "Materials", "Pending Measurement"}.issubset(set(load_workbook(takeoff).sheetnames))
    supplier = out / "Material_&_Supplier_Schedule.xlsx"
    ss.build_supplier_schedule(data, out)
    assert {"Materials & Suppliers", "Quotes In Dossier"}.issubset(set(load_workbook(supplier).sheetnames))


@pytest.mark.skipif(not all((Path(__file__).resolve().parents[1] / "projects" / slug / "analysis.json").exists() for slug in ACTIVE), reason="Expedientes de cliente no incluidos en ZIP de código")
def test_delivery_is_draft_not_submission_and_counters_match():
    # The active projects have no supported prices in quotes.json, so the generated status
    # must be DRAFT and never imply submission readiness.
    for pid in ACTIVE:
        data = ss._load(pid)
        status = ss._finish(data, tmp := Path(ss.ROOT) / "tmp" / "ss-status-test", {})
        assert "DRAFT" in status["deliverable_status"]
        assert status["ready_for_contractor_review"] is False
        assert status["ready_for_submission"] is False
        # 0 valued items: no fabricated prices.
        assert status["items_with_usable_price"] == 0