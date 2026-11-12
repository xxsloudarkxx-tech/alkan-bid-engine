"""ALKAN Estimator V1: auditable, vendor-quoted construction costing.

Does not call remote services, guess prices, certify quantities or submit bids.
This module is deliberately separate from the historical Port of Tacoma
`bidkit.estimate` workflow.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

ALLOWED_CLIENT_TYPES = {"homeowner", "commercial", "gc_subcontract", "public_works"}
ALLOWED_CATEGORIES = {"material", "labor", "equipment", "subcontract", "logistics", "tax", "other"}
MONEY = Decimal("0.01")


def _decimal(value: Any, field: str, *, max_value: Decimal | None = None) -> Decimal:
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise ValueError(f"{field}: use un número decimal como texto, no float/null")
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}: decimal inválido") from exc
    if not n.is_finite() or n < 0 or (max_value is not None and n > max_value):
        raise ValueError(f"{field}: valor fuera de rango")
    return n


def _cash(n: Decimal) -> Decimal:
    return n.quantize(MONEY, rounding=ROUND_HALF_UP)


def _fmt(n: Decimal | None) -> str | None:
    return format(_cash(n), ".2f") if n is not None else None


def _date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label}: fecha ISO YYYY-MM-DD inválida") from exc


def _ref(value: Any) -> str:
    return str(value or "").strip()


def _check_project(data: dict) -> tuple[dict, dict, list[str]]:
    if data.get("schema_version") != "1.0":
        raise ValueError("schema_version debe ser 1.0")
    p = data.get("project")
    if not isinstance(p, dict):
        raise ValueError("project es obligatorio")
    if p.get("client_type") not in ALLOWED_CLIENT_TYPES:
        raise ValueError(f"client_type debe ser uno de {sorted(ALLOWED_CLIENT_TYPES)}")
    if p.get("currency") != "USD":
        raise ValueError("V1 solamente soporta USD; no convierte monedas")
    if not _ref(p.get("estimate_id")) or not _ref(p.get("name")):
        raise ValueError("project.estimate_id y project.name son obligatorios")
    f = data.get("financial")
    if not isinstance(f, dict):
        raise ValueError("financial es obligatorio")
    return p, f, []


def calculate(data: dict, *, as_of: date | None = None) -> dict:
    """Pure calculation; blocks missing evidence instead of assuming zero."""
    p, f, blockers = _check_project(data)
    today = as_of or date.today()
    overhead_pct = _decimal(f.get("overhead_percent"), "financial.overhead_percent", max_value=Decimal("100"))
    contingency_pct = _decimal(f.get("contingency_percent"), "financial.contingency_percent", max_value=Decimal("100"))
    margin_pct = _decimal(f.get("target_margin_percent"), "financial.target_margin_percent", max_value=Decimal("99.99"))
    if f.get("confirmed") is not True:
        blockers.append("Los porcentajes financieros necesitan confirmación humana (financial.confirmed=true)")
    lines = data.get("lines")
    if not isinstance(lines, list) or not lines:
        blockers.append("No hay partidas de costos (lines)")
        lines = []
    direct = Decimal("0")
    material_total = Decimal("0")
    report_lines: list[dict] = []
    ids: set[str] = set()
    refs = {x.get("id") for x in data.get("takeoff_references", []) if isinstance(x, dict)}
    for idx, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValueError(f"lines[{idx}] debe ser un objeto")
        line_id = _ref(line.get("id"))
        if not line_id or line_id in ids:
            raise ValueError(f"lines[{idx}].id ausente o duplicado")
        ids.add(line_id)
        cat = line.get("category")
        if cat not in ALLOWED_CATEGORIES:
            raise ValueError(f"{line_id}: categoría inválida")
        unit = _ref(line.get("unit"))
        if not unit:
            raise ValueError(f"{line_id}: unidad obligatoria")
        problems: list[str] = []
        qty = None
        if line.get("quantity") is None:
            problems.append("Cantidad pendiente")
        else:
            qty = _decimal(line["quantity"], f"{line_id}.quantity")
            if qty <= 0:
                problems.append("La cantidad debe ser mayor que cero")
        if line.get("quantity_status") != "verified" or not _ref(line.get("quantity_evidence")):
            problems.append("Medición pendiente de confirmación con evidencia")
        tkref = line.get("takeoff_ref_id")
        if tkref and tkref not in refs:
            problems.append("Referencia takeoff inexistente en el expediente")
        options = line.get("options", [])
        if not isinstance(options, list):
            raise ValueError(f"{line_id}.options debe ser lista")
        evaluated: list[dict] = []
        seen_options: set[str] = set()
        for opt in options:
            if not isinstance(opt, dict):
                raise ValueError(f"{line_id}: cotización inválida")
            oid = _ref(opt.get("id"))
            if not oid or oid in seen_options:
                raise ValueError(f"{line_id}: id de cotización vacío/duplicado")
            seen_options.add(oid)
            issues: list[str] = []
            if opt.get("unit") != unit:
                issues.append("Unidad de cotización distinta de la partida; requiere conversión documentada")
            if opt.get("currency") != "USD":
                issues.append("Moneda incompatible")
            if not _ref(opt.get("provider")):
                issues.append("Proveedor/responsable no identificado")
            if not _ref(opt.get("evidence_ref")):
                issues.append("Falta evidencia de cotización o bitácora de llamada")
            try:
                quoted = _date(opt.get("quoted_on"), f"{oid}.quoted_on")
                expiry = _date(opt.get("valid_until"), f"{oid}.valid_until")
                if quoted > today:
                    issues.append("Cotización con fecha futura")
                if expiry < today:
                    issues.append("Cotización vencida")
                if expiry < quoted:
                    issues.append("Vigencia anterior a fecha de cotización")
            except ValueError as exc:
                issues.append(str(exc))
            unit_cost = None
            delivery = None
            if opt.get("unit_cost") in (None, ""):
                issues.append("Precio unitario pendiente")
            else:
                unit_cost = _decimal(opt["unit_cost"], f"{line_id}/{oid}.unit_cost")
            if opt.get("delivery_total") in (None, ""):
                issues.append("Flete pendiente (escribir 0 únicamente si fue confirmado)")
            else:
                delivery = _decimal(opt["delivery_total"], f"{line_id}/{oid}.delivery_total")
            price = _cash(qty * unit_cost + delivery) if qty is not None and qty > 0 and unit_cost is not None and delivery is not None and not issues else None
            evaluated.append({
                "id": oid,
                "provider": opt.get("provider"),
                "unit_cost": _fmt(unit_cost),
                "delivery_total": _fmt(delivery),
                "effective_total": _fmt(price),
                "eligible": not issues,
                "issues": issues,
                "evidence_ref": opt.get("evidence_ref"),
                "valid_until": opt.get("valid_until"),
            })
        selected_id = _ref(line.get("selected_option_id"))
        chosen = next((x for x in evaluated if x["id"] == selected_id), None)
        if not selected_id or chosen is None:
            problems.append("Falta seleccionar cotización válida")
        elif not chosen["eligible"]:
            problems.extend([f"Cotización seleccionada: {msg}" for msg in chosen["issues"]])
        chosen_cost = Decimal(chosen["effective_total"]) if chosen and chosen["effective_total"] is not None and chosen["eligible"] and qty is not None and qty > 0 and line.get("quantity_status") == "verified" and _ref(line.get("quantity_evidence")) and (not tkref or tkref in refs) else None
        if problems:
            blockers.extend(f"{line_id}: {problem}" for problem in problems)
        else:
            assert chosen_cost is not None
            direct += chosen_cost
            if cat == "material":
                material_total += chosen_cost
        eligible = [x for x in evaluated if x["eligible"] and x["effective_total"] is not None]
        cheapest = min(eligible, key=lambda x: Decimal(x["effective_total"])) if eligible else None
        savings = (chosen_cost - Decimal(cheapest["effective_total"])) if chosen_cost is not None and cheapest else None
        report_lines.append({
            "id": line_id,
            "description": line.get("description"),
            "category": cat,
            "unit": unit,
            "quantity": str(qty) if qty is not None else None,
            "selected_option_id": selected_id or None,
            "status": "BLOCKED" if problems else "COSTED_REVIEW_REQUIRED",
            "problems": problems,
            "line_cost": _fmt(chosen_cost),
            "eligible_cheapest_option_id": cheapest["id"] if cheapest else None,
            "potential_savings_vs_selected": _fmt(savings),
            "options": evaluated,
        })
    complete = not blockers
    overhead = _cash(direct * overhead_pct / 100) if complete else None
    contingency = _cash(direct * contingency_pct / 100) if complete else None
    all_in = direct + overhead + contingency if complete else None
    proposed = _cash(all_in / (1 - margin_pct / 100)) if complete else None
    profit = proposed - all_in if complete else None
    stress = {}
    if complete:
        assert proposed is not None and all_in is not None
        for pct in (Decimal("3"), Decimal("5")):
            extra = _cash(material_total * pct / 100)
            post_cost = all_in + extra  # Base OH/contingency are held fixed in stress scenario.
            stress[f"material_plus_{pct}%"] = {
                "additional_material_cost": _fmt(extra),
                "post_increase_cost": _fmt(post_cost),
                "fixed_price_gross_margin_percent": format(_cash(Decimal(100) * (proposed - post_cost) / proposed), ".2f") if proposed else None,
            }
    return {
        "estimator_version": "1.0.0",
        "estimate_id": p["estimate_id"],
        "project": p,
        "calculation_as_of": today.isoformat(),
        "status": "READY_FOR_HUMAN_REVIEW" if complete else "BLOCKED_INPUTS",
        "blockers": blockers,
        "notes": [
            "Nunca equivale a oferta aprobada, contrato o autorización de compra.",
            "La carga tributaria NO se infiere. Agréguela como partida con respaldo y aprobación humana cuando aplique.",
            "Las comparaciones requieren misma especificación, unidad y alcance de suministro; la elegibilidad técnica debe revisarse externamente.",
            "Los escenarios +3% y +5% solo estresan materiales conservando precio de venta y demás costos constantes.",
            "La información parcelaria es referencia contextual, nunca metrado de obra por sí sola.",
        ],
        "lines": report_lines,
        "totals": {
            "verified_partial_direct_cost": _fmt(direct),
            "material_cost": _fmt(material_total) if complete else None,
            "direct_cost": _fmt(direct) if complete else None,
            "overhead_cost": _fmt(overhead),
            "contingency_cost": _fmt(contingency),
            "estimated_all_in_cost": _fmt(all_in),
            "target_margin_percent": str(margin_pct),
            "proposed_price_before_contract_specific_taxes": _fmt(proposed),
            "estimated_gross_profit": _fmt(profit),
        },
        "price_stress": stress,
    }


def new_template(*, estimate_id: str, project_name: str, client_type: str) -> dict:
    if client_type not in ALLOWED_CLIENT_TYPES:
        raise ValueError("client_type inválido")
    return {
        "schema_version": "1.0",
        "project": {
            "estimate_id": estimate_id,
            "name": project_name,
            "address": None,
            "county": None,
            "currency": "USD",
            "client_type": client_type,
            "bid_engine_ref": None,
            "parcel_context": None,
        },
        "financial": {
            "overhead_percent": "0",
            "contingency_percent": "0",
            "target_margin_percent": "0",
            "confirmed": False,
        },
        "takeoff_references": [],
        "lines": [
            {
                "id": "LINE-001", "description": "REEMPLAZAR CON PARTIDA REAL", "category": "material",
                "unit": "EA", "quantity": None, "quantity_status": "pending", "quantity_evidence": None,
                "takeoff_ref_id": None, "selected_option_id": None, "options": [],
            }
        ],
    }


def import_bidengine_takeoff(data: dict, records: list[dict], *, source_bid_ref: str = "072026-1044") -> dict:
    """References source takeoff but NEVER auto-prices or treats plan areas as final takeoff."""
    if data.get("project", {}).get("bid_engine_ref") != source_bid_ref:
        raise ValueError(
            "El takeoff incluido pertenece a " + source_bid_ref
            + "; primero identifique la misma licitación en project.bid_engine_ref"
        )
    if data.get("takeoff_references"):
        raise ValueError("El expediente ya contiene referencias de takeoff: no sobrescribir")
    imported = []
    for i, r in enumerate(records, 1):
        imported.append({
            "id": f"TO-{i:03d}", "building": r.get("building"), "item": r.get("item"),
            "reference_quantity": r.get("quantity"), "reference_unit": r.get("unit"),
            "source_status": r.get("quantity_status"), "basis": r.get("basis"),
            "source": r.get("source"), "review_status": "requires_estimator_review",
        })
    data["takeoff_references"] = imported
    return data


def save_template(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")


def make_snapshot(data: dict, as_of: date, directory: Path) -> Path:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = sha256((raw + "|" + as_of.isoformat()).encode("utf-8")).hexdigest()
    result = calculate(data, as_of=as_of)
    result["source_sha256"] = sha256(raw.encode("utf-8")).hexdigest()
    result["snapshot_id"] = digest
    directory.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", result["estimate_id"])[:64]
    out = directory / f"{slug}-{digest[:16]}.json"
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    try:
        with out.open("x", encoding="utf-8") as fp:
            fp.write(serialized)
    except FileExistsError:
        if out.read_text(encoding="utf-8") != serialized:
            raise ValueError("Conflicto: existe snapshot con diferente contenido")
    return out
