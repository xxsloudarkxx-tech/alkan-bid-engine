"""ALKAN three-document estimate package — calculation method.

Encodes the methodology used for the S&S Custom Iron Works final estimates
(West Seattle Junction, Meridian re-bid, Orangegate Phase 1, Nov 2026):

1. Take-off from plans/specs/addenda: every line carries a quantity source
   (sheet, detail, spec section or RFQ line).
2. Materials priced line by line with an explicit price basis
   (QUOTE / CATALOG / BUDGET) and price source.  Sales tax excluded on
   purchases for resale (WA public works: retail sales tax is collected by
   the prime contractor, WAC 458-20-171).
3. Labor split by task and trade (shop / field / office).  Prevailing-wage
   trades = L&I journey-level total rate (wage + fringe) + burden %
   (payroll taxes, L&I workers' comp, liability).  Shop and office use
   loaded rates.
4. Equipment, mobilization, fees and other costs as separate lines.
5. Markups applied sequentially:
   contingency % of direct; overhead % of (direct + contingency);
   profit % of (direct + contingency + overhead).
6. Sell price = computed total rounded to the nearest rounding step ($50).
7. Three documents from the same computation: 01 Cost Analysis (internal),
   02 Material List & Price List, 03 Estimate/Proposal (single lump sum,
   scope, exclusions, payment, warranty, terms, acceptance).
8. Cross-document QA: line arithmetic, section totals, and the same sell
   price in all three documents.

Never invents a quantity, price or rate: everything comes from the input
file.  Never authorizes a proposal by itself (``release.authorized``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .alkan_method import RELATIONSHIPS, TIERS, TRADES, AlkanCommission
from .estimator_v1 import _cash, _fmt

PACKAGE_SCHEMA = "alkan-package/1"
PRICE_BASES = ("QUOTE", "CATALOG", "BUDGET")
OTHER_CATEGORIES = ("Equipment", "Mobilization", "Fees", "Other", "Subcontract")


def _d(value: Any, field_name: str, *, allow_zero: bool = True) -> Decimal:
    """Decimal from text/int (floats rejected, like the rest of the engine)."""
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise ValueError(f"{field_name}: use un número decimal como texto, no float/null")
    try:
        n = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"{field_name}: decimal inválido") from exc
    if not n.is_finite() or n < 0 or (not allow_zero and n == 0):
        raise ValueError(f"{field_name}: valor fuera de rango")
    return n


# ───────────────────────────────────────────────────────────── data classes

@dataclass
class Rate:
    key: str
    label: str
    kind: str                      # "prevailing_wage" or "loaded"
    rate: Decimal                  # PW total (wage+fringe) or loaded rate
    burden_pct: Decimal = Decimal("0")
    trade: str = ""
    source: str = ""

    @property
    def loaded(self) -> Decimal:
        if self.kind == "prevailing_wage":
            return _cash(self.rate * (1 + self.burden_pct / 100))
        return _cash(self.rate)


@dataclass
class MaterialLine:
    id: str
    section: str
    item: str
    spec: str
    qty: Decimal
    unit: str
    unit_price: Decimal
    price_basis: str
    price_source: str = ""
    qty_source: str = ""
    supplier: str = ""             # id in the supplier directory (knowledge table "suppliers")
    quote_ref: str = ""            # supplier quote number (required for QUOTE lines set by re-pricing)
    quote_date: str = ""
    supplier_source: str = ""      # "auto" = suggested from directory keywords, not confirmed

    @property
    def extended(self) -> Decimal:
        return _cash(self.qty * self.unit_price)


@dataclass
class LaborLine:
    id: str
    task: str
    rate_key: str
    hours: Decimal


@dataclass
class OtherLine:
    id: str
    item: str
    category: str
    qty: Decimal
    unit: str
    rate: Decimal
    source: str = ""

    @property
    def extended(self) -> Decimal:
        return _cash(self.qty * self.rate)


@dataclass
class Package:
    estimate_id: str
    date: str
    contractor: dict
    project: dict
    relationship: str
    tier: str
    rates: dict[str, Rate]
    contingency_pct: Decimal
    overhead_pct: Decimal
    profit_pct: Decimal
    rounding: Decimal
    tax: dict
    materials: list[MaterialLine]
    labor: list[LaborLine]
    other: list[OtherLine]
    scope: list[dict]
    exclusions: list[str]
    assumptions: list[str] = field(default_factory=list)
    terms: dict = field(default_factory=dict)
    release: dict = field(default_factory=dict)
    commission: dict | None = None
    validity_days: int = 30
    base_dir: Path | None = None
    subcontract: dict = field(default_factory=dict)   # optional "subcontract_package" block (texts and flags)


# ───────────────────────────────────────────────────────────── loading

def load_package(path: str | Path) -> Package:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    pkg = package_from_dict(data)
    pkg.base_dir = path.parent
    return pkg


def package_from_dict(data: dict) -> Package:
    if data.get("schema") != PACKAGE_SCHEMA:
        raise ValueError(f"schema debe ser '{PACKAGE_SCHEMA}'")
    rates = {}
    for key, r in data["labor_rates"].items():
        kind = r.get("kind", "loaded")
        if kind not in ("prevailing_wage", "loaded"):
            raise ValueError(f"labor_rates.{key}.kind inválido")
        rates[key] = Rate(key=key, label=r["label"], kind=kind,
                          rate=_d(r["rate"], f"labor_rates.{key}.rate", allow_zero=False),
                          burden_pct=_d(r.get("burden_pct", "0"), f"labor_rates.{key}.burden_pct"),
                          trade=r.get("trade", ""), source=r.get("source", ""))
    mk = data["markups"]
    mats = [MaterialLine(id=m.get("id") or f"M{i:03d}", section=m["section"], item=m["item"], spec=m.get("spec", ""),
                         qty=_d(m["qty"], f"materials[{i}].qty", allow_zero=False), unit=m["unit"],
                         unit_price=_d(m["unit_price"], f"materials[{i}].unit_price"),
                         price_basis=m.get("price_basis", "BUDGET").upper(), price_source=m.get("price_source", ""),
                         qty_source=m.get("qty_source", ""), supplier=str(m.get("supplier", "") or ""),
                         quote_ref=str(m.get("quote_ref", "") or ""), quote_date=str(m.get("quote_date", "") or ""),
                         supplier_source=str(m.get("supplier_source", "") or ""))
            for i, m in enumerate(data["materials"], 1)]
    labor = [LaborLine(id=l.get("id") or f"L{i:03d}", task=l["task"], rate_key=l["rate"],
                       hours=_d(l["hours"], f"labor[{i}].hours", allow_zero=False))
             for i, l in enumerate(data["labor"], 1)]
    other = [OtherLine(id=o.get("id") or f"O{i:03d}", item=o["item"], category=o.get("category", "Other"),
                       qty=_d(o["qty"], f"other[{i}].qty", allow_zero=False), unit=o["unit"],
                       rate=_d(o["rate"], f"other[{i}].rate"), source=o.get("source", ""))
             for i, o in enumerate(data.get("other", []), 1)]
    return Package(
        estimate_id=data["estimate_id"], date=data["date"], contractor=data["contractor"], project=data["project"],
        relationship=data.get("relationship", "sub_to_gc"), tier=data.get("tier", "competitive"), rates=rates,
        contingency_pct=_d(mk["contingency_pct"], "markups.contingency_pct"),
        overhead_pct=_d(mk["overhead_pct"], "markups.overhead_pct"),
        profit_pct=_d(mk["profit_pct"], "markups.profit_pct"),
        rounding=_d(mk.get("rounding", "50"), "markups.rounding", allow_zero=False),
        tax=data.get("tax", {"mode": "excluded_resale"}), materials=mats, labor=labor, other=other,
        scope=data["scope"], exclusions=data.get("exclusions", []), assumptions=data.get("assumptions", []),
        terms=data.get("terms", {}), release=data.get("release", {}), commission=data.get("alkan_commission"),
        validity_days=int(data.get("validity_days", 30)),
        subcontract=data.get("subcontract_package") or {},
    )


# ───────────────────────────────────────────────────────────── validation

def validate(pkg: Package) -> dict:
    """Blockers stop the build; warnings are printed in the cost analysis."""
    blockers, warnings = [], []
    for k in ("name", "address", "license", "phone", "contact"):
        if not pkg.contractor.get(k):
            blockers.append(f"contractor.{k} requerido")
    for k in ("key", "title", "short", "owner", "site", "county"):
        if not pkg.project.get(k):
            blockers.append(f"project.{k} requerido")
    if not pkg.project.get("documents"):
        blockers.append("project.documents: lista de planos/specs/adendas usados para el takeoff")
    if pkg.relationship not in RELATIONSHIPS:
        blockers.append(f"relationship desconocida: {pkg.relationship}")
    if pkg.tier not in TIERS:
        blockers.append(f"tier desconocido: {pkg.tier}")
    for key, r in pkg.rates.items():
        if r.kind == "prevailing_wage":
            if not r.source:
                blockers.append(f"labor_rates.{key}: prevailing wage requiere fuente L&I (condado y fecha)")
            if r.trade and r.trade not in TRADES:
                warnings.append(f"labor_rates.{key}: oficio '{r.trade}' no está en el registro TRADES")
    if not pkg.materials:
        blockers.append("materials vacío")
    if not pkg.labor:
        blockers.append("labor vacío")
    for m in pkg.materials:
        if m.price_basis not in PRICE_BASES:
            blockers.append(f"{m.id}: price_basis debe ser {PRICE_BASES}")
        if not m.qty_source:
            warnings.append(f"{m.id}: sin referencia de cantidad (hoja/detalle/spec)")
    for name, rows in (("materials", pkg.materials), ("labor", pkg.labor), ("other", pkg.other)):
        ids = [x.id for x in rows]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            blockers.append(f"{name}: id repetido {', '.join(dup)} — cada renglón necesita un id único "
                            f"(los cambios de precio y proveedor se aplican por id)")
    used = sorted({m.supplier for m in pkg.materials if m.supplier})
    if used:
        from .suppliers import load_directory
        known = {s["id"] for s in load_directory()}
        for sid in used:
            if sid not in known:
                warnings.append(f"Proveedor «{sid}» no está en el directorio de proveedores")
        for m in pkg.materials:
            if m.price_basis == "QUOTE" and m.supplier and not m.quote_ref and "#" not in m.price_source:
                warnings.append(f"{m.id}: QUOTE de {m.supplier} sin número de cotización")
        auto = [m.id for m in pkg.materials if m.supplier_source == "auto"]
        if auto:
            warnings.append(f"{len(auto)} renglones con proveedor sugerido automáticamente — confirmar antes de comprar")
    for l in pkg.labor:
        if l.rate_key not in pkg.rates:
            blockers.append(f"{l.id}: tarifa '{l.rate_key}' no definida en labor_rates")
    for o in pkg.other:
        if o.category not in OTHER_CATEGORIES:
            warnings.append(f"{o.id}: categoría '{o.category}' fuera de {OTHER_CATEGORIES}")
    if not pkg.scope:
        blockers.append("scope vacío")
    if not pkg.exclusions:
        warnings.append("Sin exclusiones declaradas")
    budget = [m.id for m in pkg.materials if m.price_basis != "QUOTE"]
    if budget:
        warnings.append(f"{len(budget)} de {len(pkg.materials)} líneas de material con precio no cotizado "
                        f"(CATALOG/BUDGET) — reemplazar con cotizaciones de proveedor")
    return {"blockers": blockers, "warnings": warnings, "unquoted_lines": budget}


# ───────────────────────────────────────────────────────────── computation

def round_to(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def compute(pkg: Package) -> dict:
    v = validate(pkg)
    if v["blockers"]:
        raise ValueError("Paquete bloqueado:\n- " + "\n- ".join(v["blockers"]))
    M = _cash(sum((m.extended for m in pkg.materials), Decimal(0)))
    labor_rows = []
    for l in pkg.labor:
        r = pkg.rates[l.rate_key]
        labor_rows.append({"id": l.id, "task": l.task, "trade": r.label, "hours": l.hours, "rate": r.loaded,
                           "cost": _cash(l.hours * r.loaded)})
    L = _cash(sum((x["cost"] for x in labor_rows), Decimal(0)))
    O = _cash(sum((o.extended for o in pkg.other), Decimal(0)))
    D = _cash(M + L + O)
    cont = _cash(D * pkg.contingency_pct / 100)
    oh = _cash((D + cont) * pkg.overhead_pct / 100)
    prof = _cash((D + cont + oh) * pkg.profit_pct / 100)
    total = _cash(D + cont + oh + prof)
    price = _cash(round_to(total, pkg.rounding))
    hours: dict[str, Decimal] = {}
    for x in labor_rows:
        hours[x["trade"]] = hours.get(x["trade"], Decimal(0)) + x["hours"]
    sections: dict[str, Decimal] = {}
    for m in pkg.materials:
        sections[m.section] = sections.get(m.section, Decimal(0)) + m.extended
    by_supplier: dict[str, dict] = {}
    for m in pkg.materials:
        g = by_supplier.setdefault(m.supplier, {"lines": 0, "unquoted": 0, "total": Decimal(0)})
        g["lines"] += 1
        g["unquoted"] += m.price_basis != "QUOTE"
        g["total"] += m.extended
    commission = None
    if pkg.commission:
        c = AlkanCommission(gross_sale=price,
                            find_estimate_pct=_d(pkg.commission.get("find_estimate_pct", "3"), "alkan_commission.find_estimate_pct"),
                            coordination_pct=_d(pkg.commission.get("coordination_pct", "3"), "alkan_commission.coordination_pct"),
                            coordination_included=bool(pkg.commission.get("coordination_included", False)))
        commission = {"total": c.total_fee, "schedule": c.schedule(), "net_margin": _cash(price - D - c.total_fee)}
    status = "READY_FOR_REVIEW" if not v["unquoted_lines"] else "BUDGETARY"
    if pkg.release.get("authorized") is True:
        status = "AUTHORIZED" if (not v["unquoted_lines"] or pkg.release.get("allow_budget_prices")) else status
    return {
        "materials": M, "labor": L, "other": O, "direct": D, "contingency": cont, "overhead": oh, "profit": prof,
        "total": total, "price": price, "labor_rows": labor_rows, "hours": hours, "sections": sections,
        "by_supplier": by_supplier, "commission": commission, "validation": v, "status": status,
        "break_even": _cash(D + cont + oh), "gross_margin": _cash(price - D),
    }


def proposal_release(pkg: Package, result: dict) -> dict:
    """Decide whether document 03 may be produced and how it is labeled.

    The engine never authorizes on its own: without ``release.authorized`` the
    proposal is stamped DRAFT.  Unquoted prices block the proposal unless the
    human sets ``release.allow_budget_prices`` with a written note.
    """
    unquoted = result["validation"]["unquoted_lines"]
    rel = pkg.release or {}
    if unquoted and not rel.get("allow_budget_prices"):
        return {"produce": False, "label": None,
                "reason": "Precios no cotizados: defina release.allow_budget_prices=true con nota, o cargue cotizaciones."}
    if unquoted and not rel.get("note"):
        return {"produce": False, "label": None, "reason": "release.allow_budget_prices requiere release.note (justificación)."}
    if rel.get("authorized") is True:
        return {"produce": True, "label": "LUMP-SUM PROPOSAL", "reason": ""}
    return {"produce": True, "label": "DRAFT — PENDING AUTHORIZATION",
            "reason": "release.authorized no está en true: propuesta marcada como borrador."}


def result_json(pkg: Package, r: dict) -> dict:
    """Serializable computation record (money as text, like the engine)."""
    return {
        "package_schema": PACKAGE_SCHEMA, "estimate_id": pkg.estimate_id, "date": pkg.date,
        "project": pkg.project.get("title"), "contractor": pkg.contractor.get("name"),
        "relationship": RELATIONSHIPS[pkg.relationship]["label"], "tier": pkg.tier,
        "tier_precision": TIERS[pkg.tier]["precision"], "status": r["status"],
        "totals": {k: _fmt(r[k]) for k in ("materials", "labor", "other", "direct", "contingency", "overhead",
                                            "profit", "total", "price", "break_even", "gross_margin")},
        "markups": {"contingency_pct": str(pkg.contingency_pct), "overhead_pct": str(pkg.overhead_pct),
                    "profit_pct": str(pkg.profit_pct), "rounding": str(pkg.rounding), "method": "sequential"},
        "rates": {k: {"label": x.label, "kind": x.kind, "rate": _fmt(x.rate), "burden_pct": str(x.burden_pct),
                      "loaded": _fmt(x.loaded), "source": x.source} for k, x in pkg.rates.items()},
        "hours_by_trade": {k: str(v) for k, v in r["hours"].items()},
        "sections": {k: _fmt(v) for k, v in r["sections"].items()},
        "by_supplier": {(k or "(sin proveedor)"): {"lines": g["lines"], "unquoted": g["unquoted"], "total": _fmt(g["total"])}
                        for k, g in r["by_supplier"].items()},
        "materials": [{"id": m.id, "section": m.section, "item": m.item, "qty": str(m.qty), "unit": m.unit,
                       "unit_price": _fmt(m.unit_price), "extended": _fmt(m.extended), "price_basis": m.price_basis,
                       "price_source": m.price_source, "qty_source": m.qty_source, "supplier": m.supplier,
                       "quote_ref": m.quote_ref} for m in pkg.materials],
        "labor": [{"id": x["id"], "task": x["task"], "trade": x["trade"], "hours": str(x["hours"]),
                   "rate": _fmt(x["rate"]), "cost": _fmt(x["cost"])} for x in r["labor_rows"]],
        "other": [{"id": o.id, "item": o.item, "category": o.category, "qty": str(o.qty), "unit": o.unit,
                   "rate": _fmt(o.rate), "extended": _fmt(o.extended)} for o in pkg.other],
        "alkan_commission": ({"total": _fmt(r["commission"]["total"]), "net_margin": _fmt(r["commission"]["net_margin"]),
                              **r["commission"]["schedule"]} if r["commission"] else None),
        "validation": r["validation"],
        "notes": ["No equivale a oferta aprobada, contrato ni autorización de compra.",
                  "Cantidades y precios sujetos a validación por el estimador responsable."],
    }
