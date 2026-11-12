"""ALKAN estimation methodology — configurable, trade-agnostic, multi-client.

Encodes the practices used across all Alkan clients (S&S Custom Iron Works,
The Fabricator, P.J. Roofing, Diaz Finish Carpenter, Green State Insulation,
JC Granite Design, Alvarez Landscaping, etc.) into reusable calculation and
document-generation rules.

This module is deliberately separate from the S&S-specific ``lumpsum_cost``
and ``metal_scope`` modules.  It never invents a price, a rate or a quantity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .estimator_v1 import _cash, _decimal, _fmt

# ──────────────────────────────────────────────────────────────────── constants

WA_STATE_TAX = Decimal("6.5")  # base; city/county on top

# Verified tax rates for Alkan's operating counties (WA DOR, as of 2026).
# The engine NEVER defaults to one of these; it requires the user to confirm.
WA_JURISDICTION_TAXES: dict[str, Decimal] = {
    "seattle":          Decimal("10.35"),
    "bellevue":         Decimal("10.20"),
    "kent":             Decimal("10.20"),
    "federal_way":      Decimal("10.20"),
    "tacoma":           Decimal("10.30"),
    "lakewood":         Decimal("10.20"),
    "olympia":          Decimal("9.80"),
    "everett":          Decimal("9.90"),
    "monroe":           Decimal("9.00"),
    "snohomish_unincorp": Decimal("8.70"),
    "bainbridge_island": Decimal("9.30"),
    "mountlake_terrace": Decimal("10.50"),
    "king_county_unincorp": Decimal("10.00"),
    "pierce_county_unincorp": Decimal("8.10"),
    "snohomish_county_unincorp": Decimal("8.70"),
    "kitsap_county_unincorp": Decimal("9.20"),
}

# Trade-specific labor categories for prevailing wage lookups.
TRADES: dict[str, dict[str, str]] = {
    "ironworker": {"l_and_i_class": "Ironworker", "default_unit": "HR"},
    "laborer_welder": {"l_and_i_class": "Laborer (Welder)", "default_unit": "HR"},
    "roofer": {"l_and_i_class": "Roofer", "default_unit": "HR"},
    "carpenter": {"l_and_i_class": "Carpenter", "default_unit": "HR"},
    "laborer": {"l_and_i_class": "Laborer", "default_unit": "HR"},
    "insulator": {"l_and_i_class": "Insulator (Heat and Frost)", "default_unit": "HR"},
    "painter": {"l_and_i_class": "Painter", "default_unit": "HR"},
    "electrician": {"l_and_i_class": "Electrician (Inside Wireman)", "default_unit": "HR"},
    "plumber": {"l_and_i_class": "Plumber", "default_unit": "HR"},
    "operator": {"l_and_i_class": "Operating Engineer", "default_unit": "HR"},
    "glazier": {"l_and_i_class": "Glazier", "default_unit": "HR"},
    "stone_mason": {"l_and_i_class": "Bricklayer (includes Stone Mason)", "default_unit": "HR"},
    "concrete_finisher": {"l_and_i_class": "Cement Mason", "default_unit": "HR"},
    "landscaper": {"l_and_i_class": "Landscape Construction Worker", "default_unit": "HR"},
    "fence_erector": {"l_and_i_class": "Fence Erector", "default_unit": "HR"},
}

# Default waste factors by material type (Alkan empirical, adjustable per job).
WASTE_DEFAULTS: dict[str, Decimal] = {
    "roofing_shingles":   Decimal("12"),
    "roofing_flat":       Decimal("8"),
    "underlayment":       Decimal("10"),
    "metal_fabrication":  Decimal("5"),
    "steel_structural":   Decimal("3"),
    "chain_link_fabric":  Decimal("5"),
    "concrete":           Decimal("5"),
    "aggregate":          Decimal("10"),
    "lumber":             Decimal("8"),
    "insulation_batt":    Decimal("5"),
    "insulation_blown":   Decimal("3"),
    "drywall":            Decimal("10"),
    "paint":              Decimal("10"),
    "siding_hardie":      Decimal("10"),
    "tile_stone":         Decimal("10"),
    "pipe_conduit":       Decimal("3"),
    "general":            Decimal("5"),
}

# Estimate tiers — each with a different precision and purpose.
TIERS = {
    "budgetary":    {"precision": "±25–30%", "purpose": "Order-of-magnitude for go/no-go decisions"},
    "competitive":  {"precision": "±10–15%", "purpose": "Bid submission or client proposal"},
    "detailed":     {"precision": "±5%",     "purpose": "Contract-ready, fully documented"},
}

# Pricing methods.
PRICING_METHODS = ("margin", "markup")

# Relationship types that affect O&P and document labeling.
RELATIONSHIPS = {
    "prime_to_owner":    {"label": "Prime contractor → Owner",       "default_op_pct": Decimal("15")},
    "sub_to_gc":         {"label": "Subcontractor → GC",            "default_op_pct": Decimal("15")},
    "sub_to_sub":        {"label": "Sub-subcontractor → Sub",       "default_op_pct": Decimal("10")},
    "gc_to_owner":       {"label": "General contractor → Owner",    "default_op_pct": Decimal("20")},
    "direct_homeowner":  {"label": "Contractor → Homeowner",        "default_op_pct": Decimal("25")},
    "cost_plus":         {"label": "Cost + fee",                    "default_op_pct": Decimal("0")},
}


# ──────────────────────────────────────────────────────────────── data classes

@dataclass
class LaborRate:
    """A single labor rate with its basis and source."""
    trade: str
    base_rate: Decimal
    fringe: Decimal = Decimal("0")
    county: str = ""
    prevailing_wage: bool = False
    effective_date: str = ""
    source: str = ""

    @property
    def total_rate(self) -> Decimal:
        return self.base_rate + self.fringe

    def validate(self) -> list[str]:
        issues = []
        if self.trade not in TRADES:
            issues.append(f"Trade '{self.trade}' not in registry; verify L&I classification")
        if self.base_rate <= 0:
            issues.append("Base rate must be positive")
        if self.prevailing_wage and not self.county:
            issues.append("Prevailing wage requires county for rate determination")
        if self.prevailing_wage and not self.source:
            issues.append("Prevailing wage rate requires L&I source reference")
        return issues


@dataclass
class ScopeItem:
    """One line item in the estimate."""
    id: str
    description: str
    trade: str
    category: str  # material, labor, equipment, subcontract, logistics, other
    quantity: Decimal | None = None
    unit: str = ""
    quantity_status: str = "PENDING"  # PENDING, MEASURED, CONFIRMED
    quantity_source: str = ""
    specification: str = ""
    waste_pct: Decimal | None = None
    unit_cost: Decimal | None = None
    cost_source: str = ""
    shop_hours: Decimal | None = None
    field_hours: Decimal | None = None
    labor_rate: LaborRate | None = None
    notes: str = ""

    @property
    def waste_factor(self) -> Decimal:
        if self.waste_pct is not None:
            return self.waste_pct
        # Look up default by trade/material type, fall back to general.
        return WASTE_DEFAULTS.get(self.trade, WASTE_DEFAULTS["general"])

    @property
    def adjusted_quantity(self) -> Decimal | None:
        if self.quantity is None:
            return None
        return _cash(self.quantity * (1 + self.waste_factor / 100))

    @property
    def material_cost(self) -> Decimal | None:
        if self.category != "material" or self.adjusted_quantity is None or self.unit_cost is None:
            return None
        return _cash(self.adjusted_quantity * self.unit_cost)

    @property
    def labor_cost(self) -> Decimal | None:
        if self.category != "labor":
            return None
        hours = (self.shop_hours or Decimal(0)) + (self.field_hours or Decimal(0))
        if hours <= 0 or self.labor_rate is None:
            return None
        return _cash(hours * self.labor_rate.total_rate)

    @property
    def line_cost(self) -> Decimal | None:
        if self.category == "material":
            return self.material_cost
        if self.category == "labor":
            return self.labor_cost
        # equipment, subcontract, logistics, other: flat cost from unit_cost × quantity
        if self.quantity is not None and self.unit_cost is not None:
            return _cash(self.quantity * self.unit_cost)
        return None

    def validate(self) -> list[str]:
        issues = []
        if self.quantity_status != "CONFIRMED":
            issues.append(f"{self.id}: Quantity not confirmed ({self.quantity_status})")
        if self.quantity is None:
            issues.append(f"{self.id}: Quantity missing")
        if self.category == "material" and self.unit_cost is None:
            issues.append(f"{self.id}: Material unit cost missing")
        if self.category == "labor" and self.labor_rate is None:
            issues.append(f"{self.id}: Labor rate missing")
        if self.category == "labor" and (self.shop_hours or Decimal(0)) + (self.field_hours or Decimal(0)) <= 0:
            issues.append(f"{self.id}: No labor hours")
        return issues


@dataclass
class EstimateConfig:
    """Job-level configuration for one estimate."""
    estimate_id: str
    project_name: str
    contractor_name: str
    contractor_license: str = ""
    contractor_address: str = ""
    contractor_phone: str = ""
    client_name: str = ""
    project_address: str = ""
    jurisdiction: str = ""  # key into WA_JURISDICTION_TAXES
    county: str = ""
    relationship: str = "sub_to_gc"
    tier: str = "competitive"
    pricing_method: str = "margin"  # margin or markup
    prevailing_wage: bool = False
    tax_rate: Decimal | None = None  # confirmed tax rate (overrides jurisdiction lookup)
    tax_confirmed: bool = False
    overhead_pct: Decimal = Decimal("10")
    contingency_pct: Decimal = Decimal("5")
    target_margin_pct: Decimal = Decimal("15")  # for margin method
    markup_pct: Decimal | None = None  # for markup method (e.g. 15% O&P)
    mobilization: Decimal | None = None
    mobilization_source: str = ""
    estimator: str = ""
    date: str = ""
    valid_until: str = ""

    def effective_tax_rate(self) -> Decimal | None:
        """Resolve tax: explicit override > jurisdiction lookup > None (blocked)."""
        if self.tax_confirmed and self.tax_rate is not None:
            return self.tax_rate
        return WA_JURISDICTION_TAXES.get(self.jurisdiction.lower().replace(" ", "_"))

    def relationship_label(self) -> str:
        return RELATIONSHIPS.get(self.relationship, {}).get("label", self.relationship)

    def validate(self) -> list[str]:
        issues = []
        if not self.estimate_id:
            issues.append("estimate_id required")
        if not self.project_name:
            issues.append("project_name required")
        if not self.contractor_name:
            issues.append("contractor_name required")
        if self.relationship not in RELATIONSHIPS:
            issues.append(f"Unknown relationship: {self.relationship}")
        if self.tier not in TIERS:
            issues.append(f"Unknown tier: {self.tier}")
        if self.pricing_method not in PRICING_METHODS:
            issues.append(f"Unknown pricing method: {self.pricing_method}")
        if self.prevailing_wage and not self.county:
            issues.append("Prevailing wage requires county")
        if not self.tax_confirmed and self.effective_tax_rate() is None:
            issues.append(f"Tax rate not confirmed and jurisdiction '{self.jurisdiction}' not in registry")
        return issues


# ──────────────────────────────────────────────────────────────── calculation

def calculate_estimate(config: EstimateConfig, items: list[ScopeItem]) -> dict:
    """Pure calculation from validated inputs. Never assumes or invents."""
    config_issues = config.validate()
    item_issues = []
    for item in items:
        item_issues.extend(item.validate())

    all_issues = config_issues + item_issues
    complete = not all_issues

    # Subtotals by category.
    material_total = Decimal(0)
    labor_total = Decimal(0)
    equipment_total = Decimal(0)
    subcontract_total = Decimal(0)
    other_total = Decimal(0)
    lines = []

    for item in items:
        cost = item.line_cost
        if cost is not None and not item.validate():
            if item.category == "material":
                material_total += cost
            elif item.category == "labor":
                labor_total += cost
            elif item.category == "equipment":
                equipment_total += cost
            elif item.category == "subcontract":
                subcontract_total += cost
            else:
                other_total += cost

        lines.append({
            "id": item.id,
            "description": item.description,
            "trade": item.trade,
            "category": item.category,
            "quantity": str(item.quantity) if item.quantity is not None else None,
            "adjusted_quantity": str(item.adjusted_quantity) if item.adjusted_quantity is not None else None,
            "unit": item.unit,
            "waste_pct": str(item.waste_factor),
            "unit_cost": _fmt(item.unit_cost) if item.unit_cost is not None else None,
            "shop_hours": str(item.shop_hours) if item.shop_hours else None,
            "field_hours": str(item.field_hours) if item.field_hours else None,
            "labor_rate": str(item.labor_rate.total_rate) if item.labor_rate else None,
            "line_cost": _fmt(cost),
            "status": "COSTED" if cost is not None and not item.validate() else "BLOCKED",
            "issues": item.validate(),
        })

    direct_cost = material_total + labor_total + equipment_total + subcontract_total + other_total
    mobilization = _decimal(config.mobilization, "mobilization") if config.mobilization else Decimal(0)
    subtotal_before_markup = direct_cost + mobilization

    # Pricing depends on method.
    if config.pricing_method == "markup" and config.markup_pct is not None:
        markup = _cash(subtotal_before_markup * config.markup_pct / 100)
        overhead = Decimal(0)
        contingency = Decimal(0)
        selling_price = subtotal_before_markup + markup
        gross_profit = markup
    else:
        overhead = _cash(direct_cost * config.overhead_pct / 100)
        contingency = _cash(direct_cost * config.contingency_pct / 100)
        all_in_cost = subtotal_before_markup + overhead + contingency
        if config.target_margin_pct >= 100:
            selling_price = None
            gross_profit = None
        else:
            selling_price = _cash(all_in_cost / (1 - config.target_margin_pct / 100))
            gross_profit = selling_price - all_in_cost if selling_price else None
        markup = None

    # Tax.
    tax_rate = config.effective_tax_rate()
    tax_amount = _cash(selling_price * tax_rate / 100) if selling_price and tax_rate and config.tax_confirmed else None
    total_with_tax = _cash(selling_price + tax_amount) if selling_price and tax_amount is not None else None

    # Stress test: material +5%.
    stress = {}
    if complete and selling_price:
        for pct in (Decimal("3"), Decimal("5"), Decimal("10")):
            extra = _cash(material_total * pct / 100)
            stress[f"material_plus_{pct}%"] = {
                "additional_cost": _fmt(extra),
                "margin_impact": _fmt(gross_profit - extra) if gross_profit else None,
            }

    return {
        "alkan_method_version": "1.0.0",
        "estimate_id": config.estimate_id,
        "project_name": config.project_name,
        "contractor": config.contractor_name,
        "client": config.client_name,
        "relationship": config.relationship_label(),
        "tier": config.tier,
        "tier_precision": TIERS[config.tier]["precision"] if config.tier in TIERS else None,
        "pricing_method": config.pricing_method,
        "prevailing_wage": config.prevailing_wage,
        "status": "READY_FOR_REVIEW" if complete else "BLOCKED",
        "blockers": all_issues,
        "lines": lines,
        "totals": {
            "material": _fmt(material_total),
            "labor": _fmt(labor_total),
            "equipment": _fmt(equipment_total),
            "subcontract": _fmt(subcontract_total),
            "other": _fmt(other_total),
            "direct_cost": _fmt(direct_cost),
            "mobilization": _fmt(mobilization),
            "subtotal_before_markup": _fmt(subtotal_before_markup),
            "overhead": _fmt(overhead) if overhead else None,
            "contingency": _fmt(contingency) if contingency else None,
            "markup": _fmt(markup) if markup is not None else None,
            "selling_price_before_tax": _fmt(selling_price),
            "gross_profit": _fmt(gross_profit),
            "tax_rate": str(tax_rate) + "%" if tax_rate else None,
            "tax_amount": _fmt(tax_amount),
            "total_with_tax": _fmt(total_with_tax),
        },
        "stress_test": stress,
        "notes": [
            "No equivale a oferta aprobada, contrato ni autorización de compra.",
            "Cantidades y precios sujetos a validación por profesional responsable.",
            f"Precisión declarada: {TIERS.get(config.tier, {}).get('precision', 'N/A')}.",
        ],
        "validation_note": "Quantities and prices subject to validation by responsible engineer, architect or estimator before contracting or bidding.",
    }


# ──────────────────────────────────────────────── Alkan commission calculator

@dataclass
class AlkanCommission:
    """Alkan's standard commission structure per the services agreements."""
    gross_sale: Decimal
    find_estimate_pct: Decimal = Decimal("3")
    coordination_pct: Decimal = Decimal("3")
    coordination_included: bool = False

    @property
    def find_estimate_fee(self) -> Decimal:
        return _cash(self.gross_sale * self.find_estimate_pct / 100)

    @property
    def coordination_fee(self) -> Decimal:
        if not self.coordination_included:
            return Decimal(0)
        return _cash(self.gross_sale * self.coordination_pct / 100)

    @property
    def total_fee(self) -> Decimal:
        return self.find_estimate_fee + self.coordination_fee

    def schedule(self) -> dict:
        """Payment schedule: 50% at contract signing, 50% on first payment."""
        half = _cash(self.total_fee / 2)
        return {
            "total_commission": _fmt(self.total_fee),
            "at_contract_signing": _fmt(half),
            "on_first_payment": _fmt(self.total_fee - half),
            "find_estimate_fee": _fmt(self.find_estimate_fee),
            "coordination_fee": _fmt(self.coordination_fee) if self.coordination_included else None,
        }


