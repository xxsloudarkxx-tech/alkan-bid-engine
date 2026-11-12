"""Explicit project cost compositions. Decimal arithmetic; no default rates or prices."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .audit import sha256
from .data_store import fingerprint, read_json, write_json

KINDS = ("material", "labor", "equipment", "subcontract", "other")
EXCLUDED_TAX = "EXCLUDED_FROM_BID_ADDED_BY_OWNER_TO_PAYMENTS"
OWNER_ADDED_TAX = (EXCLUDED_TAX, "EXCLUDED_FROM_ELECTRONIC_BID_CITY_APPLIES_AT_AWARD")


def number(value, label="value", *, fraction=False, positive=False):
    if value is None:
        return None
    if type(value) not in (int, float, str) or isinstance(value, bool):
        raise ValueError(f"{label}: numeric value required")
    try:
        n = Decimal(str(value))
    except ArithmeticError as exc:
        raise ValueError(f"{label}: invalid number") from exc
    if not n.is_finite() or n < 0 or (positive and n == 0) or (fraction and n >= 1):
        raise ValueError(f"{label}: invalid range")
    return n


def money(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None


def conversion(source, destination):
    """Quote units per resource unit; conversions never create a takeoff quantity."""
    if not source or not destination:
        return None
    source, destination = source.upper(), destination.upper()
    if source == destination:
        return Decimal(1)
    units = {"LF": ("length", Decimal(1)), "FT": ("length", Decimal(1)), "IN": ("length", Decimal(1)/12),
             "SF": ("area", Decimal(1)), "SY": ("area", Decimal(9)),
             "CF": ("volume", Decimal(1)), "CY": ("volume", Decimal(27)),
             "H": ("time", Decimal(1)), "HR": ("time", Decimal(1))}
    if source not in units or destination not in units or units[source][0] != units[destination][0]:
        raise ValueError(f"Incompatible conversion: {source} -> {destination}")
    return units[source][1] / units[destination][1]


def primary_quantities(analysis):
    return [q for q in analysis["quantities"] if q.get("pricing_scope") != "included_component_check"]


def templates(project_id, analysis):
    items = []
    for q in primary_quantities(analysis):
        # Start with supply and installation; estimator adds distinct resources as needed.
        # Composition approval, rather than empty rows for every class, governs completeness.
        kinds = ("material",) if not q.get("estimate_included", True) else ("material", "labor")
        items.append({"quantity_id": q["id"], "composition_complete": False, "composition_reference": None,
                      "effect": "ADD", "components": [{"id": q["id"]+"-"+kind, "kind": kind,
                      "description": kind, "applicability": "PENDING", "method": "PRODUCTIVITY" if kind in ("labor", "equipment") else "FACTOR",
                      "resource_unit": "H" if kind in ("labor", "equipment") else q["unit"],
                      "factor": None, "productivity": None, "waste_fraction": None, "quote_id": None,
                      "basis": None, "basis_source": None, "taxable": None} for kind in kinds]})
    indirects = [{"id": r["id"], "description": r["item"], "scope": "unallocated", "applicability": "PENDING",
                  "method": "FIXED", "value": None, "basis": None, "basis_source": None, "taxable": None}
                 for r in analysis.get("cost_pending", [])]
    for r in indirects:
        if "profit" in r["description"].lower():
            r["description"] = "Freight, disposal and other overhead ONLY; exclude waste priced in components and commercial margin. Reconcile original " + r["id"]
    pricing = {"schema_version": 1, "project_id": project_id, "mode": "REAL", "as_of": None, "currency": None,
               "scope_complete": False, "scope_reference": None, "selected_alternates": [], "margin_rate": None, "margin_source": None,
               "tax_rate": None, "tax_source": None, "margin_taxable": None,
               "indirects_reviewed": False, "allowances_reviewed": False, "items": items, "indirects": indirects}
    quotes = {"schema_version": 1, "project_id": project_id, "quotes": []}
    return pricing, quotes


def initialize(config, analysis):
    pricing, quotes = templates(config.id, analysis)
    if config.metadata.get("historical_test"):
        pricing["historical_test"] = True
    for name, value in (("pricing.json", pricing), ("quotes.json", quotes)):
        path = config.project_dir / name
        if not path.exists():
            write_json(path, value)
    return {"pricing": str(config.project_dir / "pricing.json"), "quotes": str(config.project_dir / "quotes.json")}


def evaluate(analysis, pricing, registry, *, root=None):
    project_id = analysis["project_id"]
    for obj in (pricing, registry):
        if obj.get("schema_version") != 1 or obj.get("project_id") != project_id:
            raise ValueError("Cost input version/project mismatch")
    mode = pricing.get("mode")
    if mode not in ("REAL", "FICTITIOUS"):
        raise ValueError("Cost mode must be REAL or FICTITIOUS")
    evidence = {}
    def supported(ref):
        if isinstance(ref, dict) and ref.get("reference") and not ref.get("path"):
            return True  # Explicit historical/estimator reference; not claimed as file authentication.
        if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256") or root is None:
            return False
        path = (Path(root)/ref["path"]).resolve()
        folder = (Path(root)/"projects"/project_id).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            return False
        if ref["path"] not in evidence:
            evidence[ref["path"]] = sha256(path)
        return evidence[ref["path"]] == ref["sha256"]
    def basis_ok(row):
        return row.get("basis_reviewed", True) is True and bool(row.get("basis")) and (mode == "FICTITIOUS" or supported(row.get("basis_source")))
    def unique(rows, key):
        result = {r[key]: r for r in rows}
        if any(not isinstance(r[key], str) or not r[key] for r in rows) or len({r[key].casefold() for r in rows}) != len(rows):
            raise ValueError(f"Duplicate {key}")
        return result
    quantities = unique(primary_quantities(analysis), "id")
    inputs = unique(pricing["items"], "quantity_id")
    if set(quantities) != set(inputs):
        raise ValueError("Cost compositions must cover exactly the primary quantity IDs; auxiliaries excluded")
    quotes = unique(registry["quotes"], "id")
    as_of = date.fromisoformat(pricing["as_of"]) if pricing.get("as_of") else None
    quote_status = {}
    for qid, q in quotes.items():
        number(q.get("unit_price"), qid)
        low, high = number(q.get("unit_price_low"), qid), number(q.get("unit_price_high"), qid)
        if (low is None) != (high is None) or (low is not None and low > high):
            raise ValueError("Price interval requires ordered low and high values")
        if low is not None and q.get("unit_price") is not None and not low <= number(q["unit_price"]) <= high:
            raise ValueError("Central price must lie inside its documented interval")
        start = date.fromisoformat(q["date"]) if q.get("date") else None
        end = date.fromisoformat(q["valid_until"]) if q.get("valid_until") else None
        classification = q.get("price_status")
        valid = (classification in ("CONFIRMED", "ESTIMATED") and q.get("confidence") in ("LOW", "MEDIUM", "HIGH")
                 and bool(q.get("reference")) and bool(q.get("supplier")) and bool(q.get("unit"))
                 and (q.get("unit_price") is not None or low is not None) and bool(pricing.get("currency"))
                 and q.get("currency") == pricing["currency"] and start is not None
                 and as_of is not None and start <= as_of and (end is None or as_of <= end)
                 and (end is not None or (classification == "ESTIMATED" and bool(q.get("applicability_note"))))
                 and q.get("reviewed", True) is True and q.get("kind") == mode and (mode == "FICTITIOUS" or supported(q.get("source"))))
        quote_status[qid] = "VALID" if valid else "PENDING_OR_INVALID_QUOTE"
    items, resources, component_ids = [], [], set()
    for qid, quantity in quantities.items():
        spec = inputs[qid]
        if spec.get("effect", "ADD") not in ("ADD", "DEDUCT"):
            raise ValueError("effect must be ADD or DEDUCT")
        if spec.get("effect") == "DEDUCT" and not quantity.get("pricing_scope", "").startswith("alternate_"):
            raise ValueError("Deductive adjustments must have an explicit alternate scope")
        blockers = []
        if quantity["quantity"] is None:
            blockers.append("PENDING_MEASUREMENT")
        if spec.get("composition_complete") is not True or not spec.get("composition_reference"):
            blockers.append("COMPOSITION_REVIEW_PENDING")
        kinds = set()
        totals = {kind: Decimal(0) for kind in KINDS}
        for c in spec["components"]:
            if not c.get("id") or c["id"].casefold() in component_ids:
                raise ValueError("Duplicate component ID")
            component_ids.add(c["id"].casefold())
            kind = c["kind"]
            if kind not in KINDS:
                raise ValueError("Unknown resource kind")
            if not quantity.get("estimate_included", True) and kind in ("labor", "equipment", "subcontract"):
                raise ValueError("Supply-only item cannot include installation resources")
            kinds.add(kind)
            state = c["applicability"]
            if state not in ("INCLUDED", "NOT_APPLICABLE", "PENDING"):
                raise ValueError("Invalid applicability")
            problems, amount = [], None
            if not basis_ok(c): problems.append("RESOURCE_BASIS_PENDING")
            factor = number(c.get("factor"), c["id"])
            productivity = number(c.get("productivity"), c["id"], positive=True)
            waste = number(c.get("waste_fraction"), c["id"])
            quote = quotes.get(c.get("quote_id"), {})
            rate = number(quote.get("unit_price"), c["id"])
            unit_conversion = conversion(c.get("resource_unit"), quote.get("unit")) if quote else None
            resource_quantity = purchase_quantity = None
            if state == "PENDING": problems.append("APPLICABILITY_PENDING")
            if state == "NOT_APPLICABLE":
                if not problems: amount = Decimal(0)
            elif state == "INCLUDED":
                if quote_status.get(c.get("quote_id")) != "VALID": problems.append("QUOTE_PENDING_OR_INVALID")
                if waste is None: problems.append("WASTE_APPLICABILITY_PENDING")
                method = c.get("method")
                if method not in ("FACTOR", "PRODUCTIVITY"): raise ValueError("Invalid resource method")
                if method == "PRODUCTIVITY" and c.get("resource_unit") not in ("H", "HR"):
                    raise ValueError("Productivity must be output quantity per resource hour")
                usage = factor if method == "FACTOR" else (Decimal(1)/productivity if productivity is not None else None)
                if usage is None: problems.append("FACTOR_OR_PRODUCTIVITY_PENDING")
                if unit_conversion is None: problems.append("UNIT_PENDING")
                if quantity["quantity"] is None: problems.append("PENDING_MEASUREMENT")
                if not problems:
                    resource_quantity = number(quantity["quantity"])*usage*(1+waste)
                    purchase_quantity = resource_quantity*unit_conversion
                    amount = purchase_quantity*rate if rate is not None else None
            rounded = money(amount)
            low = number(quote.get("unit_price_low", quote.get("unit_price")))
            high = number(quote.get("unit_price_high", quote.get("unit_price")))
            low = rate if low is None else low
            high = rate if high is None else high
            cost_low = money(purchase_quantity*low) if purchase_quantity is not None and low is not None else (0.0 if state == "NOT_APPLICABLE" and rounded is not None else None)
            cost_high = money(purchase_quantity*high) if purchase_quantity is not None and high is not None else (0.0 if state == "NOT_APPLICABLE" and rounded is not None else None)
            if state == "INCLUDED" and not problems and rounded is None:
                problems.append("POINT_PRICE_NOT_ESTIMATED_RANGE_ONLY")
            if rounded is not None: totals[kind] += Decimal(str(rounded))
            blockers.extend(problems)
            resources.append({**c, "quantity_id": qid, "pricing_scope": quantity.get("pricing_scope", "unallocated"),
                              "package": quantity["package"], "item_quantity": quantity["quantity"], "item_unit": quantity["unit"],
                              "quote_unit": quote.get("unit"), "unit_price": quote.get("unit_price"),
                              "conversion": float(unit_conversion) if unit_conversion is not None else None,
                              "quote_status": quote_status.get(c.get("quote_id"), "PENDING_OR_INVALID_QUOTE"),
                              "basis_valid": basis_ok(c), "resource_quantity": float(resource_quantity) if resource_quantity is not None else None,
                              "purchase_quantity": float(purchase_quantity) if purchase_quantity is not None else None,
                              "extended_cost": rounded, "cost_low": cost_low, "cost_high": cost_high,
                              "price_status": quote.get("price_status", "PENDING"), "confidence": quote.get("confidence"),
                              "blockers": sorted(set(problems))})
        if not kinds: blockers.append("RESOURCE_COMPOSITION_EMPTY")
        sign = -1 if spec.get("effect") == "DEDUCT" else 1
        direct = money(sum(totals.values())*sign) if not blockers else None
        items.append({"id": qid, "item": quantity["item"], "unit": quantity["unit"], "quantity": quantity["quantity"],
                      "package": quantity["package"], "pricing_scope": quantity.get("pricing_scope", "unallocated"),
                      "sources": quantity["sources"], "composition_complete": spec.get("composition_complete", False),
                      "composition_reference": spec.get("composition_reference"), "effect": spec.get("effect", "ADD"),
                      "categories": {k: (money(v)*sign if any(r["kind"] == k and r["quantity_id"] == qid and r["extended_cost"] is not None for r in resources) else None) for k, v in totals.items()},
                      "known_direct_partial": money(sum(totals.values())*sign) if any(r["quantity_id"] == qid and r["extended_cost"] is not None for r in resources) else None,
                      "direct_cost": direct,
                      "blockers": sorted(set(blockers)),
                      "calculation_ready": not blockers and direct is not None})
    indirect_ids = unique(pricing["indirects"], "id")
    if not {r["id"] for r in analysis.get("cost_pending", [])}.issubset(indirect_ids):
        raise ValueError("Required general-condition/indirect concepts may not be deleted")
    scopes = ["base"] + sorted(({i["pricing_scope"] for i in items} | {i["scope"] for i in pricing["indirects"]})-{"base"})
    selected = pricing.get("selected_alternates", [])
    if len(selected) != len(set(selected)) or any(s not in scopes or not s.startswith("alternate_") for s in selected):
        raise ValueError("Selected alternates must be distinct, existing alternate scopes")
    required_scopes = {"base", "unallocated", *selected}
    margin = number(pricing.get("margin_rate"), "margin_rate", fraction=True)
    margin_valid = margin is not None and (mode == "FICTITIOUS" or supported(pricing.get("margin_source")))
    tax_rate = number(pricing.get("tax_rate"), "tax_rate", fraction=True)
    tax_valid = tax_rate is not None and (mode == "FICTITIOUS" or supported(pricing.get("tax_source")))
    treatment = analysis.get("tax_treatment", "PENDING")
    tax_documented = bool(analysis.get("tax_treatment_source"))
    indirects, summaries = [], []
    for scope in scopes:
        members = [i for i in items if i["pricing_scope"] == scope]
        missing = sum(i["direct_cost"] is None for i in members)
        direct = sum(Decimal(str(i["direct_cost"])) for i in members if i["direct_cost"] is not None)
        partial = [r for r in resources if r["pricing_scope"] == scope]
        def signed_total(field):
            def signed(r):
                negative = inputs[r["quantity_id"]].get("effect") == "DEDUCT"
                key = ({"cost_low": "cost_high", "cost_high": "cost_low"}.get(field, field)) if negative else field
                return Decimal(str(r[key])) * (-1 if negative else 1)
            available = [r for r in partial if r[field] is not None]
            return money(sum(signed(r) for r in available)) if available else None
        overhead, missing_indirect = Decimal(0), 0
        for row in pricing["indirects"]:
            if row["scope"] != scope: continue
            state = row["applicability"]
            if state not in ("PENDING", "INCLUDED", "NOT_APPLICABLE"): raise ValueError("Invalid indirect applicability")
            value = number(row.get("value"), row["id"])
            if row["method"] not in ("FIXED", "PERCENT_DIRECT"): raise ValueError("Invalid indirect method")
            amount = None
            if basis_ok(row) and state == "NOT_APPLICABLE": amount = Decimal(0)
            if basis_ok(row) and state == "INCLUDED" and value is not None:
                if row["method"] == "FIXED": amount = value
                elif missing == 0: amount = direct*value
            rounded = money(amount)
            if rounded is None: missing_indirect += 1
            else: overhead += Decimal(str(rounded))
            indirects.append({**row, "basis_valid": basis_ok(row), "extended_cost": rounded})
        valid = bool(members) and missing == 0 and missing_indirect == 0 and pricing.get("indirects_reviewed") is True
        cost = direct+overhead if valid else None
        selling = cost/(1-margin) if cost is not None and margin_valid else None
        selling = Decimal(str(money(selling))) if selling is not None else None
        taxable_rows = [r for r in resources if r["pricing_scope"] == scope and r["applicability"] == "INCLUDED"]
        taxable_indirect = [r for r in indirects if r["scope"] == scope and r["applicability"] == "INCLUDED"]
        tax_basis_valid = all(type(r.get("taxable")) is bool for r in taxable_rows+taxable_indirect) and type(pricing.get("margin_taxable")) is bool
        taxable_base = sum(Decimal(str(r["extended_cost"] or 0)) * (-1 if inputs[r["quantity_id"]].get("effect") == "DEDUCT" else 1) for r in taxable_rows if r.get("taxable") is True)
        taxable_base += sum(Decimal(str(r["extended_cost"] or 0)) for r in taxable_indirect if r.get("taxable") is True)
        if pricing.get("margin_taxable") is True and selling is not None: taxable_base += selling-cost
        tax = money(taxable_base*tax_rate) if selling is not None and tax_valid and tax_basis_valid and tax_documented else None
        # Documented owner-added sales tax is kept outside the bid amount.
        candidate = money(selling) if tax_documented and treatment in OWNER_ADDED_TAX else (money(selling+Decimal(str(tax))) if selling is not None and tax is not None and treatment == "INCLUDED_IN_BID" else None)
        summaries.append({"scope": scope, "item_count": len(members), "missing_items": missing,
                          "missing_indirects": missing_indirect, "known_direct_partial": signed_total("extended_cost"),
                          "known_direct_low": signed_total("cost_low"), "known_direct_high": signed_total("cost_high"),
                          "priced_components": len([r for r in partial if r["applicability"] == "INCLUDED" and r["extended_cost"] is not None]),
                          "range_components": len([r for r in partial if r["applicability"] == "INCLUDED" and r["cost_low"] is not None]),
                          "estimated_components": len([r for r in partial if r["price_status"] == "ESTIMATED" and r["extended_cost"] is not None]),
                          "confirmed_components": len([r for r in partial if r["price_status"] == "CONFIRMED" and r["extended_cost"] is not None]),
                          "direct_cost": money(direct) if members and missing == 0 else None,
                          "indirect_cost": money(overhead) if missing_indirect == 0 and pricing.get("indirects_reviewed") is True else None,
                          "cost": money(cost), "margin_amount": money(selling-cost) if selling is not None else None,
                          "price_before_tax": money(selling),
                          "candidate_price": candidate, "tax": tax,
                          "payment_with_tax": money(selling+Decimal(str(tax))) if selling is not None and tax is not None else None})
    blockers = []
    if any(i["blockers"] for i in items if i["pricing_scope"] in required_scopes): blockers.append("REQUIRED_ITEMS_INCOMPLETE")
    if any(i["extended_cost"] is None for i in indirects if i["scope"] in required_scopes) or not pricing.get("indirects_reviewed"): blockers.append("INDIRECTS_INCOMPLETE")
    if any(i["pricing_scope"] == "unallocated" for i in items) or any(i["scope"] == "unallocated" for i in indirects): blockers.append("SCOPE_ALLOCATION_PENDING")
    if analysis["scope_status"] != "COMPLETE_VERIFIED" or pricing.get("scope_complete") is not True or not pricing.get("scope_reference"):
        blockers.append("SCOPE_REVIEW_PENDING")
    if not margin_valid: blockers.append("COMMERCIAL_MARGIN_PENDING")
    if pricing.get("allowances_reviewed") is not True: blockers.append("ALLOWANCE_APPLICABILITY_PENDING")
    if not pricing.get("currency") or as_of is None: blockers.append("CURRENCY_OR_AS_OF_PENDING")
    if not tax_documented or treatment not in (*OWNER_ADDED_TAX, "INCLUDED_IN_BID"): blockers.append("TAX_TREATMENT_PENDING")
    if mode == "FICTITIOUS": blockers.append("FICTITIOUS_NOT_AN_OFFER")
    base = next(s for s in summaries if s["scope"] == "base")
    selected_prices = [s["candidate_price"] for s in summaries if s["scope"] in {"base", *selected}]
    if any(v is None for v in selected_prices): blockers.append("SELECTED_SCOPE_INCOMPLETE")
    offer = money(sum(Decimal(str(v)) for v in selected_prices)) if not blockers else None
    if base["candidate_price"] is None and "BASE_PRICE_INCOMPLETE" not in blockers: blockers.append("BASE_PRICE_INCOMPLETE")
    # Explicit, automatically-recomputed readiness states (never fabricate an approval).
    # On every evaluate() these are derived solely from the current data, so statuses
    # update by themselves as supported data is incorporated.
    tech_scopes = []
    draft_scopes = []
    for s in summaries:
        scope_items = [i for i in items if i["pricing_scope"] == s["scope"]]
        measured = [i for i in scope_items if i["quantity"] is not None]
        # Technical calculation ready: every identified item in the scope is measured,
        # fully composed, and every included resource has a supported amount computed.
        technical = bool(measured) and len(measured) == len(scope_items) and all(i["calculation_ready"] for i in scope_items) and bool(s.get("direct_cost"))
        # Draft ready: the scope may be partially valued, but at least one identified item
        # has a reproducible calculated amount (or the whole scope is technically ready),
        # and remaining items are explicitly identified rather than treated as zero.
        draft = technical or (bool(measured) and s.get("known_direct_partial") is not None)
        s["technical_calculation_ready"] = technical
        s["draft_ready"] = draft and len(measured) == len(scope_items)
        if technical: tech_scopes.append(s["scope"])
        if draft and len(measured) == len(scope_items): draft_scopes.append(s["scope"])
    required_tech = all(s.get("technical_calculation_ready") for s in summaries if s["scope"] in required_scopes)
    required_draft = all(s.get("draft_ready") for s in summaries if s["scope"] in required_scopes)
    # Contractor-review readiness also requires the economic parameters that turn a
    # calculation into a reviewable estimate: composition, quoted resources, indirects,
    # margin, scope completeness, allowance and currency are all already required above.
    review_ready = bool(required_tech) and not blockers and base.get("candidate_price") is not None

    def _calc_status():
        if required_tech and not blockers and offer is not None:
            return "CALCULATED_REQUIRES_ESTIMATOR_RELEASE"
        if required_tech and not blockers and base.get("candidate_price") is not None:
            return "READY_FOR_CONTRACTOR_REVIEW"
        if required_draft:
            return "DRAFT_READY"
        return "BLOCKED" if blockers else "PARTIAL_CALCULATION_READY"

    status = _calc_status()
    readiness = {
        "technical_calculation_ready": required_tech,
        "draft_ready": required_draft,
        "ready_for_contractor_review": review_ready,
        # Submission readiness is NEVER inferred from costs alone: it additionally requires
        # verified submission requirements and explicit, current contractor authorization
        # (a separate human gate outside this costing engine) before any document is marked
        # ready to hand to the owner. Until that gate is recorded, this stays False.
        "ready_for_submission": bool(False),
        "submission_auth_gate": "REQUIRES_EXPLICIT_CONTRACTOR_AUTHORIZATION",
        "technical_calculation_scopes": sorted(tech_scopes),
        "draft_ready_scopes": sorted(draft_scopes),
    }
    packages = []
    for scope, package in sorted({(i["pricing_scope"], i["package"]) for i in items}):
        rr = [r for r in resources if r["pricing_scope"] == scope and r["package"] == package]
        def partial_amount(field):
            def signed(row):
                neg = inputs[row["quantity_id"]].get("effect") == "DEDUCT"
                key = {"cost_low": "cost_high", "cost_high": "cost_low"}.get(field, field) if neg else field
                return Decimal(str(row[key])) * (-1 if neg else 1)
            available = [r for r in rr if r[field] is not None]
            return money(sum(signed(r) for r in available)) if available else None
        packages.append({"scope": scope, "package": package, "known_direct_partial": partial_amount("extended_cost"), "low_covered": partial_amount("cost_low"), "high_covered": partial_amount("cost_high")})
    return {"schema_version": 1, "project_id": project_id, "mode": mode, "historical_test": pricing.get("historical_test", False), "currency": pricing.get("currency"),
            "as_of": pricing.get("as_of"), "pricing_fingerprint": fingerprint({"analysis": analysis, "pricing": pricing, "quotes": registry, "evidence": evidence}),
            "items": items, "resources": resources, "indirects": indirects, "quotes": [{**q, "validation_status": quote_status[qid]} for qid, q in quotes.items()],
            "settings": pricing, "tax_treatment": treatment, "tax_documented": tax_documented,
            "documentary_scope_complete": analysis["scope_status"] == "COMPLETE_VERIFIED",
            "summaries": summaries, "packages": packages, "offer_total": offer, "offer_blockers": sorted(set(blockers)),
            "status": status, "readiness": readiness}


def calculate(config, analysis):
    pricing = read_json(config.project_dir / "pricing.json")
    if pricing.get("mode") != "REAL":
        raise ValueError("Fictitious inputs must use the isolated QA workflow")
    result = evaluate(analysis, pricing, read_json(config.project_dir / "quotes.json"), root=config.root)
    write_json(config.data_dir / "estimate/cost_result.json", result)
    from .reports import _write_csv
    _write_csv(config.output_dir / "cost_sources.csv", result["quotes"], ["id", "price_status", "confidence", "supplier", "reference", "date", "valid_until", "currency", "unit", "unit_price", "unit_price_low", "unit_price_high", "source", "applicability_note", "validation_status"])
    _write_csv(config.output_dir / "cost_unresolved.csv", [{"id": i["id"], "item": i["item"], "quantity": i["quantity"], "unit": i["unit"], "scope": i["pricing_scope"], "known_direct_partial": i["known_direct_partial"], "pending": i["blockers"], "sources": i["sources"]} for i in result["items"] if i["blockers"]])
    return result
