from copy import deepcopy

import pytest
from openpyxl import load_workbook

from bidkit.__main__ import main
from bidkit.costing import evaluate, templates, conversion, number
from bidkit.cost_workbooks import build_cost_workbook, import_cost_workbook
from bidkit.data_store import read_json, write_json
from bidkit.project_schema import load_analysis


def fixture_inputs(config):
    a = load_analysis(config)
    a.update(scope_status="COMPLETE_VERIFIED", tax_treatment="EXCLUDED_FROM_BID_ADDED_BY_OWNER_TO_PAYMENTS", tax_treatment_source=a["quantities"][0]["sources"][0])
    p, registry = templates(config.id, a)
    p.update(mode="FICTITIOUS", as_of="2026-10-26", currency="USD", scope_complete=True, scope_reference="FICTITIOUS review", indirects_reviewed=True, margin_rate=.2, tax_rate=.1, margin_taxable=False)
    p.update(margin_source={"reference": "FICTITIOUS test margin"}, tax_source={"reference": "FICTITIOUS test tax"})
    p["allowances_reviewed"] = True
    item = p["items"][0]
    item.update(composition_complete=True, composition_reference="FICTITIOUS composition review")
    item["components"] = []
    for kind, method, unit, factor, prod, price in (("material", "FACTOR", "SF", 2, None, 9), ("labor", "PRODUCTIVITY", "H", None, 2, 20), ("equipment", "PRODUCTIVITY", "H", None, 1, 5)):
        qid = "TEST-"+kind
        registry["quotes"].append({"id": qid, "kind": "FICTITIOUS", "price_status": "ESTIMATED", "confidence": "MEDIUM", "supplier": "FICTITIOUS TEST", "reference": "FICTITIOUS NO COMMERCIAL VALUE", "date": "2026-10-01", "valid_until": "2026-12-31", "currency": "USD", "unit": "SY" if kind == "material" else "H", "unit_price": price, "source": {"reference": "FICTITIOUS source"}})
        item["components"].append({"id": qid, "kind": kind, "description": "FICTITIOUS "+kind, "applicability": "INCLUDED", "method": method, "resource_unit": unit, "factor": factor, "productivity": prod, "waste_fraction": .1 if kind == "material" else 0, "quote_id": qid, "basis": "FICTITIOUS test basis", "basis_source": {"reference": "FICTITIOUS test"}, "taxable": True})
    p["indirects"] = [{"id": "OH", "description": "FICTITIOUS overhead", "scope": "base", "applicability": "INCLUDED", "method": "PERCENT_DIRECT", "value": .1, "basis": "FICTITIOUS test", "basis_source": {"reference": "FICTITIOUS basis"}, "taxable": False}]
    return a, p, registry


def test_decimal_units_productivity_waste_margin_and_tax(project_factory):
    a, p, q = fixture_inputs(project_factory())
    r = evaluate(a, p, q)
    i = r["items"][0]
    assert i["categories"] == {"material": 15.4, "labor": 70, "equipment": 35, "subcontract": None, "other": None}
    assert i["direct_cost"] == 120.4
    s = r["summaries"][0]
    assert (s["indirect_cost"], s["cost"], s["candidate_price"], s["tax"], s["payment_with_tax"]) == (12.04, 132.44, 165.55, 12.04, 177.59)
    assert r["offer_total"] is None and "FICTITIOUS_NOT_AN_OFFER" in r["offer_blockers"]


@pytest.mark.parametrize("mutation", ["missing_quantity", "missing_price", "expired", "future", "currency", "foreign", "zero_productivity", "bad_unit", "negative", "margin_one", "duplicates"])
def test_invalid_or_missing_cost_inputs(project_factory, mutation):
    a, p, q = fixture_inputs(project_factory())
    raises = mutation in ("foreign", "zero_productivity", "bad_unit", "negative", "margin_one", "duplicates")
    if mutation == "missing_quantity": a["quantities"][0]["quantity"] = None
    if mutation == "missing_price": q["quotes"][0]["unit_price"] = None
    if mutation == "expired": q["quotes"][0]["valid_until"] = "2026-10-20"
    if mutation == "future": q["quotes"][0]["date"] = "2026-11-01"
    if mutation == "currency": q["quotes"][0]["currency"] = "EUR"
    if mutation == "foreign": q["project_id"] = "Other"
    if mutation == "zero_productivity": p["items"][0]["components"][1]["productivity"] = 0
    if mutation == "bad_unit": q["quotes"][0]["unit"] = "CY"
    if mutation == "negative": q["quotes"][0]["unit_price"] = -1
    if mutation == "margin_one": p["margin_rate"] = 1
    if mutation == "duplicates": q["quotes"].append(deepcopy(q["quotes"][0]))
    if raises:
        with pytest.raises(ValueError): evaluate(a, p, q)
    else:
        r = evaluate(a, p, q)
        assert r["items"][0]["direct_cost"] is None and r["offer_total"] is None


