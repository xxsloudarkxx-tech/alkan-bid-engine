"""
Contractor identity and compliance configuration for bid submissions.

This module defines the bidding contractor's corporate identity and tracks
compliance requirements. All information must be verified against official
documents before use in formal bid submissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ContractorIdentity:
    """Corporate identity of the bidding contractor."""

    legal_name: str
    location_city: str
    location_state: str
    wa_ubi: str
    contractor_registration: str
    classification: str
    registration_status: str

    def format_full_location(self) -> str:
        """Returns 'City, State' format."""
        return f"{self.location_city}, {self.location_state}"

    def format_legal_header(self) -> str:
        """Returns formatted name and location for bid documents."""
        return f"{self.legal_name}\n{self.format_full_location()}"


@dataclass(frozen=True)
class ComplianceRequirement:
    """Tracks a single compliance requirement for the bid."""

    requirement_name: str
    category: Literal[
        "bid_security",
        "bonds",
        "wages",
        "insurance",
        "bidder_responsibility",
        "authorization"
    ]
    status: Literal["verified", "pending", "not_applicable"]
    evidence_file: str | None = None
    notes: str = ""

    def is_blocking(self) -> bool:
        """Returns True if this requirement must be met before bid submission."""
        return self.status == "pending" and self.category != "not_applicable"


# P J Roofing LLC identity - confirmed from WA L&I screenshot
PJ_ROOFING = ContractorIdentity(
    legal_name="P J ROOFING LLC",
    location_city="Kent",
    location_state="Washington",
    wa_ubi="604785233",
    contractor_registration="PJROOJR747OT",
    classification="GENERAL",
    registration_status="Active"
)


# Compliance requirements for Port of Tacoma 072026-1044
# Status reflects current evidence availability
PORT_TACOMA_COMPLIANCE = [
    ComplianceRequirement(
        requirement_name="Bid Security (Bid Bond or equivalent)",
        category="bid_security",
        status="pending",
        notes="Required per bid instructions. Amount and form TBD from specifications."
    ),
    ComplianceRequirement(
        requirement_name="Performance Bond",
        category="bonds",
        status="pending",
        notes="Typically 100% of contract amount. Awaiting surety confirmation."
    ),
    ComplianceRequirement(
        requirement_name="Payment Bond",
        category="bonds",
        status="pending",
        notes="Typically 100% of contract amount. Awaiting surety confirmation."
    ),
    ComplianceRequirement(
        requirement_name="Prevailing Wage Compliance",
        category="wages",
        status="pending",
        notes="WA State prevailing wage rates apply. Intent to Pay Prevailing Wages form required."
    ),
    ComplianceRequirement(
        requirement_name="General Liability Insurance",
        category="insurance",
        status="pending",
        notes="Certificate of Insurance with required coverage limits per specifications."
    ),
    ComplianceRequirement(
        requirement_name="Workers' Compensation Insurance",
        category="insurance",
        status="pending",
        notes="WA State L&I coverage or self-insurance certificate required."
    ),
    ComplianceRequirement(
        requirement_name="Bidder Responsibility Criteria",
        category="bidder_responsibility",
        status="pending",
        notes="May include questionnaire, financial statements, or reference list."
    ),
    ComplianceRequirement(
        requirement_name="Authorized Signature",
        category="authorization",
        status="pending",
        notes="Bid must be signed by authorized representative. Corporate resolution may be required."
    ),
    ComplianceRequirement(
        requirement_name="WA State Contractor Registration",
        category="bidder_responsibility",
        status="verified",
        evidence_file="WA_LI_screenshot.png",
        notes=f"Active registration confirmed: {PJ_ROOFING.contractor_registration}"
    ),
]


def get_blocking_requirements() -> list[ComplianceRequirement]:
    """Returns all compliance requirements that are currently blocking bid submission."""
    return [req for req in PORT_TACOMA_COMPLIANCE if req.is_blocking()]


def format_compliance_summary() -> str:
    """Generates a text summary of compliance status."""
    verified = [r for r in PORT_TACOMA_COMPLIANCE if r.status == "verified"]
    pending = [r for r in PORT_TACOMA_COMPLIANCE if r.status == "pending"]

    lines = ["# Compliance Requirements Summary\n"]
    lines.append(f"Verified: {len(verified)}")
    lines.append(f"Pending: {len(pending)}\n")

    if pending:
        lines.append("## Pending Requirements (Blocking Submission):\n")
        for req in pending:
            lines.append(f"- {req.requirement_name}")
            if req.notes:
                lines.append(f"  {req.notes}")

    if verified:
        lines.append("\n## Verified Requirements:\n")
        for req in verified:
            lines.append(f"- {req.requirement_name}")
            if req.evidence_file:
                lines.append(f"  Evidence: {req.evidence_file}")

    return "\n".join(lines)
