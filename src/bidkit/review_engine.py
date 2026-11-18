"""Independent Estimate Review Engine: deterministic checks + discrepancy workflow + anti-self-approval."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import re
from typing import Any

from .estimator_agent.sanity import sanity_checks
from .package_method import Package, compute as compute_legacy
from .security import SecurityContext, SelfApprovalError, assert_independent_approver, require_permission

SEVERITIES: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
DISCREPANCY_STATUSES: tuple[str, ...] = ("pending", "accepted", "rejected", "resolved")


@dataclass
class ReviewDiscrepancy:
    discrepancy_id: str
    category: str
    item_ref: str
    original_value: str
    revised_value: str
    reason: str
    source: str
    severity: str
    recommendation: str
    approval_status: str = "pending"
    resolved_by: str = ""
    resolved_at: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Invalid severity {self.severity!r}")
        if self.approval_status not in DISCREPANCY_STATUSES:
            raise ValueError(f"Invalid approval_status {self.approval_status!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm_desc(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def run_independent_review(
    pkg: Package,
    *,
    prepared_by: str,
    reviewer_id: str,
    pricebook_records: list[dict[str, Any]] | None = None,
    ai_findings: list[dict[str, Any]] | None = None,
    min_margin_pct: Decimal = Decimal("5"),
    max_margin_pct: Decimal = Decimal("45"),
    max_waste_pct: Decimal = Decimal("30"),
) -> dict[str, Any]:
    """Run independent deterministic + optional AI findings review; blocks self-review."""
    assert_independent_approver(prepared_by, reviewer_id)
    if reviewer_id.lower().startswith("agent") or reviewer_id.lower() in ("ai", "claude", "auto"):
        raise SelfApprovalError("Automated AI agent cannot act as final independent human reviewer.")

    discrepancies: list[ReviewDiscrepancy] = []
    idx = 0

    def add(
        *,
        category: str,
        item_ref: str,
        original_value: str,
        revised_value: str,
        reason: str,
        source: str,
        severity: str,
        recommendation: str,
    ) -> None:
        nonlocal idx
        idx += 1
        discrepancies.append(ReviewDiscrepancy(
            discrepancy_id=f"DISC-{idx:03d}",
            category=category,
            item_ref=item_ref,
            original_value=original_value,
            revised_value=revised_value,
            reason=reason,
            source=source,
            severity=severity,
            recommendation=recommendation,
        ))

    # 1. Reuse existing deterministic sanity alerts cleanly
    comp = compute_legacy(pkg)
    pkg_dict = {
        "project": dict(pkg.project),
        "exclusions": list(pkg.exclusions),
        "labor_rates": {k: {"kind": v.kind, "rate": str(v.rate), "burden_pct": str(v.burden_pct), "source": v.source} for k, v in pkg.rates.items()},
        "materials": [
            {"id": m.id, "section": m.section, "item": m.item, "spec": m.spec, "qty": str(m.qty),
             "unit": m.unit, "unit_price": str(m.unit_price), "price_basis": m.price_basis, "price_source": m.price_source}
            for m in pkg.materials
        ],
        "labor": [{"id": l.id, "task": l.task, "rate_key": l.rate_key, "rate": l.rate_key, "hours": str(l.hours)} for l in pkg.labor],
        "other": [{"id": o.id, "item": o.item, "category": o.category, "qty": str(o.qty), "unit": o.unit, "rate": str(o.rate)} for o in pkg.other],
        "markups": {
            "contingency_pct": str(pkg.contingency_pct),
            "overhead_pct": str(pkg.overhead_pct),
            "profit_pct": str(pkg.profit_pct),
        },
    }
    comp_totals = {k: str(v) for k, v in comp.items() if not isinstance(v, dict)}
    pb_compat = [
        {
            "item": r.get("material", ""),
            "unit": r.get("estimate_unit", "EA"),
            "unit_price": str(r.get("unit_price", "0")),
            "price_basis": r.get("price_type", "BUDGET"),
        }
        for r in (pricebook_records or [])
    ]
    for alert in sanity_checks(pkg_dict, comp_totals, pb_compat):
        lvl = str(alert.get("level") or "warning").lower()
        sev = "HIGH" if lvl in ("error", "blocking") else ("MEDIUM" if lvl == "warning" else "LOW")
        add(
            category="sanity_check",
            item_ref=str(alert.get("code") or pkg.estimate_id),
            original_value="Package input",
            revised_value="Verify source/rate",
            reason=str(alert.get("text") or ""),
            source="Deterministic Sanity Rules",
            severity=sev,
            recommendation="Verify prevailing wage, scope, or price source before approval.",
        )

    # 2. Duplicate material / labor item detection
    seen_mat: dict[tuple[str, str], list[str]] = defaultdict(list)
    for m in pkg.materials:
        key = (_norm_desc(m.item), m.unit.lower())
        seen_mat[key].append(m.id)
        if m.qty <= 0 or m.unit_price < 0:
            add(
                category="quantities_and_prices",
                item_ref=m.id,
                original_value=f"qty={m.qty}, unit_price={m.unit_price}",
                revised_value="qty > 0 and unit_price >= 0",
                reason="Non-positive quantity or negative unit price detected.",
                source=f"Material line {m.id}",
                severity="CRITICAL",
                recommendation="Correct quantity or move unresolved scope to Exclusions/RFI.",
            )
        if m.price_basis == "BUDGET" and m.extended >= Decimal("1500"):
            add(
                category="price_governance",
                item_ref=m.id,
                original_value=f"BUDGET (${m.extended})",
                revised_value="Supplier QUOTE / VERIFIED required",
                reason=f"High-value line (${m.extended}) relies on unverified BUDGET pricing.",
                source=m.price_source or "Estimate line",
                severity="HIGH",
                recommendation="Issue Supplier RFQ before locking final firm bid.",
            )
        if not m.qty_source.strip():
            add(
                category="traceability",
                item_ref=m.id,
                original_value="(no qty_source)",
                revised_value="Sheet/detail citation",
                reason=f"Material line {m.id} lacks documentary qty_source traceability.",
                source="Takeoff traceability policy",
                severity="MEDIUM",
                recommendation="Attach drawing sheet/detail reference to material line.",
            )
        waste_m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*waste", f"{m.item} {m.spec}", re.I)
        if waste_m and Decimal(waste_m.group(1)) > max_waste_pct:
            add(
                category="waste_factor",
                item_ref=m.id,
                original_value=f"{waste_m.group(1)}% waste",
                revised_value=f"<= {max_waste_pct}%",
                reason="Waste factor exceeds normal trade threshold.",
                source=f"Material line {m.id}",
                severity="MEDIUM",
                recommendation="Document nesting/cut justification or lower waste factor.",
            )

    for (desc, unit), ids in seen_mat.items():
        if len(ids) > 1:
            add(
                category="duplicate_item",
                item_ref=", ".join(ids),
                original_value=f"{len(ids)} lines ({desc[:40]})",
                revised_value="1 consolidated line",
                reason=f"Potential duplicate material lines with matching description/unit ({unit}): {ids}.",
                source="Deterministic Deduplication",
                severity="HIGH",
                recommendation="Confirm items are distinct locations or merge duplicate lines.",
            )

    # 3. Omission check: structural posts/handrails without concrete/grout/core drill or mobilization
    all_text = " ".join(f"{m.item} {m.spec}" for m in pkg.materials).lower()
    labor_text = " ".join(l.task for l in pkg.labor).lower()
    other_cats = {o.category.lower() for o in pkg.other}
    if any(k in all_text for k in ("handrail", "guardrail", "post", "bollard", "fence")) and not any(
        k in f"{all_text} {labor_text}" for k in ("grout", "core", "concrete", "footing", "anchor")
    ):
        add(
            category="omission",
            item_ref="Anchorage / Footings",
            original_value="Not listed",
            revised_value="Confirm core-drill / grout / anchor scope",
            reason="Posts/rails present without visible anchor, grout, core drill, or footing item.",
            source="Cross-trade omission heuristic",
            severity="MEDIUM",
            recommendation="Include anchor/grout/core drill or add explicit exclusion.",
        )
    if "mobilization" not in other_cats and pkg.labor:
        add(
            category="omission",
            item_ref="Mobilization",
            original_value="Not separated in Other",
            revised_value="Explicit Mobilization line or inclusion note",
            reason="Field labor exists without an explicit Mobilization line item.",
            source="Cost Engine 13-bucket completeness check",
            severity="LOW",
            recommendation="Verify mobilization is accounted for in hours or Other costs.",
        )

    # 4. Margin / Indirect bounds & double-application guard
    total = comp["total"]
    profit = comp["profit"]
    achieved_margin = (profit * Decimal("100") / total) if total > 0 else Decimal("0")
    if achieved_margin < min_margin_pct or achieved_margin > max_margin_pct:
        add(
            category="margin_check",
            item_ref="Markups/Profit",
            original_value=f"Margin {achieved_margin:.2f}% (Markup OH {pkg.overhead_pct}% + Profit {pkg.profit_pct}%)",
            revised_value=f"Expected {min_margin_pct}%–{max_margin_pct}%",
            reason="Effective profit margin falls outside configured commercial bounds.",
            source="Financial Policy Guard",
            severity="HIGH",
            recommendation="Verify markup vs margin calculation and estimator intent.",
        )

    # 5. Pricebook divergence check
    if pricebook_records:
        pb_by_name = {_norm_desc(r.get("material", "")): r for r in pricebook_records}
        for m in pkg.materials:
            match = pb_by_name.get(_norm_desc(m.item))
            if match:
                if match.get("expired"):
                    add(
                        category="expired_price",
                        item_ref=m.id,
                        original_value=f"Pricebook quote expired ({match.get('valid_until')})",
                        revised_value="Refresh supplier quote",
                        reason=f"Matched Pricebook quote for '{m.item}' is expired.",
                        source=f"Pricebook {match.get('id')}",
                        severity="HIGH",
                        recommendation="Request updated quote before bid submission.",
                    )

    # 6. Incorporate structured external AI review findings if provided
    for af in ai_findings or []:
        add(
            category=str(af.get("category") or "ai_independent_review"),
            item_ref=str(af.get("item_ref") or pkg.estimate_id),
            original_value=str(af.get("original_value") or ""),
            revised_value=str(af.get("revised_value") or ""),
            reason=str(af.get("reason") or "AI reviewer observation"),
            source=str(af.get("source") or "Independent AI Reviewer"),
            severity=str(af.get("severity") or "MEDIUM") if af.get("severity") in SEVERITIES else "MEDIUM",
            recommendation=str(af.get("recommendation") or "Human reviewer verification required."),
        )

    critical_count = sum(1 for d in discrepancies if d.severity == "CRITICAL")
    high_count = sum(1 for d in discrepancies if d.severity == "HIGH")
    return {
        "estimate_id": pkg.estimate_id,
        "prepared_by": prepared_by,
        "reviewer_id": reviewer_id,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "total_discrepancies": len(discrepancies),
        "critical_count": critical_count,
        "high_count": high_count,
        "ready_for_approval": critical_count == 0,
        "discrepancies": [d.to_dict() for d in discrepancies],
    }


def resolve_discrepancy(
    report: dict[str, Any],
    *,
    discrepancy_id: str,
    decision: str,
    actor: str,
    ctx: SecurityContext | None = None,
) -> dict[str, Any]:
    """Approve/reject/resolve a discrepancy while preventing self-approval by prepared_by."""
    if decision not in ("accepted", "rejected", "resolved"):
        raise ValueError("Decision must be 'accepted', 'rejected', or 'resolved'.")
    assert_independent_approver(report.get("prepared_by", ""), actor, ctx.role if ctx else None)
    if ctx:
        require_permission(ctx, "estimate:review")
    for d in report.get("discrepancies", []):
        if d.get("discrepancy_id") == discrepancy_id:
            d["approval_status"] = decision
            d["resolved_by"] = actor
            d["resolved_at"] = datetime.now(timezone.utc).isoformat()
            return d
    raise KeyError(f"Discrepancy {discrepancy_id} not found.")