def test_partial_cost_survives_a_missing_resource_and_ranges_are_explicit(project_factory):
    a, p, q = fixture_inputs(project_factory())
    q["quotes"][0].update(unit_price_low=8, unit_price_high=10)
    r = evaluate(a, p, q)
    assert (r["summaries"][0]["known_direct_low"], r["summaries"][0]["known_direct_high"]) == (118.69, 122.11)
    q["quotes"][1]["unit_price"] = None
    r = evaluate(a, p, q)
    assert r["items"][0]["direct_cost"] is None
    assert r["items"][0]["known_direct_partial"] == 50.4
    assert r["summaries"][0]["known_direct_partial"] == 50.4


def test_range_only_price_is_useful_without_inventing_a_midpoint(project_factory, monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/"tools"))
    from qa_excel_formulas import Evaluator
    c = project_factory();a, p, q = fixture_inputs(c)
    q["quotes"][0].update(unit_price=None, unit_price_low=8, unit_price_high=10)
    r = evaluate(a, p, q)
    assert r["summaries"][0]["known_direct_partial"] == 105
    assert (r["summaries"][0]["known_direct_low"], r["summaries"][0]["known_direct_high"]) == (118.69, 122.11)
    assert r["items"][0]["direct_cost"] is None
    path = c.output_dir/"range_only_FICTITIOUS.xlsx";build_cost_workbook(r, path)
    e = Evaluator(load_workbook(path))
    assert (e.cell("Scopes", "F2"), e.cell("Scopes", "G2"), e.cell("Scopes", "H2")) == (105, 118.69, 122.11)


def test_real_estimated_reference_and_zero_price_are_supported(project_factory):
    c = project_factory(); a, p, q = fixture_inputs(c)
    p.update(mode="REAL", margin_source={"reference": "Estimator margin decision"}, tax_source={"reference": "Project tax reference"})
    for quote in q["quotes"]:
        quote.update(kind="REAL", valid_until=None, applicability_note="Explicit estimator applicability review")
    q["quotes"][0]["unit_price"] = 0
    r = evaluate(a, p, q, root=c.root)
    assert r["resources"][0]["extended_cost"] == 0
    assert r["offer_total"] == r["summaries"][0]["candidate_price"] == 144.38
    assert all(row["validation_status"] == "VALID" for row in r["quotes"])


def test_documented_city_added_tax_stays_outside_bid_in_engine_and_excel(project_factory, monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/"tools"))
    from qa_excel_formulas import Evaluator
    c = project_factory();a, p, q = fixture_inputs(c)
    a["tax_treatment"] = "EXCLUDED_FROM_ELECTRONIC_BID_CITY_APPLIES_AT_AWARD"
    p.update(mode="REAL", margin_source={"reference": "TEST margin decision"}, tax_source={"reference": "TEST tax reference"})
    for quote in q["quotes"]: quote["kind"] = "REAL"
    r = evaluate(a, p, q, root=c.root)
    assert r["offer_total"] == 165.55
    assert r["summaries"][0]["payment_with_tax"] == 177.59
    path=c.output_dir/"city_tax_TEST.xlsx";build_cost_workbook(r,path)
    assert Evaluator(load_workbook(path)).cell("Summary", "B7") == 165.55


