"""Structured Labor Cost & Productivity Database with wage hierarchy, crews, and documented adjustments."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from typing import Any


def _d(val: Any, default: str = "0") -> Decimal:
    if val is None or val == "":
        return Decimal(default)
    return Decimal(str(val))


def _money(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hrs(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class WageClassification:
    key: str
    trade: str
    classification: str
    county: str
    state: str
    base_wage: Decimal
    fringe_benefits: Decimal = Decimal("0")
    labor_burden_pct: Decimal = Decimal("15")
    commercial_markup_pct: Decimal = Decimal("0")
    overtime_multiplier: Decimal = Decimal("1.5")
    equipment_rate: Decimal = Decimal("0")
    indirect_rate: Decimal = Decimal("0")
    effective_date: str = ""
    source: str = ""
    verified: bool = False
    is_prevailing_wage: bool = True

    def __post_init__(self) -> None:
        self.base_wage = _d(self.base_wage)
        self.fringe_benefits = _d(self.fringe_benefits)
        self.labor_burden_pct = _d(self.labor_burden_pct)
        self.commercial_markup_pct = _d(self.commercial_markup_pct)
        self.overtime_multiplier = _d(self.overtime_multiplier, "1.5")
        self.equipment_rate = _d(self.equipment_rate)
        self.indirect_rate = _d(self.indirect_rate)
        if self.base_wage < 0 or self.fringe_benefits < 0 or self.labor_burden_pct < 0:
            raise ValueError("Wage and burden figures cannot be negative.")
        if not self.source.strip():
            raise ValueError(f"WageClassification '{self.key}' requires documentary source.")

    @property
    def total_pw_package(self) -> Decimal:
        """Base wage + fringe benefits (statutory prevailing-wage total)."""
        return _money(self.base_wage + self.fringe_benefits)

    @property
    def burden_amount(self) -> Decimal:
        return _money(self.total_pw_package * self.labor_burden_pct / Decimal("100"))

    @property
    def loaded_rate(self) -> Decimal:
        """Employer loaded hourly cost: base + fringe + payroll burden."""
        return _money(self.total_pw_package + self.burden_amount)

    @property
    def commercial_rate(self) -> Decimal:
        """Commercial billing hourly rate including indirects and commercial markup."""
        return _money((self.loaded_rate + self.indirect_rate) * (Decimal("1") + self.commercial_markup_pct / Decimal("100")))

    def breakdown(self) -> dict[str, str]:
        return {
            "base_wage": str(_money(self.base_wage)),
            "fringe_benefits": str(_money(self.fringe_benefits)),
            "total_pw_package": str(self.total_pw_package),
            "labor_burden_pct": str(self.labor_burden_pct),
            "burden_amount": str(self.burden_amount),
            "loaded_rate": str(self.loaded_rate),
            "indirect_rate": str(_money(self.indirect_rate)),
            "commercial_rate": str(self.commercial_rate),
            "overtime_loaded_rate": str(_money(self.loaded_rate * self.overtime_multiplier)),
        }


@dataclass(frozen=True)
class CrewMemberSpec:
    rate_key: str
    headcount: Decimal
    role_label: str = ""


@dataclass
class CrewComposition:
    crew_id: str
    name: str
    members: list[CrewMemberSpec]
    equipment_hourly: Decimal = Decimal("0")

    def composite_loaded_rate(self, wages: dict[str, WageClassification]) -> Decimal:
        total = Decimal("0")
        for m in self.members:
            if m.rate_key not in wages:
                raise KeyError(f"Unknown wage key {m.rate_key!r} in crew {self.crew_id}")
            total += _d(m.headcount) * wages[m.rate_key].loaded_rate
        return _money(total)


@dataclass(frozen=True)
class AdjustmentFactor:
    category: str  # complexity | height | accessibility | weather | site_restriction
    multiplier: Decimal
    justification: str
    source: str

    def __post_init__(self) -> None:
        mult = _d(self.multiplier, "1")
        object.__setattr__(self, "multiplier", mult)
        if mult <= Decimal("0") or mult > Decimal("3.0"):
            raise ValueError(f"Unbounded labor adjustment multiplier {mult}; must be in (0, 3.0].")
        if mult != Decimal("1") and (not self.justification.strip() or not self.source.strip()):
            raise ValueError(
                f"Arbitrary labor multiplier ({mult}) forbidden without documented justification and source."
            )


@dataclass
class ProductivityNorm:
    norm_id: str
    task: str
    trade: str
    unit: str
    hours_per_unit: Decimal
    fixed_setup_hours: Decimal = Decimal("0")
    hours_per_post_or_element: Decimal = Decimal("0")
    prep_share_pct: Decimal = Decimal("10")
    fabrication_share_pct: Decimal = Decimal("25")
    installation_share_pct: Decimal = Decimal("55")
    mobilization_share_pct: Decimal = Decimal("10")
    source: str = ""
    effective_date: str = ""
    location: str = ""
    confidence: float = 0.8

    def __post_init__(self) -> None:
        self.hours_per_unit = _d(self.hours_per_unit)
        self.fixed_setup_hours = _d(self.fixed_setup_hours)
        self.hours_per_post_or_element = _d(self.hours_per_post_or_element)
        shares = _d(self.prep_share_pct) + _d(self.fabrication_share_pct) + _d(self.installation_share_pct) + _d(self.mobilization_share_pct)
        if shares != Decimal("100"):
            raise ValueError(f"ProductivityNorm '{self.norm_id}' phase shares must sum to 100%, got {shares}%")
        if not self.source.strip():
            raise ValueError(f"ProductivityNorm '{self.norm_id}' requires documented source.")


def calculate_labor_hours(
    norm: ProductivityNorm,
    *,
    quantity: Decimal | str | float,
    element_count: Decimal | str | float = 0,
    adjustments: list[AdjustmentFactor] | None = None,
    overtime_hours: Decimal | str | float = 0,
    wage: WageClassification | None = None,
) -> dict[str, Any]:
    """Compute base/adjusted hours, bucket split (prep/fab/install/mob), and detailed cost."""
    qty = _d(quantity)
    elems = _d(element_count)
    base_hours = (qty * norm.hours_per_unit) + (elems * norm.hours_per_post_or_element) + norm.fixed_setup_hours

    combined_mult = Decimal("1")
    applied_factors: list[dict[str, Any]] = []
    for adj in adjustments or []:
        combined_mult *= adj.multiplier
        applied_factors.append({
            "category": adj.category,
            "multiplier": str(adj.multiplier),
            "justification": adj.justification,
            "source": adj.source,
        })

    total_hours = _hrs(base_hours * combined_mult)
    ot = min(_hrs(_d(overtime_hours)), total_hours)
    reg_hours = _hrs(total_hours - ot)

    prep_h = _hrs(total_hours * _d(norm.prep_share_pct) / Decimal("100"))
    fab_h = _hrs(total_hours * _d(norm.fabrication_share_pct) / Decimal("100"))
    inst_h = _hrs(total_hours * _d(norm.installation_share_pct) / Decimal("100"))
    mob_h = _hrs(total_hours - prep_h - fab_h - inst_h)

    res: dict[str, Any] = {
        "norm_id": norm.norm_id,
        "task": norm.task,
        "trade": norm.trade,
        "base_hours": str(_hrs(base_hours)),
        "adjustment_multiplier": str(combined_mult.quantize(Decimal("0.001"))),
        "adjustments": applied_factors,
        "total_hours": str(total_hours),
        "regular_hours": str(reg_hours),
        "overtime_hours": str(ot),
        "phase_hours": {
            "prep": str(prep_h),
            "fabrication": str(fab_h),
            "installation": str(inst_h),
            "mobilization": str(mob_h),
        },
        "source": norm.source,
        "location": norm.location,
        "effective_date": norm.effective_date,
        "confidence": norm.confidence,
    }
    if wage is not None:
        base_cost = _money((reg_hours * wage.total_pw_package) + (ot * wage.total_pw_package * wage.overtime_multiplier))
        loaded_cost = _money((reg_hours * wage.loaded_rate) + (ot * wage.loaded_rate * wage.overtime_multiplier))
        burden_cost = _money(loaded_cost - base_cost)
        commercial_cost = _money((reg_hours * wage.commercial_rate) + (ot * wage.commercial_rate * wage.overtime_multiplier))
        equip_cost = _money(total_hours * wage.equipment_rate)
        indirect_cost = _money(total_hours * wage.indirect_rate)
        res["cost"] = {
            "wage_key": wage.key,
            "base_wage_cost": str(base_cost),
            "burden_cost": str(burden_cost),
            "loaded_cost": str(loaded_cost),
            "commercial_billing_value": str(commercial_cost),
            "equipment_cost": str(equip_cost),
            "indirect_cost": str(indirect_cost),
            "wage_verified": wage.verified,
        }
    return res


def load_structured_wages(wages_json_path: Path) -> list[WageClassification]:
    """Load legacy knowledge/wages.json into structured WageClassification objects."""
    raw = json.loads(Path(wages_json_path).read_text(encoding="utf-8"))
    out: list[WageClassification] = []
    for idx, row in enumerate(raw, start=1):
        out.append(WageClassification(
            key=f"WAGE-{row['county'][:3].upper()}-{idx:02d}",
            trade=row["trade"],
            classification=row.get("classification") or "Journeyman",
            county=row["county"],
            state="WA",
            base_wage=_d(row["rate"]),
            fringe_benefits=Decimal("0"),
            labor_burden_pct=Decimal("15"),
            effective_date=str(row.get("effective") or ""),
            source=str(row.get("source") or "wages.json"),
            verified=bool(row.get("verified", False)),
            is_prevailing_wage=True,
        ))
    return out


def parse_legacy_productivity(productivity_json_path: Path) -> list[ProductivityNorm]:
    """Convert legacy knowledge/productivity.json strings into numeric ProductivityNorm models."""
    raw = json.loads(Path(productivity_json_path).read_text(encoding="utf-8"))
    out: list[ProductivityNorm] = []
    for idx, row in enumerate(raw, start=1):
        rate_s = str(row.get("rate") or "0").strip()
        unit_s = str(row.get("unit") or "MH/EA").strip()
        trade_s = str(row.get("trade") or "General").strip()
        hpu = Decimal("0")
        per_elem = Decimal("0")
        fixed = Decimal("0")
        import re
        range_m = re.match(r"^(\d+(?:\.\d+)?)\s*[–-]\s*(\d+(?:\.\d+)?)$", rate_s)
        add_m = re.match(r"^(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)/(\w+)$", rate_s)
        num_m = re.match(r"^(\d+(?:\.\d+)?)$", rate_s)
        if num_m:
            hpu = _d(num_m.group(1))
        elif range_m:
            hpu = ((_d(range_m.group(1)) + _d(range_m.group(2))) / Decimal("2")).quantize(Decimal("0.001"))
        elif add_m:
            hpu = _d(add_m.group(1))
            per_elem = _d(add_m.group(2))
        else:
            nums = re.findall(r"\d+(?:\.\d+)?", rate_s)
            hpu = _d(nums[0]) if nums else Decimal("1.0")
        fab_pct = Decimal("60") if "shop" in trade_s.lower() else Decimal("10")
        inst_pct = Decimal("20") if "shop" in trade_s.lower() else Decimal("70")
        out.append(ProductivityNorm(
            norm_id=f"PROD-{idx:03d}",
            task=str(row.get("task") or f"Task {idx}"),
            trade=trade_s,
            unit=unit_s,
            hours_per_unit=hpu,
            fixed_setup_hours=fixed,
            hours_per_post_or_element=per_elem,
            prep_share_pct=Decimal("10"),
            fabrication_share_pct=fab_pct,
            installation_share_pct=inst_pct,
            mobilization_share_pct=Decimal("10"),
            source=f"{row.get('source') or 'productivity.json'} (raw='{rate_s}')",
            effective_date="2026-11-01",
            location="Puget Sound, WA",
            confidence=0.8 if num_m else 0.65,
        ))
    return out
