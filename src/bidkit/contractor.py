"""
Contractor identity and compliance configuration for bid submissions.

This module defines the bidding contractor's corporate identity and tracks
compliance requirements. All information must be verified against official
documents before use in formal bid submissions.

Example contractor identity JSON configuration:
```json
{
  "legal_name": "TO_BE_FILLED LLC",
  "location_city": "City",
  "location_state": "Washington",
  "wa_ubi": "000000000",
  "contractor_registration": "XXXXXX000XX",
  "classification": "GENERAL",
  "registration_status": "Active"
}
```
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal


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


# Hardcoded contractor identity and project-specific compliance constants have been
# removed in favor of multi-client configuration loaders:
# - load_contractor_identity(source)
# - load_compliance_requirements(source)

PLACEHOLDER_CONTRACTOR = ContractorIdentity(
    legal_name="TO_BE_FILLED",
    location_city="TO_BE_FILLED",
    location_state="TO_BE_FILLED",
    wa_ubi="TO_BE_FILLED",
    contractor_registration="TO_BE_FILLED",
    classification="TO_BE_FILLED",
    registration_status="pending",
)

DEFAULT_COMPLIANCE_TEMPLATE: list[ComplianceRequirement] = [
    ComplianceRequirement(
        requirement_name="Bid Security (Bid Bond or equivalent)",
        category="bid_security",
        status="pending",
        notes="Required per bid instructions. Amount and form TBD from specifications.",
    ),
    ComplianceRequirement(
        requirement_name="Performance Bond",
        category="bonds",
        status="pending",
        notes="Typically 100% of contract amount. Awaiting surety confirmation.",
    ),
    ComplianceRequirement(
        requirement_name="Payment Bond",
        category="bonds",
        status="pending",
        notes="Typically 100% of contract amount. Awaiting surety confirmation.",
    ),
    ComplianceRequirement(
        requirement_name="Prevailing Wage Compliance",
        category="wages",
        status="pending",
        notes="State prevailing wage rates apply where required. Intent to Pay Prevailing Wages form required.",
    ),
    ComplianceRequirement(
        requirement_name="General Liability Insurance",
        category="insurance",
        status="pending",
        notes="Certificate of Insurance with required coverage limits per specifications.",
    ),
    ComplianceRequirement(
        requirement_name="Workers' Compensation Insurance",
        category="insurance",
        status="pending",
        notes="State L&I coverage or self-insurance certificate required.",
    ),
    ComplianceRequirement(
        requirement_name="Bidder Responsibility Criteria",
        category="bidder_responsibility",
        status="pending",
        notes="May include questionnaire, financial statements, or reference list.",
    ),
    ComplianceRequirement(
        requirement_name="Authorized Signature",
        category="authorization",
        status="pending",
        notes="Bid must be signed by authorized representative. Corporate resolution may be required.",
    ),
    ComplianceRequirement(
        requirement_name="WA State Contractor Registration",
        category="bidder_responsibility",
        status="pending",
        evidence_file=None,
        notes="Verify active contractor registration before bid submission.",
    ),
]


def _read_source_payload(source: str | Path | dict[str, Any] | list[Any]) -> Any:
    """Loads a JSON payload from a file path, JSON string, dict, or list."""
    if isinstance(source, (dict, list)):
        return source
    if isinstance(source, Path):
        return json.loads(source.read_text(encoding="utf-8"))
    if isinstance(source, str):
        stripped = source.strip()
        if not stripped:
            return None
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(stripped)
        return json.loads(Path(stripped).read_text(encoding="utf-8"))
    raise TypeError(f"Unsupported configuration source type: {type(source)!r}")


def load_contractor_identity(
    source: str | Path | dict[str, Any] | ContractorIdentity | None = None,
) -> ContractorIdentity:
    """Loads contractor corporate identity from a JSON file path, JSON string, or dict.

    If ``source`` is None or empty, returns a placeholder ContractorIdentity with
    all fields marked as ``"TO_BE_FILLED"`` and ``registration_status="pending"``.
    """
    if source is None:
        return PLACEHOLDER_CONTRACTOR
    if isinstance(source, ContractorIdentity):
        return source

    payload = _read_source_payload(source)
    if not payload:
        return PLACEHOLDER_CONTRACTOR
    if not isinstance(payload, dict):
        raise ValueError("Contractor identity source must resolve to a JSON object / dict.")

    if isinstance(payload.get("contractor"), dict):
        payload = payload["contractor"]
    elif isinstance(payload.get("contractor_identity"), dict):
        inner = payload["contractor_identity"]
        payload = inner.get("contractor", inner) if isinstance(inner.get("contractor"), dict) else inner

    return ContractorIdentity(
        legal_name=str(payload.get("legal_name") or payload.get("name") or "TO_BE_FILLED"),
        location_city=str(payload.get("location_city") or payload.get("city") or "TO_BE_FILLED"),
        location_state=str(payload.get("location_state") or payload.get("state") or "TO_BE_FILLED"),
        wa_ubi=str(payload.get("wa_ubi") or payload.get("ubi") or "TO_BE_FILLED"),
        contractor_registration=str(
            payload.get("contractor_registration")
            or payload.get("license")
            or payload.get("registration")
            or "TO_BE_FILLED"
        ),
        classification=str(payload.get("classification") or "TO_BE_FILLED"),
        registration_status=str(
            payload.get("registration_status")
            or payload.get("status")
            or "pending"
        ),
    )


def _coerce_compliance_requirement(item: ComplianceRequirement | dict[str, Any]) -> ComplianceRequirement:
    if isinstance(item, ComplianceRequirement):
        return item
    if not isinstance(item, dict):
        raise ValueError(f"Invalid compliance requirement entry: {item!r}")
    status = str(item.get("status") or "pending")
    evidence = item.get("evidence_file") if "evidence_file" in item else item.get("evidence")
    return ComplianceRequirement(
        requirement_name=str(item.get("requirement_name") or item.get("requirement") or "TO_BE_FILLED"),
        category=item.get("category", "bidder_responsibility"),
        status=status,  # type: ignore[arg-type]
        evidence_file=str(evidence) if evidence else None,
        notes=str(item.get("notes") or ""),
    )


def load_compliance_requirements(
    source: str | Path | dict[str, Any] | list[Any] | None = None,
) -> list[ComplianceRequirement]:
    """Loads compliance requirements from a JSON file path, JSON string, dict, or list.

    If ``source`` is None, returns a list of generic placeholder compliance requirements
    with ``status="pending"``.
    """
    if source is None:
        return list(DEFAULT_COMPLIANCE_TEMPLATE)

    if isinstance(source, list) and all(isinstance(r, ComplianceRequirement) for r in source):
        return list(source)

    payload = _read_source_payload(source)
    if payload is None:
        return list(DEFAULT_COMPLIANCE_TEMPLATE)

    if isinstance(payload, dict):
        if "compliance" in payload and isinstance(payload["compliance"], list):
            items = payload["compliance"]
        elif "compliance_requirements" in payload and isinstance(payload["compliance_requirements"], list):
            items = payload["compliance_requirements"]
        elif "requirements" in payload and isinstance(payload["requirements"], list):
            items = payload["requirements"]
        elif "contractor_identity" in payload and isinstance(payload["contractor_identity"], dict):
            items = payload["contractor_identity"].get("compliance", [])
        elif "requirement_name" in payload or "requirement" in payload:
            items = [payload]
        else:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError("Compliance requirements source must resolve to a list or dict.")

    return [_coerce_compliance_requirement(item) for item in items]


def get_blocking_requirements(
    requirements: list[ComplianceRequirement] | str | Path | dict[str, Any] | None = None,
) -> list[ComplianceRequirement]:
    """Returns all compliance requirements that are currently blocking bid submission."""
    reqs = load_compliance_requirements(requirements)
    return [req for req in reqs if req.is_blocking()]


def format_compliance_summary(
    requirements: list[ComplianceRequirement] | str | Path | dict[str, Any] | None = None,
) -> str:
    """Generates a text summary of compliance status."""
    reqs = load_compliance_requirements(requirements)
    verified = [r for r in reqs if r.status == "verified"]
    pending = [r for r in reqs if r.status == "pending"]

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
