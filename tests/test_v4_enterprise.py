"""Enterprise Stage E tests for Domain, Security, Takeoff, Pricebook, Labor, Cost, Review, RFI/RFQ, Deliverables & Backup."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import zipfile

import pytest

from bidkit.backup import create_backup, restore_backup, verify_backup
from bidkit.cost_engine import analyze_package_costs, compute_13_buckets
from bidkit.deliverables_v4 import DELIVERABLE_TYPES, ImmutableVersionError, generate_all_deliverables
from bidkit.domain import (
    CANONICAL_STATES,
    AuditLedger,
    InvalidStateTransitionError,
    assert_transition,
    normalize_state,
)
from bidkit.labor_engine import (
    AdjustmentFactor,
    CrewComposition,
    CrewMemberSpec,
    ProductivityNorm,
    WageClassification,
    calculate_labor_hours,
    load_structured_wages,
    parse_legacy_productivity,
)
from bidkit.package_method import load_package
from bidkit.pricebook import PriceGovernanceError, PriceRecord, PricebookStore
from bidkit.review_engine import resolve_discrepancy, run_independent_review
from bidkit.revision_diff import compare_sheet_sets, detect_spec_drawing_inconsistencies
from bidkit.rfi_rfq import RFIRFQWorkspace, UnAuthorizedOutboundError
from bidkit.security import SelfApprovalError, sanitize_spreadsheet_cell
from bidkit.takeoff_engine import MaterialTakeoffItem, classify_sheet_text, detect_takeoff_gaps, inspect_pdf_drawings

ROOT = Path(__file__).resolve().parent.parent


def test_canonical_states_and_audit_ledger_integrity(tmp_path):
    assert len(CANONICAL_STATES) == 7
    assert normalize_state("lista") == "Review Required"
    assert normalize_state("autorizada") == "Approved"
    assert assert_transition("Draft", "Processing") == "Processing"
    assert assert_transition("Review Required", "Approved") == "Approved"
    with pytest.raises(InvalidStateTransitionError):
        assert_transition("Draft", "Exported")

    ledger = AuditLedger(tmp_path / "audit.jsonl")
    ledger.record(org_id="org1", project_id="P1", actor="alice", role="estimator", action="CREATE", state_to="Draft")
    ledger.record(org_id="org1", project_id="P1", actor="bob", role="reviewer", action="APPROVE", state_from="Review Required", state_to="Approved")
    assert ledger.verify_chain()["valid"] is True

    # Tamper detection
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["actor"] = "mallory"
    lines[0] = json.dumps(tampered)
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert ledger.verify_chain()["valid"] is False


def test_takeoff_material_item_override_and_anti_hallucination():
    item = MaterialTakeoffItem(
        code="MT-001",
        description="Handrail 1-1/2 Sch 40 pipe",
        material="Carbon Steel Pipe",
        specification="ASTM A53 Gr B",
        dimensions="1.90 in OD x 120 LF",
        unit="LF",
        calculated_qty=Decimal("100"),
        waste_factor_pct=Decimal("10"),
        final_qty=None,
        source_sheet="S4.1",
        document_ref="Plans p.12 / Detail 3",
        confidence=0.92,
        evidence_status="medido",
    )
    assert item.final_qty == Decimal("110.00")
    item.apply_manual_override(new_calculated_qty="115", actor="senior_est", reason="Added return bends per S4.2")
    assert item.final_qty == Decimal("126.50")
    assert item.original_measurement["calculated_qty"] == "100"
    assert item.review_status == "overridden"

    missing = MaterialTakeoffItem(
        code="MT-002",
        description="Embedded curb angles",
        material="Steel Angle",
        specification="ASTM A36",
        dimensions="missing",
        unit="LF",
        calculated_qty=None,
        waste_factor_pct=Decimal("5"),
        final_qty=None,
        source_sheet="A2.1",
        document_ref="Note 4",
        confidence=0.40,
        evidence_status="no_determinado",
    )
    gaps = detect_takeoff_gaps([item, missing])
    assert any(g["code"] == "MT-002" and g["type"] == "missing_measurement" for g in gaps)

    # Scanned vs vector classification
    scanned = classify_sheet_text("", document="drawings.pdf", page=1)
    assert scanned.is_scanned is True and "LOW_TEXT_DENSITY" in scanned.alerts[0]
    vector = classify_sheet_text("S4.1 STRUCTURAL FRAMING\nScale: 1/4\" = 1'-0\"\nREV A ASTM A992 14'-6\"", document="drawings.pdf", page=2)
    assert vector.discipline == "Structural" and not vector.is_scanned


def test_revision_diff_and_spec_vs_drawing_conflicts():
    base = [classify_sheet_text("A1.0 Scale: 1/4\"=1'-0\" REV 0", document="base.pdf", page=1).to_dict()]
    rev = [
        classify_sheet_text("A1.0 Scale: 1/8\"=1'-0\" REV 1", document="rev.pdf", page=1).to_dict(),
        classify_sheet_text("S2.0 Scale: 1/4\"=1'-0\" REV 1", document="rev.pdf", page=2).to_dict(),
    ]
    diff = compare_sheet_sets(base, rev)
    assert diff["added_sheets"] == ["S2.0"]
    assert any(f["finding_type"] == "scale_changed" for f in diff["findings"])

    conflicts = detect_spec_drawing_inconsistencies(
        spec_sections=[{"section": "05 50 00", "scope": "handrail", "text": "Hot-dip galvanized per ASTM A123", "declared_qty": "240 LF"}],
        drawing_notes=[{"sheet": "A4.1", "scope": "handrail", "text": "Finish: shop paint alkyd enamel", "declared_qty": "265 LF"}],
        addenda=[{"name": "Addendum 1", "text": "Bids due October 22, 2026"}, {"name": "Addendum 2", "text": "Bids due October 29, 2026"}],
    )
    types = {c["finding_type"] for c in conflicts}
    assert {"spec_vs_drawing_conflict", "quantity_conflict", "addendum_bid_date_supersession"} <= types


def test_pricebook_governance_expiration_history_and_imports(tmp_path):
    store = PricebookStore(tmp_path)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    next_month = (date.today() + timedelta(days=30)).isoformat()

    # Cannot create VERIFIED directly without verified_by & source
    with pytest.raises(PriceGovernanceError):
        PriceRecord(id="P1", org_id="orgA", material="W12x26", price_type="VERIFIED", unit_price=Decimal("28.60"))

    budget = PriceRecord(id="P-BUD", org_id="orgA", material="W12x26", specification_std="ASTM A992", unit_price=Decimal("28.60"), price_type="BUDGET", source="Nov 2026 Puget Sound list")
    store.upsert(budget)
    # Cannot verify BUDGET without supplier quote document
    with pytest.raises(PriceGovernanceError):
        store.verify_record(org_id="orgA", record_id="P-BUD", verifier="reviewer1", target_price_type="VERIFIED")

    # Import CSV quote -> creates pending_review QUOTE and preserves original file
    csv_bytes = b"material,spec,unit,unit_price,freight\nW12x26 wide flange,ASTM A992,LF,26.50,150.00\n"
    imp = store.import_quote_file(
        org_id="orgA",
        file_name="alaskan_steel_quote.csv",
        raw_bytes=csv_bytes,
        supplier="Pacific Steel Corp",
        city="Seattle",
        state="WA",
        valid_until=next_month,
    )
    assert imp["imported_count"] == 1 and imp["verification_status"] == "pending_review"
    assert Path(imp["original_document"]).exists()

    qid = imp["record_ids"][0]
    verified = store.verify_record(org_id="orgA", record_id=qid, verifier="senior_reviewer", target_price_type="VERIFIED")
    assert verified.price_type == "VERIFIED" and verified.verification_status == "verified"

    # Expired quote blocked unless allow_expired=True
    expired_q = PriceRecord(
        id="P-EXP", org_id="orgA", material="W12x26 wide flange", supplier="Old Steel", unit_price=Decimal("22.00"),
        price_type="QUOTE", valid_until=yesterday, source="old_quote.pdf",
    )
    store.upsert(expired_q)
    with pytest.raises(PriceGovernanceError):
        store.select_for_estimate("orgA", "P-EXP", allow_expired=False)
    sel_warn = store.select_for_estimate("orgA", "P-EXP", allow_expired=True)
    assert sel_warn["expired"] is True and any("EXPIRED_PRICE_WARNING" in w for w in sel_warn["warnings"])

    # Supplier comparison
    ranked = store.compare_suppliers("orgA", "W12x26", quantity=100)
    assert ranked[0]["id"] == qid  # valid quote beats expired even though unit_price higher


def test_labor_hierarchy_adjustments_and_legacy_knowledge_parsing():
    wage = WageClassification(
        key="IW-KING",
        trade="Ironworker",
        classification="Journeyman",
        county="King",
        state="WA",
        base_wage=Decimal("70.00"),
        fringe_benefits=Decimal("24.82"),
        labor_burden_pct=Decimal("15"),
        commercial_markup_pct=Decimal("20"),
        indirect_rate=Decimal("5.00"),
        source="WA L&I 2026-08-31",
        verified=True,
    )
    assert wage.total_pw_package == Decimal("94.82")
    assert wage.loaded_rate == Decimal("109.04")
    assert wage.commercial_rate > wage.loaded_rate

    # Reject arbitrary multiplier without justification/source
    with pytest.raises(ValueError):
        AdjustmentFactor(category="height", multiplier=Decimal("1.25"), justification="", source="")

    norm = ProductivityNorm(
        norm_id="N-01",
        task="Install pipe rail",
        trade="Ironworker",
        unit="LF",
        hours_per_unit=Decimal("0.35"),
        hours_per_post_or_element=Decimal("0.50"),
        source="Meridian baseline",
    )
    res = calculate_labor_hours(
        norm,
        quantity=100,
        element_count=20,
        adjustments=[AdjustmentFactor(category="height", multiplier=Decimal("1.15"), justification="Steep slope rigging", source="Sheet S3.1")],
        overtime_hours=10,
        wage=wage,
    )
    assert Decimal(res["total_hours"]) == Decimal("51.75")
    assert Decimal(res["cost"]["loaded_cost"]) > Decimal(res["cost"]["base_wage_cost"])

    crew = CrewComposition(crew_id="C1", name="Rail Crew", members=[CrewMemberSpec("IW-KING", Decimal("2"))])
    assert crew.composite_loaded_rate({"IW-KING": wage}) == Decimal("218.08")

    # Verify parsing of all repo knowledge entries cleanly
    wages = load_structured_wages(ROOT / "src" / "bidkit" / "estimator_agent" / "knowledge" / "wages.json")
    norms = parse_legacy_productivity(ROOT / "src" / "bidkit" / "estimator_agent" / "knowledge" / "productivity.json")
    assert len(wages) >= 5 and len(norms) >= 20


def test_cost_engine_13_buckets_margin_vs_markup_and_scenarios():
    markup_res = compute_13_buckets(
        material_net_cost=Decimal("10000"),
        labor_cost=Decimal("5000"),
        equipment_cost=Decimal("1000"),
        freight_cost=Decimal("500"),
        mobilization_cost=Decimal("500"),
        waste_allowance=Decimal("500"),
        waste_embedded_in_material=False,
        contingency_pct=Decimal("0"),
        overhead_pct=Decimal("0"),
        profit_pct=Decimal("20"),
        profit_mode="markup",
        rounding=Decimal("1"),
    )
    assert Decimal(markup_res["buckets"]["9_direct_cost"]) == Decimal("17500.00")
    assert Decimal(markup_res["buckets"]["13_final_bid_price"]) == Decimal("21000.00")

    margin_res = compute_13_buckets(
        material_net_cost=Decimal("10000"),
        labor_cost=Decimal("5000"),
        equipment_cost=Decimal("1000"),
        freight_cost=Decimal("500"),
        mobilization_cost=Decimal("500"),
        waste_allowance=Decimal("500"),
        waste_embedded_in_material=False,
        contingency_pct=Decimal("0"),
        overhead_pct=Decimal("0"),
        profit_pct=Decimal("20"),
        profit_mode="margin",
        rounding=Decimal("1"),
    )
    assert Decimal(margin_res["buckets"]["13_final_bid_price"]) == Decimal("21875.00")
    assert Decimal(margin_res["achieved_margin_pct"]) == Decimal("20.00")

    pkg = load_package(ROOT / "examples" / "packages" / "wsj.json")
    analysis = analyze_package_costs(pkg)
    prices = {s["scenario"]: Decimal(s["final_bid_price"]) for s in analysis["scenarios"]}
    assert prices["Aggressive"] <= prices["Expected"] <= prices["Conservative"]


def test_independent_review_rfi_rfq_and_6_deliverables_immutability(tmp_path):
    pkg = load_package(ROOT / "examples" / "packages" / "wsj.json")

    with pytest.raises(SelfApprovalError):
        run_independent_review(pkg, prepared_by="alice", reviewer_id="alice")
    with pytest.raises(SelfApprovalError):
        run_independent_review(pkg, prepared_by="alice", reviewer_id="agent:claude")

    review = run_independent_review(pkg, prepared_by="alice", reviewer_id="bob")
    assert review["total_discrepancies"] >= 1
    first_disc = review["discrepancies"][0]["discrepancy_id"]
    with pytest.raises(SelfApprovalError):
        resolve_discrepancy(review, discrepancy_id=first_disc, decision="accepted", actor="alice")
    resolved = resolve_discrepancy(review, discrepancy_id=first_disc, decision="accepted", actor="bob")
    assert resolved["approval_status"] == "accepted"

    # RFI / RFQ workflow + dispatch guard
    ws = RFIRFQWorkspace(tmp_path / "rfi_rfq.json")
    rfis = ws.generate_rfis_from_gaps(takeoff_gaps=[{"code": "MT-99", "severity": "HIGH", "message": "Missing post depth", "source_sheet": "S1.2"}])
    assert len(rfis) == 1 and rfis[0].rfi_id == "RFI-001"
    rfqs = ws.build_rfqs_from_package(pkg)
    assert len(rfqs) >= 1
    xlsx_path = ws.export_rfq_xlsx(rfqs[0].rfq_id, tmp_path / "rfq.xlsx")
    assert xlsx_path.exists()

    ws.record_supplier_quote(
        rfq_id=rfqs[0].rfq_id,
        supplier_name="Northwest Metals",
        quoted_lines=[{"line_id": rfqs[0].items[0]["line_id"], "unit_price": "15.00", "spec": rfqs[0].items[0]["spec"]}],
        freight="250.00",
    )
    cmp_res = ws.compare_quotes(rfqs[0].rfq_id)
    assert cmp_res["comparisons"][0]["covered_items"] == 1

    with pytest.raises(UnAuthorizedOutboundError):
        ws.authorize_dispatch(kind="rfq", item_id=rfqs[0].rfq_id, actor="bob", channel="email", recipient="vendor@example.com", explicit_human_approval=False)

    # All 6 normalized deliverables (PDF + XLSX + DOCX) + immutable approved protection
    deliv_dir = tmp_path / "deliverables"
    bundle = generate_all_deliverables(pkg, deliv_dir, version=1, status="Approved", reviewer="bob", review_report=review, rfq_snapshot=ws.snapshot())
    assert len(bundle["files"]) == len(DELIVERABLE_TYPES) == 6
    for _, _, _ in DELIVERABLE_TYPES:
        pass
    for key, formats in bundle["files"].items():
        for fmt in ("pdf", "xlsx", "docx"):
            assert Path(formats[fmt]["path"]).exists()

    with pytest.raises(ImmutableVersionError):
        generate_all_deliverables(pkg, deliv_dir, version=1, status="Draft", reviewer="bob")

    # Backup create, verify, tamper rejection, restore
    (tmp_path / "data" / "orgs" / "default").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "orgs" / "default" / "sample.json").write_text('{"ok":true}', encoding="utf-8")
    (tmp_path / "data" / "secrets.json").write_text('{"anthropic":"SECRET"}', encoding="utf-8")
    bzip = tmp_path / "backups" / "b1.zip"
    binfo = create_backup(tmp_path, bzip)
    assert binfo["file_count"] >= 1
    with zipfile.ZipFile(bzip, "r") as zf:
        assert not any("secrets.json" in n for n in zf.namelist())
    assert verify_backup(bzip)["valid"] is True
    restored = restore_backup(bzip, tmp_path / "restored_root")
    assert restored["restored_count"] == binfo["file_count"]
    assert sanitize_spreadsheet_cell("=CMD|'/C calc'!A0") == "'=CMD|'/C calc'!A0"
