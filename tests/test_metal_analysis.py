"""Regressions for the Metal Fabrications Only infrastructure.

Scope drained:

* ``price_registry`` — importing the A1 catalog (CSV/XLSX) with PUBLIC CATALOG /
  BUDGET REFERENCE / FIRM SUPPLIER QUOTE, unit-matching, PENDING QUOTE and
  deterministic hashing.
* ``metal_scope`` — Metal Fabrications Only extraction with measured vs
  PENDING MEASUREMENT and non-metal (wood) exclusion.
* ``lumpsum_cost`` — internal seven-section build-up that never releases a
  client Total Lump Sum without complete evidence and explicit authorization;
  plus the robustness guards (equipment not assumed zero, price unit/evidence
  validation, provisional-price exception, authorization coherence).
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from bidkit.metal_scope import is_metal, metal_scope
from bidkit.price_registry import (CatalogError, catalog_hash, import_catalog,
                                   normalize_record, resolve)
from bidkit.lumpsum_cost import CostParams, build_envelope, client_view

from pypdf import PdfReader
import a1_proposal
import wsj_cost_analysis

# --------------------------------------------------------------------------- fixtures

ANALYSIS = {
    "scope_status": "BASE",
    "quantities": [
        {"id": "F-01", "item": "Chain-link fence, 4 ft high, 2 mesh 9 ga",
         "unit": "LF", "quantity": "230", "quantity_status": "MEASURED",
         "pricing_scope": "base"},
        {"id": "G-01", "item": "Vehicular access gate", "unit": "EA",
         "quantity": "1", "quantity_status": "MEASURED", "pricing_scope": "base"},
        {"id": "S-01", "item": "Split rail fence", "unit": "LF",
         "quantity": "335", "quantity_status": "MEASURED", "pricing_scope": "base"},
        {"id": "STL-01", "item": "Picnic shelter structural steel", "unit": "LS",
         "quantity": None, "quantity_status": "PENDING", "pricing_scope": "base"},
        {"id": "PL-1", "item": "Serviceberry shrub", "unit": "EA",
         "quantity": "6", "quantity_status": "MEASURED", "pricing_scope": "base"},
    ],
}

CSV_BODY = (
    "material_code,description,specification,unit,supplier,price_class,unit_price,currency,quoted_on,valid_until,source,page\n"
    "F-01,Chain-link fence fabric,2 mesh 9 ga PVC,LF,ABC Fence,PUBLIC_CATALOG,12.00,USD,2026-10-01,2027-10-01,cat.p.4,4\n"
    "F-01,Chain-link fence fabric,2 mesh 9 ga PVC,LF,ABC Fence,FIRM_SUPPLIER_QUOTE,11.50,USD,2026-11-01,2027-11-01,RFQ-2026-A1,1\n"
    "G-01,Vehicular access gate,6 ft galv black,EA,Metco,BUDGET_REFERENCE,800.00,USD,2026-11-01,2027-11-01,dev-supplier-ref,2\n"
    "STL-01,Structural steel framing,ASTM A36,LS,Nord,BUDGET_REFERENCE,,USD,,,dev-supplier-ref,3\n"
)

PAPERS = {
    "material_code": "F-01", "description": "Chain-link fence fabric",
    "specification": "2 mesh 9 ga", "unit": "LF", "supplier": "ABC Fence",
    "price_class": "FIRM_SUPPLIER_QUOTE", "unit_price": "11.50", "currency": "USD",
    "quoted_on": "2026-11-01", "valid_until": "2027-11-01", "source": "RFQ", "page": "1",
}


def _sample_csv(path: Path) -> Path:
    path.write_text(CSV_BODY, encoding="utf-8")
    return path


def firm_registry():
    return [
        normalize_record({**PAPERS, "material_code": "F-01", "price_class": "FIRM_SUPPLIER_QUOTE", "unit_price": "11.50"}),
        normalize_record({**PAPERS, "material_code": "G-01", "unit": "EA", "price_class": "FIRM_SUPPLIER_QUOTE",
                          "unit_price": "2000.00", "specification": "6 ft galv black", "supplier": "Metco"}),
    ]


def full_params(**over):
    base = dict(labor_cost="800", labor_wage_basis="King Co prevailing wage Fence Erectors 2026",
                equipment_cost="100", contingency_percent="5", overhead_percent="10",
                profit_percent="15", markup_basis="documented S&S OH & profit policy",
                price_adjustment="0", authorized=True)
    base.update(over)
    return CostParams(**base)


def priced_analysis():
    return {**ANALYSIS, "quantities": [q for q in ANALYSIS["quantities"] if q["id"] in ("F-01", "G-01", "S-01")]}


# Expected maths with firm_registry + full_params:
# materials = 230*11.50 + 1*2000 = 4645.00 ; +labor 800 +equip 100 -> direct 5545.00
# cont 5% = 277.25 ; base 5822.25 ; oh 10% = 582.23 ; profit 15% = 873.34 ; cost=7277.82
FULL_TOTAL = Decimal("7277.82")

# --------------------------------------------------------------------------- metal_scope

def test_is_metal_distinguishes_scope():
    assert is_metal("Chain-link fence, 2 mesh 9 ga") is True
    assert is_metal("Vehicular access gate") is True
    assert is_metal("Park entry sign - vehicle scale") is True
    assert is_metal("Split rail fence") is False
    assert is_metal("Post-and-rail fencing") is False
    assert is_metal("Serviceberry shrub") is False


def test_metal_scope_counts_and_pending():
    scope = metal_scope(ANALYSIS)
    ids = {i["id"] for i in scope["metal_items"]}
    assert {"F-01", "G-01", "STL-01"} == ids
    assert scope["count_measured"] == 2
    assert scope["count_pending_measurement"] == 1


# --------------------------------------------------------------------------- price_registry

def test_import_catalog_csv_classes_and_quote(tmp_path):
    records = import_catalog(_sample_csv(tmp_path / "A1_METAL_SUPPLIER_REFERENCE_PRICES.csv"))
    assert len(records) == 4
    firm = [r for r in records if r["price_class"] == "firm_quote"]
    assert firm and firm[0]["unit_price"] == "11.50"
    pending = [r for r in records if r["material_code"] == "STL-01"]
    assert pending[0]["status"] == "PENDING QUOTE"


def test_import_catalog_xlsx(tmp_path):
    wb = Workbook(); ws = wb.active
    ws.append(["material_code", "description", "unit", "supplier", "price_class",
               "unit_price", "currency", "quoted_on", "valid_until", "source"])
    ws.append(["F-01", "Chain-link fence fabric", "LF", "ABC Fence", "BUDGET_REFERENCE",
               "12.50", "USD", "2026-11-01", "2027-11-01", "cat.p.4"])
    path = tmp_path / "catalog.xlsx"
    wb.save(path)
    assert import_catalog(path)[0]["price_class"] == "budget_reference"


def test_firm_quote_requires_full_evidence():
    with pytest.raises(CatalogError):
        normalize_record({**PAPERS, "valid_until": None})
    with pytest.raises(CatalogError):
        normalize_record({**PAPERS, "unit_price": None})


def test_invalid_currency_and_weight_rejected():
    with pytest.raises(CatalogError):
        normalize_record({**PAPERS, "currency": "EUR"})
    with pytest.raises(CatalogError):
        normalize_record({**PAPERS, "valid_until": "2026-01-01"})


def test_resolve_prefers_firm_and_respects_unit(tmp_path):
    records = import_catalog(_sample_csv(tmp_path / "catalog.csv"))
    assert resolve(records, "F-01")["price_class"] == "firm_quote"
    assert resolve(records, "F-01", unit="LF")["unit_price"] == "11.50"
    assert resolve(records, "F-01", unit="EA") is None   # unit mismatch


def test_catalog_hash_is_deterministic(tmp_path):
    assert catalog_hash(import_catalog(_sample_csv(tmp_path / "a.csv"))) == \
           catalog_hash(import_catalog(_sample_csv(tmp_path / "b.csv")))


# --------------------------------------------------------------------------- lump_sum - release

def test_authorized_is_coherent_and_releases(tmp_path):
    env = build_envelope(priced_analysis(), firm_registry(), full_params())
    assert env["final_releasable"] is True
    assert env["totals"]["materials_total"] == Decimal("4645.00")
    assert env["totals"]["direct_cost"] == Decimal("5545.00")
    assert env["totals"]["client_lump_sum"] == FULL_TOTAL
    view = client_view(env)
    assert view["final_releasable"] is True and view["authorized"] is True
    assert view["delivery_state"] == "FINAL_RELEASED"
    assert "PENDING AUTHORIZATION" not in view["status"]
    assert "NOT A FIRM QUOTE" not in view["status"]
    assert view["total_lump_sum"] == FULL_TOTAL
    assert not any(k in view for k in ("unit_price", "margin", "direct_cost", "materials_total"))


def test_not_authorized_never_released():
    env = build_envelope(priced_analysis(), firm_registry(), full_params(authorized=False))
    assert env["final_releasable"] is False
    assert env["delivery_state"] == "BUDGETARY_PRELIMINARY"
    view = client_view(env)
    assert view["total_lump_sum"] is None
    assert view["delivery_state"] == "BUDGETARY_PRELIMINARY"
    assert "NOT A FIRM QUOTE" in view["status"]
    assert view["budget_low"] is not None and view["budget_high"] is not None


# point 2: unit of measure must match before associating a price
def test_unit_mismatch_price_not_associated():
    bad = [normalize_record({**PAPERS, "material_code": "F-01", "unit": "EA",
                             "price_class": "FIRM_SUPPLIER_QUOTE", "unit_price": "11.50"})]
    env = build_envelope(priced_analysis(), bad, full_params())
    assert env["final_releasable"] is False
    assert any("PENDING QUOTE" in b for b in env["blockers"])


# point 3: reference prices block final release unless documented exception
def test_reference_price_blocks_without_exception():
    provisional = [
        normalize_record({**PAPERS, "material_code": "F-01", "price_class": "BUDGET_REFERENCE", "unit_price": "11.50"}),
        normalize_record({**PAPERS, "material_code": "G-01", "unit": "EA", "price_class": "FIRM_SUPPLIER_QUOTE",
                          "unit_price": "2000.00"}),
    ]
    env = build_envelope(priced_analysis(), provisional, full_params())
    assert env["final_releasable"] is False
    assert env["provisional_used"] == ["F-01"]
    assert any("provisional" in b.lower() for b in env["blockers"])


def test_reference_price_allowed_only_with_documented_exception():
    provisional = [
        normalize_record({**PAPERS, "material_code": "F-01", "price_class": "BUDGET_REFERENCE", "unit_price": "11.50"}),
        normalize_record({**PAPERS, "material_code": "G-01", "unit": "EA", "price_class": "FIRM_SUPPLIER_QUOTE",
                          "unit_price": "2000.00"}),
    ]
    env = build_envelope(priced_analysis(), provisional,
                         full_params(allow_provisional=True,
                                     provisional_exception_note="Owner-approved BUDGET REFERENCE for prelim only"))
    # Reference prices are only ever BUDGETARY, never FINAL.
    assert env["delivery_state"] == "BUDGETARY_PRELIMINARY"
    assert env["final_releasable"] is False


# point 1: equipment is never assumed to be zero
def test_equipment_not_assumed_zero():
    env = build_envelope(priced_analysis(), firm_registry(), full_params(equipment_cost=None))
    assert env["totals"]["equipment_status"] == "PENDING"
    assert env["final_releasable"] is False
    assert any("Equipo" in b for b in env["blockers"])


def test_equipment_documented_not_required_releases():
    env = build_envelope(priced_analysis(), firm_registry(),
                         full_params(equipment_cost=None, equipment_state="NOT_REQUIRED"))
    assert env["totals"]["equipment_status"] == "NONE_DOCUMENTED"
    assert env["final_releasable"] is True


# point 5: labor evidence (prevailing wage) required
def test_labor_wage_basis_required():
    env = build_envelope(priced_analysis(), firm_registry(), full_params(labor_wage_basis=None))
    assert env["final_releasable"] is False
    assert any("salario prevaleciente" in b for b in env["blockers"])


# point 5: markup (OH/profit) basis required
def test_markup_basis_required():
    env = build_envelope(priced_analysis(), firm_registry(), full_params(markup_basis=None))
    assert env["final_releasable"] is False
    assert any("markup basis" in b for b in env["blockers"])


# point 5: measured quantities block release when any metal is PENDING MEASUREMENT
def test_pending_measurement_blocks_release():
    env = build_envelope(ANALYSIS, firm_registry(), full_params())
    assert env["final_releasable"] is False
    assert any("PENDING MEASUREMENT" in b for b in env["blockers"])
    assert env["totals"]["client_lump_sum"] is None


def test_no_price_pending_quote_blocks_release():
    env = build_envelope(priced_analysis(), [], full_params())
    assert env["final_releasable"] is False
    assert any("PENDING QUOTE" in b for b in env["blockers"])


# --------------------------------------------------------------------------- renderers

def _pdf_text(path: Path) -> str:
    return "".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)


def test_renderers_produce_draft_internal_and_a1_proposal(tmp_path):
    env = build_envelope(priced_analysis(), firm_registry(), full_params())
    out = tmp_path / "out"
    wsj_cost_analysis.build_internal(env, "Test Orangegate", out)
    a1_proposal.build_proposal(env, "Test Orangegate", out)
    internal = out / "Cost_Analysis_Internal_Metal_Fab.pdf"
    proposal = out / "Bid_Proposal_A1_Metal_Fab.pdf"
    assert internal.read_bytes().startswith(b"%PDF")
    assert proposal.read_bytes().startswith(b"%PDF")

    internal_txt = _pdf_text(internal)
    assert "DRAFT" in internal_txt
    assert "Price Build-up" in internal_txt          # internal shows the build-up
    assert "$7,277.82" in internal_txt               # internal cost-based total

    proposal_txt = _pdf_text(proposal)
    assert "TOTAL LUMP SUM" in proposal_txt
    assert "$7,277.82" in proposal_txt
    # The client document must NOT leak internal unit prices / margins.
    assert "$11.50" not in proposal_txt
    assert "Price Build-up" not in proposal_txt


def test_renderer_a1_proposal_blocked_when_not_releasable(tmp_path):
    env = build_envelope(priced_analysis(), [], full_params())   # no prices -> INTERNAL_BLOCKED
    out = tmp_path / "out"
    result = a1_proposal.build_proposal(env, "Test Orangegate", out)
    assert result is None
    assert not (out / "Bid_Proposal_A1_Metal_Fab.pdf").exists()   # no commercial emission


# --------------------------------------------------------------------------- three states

def reference_registry():
    """F-01 has a range (budget 11.50 / public 12.00); G-01 is a single firm 2000."""
    return [
        normalize_record({**PAPERS, "material_code": "F-01", "price_class": "BUDGET_REFERENCE", "unit_price": "11.50"}),
        normalize_record({**PAPERS, "material_code": "F-01", "price_class": "PUBLIC_CATALOG", "unit_price": "12.00"}),
        normalize_record({**PAPERS, "material_code": "G-01", "unit": "EA", "price_class": "FIRM_SUPPLIER_QUOTE",
                          "unit_price": "2000.00"}),
    ]


def test_three_states():
    # INTERNAL_BLOCKED (no prices)
    blocked = build_envelope(priced_analysis(), [], full_params())
    assert blocked["delivery_state"] == "INTERNAL_BLOCKED"
    view = client_view(blocked)
    assert view["delivery_state"] == "INTERNAL_BLOCKED"
    assert view["status"] == "NO PROPOSAL AVAILABLE"
    assert view["total_lump_sum"] is None
    assert "blockers" not in view                     # internal blockers never leak

    # BUDGETARY_PRELIMINARY (reference prices -> evidence-based range)
    bud = build_envelope(priced_analysis(), reference_registry(), full_params())
    assert bud["delivery_state"] == "BUDGETARY_PRELIMINARY"
    assert bud["final_releasable"] is False
    low, high = bud["totals"]["budget_range"]["low"], bud["totals"]["budget_range"]["high"]
    assert low == Decimal("7277.82") and high == Decimal("7428.75")
    assert Decimal("0") < low <= high                # never arbitrary / negative
    bview = client_view(bud)
    assert bview["delivery_state"] == "BUDGETARY_PRELIMINARY"
    assert "PENDING" not in bview["status"] and "null" not in str(bview)

    # FINAL_RELEASED (firm prices + authorized)
    fin = build_envelope(priced_analysis(), firm_registry(), full_params())
    assert fin["delivery_state"] == "FINAL_RELEASED"
    assert fin["final_releasable"] is True


# --------------------------------------------------------------------------- leak prevention

_INTERNAL_TOKENS = ("PENDING", "MEASUREMENT", "SOURCE", "INTERNAL", "BLOCKER",
                    "direct cost", "overhead", "margin", "markup", "wage", "None", "null")


def _assert_no_internal_leak(text: str):
    assert "$11.50" not in text, "unit price leaked"
    for token in _INTERNAL_TOKENS:
        assert token.upper() not in text.upper(), f"internal token leaked: {token!r}"


def test_client_pdf_final_no_internal_leak(tmp_path):
    env = build_envelope(priced_analysis(), firm_registry(), full_params())
    out = tmp_path / "out"
    a1_proposal.build_proposal(env, "Test Orangegate", out)
    text = _pdf_text(out / "Bid_Proposal_A1_Metal_Fab.pdf")
    assert "TOTAL LUMP SUM" in text and "$7,277.82" in text
    _assert_no_internal_leak(text)


def test_client_pdf_budgetary_no_internal_leak_or_unit_prices(tmp_path):
    env = build_envelope(priced_analysis(), reference_registry(), full_params())
    out = tmp_path / "out"
    a1_proposal.build_proposal(env, "Test Orangegate", out)
    text = _pdf_text(out / "Bid_Proposal_A1_Metal_Fab.pdf")
    assert "BUDGETARY ESTIMATE" in text and "NOT A FIRM QUOTE" in text
    assert "$7,277.82" in text and "$7,428.75" in text
    _assert_no_internal_leak(text)


def test_client_view_never_exposes_internal_fields():
    for env in (build_envelope(priced_analysis(), [], full_params()),
                build_envelope(priced_analysis(), reference_registry(), full_params()),
                build_envelope(priced_analysis(), firm_registry(), full_params())):
        view = client_view(env)
        assert "cost" not in view or view.get("cost") is None
        assert not any(k in view for k in ("unit_price", "materials_total", "direct_cost",
                                           "blockers", "labor_cost", "equipment_cost"))