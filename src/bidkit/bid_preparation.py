"""Internal preparation records. Never edits official forms or releases a bid."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from openpyxl import Workbook

from .audit import load_audit, normalize
from .costing import money, primary_quantities
from .data_store import fingerprint, read_json, write_json
from .workbooks import _sheet, _save, reference


def prepare(analysis, manifest, form, cost=None):
    if form.get("schema_version") != 1 or form.get("project_id") != analysis["project_id"]:
        raise ValueError("Bid form version/project mismatch")
    q = {r["id"]: r for r in primary_quantities(analysis)}
    costs = {r["id"]: r for r in cost["items"]} if cost else {}
    scopes = {r["scope"]: r for r in cost["summaries"]} if cost else {}
    line_ids, assigned, descriptions = set(), {}, defaultdict(list)
    lines, warnings = [], list(form.get("pending_decisions", []))
    for line in form["lines"]:
        if line["id"] in line_ids: raise ValueError("Duplicate official line ID")
        line_ids.add(line["id"])
        descriptions[normalize(line["description"]).casefold()].append(line["id"])
        if not line.get("sources"): raise ValueError("An official line needs an available documentary source")
        ids = line.get("quantity_ids", [])
        for qid in ids:
            if qid not in q or qid in assigned: raise ValueError("Unknown or multiply assigned estimate item")
            if q[qid].get("pricing_scope") != line["scope"]: raise ValueError("Bid line mapping crosses estimate pricing scopes")
            assigned[qid] = line["id"]
        known = [costs[qid]["known_direct_partial"] for qid in ids if qid in costs and costs[qid]["known_direct_partial"] is not None]
        partial = money(sum(Decimal(str(v)) for v in known)) if known else None
        scope = scopes.get(line["scope"], {})
        scope_ids = {r["id"] for r in q.values() if r.get("pricing_scope") == line["scope"]}
        complete_mapping = bool(ids) and set(ids) == scope_ids and line.get("mapping_status") == "REVIEWED"
        amount = scope.get("candidate_price") if complete_mapping and form.get("current_official_form_verified") is True and cost and cost["mode"] == "REAL" else None
        lines.append({**line, "known_direct_partial": partial, "proposed_amount": amount,
                      "amount_status": "DRAFT_FOR_REVIEW" if amount is not None else "INCOMPLETE_OR_FORM_PENDING",
                      "estimate_item_count": len(ids)})
    for description, ids in descriptions.items():
        if len(ids) > 1: warnings.append({"issue": "DUPLICATE_FORM_DESCRIPTION_REQUIRES_CLARIFICATION", "line_ids": ids, "description": description})
    amounts = {line["id"]: line["proposed_amount"] for line in lines}
    totals = []
    for total in form.get("totals", []):
        if not total.get("line_ids") or any(lid not in amounts for lid in total["line_ids"]):
            raise ValueError("Invalid official subtotal membership")
        values = [amounts[lid] for lid in total["line_ids"]]
        value = money(sum(Decimal(str(v)) for v in values)) if all(v is not None for v in values) else None
        totals.append({**total, "amount": value})
    matrix = [{"quantity_id": r["id"], "item": r["item"], "quantity": r["quantity"], "unit": r["unit"],
               "package": r["package"], "pricing_scope": r.get("pricing_scope", "unallocated"),
               "official_line_id": assigned.get(r["id"]), "mapping_status": "PROVISIONAL_REVIEW_REQUIRED" if r["id"] in assigned else "OFFICIAL_LINE_OR_ALLOCATION_PENDING",
               "known_direct_partial": costs.get(r["id"], {}).get("known_direct_partial"), "sources": r["sources"]} for r in q.values()]
    requirements = [*analysis["requirements"], *form.get("additional_requirements", [])]
    if len({r["id"] for r in requirements}) != len(requirements):
        raise ValueError("Duplicate checklist requirement ID")
    if any(not r.get("sources") for r in requirements):
        raise ValueError("An official checklist requirement needs a documentary source")
    checklist = [{"id": r["id"], "requirement": r["requirement"], "phase": r.get("phase"), "sources": r["sources"],
                  "status": "PENDING_CONTRACTOR_EVIDENCE", "evidence_file": None, "reviewer": None, "signed": False, "submitted": False} for r in requirements]
    for topic in ("bond/garantías", "licencias y registros", "anexos", "firmas y representación", "aprobación interna"):
        checklist.append({"id": "INTERNAL-"+str(len(checklist)+1), "requirement": "Revisión interna: determinar aplicabilidad y evidencia de "+topic+" según documentos reales; no constituye una nueva exigencia oficial.", "phase": "internal_review", "sources": [], "status": "APPLICABILITY_AND_EVIDENCE_PENDING", "evidence_file": None, "reviewer": None, "signed": False, "submitted": False})
    return {"project_id": analysis["project_id"], "status": "INTERNAL_DRAFT_NOT_AUTHORIZED",
            "historical_test": form.get("historical_test", False), "form_status": form["form_status"],
            "form_sources": form.get("sources", []), "lines": lines, "totals": totals, "mapping": matrix,
            "checklist": checklist, "documents": manifest["documents"], "amendments": analysis["amendments"],
            "tax_treatment": analysis.get("tax_treatment", "PENDING"), "tax_rate": cost["settings"].get("tax_rate") if cost else None,
            "allowance": analysis.get("allowance"), "allowance_status": "REVIEW_APPLICABILITY_AND_SOURCE; no implicit zero",
            "pending_decisions": warnings, "authorization": {"technical_review": "PENDING", "estimator_review": "PENDING", "contractor_authorization": "PENDING", "signed": False, "submitted": False},
            "input_fingerprint": fingerprint({"analysis": analysis, "manifest": manifest, "form": form, "cost": cost["pricing_fingerprint"] if cost else None})}


def load_preparation(config, analysis):
    manifest = load_audit(config)
    form = read_json(config.project_dir / "bid_form.json")
    docs = {r["name"]: r for r in manifest["documents"]}
    sources = form.get("sources", []) + [s for row in [*form["lines"], *form.get("additional_requirements", [])] for s in row.get("sources", [])]
    for s in sources:
        doc = docs.get(s.get("document"))
        if not doc or s.get("sha256") != doc["sha256"] or type(s.get("page")) is not int or not 1 <= s["page"] <= (doc["pages"] or 0):
            raise ValueError("Bid form source does not match this project's original documents")
        cache = read_json(config.data_dir / "extractions" / f"{doc['sha256']}.json")
        excerpt = normalize(s.get("excerpt", ""))
        if len(excerpt) < 8 or excerpt.casefold() not in normalize(cache["pages"][s["page"]-1]["text"]).casefold():
            raise ValueError("Bid form excerpt not present on cited page")
    cost_path = config.data_dir / "estimate/cost_result.json"
    cost = read_json(cost_path) if cost_path.exists() else None
    return prepare(analysis, manifest, form, cost)


def build_preparation(config, analysis):
    from .reports import _write_csv
    result = load_preparation(config, analysis)
    write_json(config.data_dir / "estimate/bid_preparation.json", result)
    folder = config.output_dir / "bid-preparation"
    for filename, rows, headers in (("bid_mapping.csv", result["mapping"], None), ("draft_bid_amounts.csv", result["lines"], ["id", "description", "scope", "known_direct_partial", "proposed_amount", "amount_status", "sources"]), ("compliance_checklist.csv", result["checklist"], None)):
        _write_csv(folder / filename, rows, headers)
    book = Workbook();book.remove(book.active)
    book.properties.category = "INTERNAL_DRAFT_NOT_OFFICIAL_FORM"
    _sheet(book, "Read first", ["Topic", "Review instruction"], [
        ["STATUS", "BORRADOR INTERNO - NO ES FORMULARIO OFICIAL. Nada firmado, autorizado ni presentado."],
        ["Project", config.project_name], ["Form status", result["form_status"]],
        ["Historical", "HISTORICAL TEST EXPEDIENT; not represented as a currently open procurement" if result["historical_test"] else "Document dates describe supplied records; confirm current status independently"],
        ["Costs", "Cost_Budget.xlsx is the editable master. This package is a linked build snapshot; rebuild after price edits, without reparsing original PDFs."],
        ["Cost fingerprint", read_json(config.data_dir / "estimate/cost_result.json")["pricing_fingerprint"] if (config.data_dir / "estimate/cost_result.json").exists() else None],
        ["Partial costs", "Known direct partial amounts exclude unpriced resources, unmeasured work, unallocated overhead and commercial margin; they are NOT proposed official line amounts."],
        ["Tax", result["tax_treatment"]], ["Allowances", result["allowance_status"]],
    ])
    _sheet(book, "Official line matrix", ["Quantity ID", "Estimate item", "Package", "Scope", "Qty", "Unit", "Official line", "Mapping", "Covered direct partial", "Quantity source"], [[r["quantity_id"], r["item"], r["package"], r["pricing_scope"], r["quantity"], r["unit"], r["official_line_id"], r["mapping_status"], r["known_direct_partial"], reference(r["sources"])] for r in result["mapping"]])
    _sheet(book, "Bid amount DRAFT", ["Official line", "Description", "Scope", "Known direct partial", "PROPOSED AMOUNT - DRAFT", "Status", "Form source"], [[r["id"], r["description"], r["scope"], r["known_direct_partial"], r["proposed_amount"], r["amount_status"], reference(r["sources"])] for r in result["lines"]])
    _sheet(book, "Official subtotal rules", ["Label", "Included official lines", "Draft subtotal"], [[r["id"], ", ".join(r["line_ids"]), r["amount"]] for r in result["totals"]])
    _sheet(book, "Compliance checklist", ["ID", "Requirement", "Phase", "Status", "Evidence", "Reviewer", "Signed", "Submitted", "Document source"], [[r["id"], r["requirement"], r["phase"], r["status"], None, None, False, False, reference(r["sources"])] for r in result["checklist"]])
    _sheet(book, "Documents and addenda", ["Name", "Original path", "SHA256", "Pages", "Kind"], [[r["name"], r["path"], r["sha256"], r["pages"], r["kind"]] for r in result["documents"]])
    _sheet(book, "Addenda changes", ["ID", "Change", "Source"], [[r["id"], r.get("change", ""), reference(r["sources"])] for r in result["amendments"]])
    _sheet(book, "Decisions and release", ["Decision", "Status"], [[str(r), "PENDING"] for r in result["pending_decisions"]] + [[r, str(s)] for r, s in result["authorization"].items()])
    _save(book, folder / "Internal_Bid_Package_DRAFT.xlsx")
    return result
