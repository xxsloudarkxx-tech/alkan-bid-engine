"""ALKAN estimation methodology — configurable, trade-agnostic, multi-client.

Encodes the practices used across Alkan contractor clients into reusable
calculation, pre-estimation, supplier-quote matching, and document-generation rules.

This module is deliberately separate from the ``lumpsum_cost`` and ``metal_scope``
modules. It never invents a contractor identity, price, rate or quantity.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from typing import Any, Literal

from .contractor import ContractorIdentity, load_contractor_identity
from .estimator_v1 import _cash, _decimal, _fmt

# ──────────────────────────────────────────────────────────────────── constants

PROJECT_STATES: tuple[str, ...] = ("preestimado", "ajustado", "final")
BASE_MARKUP = Decimal("0.20")  # 20% overhead + profit base markup for preestimates

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
    "drywall_applicator": {"l_and_i_class": "Drywall Applicator", "default_unit": "HR"},
    "drywall_taper": {"l_and_i_class": "Drywall Tapers", "default_unit": "HR"},
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
class QuoteLineItem:
    """Single line item from a supplier quotation."""
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    total: Decimal
    matches_scope_item_id: str | None = None  # vínculo con el item del takeoff


@dataclass
class SupplierQuote:
    """Supplier quotation record with optional line-item links to scope items."""
    supplier_name: str              # "Farwest", "ABC Supply", "Conway", "Home Depot"...
    quote_number: str | None = None
    quote_date: date | None = None
    line_items: list[QuoteLineItem] = field(default_factory=list)
    file_path: str | None = None    # PDF o imagen de la cotización
    is_verified: bool = False


@dataclass
class ScopeItem:
    """One line item in the estimate."""
    id: str
    description: str
    trade: str = "general"
    category: str = "material"  # material, labor, equipment, subcontract, logistics, other
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
    pricing_source: Literal["supplier_quote", "reference", "pending"] = "pending"
    supplier_quote_id: str | None = None
    reference_price: Decimal | None = None
    final_unit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.final_unit_price is not None and self.unit_cost is None:
            self.unit_cost = self.final_unit_price
        elif self.unit_cost is not None and self.final_unit_price is None:
            self.final_unit_price = self.unit_cost
        elif self.unit_cost is None and self.final_unit_price is None and self.reference_price is not None:
            self.final_unit_price = self.reference_price
            self.unit_cost = self.reference_price
            if self.pricing_source == "pending":
                self.pricing_source = "reference"

    @property
    def effective_unit_price(self) -> Decimal | None:
        if self.final_unit_price is not None:
            return self.final_unit_price
        if self.unit_cost is not None:
            return self.unit_cost
        return self.reference_price

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
        price = self.effective_unit_price
        if self.category != "material" or self.adjusted_quantity is None or price is None:
            return None
        return _cash(self.adjusted_quantity * price)

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
        price = self.effective_unit_price
        if self.quantity is not None and price is not None:
            return _cash(self.quantity * price)
        return None

    def validate(self) -> list[str]:
        issues = []
        if self.quantity_status != "CONFIRMED":
            issues.append(f"{self.id}: Quantity not confirmed ({self.quantity_status})")
        if self.quantity is None:
            issues.append(f"{self.id}: Quantity missing")
        if self.category == "material" and self.effective_unit_price is None:
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


# ─────────────────────── 3-state preestimate → ajustado → final workflow

COUNTY_PW_RATES: dict[str, Decimal] = {
    "king": Decimal("95.00"),
    "pierce": Decimal("92.00"),
    "snohomish": Decimal("93.00"),
    "kitsap": Decimal("90.00"),
    "thurston": Decimal("89.00"),
}
DEFAULT_PW_RATE = Decimal("90.00")
DEFAULT_STANDARD_LABOR_RATE = Decimal("65.00")
DISTANCE_RATE_PER_MILE = Decimal("6.00")
CLIENT_TYPE_FACTORS: dict[str, Decimal] = {
    "gc": Decimal("0.00"),
    "owner": Decimal("0.03"),
}


@dataclass
class ProjectEstimate:
    """Three-stage project estimate record: 'preestimado' -> 'ajustado' -> 'final'."""

    project_id: str
    name: str
    status: Literal["preestimado", "ajustado", "final"]

    # Del preestimado (IA)
    scope_items: list[ScopeItem]
    materials: list[ScopeItem]
    preliminary_hours: Decimal
    base_price: Decimal          # con 20% markup
    supplier_quotes_used: list[str]

    # Del contratista (se llena después)
    confirmed_hours: Decimal | None = None
    contractor_markup_pct: Decimal | None = None
    final_price: Decimal | None = None

    # Metadata
    county: str = "TO_BE_FILLED"
    is_prevailing_wage: bool = False
    distance_miles: float | None = None
    client_type: Literal["gc", "owner"] = "gc"

    # Control de horas preliminares, cotizaciones pendientes y desglose
    preliminary_hours_status: Literal["pending_confirmation", "confirmed"] = "pending_confirmation"
    needs_quote_items: list[str] = field(default_factory=list)
    labor_rate: Decimal = DEFAULT_STANDARD_LABOR_RATE
    breakdown: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in PROJECT_STATES:
            raise ValueError(f"Estado inválido '{self.status}'. Estados permitidos: {PROJECT_STATES}")
        if self.client_type not in ("gc", "owner"):
            raise ValueError(f"client_type inválido '{self.client_type}'. Use 'gc' o 'owner'.")

    @property
    def visible_price(self) -> Decimal:
        """El precio siempre es visible en pantalla sin necesidad de generar PDFs."""
        return self.final_price if self.final_price is not None else self.base_price

    @property
    def display_price(self) -> Decimal:
        """Alias de visible_price para visualización en UI/CLI."""
        return self.visible_price

    def screen_summary(self) -> dict[str, Any]:
        """Devuelve la vista en pantalla del estimado sin requerir generación de PDFs."""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "visible_price": _fmt(self.visible_price),
            "base_price": _fmt(self.base_price),
            "final_price": _fmt(self.final_price) if self.final_price is not None else None,
            "preliminary_hours": str(self.preliminary_hours),
            "preliminary_hours_status": self.preliminary_hours_status,
            "confirmed_hours": str(self.confirmed_hours) if self.confirmed_hours is not None else None,
            "contractor_markup_pct": str(self.contractor_markup_pct) if self.contractor_markup_pct is not None else None,
            "supplier_quotes_used": list(self.supplier_quotes_used),
            "needs_quote_items": list(self.needs_quote_items),
            "county": self.county,
            "is_prevailing_wage": self.is_prevailing_wage,
            "distance_miles": self.distance_miles,
            "client_type": self.client_type,
            "pdf_generation_enabled": self.status == "final",
            "breakdown": self.breakdown,
        }

    def transition_to(self, target_status: Literal["preestimado", "ajustado", "final"]) -> ProjectEstimate:
        """Cambia el estado del proyecto validando las reglas del flujo."""
        return transition_project_state(self, target_status)

    def mark_final(self) -> ProjectEstimate:
        """Pasa el proyecto a estado 'final' para habilitar la generación de los 3 PDFs."""
        return finalize_project_estimate(self)

    def generate_pdfs(
        self,
        out_dir: str | Path,
        contractor: ContractorIdentity | dict[str, Any] | str | None = None,
    ) -> dict[str, Path]:
        """Genera los 3 PDFs (Cost Analysis, Material List, Proposal) SOLO si status == 'final'."""
        return generate_project_pdfs(self, out_dir, contractor=contractor)


def _coerce_scope_item(item: ScopeItem | dict[str, Any], index: int = 1) -> ScopeItem:
    if isinstance(item, ScopeItem):
        return item
    if not isinstance(item, dict):
        raise TypeError(f"ScopeItem inválido: {item!r}")
    qty = Decimal(str(item["quantity"])) if item.get("quantity") is not None else None
    ref_price = Decimal(str(item["reference_price"])) if item.get("reference_price") is not None else None
    unit_cost = Decimal(str(item["unit_cost"])) if item.get("unit_cost") is not None else None
    final_price = Decimal(str(item["final_unit_price"])) if item.get("final_unit_price") is not None else None
    waste_pct = Decimal(str(item["waste_pct"])) if item.get("waste_pct") is not None else None
    shop_hrs = Decimal(str(item["shop_hours"])) if item.get("shop_hours") is not None else None
    field_hrs = Decimal(str(item["field_hours"])) if item.get("field_hours") is not None else None
    return ScopeItem(
        id=str(item.get("id") or f"ITEM-{index:03d}"),
        description=str(item.get("description") or item.get("item") or "TO_BE_FILLED"),
        trade=str(item.get("trade") or "general"),
        category=str(item.get("category") or "material"),
        quantity=qty,
        unit=str(item.get("unit") or "EA"),
        quantity_status=str(item.get("quantity_status") or ("CONFIRMED" if qty is not None else "PENDING")),
        quantity_source=str(item.get("quantity_source") or "Planos"),
        specification=str(item.get("specification") or item.get("spec") or ""),
        waste_pct=waste_pct,
        unit_cost=unit_cost,
        cost_source=str(item.get("cost_source") or ""),
        shop_hours=shop_hrs,
        field_hours=field_hrs,
        notes=str(item.get("notes") or ""),
        pricing_source=item.get("pricing_source", "pending"),
        supplier_quote_id=item.get("supplier_quote_id"),
        reference_price=ref_price,
        final_unit_price=final_price,
    )


def _coerce_supplier_quote(quote: SupplierQuote | dict[str, Any]) -> SupplierQuote:
    if isinstance(quote, SupplierQuote):
        return quote
    if not isinstance(quote, dict):
        raise TypeError(f"SupplierQuote inválido: {quote!r}")
    lines = []
    for li in quote.get("line_items", []):
        if isinstance(li, QuoteLineItem):
            lines.append(li)
        elif isinstance(li, dict):
            qty = Decimal(str(li.get("quantity", "1")))
            up = Decimal(str(li.get("unit_price", "0")))
            tot = Decimal(str(li["total"])) if li.get("total") is not None else _cash(qty * up)
            lines.append(
                QuoteLineItem(
                    description=str(li.get("description") or ""),
                    quantity=qty,
                    unit=str(li.get("unit") or "EA"),
                    unit_price=up,
                    total=tot,
                    matches_scope_item_id=li.get("matches_scope_item_id"),
                )
            )
    qdate = quote.get("quote_date")
    if isinstance(qdate, str) and qdate:
        qdate = date.fromisoformat(qdate)
    return SupplierQuote(
        supplier_name=str(quote.get("supplier_name") or "TO_BE_FILLED"),
        quote_number=quote.get("quote_number"),
        quote_date=qdate,
        line_items=lines,
        file_path=quote.get("file_path"),
        is_verified=bool(quote.get("is_verified", False)),
    )


def _match_quote_line(item: ScopeItem, quotes: list[SupplierQuote]) -> tuple[SupplierQuote, QuoteLineItem] | None:
    """Finds a matching QuoteLineItem by scope item ID first, then by normalized description."""
    norm_desc = item.description.strip().lower()
    for q in quotes:
        for li in q.line_items:
            if li.matches_scope_item_id and li.matches_scope_item_id == item.id:
                return q, li
    for q in quotes:
        for li in q.line_items:
            if norm_desc and li.description.strip().lower() == norm_desc:
                return q, li
    return None


def _resolve_hourly_rate(county: str, is_prevailing_wage: bool, explicit_rate: Decimal | str | None = None) -> Decimal:
    if explicit_rate is not None:
        return Decimal(str(explicit_rate))
    if is_prevailing_wage:
        key = (county or "").strip().lower().replace(" county", "")
        return COUNTY_PW_RATES.get(key, DEFAULT_PW_RATE)
    return DEFAULT_STANDARD_LABOR_RATE


def _compute_project_totals(
    scope_items: list[ScopeItem],
    materials: list[ScopeItem],
    hours: Decimal,
    labor_rate: Decimal,
    distance_miles: float | Decimal | None,
    client_type: Literal["gc", "owner"],
    markup_ratio: Decimal,
) -> tuple[Decimal, dict[str, Any]]:
    """Calculates direct cost, variable adjustments, and total price with markup."""
    # Avoid double-counting if the same ScopeItem instance is in both scope_items and materials.
    seen_ids: set[str] = set()
    material_cost = Decimal("0.00")
    other_scope_cost = Decimal("0.00")

    for item in [*materials, *scope_items]:
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        price = item.effective_unit_price
        qty = item.quantity
        if price is None or qty is None:
            continue
        if item.category == "material":
            # Use raw qty * final_unit_price if waste_pct was explicitly 0, or item.quantity * price
            # If waste_pct is explicitly set on the item, use adjusted_quantity; otherwise qty * price.
            eff_qty = item.adjusted_quantity if item.waste_pct is not None else qty
            material_cost += _cash(eff_qty * price)
        elif item.category != "labor":
            other_scope_cost += _cash(qty * price)

    labor_cost = _cash(hours * labor_rate)
    dist_dec = Decimal(str(distance_miles)) if distance_miles is not None and float(distance_miles) > 0 else Decimal("0")
    distance_cost = _cash(dist_dec * DISTANCE_RATE_PER_MILE)
    base_direct = _cash(material_cost + labor_cost + other_scope_cost + distance_cost)

    client_factor = CLIENT_TYPE_FACTORS.get(client_type, Decimal("0.00"))
    client_adjustment = _cash(base_direct * client_factor)
    adjusted_direct = _cash(base_direct + client_adjustment)

    markup_amount = _cash(adjusted_direct * markup_ratio)
    total_price = _cash(adjusted_direct + markup_amount)

    breakdown = {
        "materials_cost": _fmt(material_cost),
        "labor_hours": str(hours),
        "labor_rate": _fmt(labor_rate),
        "labor_cost": _fmt(labor_cost),
        "other_scope_cost": _fmt(other_scope_cost),
        "distance_cost": _fmt(distance_cost),
        "client_adjustment": _fmt(client_adjustment),
        "direct_cost": _fmt(adjusted_direct),
        "markup_ratio": str(markup_ratio),
        "markup_amount": _fmt(markup_amount),
        "total_price": _fmt(total_price),
    }
    return total_price, breakdown


def _save_project_estimate(project: ProjectEstimate, db_path: str | Path | None) -> None:
    if db_path is None:
        return
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except json.JSONDecodeError:
            existing = {}
    existing[project.project_id] = project.screen_summary()
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def calculate_preestimate(
    project_id: str = "PRE-001",
    name: str = "TO_BE_FILLED",
    scope_items: list[ScopeItem | dict[str, Any]] | None = None,
    materials: list[ScopeItem | dict[str, Any]] | None = None,
    preliminary_hours: Decimal | int | str = Decimal("0"),
    supplier_quotes: list[SupplierQuote | dict[str, Any]] | None = None,
    *,
    county: str = "TO_BE_FILLED",
    is_prevailing_wage: bool = False,
    distance_miles: float | Decimal | None = None,
    client_type: Literal["gc", "owner"] = "gc",
    labor_rate: Decimal | str | None = None,
    db_path: str | Path | None = None,
) -> ProjectEstimate:
    """Genera automáticamente el preestimado desde planos con estado = 'preestimado'.

    1. Scope + materiales desde planos.
    2. Aplica cotizaciones de proveedor cuando existan; de lo contrario usa precio
       de referencia (pricing_source='reference') y agrega el ítem a needs_quote_items.
    3. Registra horas preliminares marcadas como 'pending_confirmation'.
    4. Aplica ajustes por condado, prevailing wage, distancia y tipo de cliente.
    5. Aplica BASE_MARKUP del 20%.
    6. Guarda con status='preestimado' (sin generar PDFs; precio visible en pantalla).
    """
    raw_scope = [_coerce_scope_item(x, i) for i, x in enumerate(scope_items or [], 1)]
    if materials is not None:
        raw_materials = [_coerce_scope_item(x, i) for i, x in enumerate(materials, 1)]
    else:
        raw_materials = [item for item in raw_scope if item.category == "material"]

    quotes = [_coerce_supplier_quote(q) for q in (supplier_quotes or [])]
    quotes_used: list[str] = []
    needs_quote: list[str] = []

    all_items_by_id: dict[str, ScopeItem] = {}
    for item in [*raw_scope, *raw_materials]:
        all_items_by_id[item.id] = item

    for item in all_items_by_id.values():
        if item.category != "material":
            continue
        match = _match_quote_line(item, quotes)
        if match is not None:
            q, q_line = match
            qid = q.quote_number or q.supplier_name
            item.pricing_source = "supplier_quote"
            item.supplier_quote_id = qid
            item.final_unit_price = q_line.unit_price
            item.unit_cost = q_line.unit_price
            item.cost_source = f"{q.supplier_name}" + (f" #{q.quote_number}" if q.quote_number else "")
            if qid not in quotes_used:
                quotes_used.append(qid)
        else:
            ref = item.reference_price if item.reference_price is not None else item.unit_cost
            if ref is not None:
                item.reference_price = ref
                item.final_unit_price = ref
                item.unit_cost = ref
                item.pricing_source = "reference"
            else:
                item.pricing_source = "pending"
            if item.id not in needs_quote:
                needs_quote.append(item.id)

    prelim_hrs = Decimal(str(preliminary_hours))
    if prelim_hrs == Decimal("0"):
        prelim_hrs = sum(
            ((it.shop_hours or Decimal("0")) + (it.field_hours or Decimal("0")) for it in all_items_by_id.values()),
            Decimal("0"),
        )

    eff_labor_rate = _resolve_hourly_rate(county, is_prevailing_wage, labor_rate)
    base_price, breakdown = _compute_project_totals(
        scope_items=raw_scope,
        materials=raw_materials,
        hours=prelim_hrs,
        labor_rate=eff_labor_rate,
        distance_miles=distance_miles,
        client_type=client_type,
        markup_ratio=BASE_MARKUP,
    )

    project = ProjectEstimate(
        project_id=project_id,
        name=name,
        status="preestimado",
        scope_items=raw_scope,
        materials=raw_materials,
        preliminary_hours=prelim_hrs,
        base_price=base_price,
        supplier_quotes_used=quotes_used,
        confirmed_hours=None,
        contractor_markup_pct=None,
        final_price=None,
        county=county,
        is_prevailing_wage=is_prevailing_wage,
        distance_miles=float(distance_miles) if distance_miles is not None else None,
        client_type=client_type,
        preliminary_hours_status="pending_confirmation",
        needs_quote_items=needs_quote,
        labor_rate=eff_labor_rate,
        breakdown=breakdown,
    )
    _save_project_estimate(project, db_path)
    return project


def _normalize_markup_ratio(contractor_markup: Decimal | int | float | str) -> tuple[Decimal, Decimal]:
    """Returns (stored_pct_value, decimal_ratio)."""
    raw = Decimal(str(contractor_markup))
    if raw < 0:
        raise ValueError("contractor_markup no puede ser negativo")
    if raw <= Decimal("1"):
        return raw, raw
    return raw, raw / Decimal("100")


def apply_contractor_adjustment(
    project: ProjectEstimate,
    confirmed_hours: Decimal | int | float | str,
    contractor_markup: Decimal | int | float | str,
    *,
    db_path: str | Path | None = None,
) -> ProjectEstimate:
    """Recalcula el estimado con las horas reales y markup confirmados por el contratista.

    Actualiza únicamente ``confirmed_hours`` y ``contractor_markup_pct``, calcula
    ``final_price`` y cambia el estado a ``"ajustado"``.
    """
    hrs = Decimal(str(confirmed_hours))
    if hrs < 0:
        raise ValueError("confirmed_hours no puede ser negativo")
    stored_markup, markup_ratio = _normalize_markup_ratio(contractor_markup)

    final_price, breakdown = _compute_project_totals(
        scope_items=project.scope_items,
        materials=project.materials,
        hours=hrs,
        labor_rate=project.labor_rate,
        distance_miles=project.distance_miles,
        client_type=project.client_type,
        markup_ratio=markup_ratio,
    )

    project.confirmed_hours = hrs
    project.contractor_markup_pct = stored_markup
    project.final_price = final_price
    project.preliminary_hours_status = "confirmed"
    project.status = "ajustado"
    project.breakdown = breakdown
    _save_project_estimate(project, db_path)
    return project


def apply_supplier_quote(
    project: ProjectEstimate,
    quote: SupplierQuote | dict[str, Any],
    *,
    db_path: str | Path | None = None,
) -> ProjectEstimate:
    """Sube una cotización real de proveedor, reemplaza precios de referencia y actualiza totales."""
    q = _coerce_supplier_quote(quote)
    qid = q.quote_number or q.supplier_name

    all_items: dict[str, ScopeItem] = {}
    for item in [*project.scope_items, *project.materials]:
        all_items[item.id] = item

    matched_any = False
    for item in all_items.values():
        match = _match_quote_line(item, [q])
        if match is not None:
            _, q_line = match
            item.pricing_source = "supplier_quote"
            item.supplier_quote_id = qid
            item.final_unit_price = q_line.unit_price
            item.unit_cost = q_line.unit_price
            item.cost_source = f"{q.supplier_name}" + (f" #{q.quote_number}" if q.quote_number else "")
            if item.id in project.needs_quote_items:
                project.needs_quote_items.remove(item.id)
            matched_any = True

    if matched_any and qid not in project.supplier_quotes_used:
        project.supplier_quotes_used.append(qid)

    # Recalcular base_price
    base_price, base_breakdown = _compute_project_totals(
        scope_items=project.scope_items,
        materials=project.materials,
        hours=project.preliminary_hours,
        labor_rate=project.labor_rate,
        distance_miles=project.distance_miles,
        client_type=project.client_type,
        markup_ratio=BASE_MARKUP,
    )
    project.base_price = base_price

    # Si está en 'ajustado' o 'final' (o ya tiene horas y markup confirmados), actualizar final_price automáticamente
    if project.confirmed_hours is not None and project.contractor_markup_pct is not None:
        _, markup_ratio = _normalize_markup_ratio(project.contractor_markup_pct)
        final_price, adj_breakdown = _compute_project_totals(
            scope_items=project.scope_items,
            materials=project.materials,
            hours=project.confirmed_hours,
            labor_rate=project.labor_rate,
            distance_miles=project.distance_miles,
            client_type=project.client_type,
            markup_ratio=markup_ratio,
        )
        project.final_price = final_price
        project.breakdown = adj_breakdown
    else:
        project.breakdown = base_breakdown
        if project.status == "final":
            project.final_price = project.base_price

    _save_project_estimate(project, db_path)
    return project


def transition_project_state(
    project: ProjectEstimate,
    target_status: Literal["preestimado", "ajustado", "final"],
    *,
    db_path: str | Path | None = None,
) -> ProjectEstimate:
    """Gestiona el cambio de estado entre 'preestimado', 'ajustado' y 'final'."""
    if target_status not in PROJECT_STATES:
        raise ValueError(f"Estado inválido '{target_status}'. Estados permitidos: {PROJECT_STATES}")
    if target_status == "ajustado":
        if project.confirmed_hours is None or project.contractor_markup_pct is None:
            raise ValueError("Para pasar a 'ajustado' se requieren confirmed_hours y contractor_markup_pct.")
    if target_status == "final":
        if project.confirmed_hours is None or project.contractor_markup_pct is None:
            raise ValueError("Para pasar a 'final' primero deben confirmarse las horas y el markup del contratista.")
        if project.final_price is None:
            apply_contractor_adjustment(project, project.confirmed_hours, project.contractor_markup_pct)
    project.status = target_status
    _save_project_estimate(project, db_path)
    return project


def finalize_project_estimate(
    project: ProjectEstimate,
    *,
    db_path: str | Path | None = None,
) -> ProjectEstimate:
    """Pasa el proyecto a estado 'final' tras verificar que el ajuste del contratista está completo."""
    return transition_project_state(project, "final", db_path=db_path)


def generate_project_pdfs(
    project: ProjectEstimate,
    out_dir: str | Path,
    contractor: ContractorIdentity | dict[str, Any] | str | None = None,
) -> dict[str, Path]:
    """Genera los 3 PDFs (Cost Analysis, Material List, Proposal) SOLO cuando status == 'final'."""
    if project.status != "final":
        raise ValueError(
            f"Los 3 PDFs (Cost Analysis, Material List, Proposal) solo se generan cuando el estado es 'final' "
            f"(estado actual: '{project.status}')."
        )

    from .package_method import LaborLine, MaterialLine, OtherLine, Package, Rate, compute
    from .package_render import render_cost_analysis, render_material_list, render_proposal

    identity = load_contractor_identity(contractor)
    contractor_dict = {
        "name": identity.legal_name,
        "address": identity.format_full_location(),
        "license": f"Reg: {identity.contractor_registration} · UBI: {identity.wa_ubi}",
        "phone": "TO_BE_FILLED",
        "contact": identity.legal_name,
        "email": "",
    }

    mat_lines: list[MaterialLine] = []
    other_lines: list[OtherLine] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate([*project.materials, *project.scope_items], 1):
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        qty = item.quantity if item.quantity is not None and item.quantity > 0 else Decimal("1")
        price = item.effective_unit_price if item.effective_unit_price is not None else Decimal("0")
        if item.category == "material":
            basis = "QUOTE" if item.pricing_source == "supplier_quote" else "CATALOG"
            eff_qty = item.adjusted_quantity if (item.waste_pct is not None and item.adjusted_quantity) else qty
            mat_lines.append(
                MaterialLine(
                    id=item.id or f"M{idx:03d}",
                    section=item.trade or "Materials",
                    item=item.description,
                    spec=item.specification or "Per plans",
                    qty=eff_qty,
                    unit=item.unit or "EA",
                    unit_price=price,
                    price_basis=basis,
                    price_source=item.cost_source or item.supplier_quote_id or "Reference",
                    qty_source=item.quantity_source or "Plans",
                )
            )
        elif item.category != "labor" and price > 0:
            other_lines.append(
                OtherLine(
                    id=item.id or f"O{idx:03d}",
                    item=item.description,
                    category="Other",
                    qty=qty,
                    unit=item.unit or "LS",
                    rate=price,
                    source=item.quantity_source or "Plans",
                )
            )

    if not mat_lines:
        mat_lines.append(
            MaterialLine(
                id="M001",
                section="General",
                item="Materials per scope",
                spec="Per plans",
                qty=Decimal("1"),
                unit="LS",
                unit_price=Decimal("0"),
                price_basis="CATALOG",
                price_source="Reference",
                qty_source="Plans",
            )
        )

    if project.distance_miles and project.distance_miles > 0:
        dist_cost = _cash(Decimal(str(project.distance_miles)) * DISTANCE_RATE_PER_MILE)
        other_lines.append(
            OtherLine(
                id="MOB-001",
                item=f"Mobilization / distance ({project.distance_miles} mi)",
                category="Mobilization",
                qty=Decimal("1"),
                unit="LS",
                rate=dist_cost,
                source="Distance adjustment",
            )
        )

    hours = project.confirmed_hours if project.confirmed_hours is not None else project.preliminary_hours
    eff_hours = hours if hours > 0 else Decimal("1")
    rate_kind = "prevailing_wage" if project.is_prevailing_wage else "loaded"
    rates = {
        "CREW": Rate(
            key="CREW",
            label="Field / Shop Crew",
            kind=rate_kind,
            rate=project.labor_rate,
            burden_pct=Decimal("0"),
            trade="laborer",
            source=f"{project.county} L&I Prevailing Wage" if project.is_prevailing_wage else "Contractor loaded rate",
        )
    }
    labor_lines = [LaborLine(id="L001", task="Project installation & fabrication", rate_key="CREW", hours=eff_hours)]

    _, markup_ratio = _normalize_markup_ratio(
        project.contractor_markup_pct if project.contractor_markup_pct is not None else BASE_MARKUP
    )
    profit_pct = _cash(markup_ratio * Decimal("100"))

    pkg = Package(
        estimate_id=project.project_id,
        date=date.today().isoformat(),
        contractor=contractor_dict,
        project={
            "key": project.project_id,
            "title": project.name,
            "short": project.name[:40],
            "owner": "Owner / GC" if project.client_type == "gc" else "Property Owner",
            "site": project.county,
            "county": project.county,
            "documents": ["Project Drawings & Specifications"],
            "scope_label": "construction scope",
        },
        relationship="sub_to_gc" if project.client_type == "gc" else "prime_to_owner",
        tier="competitive",
        rates=rates,
        contingency_pct=Decimal("0"),
        overhead_pct=Decimal("0"),
        profit_pct=profit_pct,
        rounding=Decimal("1"),
        tax={"mode": "excluded_resale" if project.client_type == "gc" else "excluded"},
        materials=mat_lines,
        labor=labor_lines,
        other=other_lines,
        scope=[{"title": it.description, "text": it.specification or f"{it.quantity or 1} {it.unit or 'LS'} per plans."} for it in (project.scope_items or mat_lines)],
        exclusions=["Work not explicitly shown in project drawings or scope items."],
        release={"authorized": True, "allow_budget_prices": True, "note": "Finalized project estimate."},
    )

    computed = compute(pkg)
    # Ensure exact final_price alignment in rendered PDFs
    if project.final_price is not None:
        computed["total"] = project.final_price
        computed["price"] = project.final_price

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    key = project.project_id
    return {
        "cost_analysis": render_cost_analysis(pkg, computed, out_path / f"{key}_01_COST_ANALYSIS.pdf"),
        "material_list": render_material_list(pkg, computed, out_path / f"{key}_02_MATERIAL_LIST.pdf"),
        "proposal": render_proposal(pkg, computed, out_path / f"{key}_03_ESTIMATE_PROPOSAL.pdf", "LUMP-SUM PROPOSAL"),
    }

