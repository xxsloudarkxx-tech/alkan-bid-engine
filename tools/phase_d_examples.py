"""Five isolated, explicitly fictitious Orangegate compositions and XLSX checks."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bidkit.costing import templates, evaluate
from bidkit.cost_workbooks import build_cost_workbook
from bidkit.data_store import read_json, write_json
from qa_excel_formulas import Evaluator, FormulaReader

QA = ROOT / "data/qa/phase-d"
OUTPUT = ROOT / "output/qa-phase-d"


def examples(analysis):
    p, quotes = templates(analysis["project_id"], analysis)
    p.update(mode="FICTITIOUS", currency="USD", as_of="2026-10-26", margin_rate=.2, margin_taxable=False, tax_rate=.1)
    items = {i["quantity_id"]: i for i in p["items"]}
    specs = {
        "LS-A-02": [("material", "FACTOR", "SF", 1, "SY", 90), ("labor", "PRODUCTIVITY", "H", 100, "H", 50), ("equipment", "PRODUCTIVITY", "H", 200, "H", 20)],
        "LP-A-01": [("material", "FACTOR", "EA", 1, "EA", 12), ("labor", "PRODUCTIVITY", "H", 8, "H", 40)],
        "LP-A-11": [("material", "FACTOR", "CY", 1/81, "CY", 30), ("labor", "PRODUCTIVITY", "H", 200, "H", 40), ("equipment", "PRODUCTIVITY", "H", 400, "H", 20)],
        "LS-B-09": [("material", "FACTOR", "EA", 1, "EA", 100)],
        "LS-B-10": [("material", "FACTOR", "EA", 1, "EA", 200)],
    }
    for qid, resources in specs.items():
        item = items[qid]
        item.update(composition_complete=qid != "LP-A-11", composition_reference="FICTITIOUS QA composition; not a real productivity or scope certification")
        item["components"] = []
        for kind, method, unit, usage, quote_unit, rate in resources:
            cid = "FICT-"+qid+"-"+kind
            q = {"id": cid, "kind": "FICTITIOUS", "price_status": "ESTIMATED" if kind == "material" else "CONFIRMED", "confidence": "LOW", "supplier": "FICTITIOUS QA - NO SUPPLIER", "reference": "FICTITIOUS TEST PRICE - NOT A QUOTATION", "date": "2026-10-26", "valid_until": "2026-11-30", "currency": "USD", "unit": quote_unit, "unit_price": rate, "source": {"reference": "FICTITIOUS QA parameters only"}, "applicability_note": "All prices, dates, productivities and percentages in this example are fictitious."}
            if qid == "LS-A-02" and kind == "material": q.update(unit_price_low=80, unit_price_high=100)
            quotes["quotes"].append(q)
            item["components"].append({"id": cid, "kind": kind, "description": "FICTITIOUS QA "+kind,
                                       "applicability": "INCLUDED", "method": method, "resource_unit": unit,
                                       "factor": usage if method == "FACTOR" else None, "productivity": usage if method == "PRODUCTIVITY" else None,
                                       "waste_fraction": 0, "quote_id": cid, "basis": "FICTITIOUS QA PARAMETER; quantities are documentary but rates/productivity are NOT a real estimate", "basis_source": {"reference": "FICTITIOUS test parameters"}, "taxable": kind == "material"})
    return p, quotes, specs


def verify_workbook(path, result, analysis, p, quotes):
    book = load_workbook(path)
    formula_cells = [(s.title, c.coordinate) for s in book for row in s for c in row if c.data_type == "f"]
    for sheet, cell in formula_cells:
        FormulaReader(book[sheet][cell].value).tree()
    evaluator = Evaluator(book)
    for sheet, cell in formula_cells:
        evaluator.cell(sheet, cell)
    checks = []
    def check(name, got, expected):
        if expected is None: expected = ""
        assert abs(got-expected) < .011 if isinstance(expected, (int, float)) else got == expected, (name, got, expected)
        checks.append({"name": name, "actual": got, "expected": expected, "status": "PASS"})
    for row, r in enumerate(result["resources"], 2):
        check("Resource "+r["id"], evaluator.cell("Resources", f"W{row}"), r["extended_cost"])
    for row, i in enumerate(result["items"], 2):
        check("Partial item "+i["id"], evaluator.cell("Items", f"P{row}"), i["known_direct_partial"])
        check("Complete item "+i["id"], evaluator.cell("Items", f"Q{row}"), i["direct_cost"])
        for col, kind in zip(("K", "L", "M", "N", "O"), ("material", "labor", "equipment", "subcontract", "other")):
            check(kind+" subtotal "+i["id"], evaluator.cell("Items", f"{col}{row}"), i["categories"][kind])
    for row, s in enumerate(result["summaries"], 2):
        for col, key in (("F", "known_direct_partial"), ("G", "known_direct_low"), ("H", "known_direct_high")):
            check(s["scope"]+" "+key, evaluator.cell("Scopes", f"{col}{row}"), s[key])
    for row, s in enumerate(result["packages"], 2):
        for col, key in (("C", "known_direct_partial"), ("D", "low_covered"), ("E", "high_covered")):
            check(s["scope"]+" / "+s["package"]+" "+key, evaluator.cell("Schedules", f"{col}{row}"), s[key])
    check("Fictitious offer blocked", evaluator.cell("Summary", "B7"), None)
    ids = {i["id"]: n for n, i in enumerate(result["items"], 2)}
    qrow = next(n for n, q in enumerate(result["quotes"], 2) if q["id"] == "FICT-LS-A-02-material")
    # Quantity change is a scenario, not a new measurement. Compare to independent Python recalculation.
    changed = deepcopy(book);changed["Items"][f"G{ids['LS-A-02']}"] = 5480
    a = deepcopy(analysis);next(i for i in a["quantities"] if i["id"] == "LS-A-02")["quantity"] = 5480
    expected = evaluate(a, p, quotes)
    check("Quantity change recalculates covered base", Evaluator(changed).cell("Scopes", "F2"), expected["summaries"][0]["known_direct_partial"])
    check("Changed quantity blocks offer", Evaluator(changed).cell("Summary", "B7"), None)
    changed = deepcopy(book);changed["Quotes"][f"J{qrow}"] = 99
    q = deepcopy(quotes);next(r for r in q["quotes"] if r["id"] == "FICT-LS-A-02-material")["unit_price"] = 99
    expected = evaluate(analysis, p, q)
    check("Price change recalculates covered base", Evaluator(changed).cell("Scopes", "F2"), expected["summaries"][0]["known_direct_partial"])
    changed = deepcopy(book);changed["Quotes"][f"G{qrow}"] = "2026-10-01"
    q = deepcopy(quotes);next(r for r in q["quotes"] if r["id"] == "FICT-LS-A-02-material")["valid_until"] = "2026-10-01"
    expected = evaluate(analysis, p, q)
    check("Expired quote removes only its covered cost", Evaluator(changed).cell("Scopes", "F2"), expected["summaries"][0]["known_direct_partial"])
    changed = deepcopy(book);changed["Quotes"][f"I{qrow}"] = "SF";changed["Quotes"][f"J{qrow}"] = 10
    changed["Quotes"][f"K{qrow}"] = None;changed["Quotes"][f"L{qrow}"] = None
    check("Equivalent SF/SY conversion", Evaluator(changed).cell("Scopes", "F2"), result["summaries"][0]["known_direct_partial"])
    changed = deepcopy(book);changed["Settings"]["B5"] = "REAL";changed["Settings"]["B12"] = 1
    check("Incomplete real scope cannot be overridden to obtain offer", Evaluator(changed).cell("Summary", "B7"), None)
    return {"actual_formula_count": len(formula_cells), "assertions": checks, "native_excel_recalculated": False, "method": "Independent evaluator of actual XLSX formula tokens; no native Excel certification. Python Decimal engine cross-checks changed quantity, price, validity, conversion and covered scope.", "status": "PASS"}


def main():
    analysis = read_json(ROOT / "projects/orangegate-park-phase-1/analysis.json")
    p, quotes, specs = examples(analysis)
    result = evaluate(analysis, p, quotes)
    assert result["summaries"][0]["known_direct_partial"] == 60671.90
    assert result["offer_total"] is None
    QA.mkdir(parents=True, exist_ok=True);OUTPUT.mkdir(parents=True, exist_ok=True)
    write_json(QA / "pricing_FICTITIOUS.json", p)
    write_json(QA / "quotes_FICTITIOUS.json", quotes)
    write_json(QA / "cost_result_FICTITIOUS.json", result)
    path = OUTPUT / "Cost_Budget_FICTITIOUS.xlsx"
    build_cost_workbook(result, path)
    evidence = verify_workbook(path, result, analysis, p, quotes)
    evidence["five_examples"] = [{"id": i["id"], "scope": i["pricing_scope"], "categories": i["categories"], "known_direct_partial": i["known_direct_partial"], "complete_direct": i["direct_cost"]} for i in result["items"] if i["id"] in specs]
    write_json(QA / "calculation_checks.json", evidence)
    print(f"PASS: 5 FICTITIOUS examples; {evidence['actual_formula_count']} actual XLSX formulas; {len(evidence['assertions'])} cross-checks")


if __name__ == "__main__":
    main()