# ──────────────────────────────────────────── mobilization estimator

def estimate_mobilization(
    distance_miles: Decimal,
    crew_size: int,
    trips: int = 2,
    truck_rate_per_mile: Decimal = Decimal("1.50"),
    crew_travel_rate: Decimal = Decimal("45"),
    equipment_delivery: Decimal = Decimal("0"),
) -> dict:
    """Mobilization cost estimate based on distance and crew."""
    travel_time_hrs = _cash(distance_miles / 35)  # ~35 mph average with equipment
    truck_cost = _cash(distance_miles * truck_rate_per_mile * trips)
    crew_travel_cost = _cash(travel_time_hrs * crew_size * crew_travel_rate * trips)
    total = truck_cost + crew_travel_cost + _decimal(equipment_delivery, "equipment_delivery")
    return {
        "distance_miles": str(distance_miles),
        "trips": trips,
        "crew_size": crew_size,
        "travel_time_hours_each_way": str(travel_time_hrs),
        "truck_cost": _fmt(truck_cost),
        "crew_travel_cost": _fmt(crew_travel_cost),
        "equipment_delivery": _fmt(_decimal(equipment_delivery, "equipment_delivery")),
        "total_mobilization": _fmt(total),
    }


# ───────────────────────────────────────── consumables estimator (metal fab)

def estimate_consumables(
    welding_hours: Decimal,
    rod_rate: Decimal = Decimal("8"),    # $/hr welding
    gas_rate: Decimal = Decimal("5"),    # $/hr welding
    grinding_rate: Decimal = Decimal("3"),  # $/hr
    paint_gallons: Decimal = Decimal("0"),
    paint_cost_per_gallon: Decimal = Decimal("45"),
) -> dict:
    """Consumables lump sum based on welding hours and finishing."""
    welding_consumables = _cash(welding_hours * (rod_rate + gas_rate + grinding_rate))
    paint_cost = _cash(paint_gallons * paint_cost_per_gallon)
    return {
        "welding_hours": str(welding_hours),
        "welding_consumables": _fmt(welding_consumables),
        "paint_cost": _fmt(paint_cost),
        "total_consumables": _fmt(welding_consumables + paint_cost),
    }
