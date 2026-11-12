from __future__ import annotations

import json
import csv
from datetime import UTC, datetime
from pathlib import Path

from .audit import load_audit, validate_source_integrity
from .config import ProjectConfig
from .contractor import (
    PJ_ROOFING,
    PORT_TACOMA_COMPLIANCE,
    format_compliance_summary,
    get_blocking_requirements,
)
from .records import AMENDMENTS, REQUIREMENTS, RISKS, TAKEOFF


def _write_json(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_data_records(config: ProjectConfig) -> dict:
    audit = load_audit(config)

    # Include contractor identity and compliance status
    contractor_info = {
        "contractor": {
            "legal_name": PJ_ROOFING.legal_name,
            "location": PJ_ROOFING.format_full_location(),
            "wa_ubi": PJ_ROOFING.wa_ubi,
            "contractor_registration": PJ_ROOFING.contractor_registration,
            "classification": PJ_ROOFING.classification,
            "status": PJ_ROOFING.registration_status,
        },
        "compliance": [
            {
                "requirement": req.requirement_name,
                "category": req.category,
                "status": req.status,
                "evidence": req.evidence_file,
                "notes": req.notes,
            }
            for req in PORT_TACOMA_COMPLIANCE
        ],
    }

    payload = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "contractor_identity": contractor_info,
        "requirements": REQUIREMENTS,
        "amendments": AMENDMENTS,
        "risks": RISKS,
        "takeoff": TAKEOFF,
        "source_manifest": audit["documents"],
        "document_issues": [
            {"status": "PENDING", "issue": "Addendum 03 filename conflicts with its internal header, which says Addendum Number 02.", "source": {"document": "072026-1044_addendum_03.pdf", "page": 1, "confidence": "HIGH"}},
            {"status": "PENDING", "issue": "Drawings contain field-verification notes for dimensions, penetrations, utilities and conditions; controlled measurement is not supplied.", "source": {"document": "072026-1044_drawings-(1).pdf", "page": "A1-401 / A2-401", "confidence": "HIGH"}},
            {"status": "PENDING", "issue": "No bidder-specific license, bonding, insurance, workforce, wage, quote or supplier documentation was provided in the local source set.", "source": {"document": "local source inventory", "page": "n/a", "confidence": "HIGH"}},
        ],
    }
    _write_json(config.root / "data" / "audit" / "bid_audit.json", payload)
    return payload


def validation_report(config: ProjectConfig) -> dict:
    records = build_data_records(config)
    integrity = validate_source_integrity(config)
    blocking_compliance = get_blocking_requirements()

    statuses = {
        "VERIFICADO": [
            {"item": "Source document integrity", "status": "VERIFICADO", "evidence": f"{sum(1 for row in integrity if row['status'] == 'PASS')} of {len(integrity)} local PDF hashes match the audit manifest."},
            {"item": "Final bid receipt date and time", "status": "VERIFICADO", "evidence": "Addendum 04 p. 1: October 29, 2026 at 2:00 PM, Port Administration Office."},
            {"item": "Bid Form allowance and tax fields", "status": "VERIFICADO", "evidence": "Section 00 41 00 p. 1: $25,000 allowance and 10.5% WSST field."},
            {"item": "WA State Contractor Registration", "status": "VERIFICADO", "evidence": f"{PJ_ROOFING.contractor_registration} - Active (verified from screenshot)"},
        ],
        "PENDIENTE": [
            *([r for r in records["requirements"] if r["status"] == "PENDING"]),
            *([r for r in records["risks"] if r["status"] == "PENDING"]),
            *records["document_issues"],
            *[
                {
                    "item": req.requirement_name,
                    "status": "PENDING",
                    "issue": req.notes,
                    "source": {"document": "compliance requirements", "page": req.category, "confidence": "HIGH"},
                }
                for req in blocking_compliance
            ],
        ],
        "BLOQUEANTE": [r for r in records["risks"] if r["status"] == "BLOCKING"],
    }

    # Add compliance summary
    compliance_summary = {
        "verified_count": sum(1 for c in records["contractor_identity"]["compliance"] if c["status"] == "verified"),
        "pending_count": sum(1 for c in records["contractor_identity"]["compliance"] if c["status"] == "pending"),
        "blocking_items": [req.requirement_name for req in blocking_compliance],
    }

    payload = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "contractor": records["contractor_identity"]["contractor"],
        "compliance_summary": compliance_summary,
        "source_integrity": integrity,
        "status": statuses,
    }
    _write_json(config.output_dir / "validation_report.json", payload)
    return payload