def test_alternates_credits_and_unmeasured_scope_are_separate(project_factory):
    a, p, q = fixture_inputs(project_factory())
    alt = deepcopy(a["quantities"][0]); alt.update(id="ALT", pricing_scope="alternate_1")
    a["quantities"].append(alt)
    item = deepcopy(p["items"][0]);item.update(quantity_id="ALT", effect="DEDUCT")
    for c in item["components"]: c["id"] += "-ALT"
    p["items"].append(item)
    q["quotes"][0].update(unit_price_low=8, unit_price_high=10)
    r = evaluate(a, p, q)
    base, credit = r["summaries"]
    assert base["known_direct_partial"] == 120.4 and credit["known_direct_partial"] == -120.4
    assert credit["known_direct_low"] == -122.11 and credit["known_direct_high"] == -118.69
    alt["quantity"] = None
    assert evaluate(a, p, q)["summaries"][0]["known_direct_partial"] == 120.4


def test_supply_only_cannot_charge_installation(project_factory):
    a, p, q = fixture_inputs(project_factory())
    a["quantities"][0]["estimate_included"] = False
    with pytest.raises(ValueError, match="Supply-only"): evaluate(a, p, q)


def test_subcontracts_other_costs_and_calculated_primary_quantities(project_factory):
    a, p, q = fixture_inputs(project_factory())
    a["quantities"][0].update(quantity_status="CALCULATED_FROM_DOCUMENT", calculation={"operation": "product", "operands": [7, 1]})
    for kind, price in (("subcontract", 7), ("other", 5)):
        quote = deepcopy(q["quotes"][0]);quote.update(id=kind, unit="EA", unit_price=price)
        q["quotes"].append(quote)
        resource = deepcopy(p["items"][0]["components"][0])
        resource.update(id=kind, kind=kind, resource_unit="EA", factor=1, waste_fraction=0, quote_id=kind)
        p["items"][0]["components"].append(resource)
    assert evaluate(a, p, q)["items"][0]["direct_cost"] == 204.4


def test_actual_excel_cost_formulas_and_human_recalculation(project_factory, monkeypatch):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/"tools"))
    from qa_excel_formulas import Evaluator
    c = project_factory();a, p, q = fixture_inputs(c)
    result = evaluate(a, p, q)
    path = c.output_dir/"test_FICTITIOUS.xlsx";build_cost_workbook(result, path)
    book = load_workbook(path);e = Evaluator(book)
    for sheet in book:
        for row in sheet:
            for cell in row:
                if cell.data_type == "f": e.cell(sheet.title, cell.coordinate)
    assert e.cell("Scopes", "F2") == 120.4
    assert (e.cell("Scopes", "I2"), e.cell("Scopes", "J2"), e.cell("Scopes", "M2"), e.cell("Scopes", "N2"), e.cell("Scopes", "O2")) == (120.4, 12.04, 165.55, 12.04, 177.59)
    book["Items"]["G2"] = 14
    assert Evaluator(book).cell("Scopes", "F2") == 240.8
    assert Evaluator(book).cell("Summary", "B7") == ""
    write_json(c.project_dir/"pricing.json", p);write_json(c.project_dir/"quotes.json", q)
    book["Settings"]["B5"] = "REAL";book.save(path)
    with pytest.raises(ValueError, match="fictitious"): import_cost_workbook(c, path, a)


def test_price_edits_are_detected_and_build_is_reproducible(project_factory):
    c = project_factory()
    assert main(["cost-init", "--root", str(c.root), "--project", c.id]) == 0
    assert main(["build", "--root", str(c.root), "--project", c.id]) == 0
    before = {f.name: f.read_bytes() for f in c.output_dir.iterdir()}
    assert main(["build", "--root", str(c.root), "--project", c.id]) == 0
    assert before == {f.name: f.read_bytes() for f in c.output_dir.iterdir()}
    p = read_json(c.project_dir/"pricing.json");p["margin_rate"] = .1
    write_json(c.project_dir/"pricing.json", p)
    assert main(["validate", "--root", str(c.root), "--project", c.id]) == 1


