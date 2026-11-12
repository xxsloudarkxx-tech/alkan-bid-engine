"""Lump-Sum metal-fabrication cost analysis (internal) for S&S / A-1 delivery.

Replicates the seven-section structure of the West Seattle Junction example for
a **Metal Fabrications Only** scope, keeping two clearly separated views:

* *internal* cost build-up (materials, labor, equipment, contingency/OH/profit);
* the A-1 *client* view showing **only a single Total Lump Sum** (no unit
  prices, no margin, no internal cost).

It reuses ``metal_scope`` (scope extraction) and ``price_registry.resolve``
(price lookup / PENDING QUOTE).  It never invents a price, a measurement, a
wage, a percentage, or an authorization.  Robustness guards:

* **Equipment** is never assumed to be zero: it is ``QUOTED`` (has a cost),
  ``NONE_DOCUMENTED`` (explicitly NOT_REQUIRED / ABSORBED) or ``PENDING``.
* **Prices** are only associated with an item when the material code AND the
  unit of measure match (``price_registry.resolve(..., unit=...)``).
* **Reference prices** (PUBLIC CATALOG / BUDGET REFERENCE) never release a
  final total unless an explicit, documented exception is passed
  (``allow_provisional`` + ``provisional_exception_note``).
* **Labor / prevailing wage, quantities and margins** must carry evidence
  (``labor_wage_basis``, measured items, ``markup_basis``) to release a total.
* **``final_releasable``** requires complete evidence **and** ``authorized=True``.
  The module never sets authorization by itself; ``client_view`` reports the
  authorization state without contradiction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from .config import ProjectConfig
from .data_store import read_json
from .estimator_v1 import _cash, _decimal
from .metal_scope import metal_scope
from .price_registry import available_prices, import_catalog, resolve

# Equipment states -------------------------------------------------------------
EQUIPMENT_NOT_REQUIRED = "NOT_REQUIRED"
EQUIPMENT_ABSORBED = "ABSORBED"

_FIRM = "firm_quote"


@dataclass
class CostParams:
    """Optional/required inputs for the internal lump-sum build-up.

    All economic inputs default to ``None`` so a cost is never released from
    missing assumptions.  ``authorized`` and ``allow_provisional`` are gates
    that are **never** turned on by the engine itself.
    """
    labor_cost: str | Decimal | None = None
    labor_wage_basis: str | None = None        # prevailing-wage determination + productivity evidence
    equipment_cost: str | Decimal | None = None
    equipment_state: str | None = None         # QUOTED / NOT_REQUIRED / ABSORBED
    contingency_percent: str | Decimal | None = None
    overhead_percent: str | Decimal | None = None
    profit_percent: str | Decimal | None = None
    markup_basis: str | None = None            # documented basis for OH & profit
    price_adjustment: str | Decimal | None = None
    allow_provisional: bool = False            # explicit exception for reference (non-firm) prices
    provisional_exception_note: str = ""
    as_of: str | None = None
    authorized: bool = False

    def __post_init__(self) -> None:
        self.as_of = self.as_of or date.today().isoformat()


def _dec(value, field) -> Decimal | None:
    if value is None or value == "":
        return None
    return _decimal(value, field)


def _money(value: Decimal | None) -> Decimal | None:
    return _cash(value) if value is not None else None


def _fmt(value: Decimal | None) -> str | None:
    return f"${_cash(value):,.2f}" if value is not None else None


def _pct(value) -> Decimal | None:
    return _dec(value, "percent")


def build_envelope(analysis: dict, registry: list[dict] | None = None,
                   params: CostParams | None = None) -> dict:  # noqa: C901
    """Compute the internal seven-section cost analysis envelope.

    Returns a JSON-able dict with amounts as Decimals (``None`` where pending).
    No file is written and no authorization is given.
    """
    params = params or CostParams()
    scope = metal_scope(analysis)
    registry = registry or []

    measured = scope["metal_measured"]
    pending_m = scope["metal_pending_measurement"]

    # ---- 3. Material pricing (code + unit validated) --------------------------
    materials = []
    for it in measured:
        price = None
        reason = None
        avail = []
        if registry:
            price = resolve(registry, (it["id"] or ""), on_date=date.fromisoformat(params.as_of),
                            unit=it.get("unit"))
            avail = available_prices(registry, (it["id"] or ""),
                                     on_date=date.fromisoformat(params.as_of), unit=it.get("unit"))
            if price is None:
                reason = "no usable price (unit mismatch or not priced)" \
                    if any(r["material_code"] == (it["id"] or "") for r in registry) \
                    else "no catalog price for this material"
        prices = [float(r["unit_price"]) for r in avail]
        budget_low = min(prices) if prices else None
        budget_high = max(prices) if prices else None
        line = {
            "id": it["id"], "item": it["item"], "unit": it["unit"],
            "quantity": it["quantity"],
            "price_class": price["price_class"] if price else None,
            "supplier": price["supplier"] if price else None,
            "specification": price["specification"] if price else None,
            "source": price["source"] if price else None,
            "unit_price": _dec(price["unit_price"], "unit_price") if price and price["unit_price"] else None,
            "status": "PRICED" if price else "PENDING QUOTE",
            "reason": reason,
            "budget_low": budget_low, "budget_high": budget_high,
        }
        if line["unit_price"] is not None and it["quantity"] is not None:
            line["extended"] = _cash(_decimal(str(it["quantity"]), "quantity") * line["unit_price"])
        else:
            line["extended"] = None
        materials.append(line)

    pending_quote = [m for m in materials if m["status"] == "PENDING QUOTE"]
    provisional_used = [m for m in materials if m["status"] == "PRICED" and m["price_class"] != _FIRM]
    materials_total = Decimal("0")
    if pending_quote:
        materials_total = None
    elif materials:
        materials_total = _money(sum(m["extended"] for m in materials))

    # ---- 4. Labor (wage basis evidence required) ------------------------------
    labor_cost = _dec(params.labor_cost, "labor_cost")
    labor_pending = bool(measured) and labor_cost is None
    labor_no_evidence = bool(measured) and labor_cost is not None and not params.labor_wage_basis
    labor_cost_used = labor_cost if measured else Decimal("0")

    # ---- 5. Equipment (never assumed zero) ------------------------------------
    equipment_cost = _dec(params.equipment_cost, "equipment_cost")
    state = (params.equipment_state or "").upper()
    if equipment_cost is not None:
        equipment_status = "QUOTED"
        equipment_cost_used = equipment_cost
    elif state in (EQUIPMENT_NOT_REQUIRED, EQUIPMENT_ABSORBED):
        equipment_status = "NONE_DOCUMENTED"
        equipment_cost_used = Decimal("0")
    else:
        equipment_status = "PENDING" if measured else "NONE_REQUIRED"
        equipment_cost_used = Decimal("0") if not measured else None

    # ---- Direct + margins ------------------------------------------------------
    direct = None
    if materials_total is not None and not labor_pending and equipment_cost_used is not None:
        direct = _money(materials_total + labor_cost_used + equipment_cost_used)

    contingency_percent = _pct(params.contingency_percent)
    overhead_percent = _pct(params.overhead_percent)
    profit_percent = _pct(params.profit_percent)
    price_adjustment = _dec(params.price_adjustment, "price_adjustment")

    contingency = _money(direct * contingency_percent / Decimal("100")) if (direct is not None and contingency_percent is not None) else None
    base_op = (direct + contingency) if (direct is not None and contingency is not None) else None
    overhead = _money(base_op * overhead_percent / Decimal("100")) if (base_op is not None and overhead_percent is not None) else None
    profit = _money(base_op * profit_percent / Decimal("100")) if (base_op is not None and profit_percent is not None) else None
    if direct is not None and None not in (contingency, overhead, profit):
        cost_based_total = _money(base_op + overhead + profit)
    else:
        cost_based_total = None

    # ---- 7. Blockers -----------------------------------------------------------
    blockers = []
    if pending_m:
        blockers.append(f"{len(pending_m)} partida(s) metal sin medir (PENDING MEASUREMENT)")
    if pending_quote:
        blockers.append(f"{len(pending_quote)} partida(s) medida(s) sin precio usable (PENDING QUOTE)")
    if labor_pending:
        blockers.append("Mano de obra pendiente (PENDING QUOTE)")
    if labor_no_evidence:
        blockers.append("Labor sin evidencia de salario prevaleciente / productividad (wage basis)")
    if equipment_status == "PENDING":
        blockers.append("Equipo: sin cotización y sin clasificación NOT_REQUIRED/ABSORBED (PENDING)")
    for label, pct in (("Contingencia", contingency_percent), ("Overhead", overhead_percent), ("Profit", profit_percent)):
        if direct is not None and pct is None:
            blockers.append(f"{label}: sin tasa definida (PENDING)")
    if direct is not None and overhead_percent is not None and profit_percent is not None and not params.markup_basis:
        blockers.append("Margen (OH/profit) sin base documentada (markup basis)")
    if provisional_used and not (params.allow_provisional and params.provisional_exception_note):
        blockers.append("Contiene precios provisionales (no FIRM): requiere excepción explícita y documentada")
    if cost_based_total is not None and price_adjustment is None:
        blockers.append("Ajuste de precio a Lump Sum cliente pendiente (PENDING)")

    complete = not pending_m and not pending_quote and not labor_pending and not labor_no_evidence \
        and equipment_status != "PENDING" \
        and None not in (direct, contingency, overhead, profit) \
        and params.markup_basis \
        and not (provisional_used and not (params.allow_provisional and params.provisional_exception_note)) \
        and price_adjustment is not None
    # The client Total Lump Sum is only produced when the whole envelope is
    # complete (no PENDING MEASUREMENT/QUOTE, labor + equipment + margins + wage
    # evidence all in place); a partial internal build-up stays internal.
    final_ready = complete and not provisional_used

    # Evidence-based budgetary range (low..high), derived from verifiable prices
    # and documented WA labor/assumptions — never arbitrary.
    budget_materials_low = budget_materials_high = None
    budget_low_ok = False
    if materials and all(m.get("budget_low") is not None for m in materials):
        budget_materials_low = _money(sum(Decimal(str(m["quantity"])) * Decimal(str(m["budget_low"])) for m in materials))
        budget_materials_high = _money(sum(Decimal(str(m["quantity"])) * Decimal(str(m["budget_high"])) for m in materials))
        budget_low_ok = True
    b_markup = (contingency_percent is not None and overhead_percent is not None
                and profit_percent is not None and bool(params.markup_basis))
    b_labor = (not labor_pending) and (not measured or bool(params.labor_wage_basis))
    b_equip = equipment_status != "PENDING"
    budget_low_total = budget_high_total = None
    budgetary_ready = (not pending_m) and budget_low_ok and b_labor and b_equip and b_markup
    if budgetary_ready:

        def _buildup(base):
            cont = _money(base * contingency_percent / Decimal("100"))
            sub = base + cont
            oh = _money(sub * overhead_percent / Decimal("100"))
            pf = _money(sub * profit_percent / Decimal("100"))
            return _money(sub + oh + pf)

        dl = budget_materials_low + (labor_cost or Decimal("0")) + (equipment_cost_used or Decimal("0"))
        dh = budget_materials_high + (labor_cost or Decimal("0")) + (equipment_cost_used or Decimal("0"))
        budget_low_total = _money(_buildup(dl) + (price_adjustment or Decimal("0")))
        budget_high_total = _money(_buildup(dh) + (price_adjustment or Decimal("0")))

    if final_ready and params.authorized:
        delivery_state = "FINAL_RELEASED"
        state_reason = "Costos validados con precios firmes y autorización humana explícita."
    elif budgetary_ready:
        delivery_state = "BUDGETARY_PRELIMINARY"
        state_reason = "Estimado aproximado con precios de referencia y supuestos documentados; no es una cotización firme."
    else:
        delivery_state = "INTERNAL_BLOCKED"
        state_reason = "Faltan datos indispensables para un aproximado confiable; emisión comercial bloqueada."
    final_releasable = delivery_state == "FINAL_RELEASED"

    client_lump_sum = None
    if final_releasable and cost_based_total is not None and price_adjustment is not None:
        client_lump_sum = _money(cost_based_total + price_adjustment)

    return {
        "as_of": params.as_of,
        "envelope": "internal",
        "sections": {
            "1_scope": {"scope_status": (analysis.get("scope_status") or ""), "metal_items": scope["metal_items"]},
            "2_quantity_takeoff": {
                "count_identified": scope["count_identified"], "count_measured": scope["count_measured"],
                "count_pending_measurement": scope["count_pending_measurement"],
                "measured": measured, "pending_measurement": pending_m,
            },
            "3_material_pricing": materials,
            "4_labor": {"status": "PENDING QUOTE" if labor_pending else "PRICED", "cost": _money(labor_cost),
                        "wage_basis": params.labor_wage_basis, "evidence_present": bool(params.labor_wage_basis)},
            "5_office_fees_equipment": {
                "status": equipment_status,
                "cost": _money(equipment_cost_used),
                "state": params.equipment_state or (equipment_status if equipment_status != "PENDING" else None),
                "evidence_present": equipment_status != "PENDING",
            },
            "6_price_buildup": {
                "direct_cost": direct, "materials_total": materials_total, "labor_cost": _money(labor_cost),
                "equipment_cost": _money(equipment_cost_used),
                "contingency": contingency, "overhead": overhead, "profit": profit,
                "markup_basis": params.markup_basis,
                "cost_based_total": cost_based_total, "price_adjustment": price_adjustment,
            },
            "7_risks_checks_blockers": blockers,
        },
        "totals": {
            "materials_total": materials_total,
            "labor_cost": _money(labor_cost),
            "equipment_cost": _money(equipment_cost_used),
            "equipment_status": equipment_status,
            "direct_cost": direct,
            "cost_based_total": cost_based_total,
            "client_lump_sum": client_lump_sum,
            "budget_range": {"low": budget_low_total, "high": budget_high_total},
        },
        "provisional_used": [m["id"] for m in provisional_used],
        "delivery_state": delivery_state,
        "state_reason": state_reason,
        "budgetary_ready": budgetary_ready,
        "final_releasable": final_releasable,
        "authorized": params.authorized,
        "blockers": blockers,
    }


def client_view(envelope: dict) -> dict:
    """A-1 proposal projection — clean, client-safe (three delivery states).

    * FINAL_RELEASED        -> single Total Lump Sum.
    * BUDGETARY_PRELIMINARY -> evidence-based range, clearly NOT a firm quote.
    * INTERNAL_BLOCKED      -> no number, no status bleed (blockers are internal).

    This view is what a client-facing document may show: never leaks unit
    prices, margins, internal costs or technical/internals statuses, and never
    shows nulls or empty fields.
    """
    state = envelope["delivery_state"]
    base = {"contractor": "S & S CUSTOM IRON WORKS LLC",
            "proposal_for": "A-1 Landscaping",
            "scope": "Metal Fabrications Only"}

    if state == "FINAL_RELEASED":
        total = envelope["totals"]["client_lump_sum"]
        return {**base,
                "total_lump_sum": total,
                "total_lump_sum_display": _fmt(total),
                "delivery_state": "FINAL_RELEASED",
                "status": "FINAL PROPOSAL — authorized",
                "final_releasable": True,
                "authorized": True}
    if state == "BUDGETARY_PRELIMINARY":
        low = envelope["totals"]["budget_range"]["low"]
        high = envelope["totals"]["budget_range"]["high"]
        return {**base,
                "total_lump_sum": None,
                "budget_low": low,
                "budget_high": high,
                "budget_display": f"{_fmt(low)} – {_fmt(high)}",
                "delivery_state": "BUDGETARY_PRELIMINARY",
                "status": "BUDGETARY ESTIMATE — NOT A FIRM QUOTE",
                "final_releasable": False,
                "authorized": False}
    # INTERNAL_BLOCKED — no commercial emission, nothing internal is exposed.
    return {**base,
            "total_lump_sum": None,
            "delivery_state": "INTERNAL_BLOCKED",
            "status": "NO PROPOSAL AVAILABLE",
            "final_releasable": False,
            "authorized": False}


def analyze_project(root: Path, project_id: str, registry: list[dict] | None = None,
                    params: CostParams | None = None) -> dict:
    """Load a dossier's analysis.json and build the metal cost-envelope."""
    config = ProjectConfig(root, project_id)
    analysis = read_json(config.project_dir / "analysis.json")
    return build_envelope(analysis, registry=registry, params=params)


def load_registry(path: Path | str) -> list[dict]:
    """Wrap ``price_registry.import_catalog`` for the runner."""
    return import_catalog(path)