def write_working_registers(config: ProjectConfig) -> None:
    """Export review-friendly registers without claiming an official submission format."""
    def flatten(rows: list[dict]) -> list[dict]:
        result = []
        for row in rows:
            copy = dict(row)
            ref = copy.pop("source", {})
            copy["source_document"] = ref.get("document", "")
            copy["source_page_or_sheet"] = ref.get("page", "")
            copy["source_confidence"] = ref.get("confidence", "")
            result.append(copy)
        return result

    _write_csv(config.output_dir / "Compliance_and_Bid_Submission_Checklist.csv", flatten(REQUIREMENTS))
    _write_csv(config.output_dir / "Risk_and_Clarification_Register.csv", flatten(RISKS))
    suppliers = [
        {"material_or_service": "Standing seam roof system", "supplier_or_manufacturer": "PENDING CONTRACTOR SELECTION", "required_confirmation": "Approved system, 0.040 aluminum, seam, clips, thermal blocks, load chart and warranty", "status": "PENDING", "source_document": "Addenda 01 and 02", "source_page_or_sheet": "1-2", "source_confidence": "HIGH"},
        {"material_or_service": "Aluminum gutters and downspouts", "supplier_or_manufacturer": "PENDING QUOTE", "required_confirmation": "6 in gutter and 4 in x 4 in downspouts, finish and lead time", "status": "PENDING", "source_document": "A1-401 / A2-401", "source_page_or_sheet": "PDF 5 / PDF 7", "source_confidence": "HIGH"},
        {"material_or_service": "Bid, performance and payment bonds", "supplier_or_manufacturer": "PENDING SURETY", "required_confirmation": "WA authority, A.M. Best A- FSC 6 or higher, power of attorney", "status": "BLOCKING", "source_document": "00 21 00 / 00 61 13.13", "source_page_or_sheet": "p. 6 / p. 2", "source_confidence": "HIGH"},
    ]
    _write_csv(config.output_dir / "Materials_and_Suppliers_Pending.csv", suppliers)
    sov = [
        {"schedule_item": "Mobilization and demobilization", "basis": "Official Bid Form item 1", "amount": "", "status": "PENDING PRICE", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
        {"schedule_item": "Project administration", "basis": "Official Bid Form item 2", "amount": "", "status": "PENDING PRICE", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
        {"schedule_item": "Building 1 roof install", "basis": "Official Bid Form item 3", "amount": "", "status": "PENDING PRICE", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
        {"schedule_item": "Building 1 gutters and downspouts", "basis": "Official Bid Form item 4", "amount": "", "status": "PENDING PRICE", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
        {"schedule_item": "Building 2 roof install", "basis": "Official Bid Form item 5", "amount": "", "status": "PENDING PRICE", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
        {"schedule_item": "Building 2 gutters and downspouts", "basis": "Official Bid Form item 6", "amount": "", "status": "PENDING PRICE", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
        {"schedule_item": "Unforeseen Conditions Allowance", "basis": "Official Bid Form item 7", "amount": "25000.00", "status": "VERIFIED BID FORM", "source_document": "00 41 00", "source_page_or_sheet": "p. 1", "source_confidence": "HIGH"},
    ]
    _write_csv(config.output_dir / "Schedule_of_Values_Preliminary.csv", sov)
    schedule = [
        {"sequence": 1, "activity": "Contract execution and submittal kickoff", "duration": "PENDING", "predecessor": "Award", "status": "PENDING CONTRACT DATE", "source_document": "00 52 00", "source_page_or_sheet": "p. 2", "source_confidence": "HIGH"},
        {"sequence": 2, "activity": "Field verification, procurement and submittal approval", "duration": "PENDING", "predecessor": "1", "status": "PENDING SUPPLIER DATA", "source_document": "A1-401 / A2-401", "source_page_or_sheet": "PDF 5 / PDF 7", "source_confidence": "HIGH"},
        {"sequence": 3, "activity": "Building 1 demolition and roof installation", "duration": "PENDING", "predecessor": "2", "status": "PENDING ESTIMATOR", "source_document": "00 52 00", "source_page_or_sheet": "p. 2", "source_confidence": "HIGH"},
        {"sequence": 4, "activity": "Building 2 demolition, mechanical coordination and roof installation", "duration": "PENDING", "predecessor": "2", "status": "PENDING ESTIMATOR", "source_document": "A2-401", "source_page_or_sheet": "PDF 7", "source_confidence": "HIGH"},
        {"sequence": 5, "activity": "Punch, warranty closeout and Final Completion", "duration": "PENDING", "predecessor": "3,4", "status": "PENDING CONTRACT DATE", "source_document": "00 52 00", "source_page_or_sheet": "p. 2", "source_confidence": "HIGH"},
    ]
    _write_csv(config.output_dir / "Construction_Schedule_Preliminary.csv", schedule)


def write_compliance_report(config: ProjectConfig) -> None:
    """Generate a standalone compliance requirements report for bid submission readiness."""
    output_path = config.output_dir / "Compliance_Requirements_Status.txt"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    content = [
        "=" * 80,
        "COMPLIANCE REQUIREMENTS STATUS REPORT",
        "=" * 80,
        "",
        "Project: 5301 8th St E Roof Replacement",
        "Procurement No: 072026-1044",
        f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "=" * 80,
        "CONTRACTOR IDENTITY",
        "=" * 80,
        "",
        f"Legal Name:             {PJ_ROOFING.legal_name}",
        f"Location:               {PJ_ROOFING.format_full_location()}",
        f"WA UBI:                 {PJ_ROOFING.wa_ubi}",
        f"Contractor Reg:         {PJ_ROOFING.contractor_registration}",
        f"Classification:         {PJ_ROOFING.classification}",
        f"Registration Status:    {PJ_ROOFING.registration_status}",
        "",
        "=" * 80,
        "COMPLIANCE REQUIREMENTS",
        "=" * 80,
        "",
    ]

    verified = [r for r in PORT_TACOMA_COMPLIANCE if r.status == "verified"]
    pending = [r for r in PORT_TACOMA_COMPLIANCE if r.status == "pending"]

    content.append(f"Summary: {len(verified)} Verified | {len(pending)} Pending")
    content.append("")

    if verified:
        content.append("-" * 80)
        content.append("VERIFIED REQUIREMENTS")
        content.append("-" * 80)
        content.append("")
        for req in verified:
            content.append(f"✓ {req.requirement_name}")
            content.append(f"  Category: {req.category}")
            if req.evidence_file:
                content.append(f"  Evidence: {req.evidence_file}")
            if req.notes:
                content.append(f"  Notes: {req.notes}")
            content.append("")

    if pending:
        content.append("-" * 80)
        content.append("PENDING REQUIREMENTS (BLOCKING BID SUBMISSION)")
        content.append("-" * 80)
        content.append("")
        for req in pending:
            content.append(f"⚠ {req.requirement_name}")
            content.append(f"  Category: {req.category}")
            if req.notes:
                content.append(f"  Notes: {req.notes}")
            content.append("")

    content.extend([
        "=" * 80,
        "IMPORTANT NOTICE",
        "=" * 80,
        "",
        "This report identifies compliance requirements based on typical Port of Tacoma",
        "bidding standards. The contractor must:",
        "",
        "1. Review the complete bid documents (specifications and addenda) for exact",
        "   requirements and forms.",
        "2. Obtain and submit all required documents before bid submission.",
        "3. Ensure all pending items are resolved before the bid deadline.",
        "4. Have authorized personnel review and sign all bid documents.",
        "",
        "ALKAN Bid Engine serves as an internal estimation tool only. It does not:",
        "- Complete official bid forms",
        "- Certify contractor eligibility or qualifications",
        "- Provide legal, bonding, or insurance advice",
        "- Sign or submit bids on behalf of the contractor",
        "",
        "All pending items must be addressed by the contractor's authorized",
        "representatives before bid submission is ready.",
        "=" * 80,
    ])

    output_path.write_text("\n".join(content), encoding="utf-8")
    print(f"Compliance report written to: {output_path}")