def test_workbook_roundtrip_preserves_inputs_and_rejects_scenario_measurements(project_factory):
    c = project_factory(); a, p, q = fixture_inputs(c)
    p.update(mode="REAL", margin_source={"reference": "Test margin"}, tax_source={"reference": "Test tax"})
    for quote in q["quotes"]: quote["kind"] = "REAL"
    write_json(c.project_dir/"pricing.json", p);write_json(c.project_dir/"quotes.json", q)
    result = evaluate(a, p, q, root=c.root)
    path = c.output_dir/"Cost_Budget.xlsx";build_cost_workbook(result, path)
    import_cost_workbook(c, path, a)
    again = evaluate(a, read_json(c.project_dir/"pricing.json"), read_json(c.project_dir/"quotes.json"), root=c.root)
    assert again["summaries"] == result["summaries"]
    book = load_workbook(path);book["Items"]["G2"] = 99;book.save(path)
    with pytest.raises(ValueError, match="Scenario"): import_cost_workbook(c, path, a)


def test_readiness_states_auto_update_and_never_unlock_without_support(project_factory):
    # A fully composed and fully valued item exposes technical_calculation_ready=True,
    # but FICTITIOUS mode keeps the offer blocked, so submission/review stay False.
    a, p, q = fixture_inputs(project_factory())
    r = evaluate(a, p, q)
    assert r["items"][0]["calculation_ready"] is True
    assert r["summaries"][0]["technical_calculation_ready"] is True
    assert "FICTITIOUS_NOT_AN_OFFER" in r["offer_blockers"]
    assert r["readiness"]["ready_for_submission"] is False
    assert r["readiness"]["ready_for_contractor_review"] is False
    # A purely provisional/missing quote must NOT flip the item to calculation-ready.
    q["quotes"][0]["unit_price"] = None
    r2 = evaluate(a, p, q)
    assert r2["items"][0]["calculation_ready"] is False
    assert r2["summaries"][0]["technical_calculation_ready"] is False


def test_real_supported_quote_is_recognized_as_calculation_ready_but_keeps_approval_gated(project_factory):
    # Even with real quotes, no approved margin means no submission readiness.
    c = project_factory(); a, p, q = fixture_inputs(c)
    p.update(mode="REAL", margin_source={"reference": "Estimator margin decision"}, tax_source={"reference": "Project tax reference"}, allowances_reviewed=True, scope_complete=True, scope_reference="Real scope", indirects_reviewed=True)
    a.update(scope_status="COMPLETE_VERIFIED", tax_treatment="EXCLUDED_FROM_BID_ADDED_BY_OWNER_TO_PAYMENTS", tax_treatment_source=a["quantities"][0]["sources"][0])
    for quote in q["quotes"]: quote.update(kind="REAL", valid_until=None, applicability_note="Explicit estimator applicability review")
    r = evaluate(a, p, q, root=c.root)
    assert r["items"][0]["calculation_ready"] is True
    assert r["summaries"][0]["technical_calculation_ready"] is True
    assert r["summaries"][0]["draft_ready"] is True
    # Submission is never inferred from costs alone; it needs a separate contractor
    # authorization gate, so it stays False even when the offer is fully computed.
    assert r["readiness"]["ready_for_submission"] is False


@pytest.mark.parametrize("sheet,cell", [("Quotes", "P2"), ("Resources", "M2"), ("Indirects", "I2")])
def test_unreviewed_excel_inputs_stay_pending_after_import(project_factory, sheet, cell):
    c = project_factory();a, p, q = fixture_inputs(c)
    p.update(mode="REAL", margin_source={"reference": "TEST margin"}, tax_source={"reference": "TEST tax"})
    for quote in q["quotes"]: quote["kind"] = "REAL"
    write_json(c.project_dir/"pricing.json",p);write_json(c.project_dir/"quotes.json",q)
    path=c.output_dir/"TEST_review.xlsx";build_cost_workbook(evaluate(a,p,q,root=c.root),path)
    book=load_workbook(path);book[sheet][cell]=0;book.save(path)
    import_cost_workbook(c,path,a)
    actual=evaluate(a,read_json(c.project_dir/"pricing.json"),read_json(c.project_dir/"quotes.json"),root=c.root)
    assert actual["offer_total"] is None
    if sheet == "Quotes":
        assert actual["quotes"][0]["source"] == q["quotes"][0]["source"]
        assert actual["quotes"][0]["validation_status"] != "VALID"
    elif sheet == "Resources": assert actual["resources"][0]["basis_valid"] is False
    else: assert actual["summaries"][0]["indirect_cost"] is None
