"""Transparent 13-bucket financial cost engine with Markup vs Margin and 3-scenario analysis."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .package_method import Package, compute as compute_legacy, round_to


def _d(val: Any, default: str = "0") -> Decimal:
    if val is None or val == "":
        return Decimal(default)
    return Decimal(str(val))


def _cash(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class CostProfile:
    company: str = "Generic Contractor"
    trade: str = "Metal Fabrication"
    project_type: str = "Public Works"
    overhead_pct: Decimal = Decimal("10")
    contingency_pct: Decimal = Decimal("5")
    profit_pct: Decimal = Decimal("10")
    profit_mode: str = "markup"  # "markup" or "margin"
    default_waste_pct: Decimal = Decimal("0")
    sales_tax_pct: Decimal = Decimal("0")
    rounding: Decimal = Decimal("10")

    def __post_init__(self) -> None:
        if self.profit_mode not in ("markup", "margin"):
            raise ValueError("profit_mode must be 'markup' or 'margin'")
        self.overhead_pct = _d(self.overhead_pct)
        self.contingency_pct = _d(self.contingency_pct)
        self.profit_pct = _d(self.profit_pct)
        self.default_waste_pct = _d(self.default_waste_pct)
        self.sales_tax_pct = _d(self.sales_tax_pct)
        self.rounding = _d(self.rounding, "1")
        if self.profit_mode == "margin" and self.profit_pct >= Decimal("100"):
            raise ValueError("Target margin percentage must be < 100%.")


@dataclass
class ScenarioAssumption:
    name: str  # Conservative | Expected | Aggressive
    material_factor: Decimal = Decimal("1.00")
    labor_hours_factor: Decimal = Decimal("1.00")
    equipment_factor: Decimal = Decimal("1.00")
    contingency_pct: Decimal | None = None
    overhead_pct: Decimal | None = None
    profit_pct: Decimal | None = None
    description: str = ""


DEFAULT_SCENARIOS: tuple[ScenarioAssumption, ...] = (
    ScenarioAssumption(
        name="Conservative",
        material_factor=Decimal("1.08"),
        labor_hours_factor=Decimal("1.15"),
        equipment_factor=Decimal("1.10"),
        contingency_pct=Decimal("8"),
        description="Higher escalation (+8% mat, +15% labor hrs) and 8% risk contingency.",
    ),
    ScenarioAssumption(
        name="Expected",
        material_factor=Decimal("1.00"),
        labor_hours_factor=Decimal("1.00"),
        equipment_factor=Decimal("1.00"),
        description="Baseline calibrated quantities, wage rates, and bid markups.",
    ),
    ScenarioAssumption(
        name="Aggressive",
        material_factor=Decimal("0.97"),
        labor_hours_factor=Decimal("0.92"),
        equipment_factor=Decimal("0.95"),
        contingency_pct=Decimal("2"),
        description="Lean field productivity (-8% hrs), bulk supplier discount (-3% mat), 2% contingency.",
    ),
)


def classify_other_category(category: str) -> str:
    """Map OtherLine category into Equipment, Mobilization, Subcontractor, Freight, or Permits/Other."""
    low = (category or "").strip().lower()
    if "equip" in low or "crane" in low or "lift" in low:
        return "equipment_cost"
    if "mob" in low:
        return "mobilization_cost"
    if "sub" in low:
        return "subcontractor_cost"
    if "freight" in low or "ship" in low or "deliv" in low:
        return "freight_cost"
    return "permits_and_other_cost"


def compute_13_buckets(
    *,
    material_net_cost: Decimal,
    labor_cost: Decimal,
    equipment_cost: Decimal = Decimal("0"),
    subcontractor_cost: Decimal = Decimal("0"),
    freight_cost: Decimal = Decimal("0"),
    mobilization_cost: Decimal = Decimal("0"),
    permits_and_other_cost: Decimal = Decimal("0"),
    waste_allowance: Decimal = Decimal("0"),
    waste_embedded_in_material: bool = False,
    contingency_pct: Decimal = Decimal("0"),
    overhead_pct: Decimal = Decimal("10"),
    profit_pct: Decimal = Decimal("10"),
    profit_mode: str = "markup",
    sales_tax_pct: Decimal = Decimal("0"),
    rounding: Decimal = Decimal("10"),
    indirect_calc_mode: str = "sequential",  # "sequential" (alkan-package/1) or "on_direct"
) -> dict[str, Any]:
    """Compute transparent 13-bucket cost estimate with zero double-counting and markup/margin reporting."""
    if profit_mode not in ("markup", "margin"):
        raise ValueError("profit_mode must be 'markup' or 'margin'")
    mat = _cash(_d(material_net_cost))
    lab = _cash(_d(labor_cost))
    eqp = _cash(_d(equipment_cost))
    sub = _cash(_d(subcontractor_cost))
    frt = _cash(_d(freight_cost))
    mob = _cash(_d(mobilization_cost))
    prm = _cash(_d(permits_and_other_cost))
    wst = _cash(_d(waste_allowance))

    # Avoid double-counting waste when waste_allowance is already baked into material_net_cost
    effective_waste_in_direct = Decimal("0") if waste_embedded_in_material else wst
    direct_cost = _cash(mat + lab + eqp + sub + frt + mob + prm + effective_waste_in_direct)

    cont_p = _d(contingency_pct)
    oh_p = _d(overhead_pct)
    prof_p = _d(profit_pct)

    contingency = _cash(direct_cost * cont_p / Decimal("100"))
    oh_base = direct_cost if indirect_calc_mode == "on_direct" else _cash(direct_cost + contingency)
    overhead = _cash(oh_base * oh_p / Decimal("100"))
    cost_before_profit = _cash(direct_cost + contingency + overhead)

    if profit_mode == "margin":
        if prof_p >= Decimal("100"):
            raise ValueError("Target margin % must be < 100.")
        pre_tax_sell = _cash(cost_before_profit / (Decimal("1") - (prof_p / Decimal("100"))))
        profit = _cash(pre_tax_sell - cost_before_profit)
    else:
        profit = _cash(cost_before_profit * prof_p / Decimal("100"))
        pre_tax_sell = _cash(cost_before_profit + profit)

    tax_amount = _cash(pre_tax_sell * _d(sales_tax_pct) / Decimal("100"))
    unrounded_total = _cash(pre_tax_sell + tax_amount)
    final_bid_price = _cash(round_to(unrounded_total, _d(rounding, "1")))

    achieved_markup_pct = (
        (profit * Decimal("100") / cost_before_profit).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if cost_before_profit > 0 else Decimal("0.00")
    )
    achieved_margin_pct = (
        (profit * Decimal("100") / pre_tax_sell).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if pre_tax_sell > 0 else Decimal("0.00")
    )

    return {
        "buckets": {
            "1_material_cost": str(mat),
            "2_labor_cost": str(lab),
            "3_equipment_cost": str(eqp),
            "4_subcontractor_cost": str(sub),
            "5_freight": str(frt),
            "6_mobilization": str(mob),
            "7_permits_and_other": str(prm),
            "8_waste_allowance": str(wst),
            "9_direct_cost": str(direct_cost),
            "10_overhead": str(overhead),
            "11_contingency": str(contingency),
            "12_profit": str(profit),
            "13_final_bid_price": str(final_bid_price),
        },
        "waste_embedded_in_material": waste_embedded_in_material,
        "indirect_calc_mode": indirect_calc_mode,
        "cost_before_profit": str(cost_before_profit),
        "tax_amount": str(tax_amount),
        "unrounded_total": str(unrounded_total),
        "profit_mode": profit_mode,
        "configured_profit_pct": str(prof_p),
        "achieved_markup_pct": str(achieved_markup_pct),
        "achieved_margin_pct": str(achieved_margin_pct),
        "rounding_step": str(rounding),
    }


def analyze_package_costs(
    pkg: Package,
    *,
    profit_mode: str = "markup",
    sales_tax_pct: Decimal = Decimal("0"),
    scenarios: tuple[ScenarioAssumption, ...] = DEFAULT_SCENARIOS,
) -> dict[str, Any]:
    """Compute transparent 13-bucket breakdown and Conservative/Expected/Aggressive scenarios for a Package."""
    legacy = compute_legacy(pkg)
    other_split = {
        "equipment_cost": Decimal("0"),
        "mobilization_cost": Decimal("0"),
        "subcontractor_cost": Decimal("0"),
        "freight_cost": Decimal("0"),
        "permits_and_other_cost": Decimal("0"),
    }
    for o in pkg.other:
        other_split[classify_other_category(o.category)] += o.extended

    # Detect embedded waste if materials have explicit waste_pct metadata, otherwise 0 extra
    net_mat = Decimal("0")
    waste_val = Decimal("0")
    for m in pkg.materials:
        ext = m.extended
        net_mat += ext

    base_13 = compute_13_buckets(
        material_net_cost=net_mat,
        labor_cost=legacy["labor"],
        equipment_cost=other_split["equipment_cost"],
        subcontractor_cost=other_split["subcontractor_cost"],
        freight_cost=other_split["freight_cost"],
        mobilization_cost=other_split["mobilization_cost"],
        permits_and_other_cost=other_split["permits_and_other_cost"],
        waste_allowance=waste_val,
        waste_embedded_in_material=False,
        contingency_pct=pkg.contingency_pct,
        overhead_pct=pkg.overhead_pct,
        profit_pct=pkg.profit_pct,
        profit_mode=profit_mode,
        sales_tax_pct=sales_tax_pct,
        rounding=pkg.rounding,
        indirect_calc_mode="sequential",
    )

    scenario_rows: list[dict[str, Any]] = []
    expected_price = Decimal(base_13["buckets"]["13_final_bid_price"])
    for sc in scenarios:
        sc_mat = _cash(net_mat * sc.material_factor)
        sc_lab = _cash(legacy["labor"] * sc.labor_hours_factor)
        sc_eqp = _cash(other_split["equipment_cost"] * sc.equipment_factor)
        cont_p = sc.contingency_pct if sc.contingency_pct is not None else pkg.contingency_pct
        oh_p = sc.overhead_pct if sc.overhead_pct is not None else pkg.overhead_pct
        prof_p = sc.profit_pct if sc.profit_pct is not None else pkg.profit_pct
        res = compute_13_buckets(
            material_net_cost=sc_mat,
            labor_cost=sc_lab,
            equipment_cost=sc_eqp,
            subcontractor_cost=other_split["subcontractor_cost"],
            freight_cost=other_split["freight_cost"],
            mobilization_cost=other_split["mobilization_cost"],
            permits_and_other_cost=other_split["permits_and_other_cost"],
            waste_allowance=waste_val,
            contingency_pct=cont_p,
            overhead_pct=oh_p,
            profit_pct=prof_p,
            profit_mode=profit_mode,
            sales_tax_pct=sales_tax_pct,
            rounding=pkg.rounding,
            indirect_calc_mode="sequential",
        )
        sc_price = Decimal(res["buckets"]["13_final_bid_price"])
        delta = _cash(sc_price - expected_price)
        scenario_rows.append({
            "scenario": sc.name,
            "description": sc.description,
            "assumptions": {
                "material_factor": str(sc.material_factor),
                "labor_hours_factor": str(sc.labor_hours_factor),
                "equipment_factor": str(sc.equipment_factor),
                "contingency_pct": str(cont_p),
                "overhead_pct": str(oh_p),
                "profit_pct": str(prof_p),
            },
            "direct_cost": res["buckets"]["9_direct_cost"],
            "final_bid_price": str(sc_price),
            "delta_vs_expected": str(delta),
            "achieved_margin_pct": res["achieved_margin_pct"],
            "achieved_markup_pct": res["achieved_markup_pct"],
        })

    return {
        "estimate_id": pkg.estimate_id,
        "legacy_total": str(legacy["price"]),
        "breakdown_13": base_13,
        "scenarios": scenario_rows,
    }
