from __future__ import annotations

from .alkan_method import (
    BASE_MARKUP,
    PROJECT_STATES,
    ProjectEstimate,
    QuoteLineItem,
    ScopeItem,
    SupplierQuote,
    apply_contractor_adjustment,
    apply_supplier_quote,
    calculate_preestimate,
    finalize_project_estimate,
    generate_project_pdfs,
    transition_project_state,
)
from .config import ProjectConfig
from .data_store import write_json
from .project_schema import require_valid_analysis
from .takeoff import takeoff

__all__ = [
    "BASE_MARKUP",
    "PROJECT_STATES",
    "ProjectEstimate",
    "QuoteLineItem",
    "ScopeItem",
    "SupplierQuote",
    "apply_contractor_adjustment",
    "apply_supplier_quote",
    "calculate_preestimate",
    "estimate_data",
    "finalize_project_estimate",
    "generate_project_pdfs",
    "transition_project_state",
]


def estimate_data(config: ProjectConfig) -> dict:
    measured = takeoff(config)
    analysis = require_valid_analysis(config)
    rows = []
    # Quantities are retained independently for each cost class. Materials are not
    # priced again as work items, which would double count the same supply.
    for material in measured["materials"]:
        quantity = next((r for r in measured["records"] if r["id"] == material.get("quantity_id")), {})
        rows.append({"id": material["id"], "item": material["description"], "cost_class": "material", "pricing_scope": quantity.get("pricing_scope", "unallocated"), "unit": material["unit"], "quantity": material["quantity"], "quantity_id": material.get("quantity_id"), "unit_price": None, "quote_reference": None, "extended_cost": None, "status": "PENDING_QUOTE", "sources": material["sources"]})
    for quantity in measured["records"]:
        if not quantity.get("estimate_included", True):
            continue
        rows.append({"id": "INSTALL-" + quantity["id"], "item": quantity["item"], "cost_class": "labor_equipment_or_subcontract_excluding_materials", "pricing_scope": quantity.get("pricing_scope", "unallocated"), "unit": quantity["unit"], "quantity": quantity["quantity"], "quantity_id": quantity["id"], "unit_price": None, "quote_reference": None, "extended_cost": None, "status": "PENDING_QUOTE", "sources": quantity["sources"]})
    for item in analysis.get("cost_pending", []):
        rows.append({"id": item["id"], "item": item["item"], "cost_class": item["cost_class"], "pricing_scope": "unallocated", "unit": "LS", "quantity": None, "quantity_id": None, "unit_price": None, "quote_reference": None, "extended_cost": None, "status": "PENDING_SCOPE_AND_QUOTE", "sources": []})
    payload = {"project_id": config.id, "input_fingerprint": measured["input_fingerprint"], "tax_rate": analysis.get("tax_rate"), "tax_rate_source": analysis.get("tax_rate_source"), "allowance": analysis.get("allowance"), "allowance_source": analysis.get("allowance_source"), "subtotal": None, "total": None, "status": "INCOMPLETE_UNPRICED", "price_policy": "No unsupported prices. Pending scope and blank prices block totals; no default tax or allowance.", "rows": rows}
    if (config.project_dir / "pricing.json").exists():
        from .costing import calculate
        result = calculate(config, analysis)
        payload["cost_engine"] = {"pricing_fingerprint": result["pricing_fingerprint"], "status": result["status"], "offer_total": result["offer_total"]}
    write_json(config.data_dir / "estimate" / "estimate_inputs.json", payload)
    return payload
