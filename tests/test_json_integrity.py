"""Test JSON integrity and multi-client contractor / compliance configuration loaders."""

from __future__ import annotations

import json
from pathlib import Path

from bidkit.contractor import (
    ComplianceRequirement,
    ContractorIdentity,
    format_compliance_summary,
    get_blocking_requirements,
    load_compliance_requirements,
    load_contractor_identity,
)


def test_no_duplicate_keys_in_audit():
    """Verify bid_audit.json has no duplicate keys."""
    audit_file = Path("data/audit/bid_audit.json")
    if not audit_file.exists():
        return

    text = audit_file.read_text(encoding="utf-8")

    def check_duplicates(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            duplicates = [k for k in keys if keys.count(k) > 1]
            raise ValueError(f"Duplicate keys found: {set(duplicates)}")
        return dict(pairs)

    json.loads(text, object_pairs_hook=check_duplicates)


def test_no_duplicate_keys_in_validation():
    """Verify validation_report.json has no duplicate keys."""
    validation_file = Path("output/validation_report.json")
    if not validation_file.exists():
        return

    text = validation_file.read_text(encoding="utf-8")

    def check_duplicates(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            duplicates = [k for k in keys if keys.count(k) > 1]
            raise ValueError(f"Duplicate keys found: {set(duplicates)}")
        return dict(pairs)

    json.loads(text, object_pairs_hook=check_duplicates)


def test_placeholder_contractor_identity_when_no_source():
    """Verify load_contractor_identity(None) returns placeholder with TO_BE_FILLED and pending."""
    identity = load_contractor_identity(None)
    assert isinstance(identity, ContractorIdentity)
    assert identity.legal_name == "TO_BE_FILLED"
    assert identity.location_city == "TO_BE_FILLED"
    assert identity.location_state == "TO_BE_FILLED"
    assert identity.wa_ubi == "TO_BE_FILLED"
    assert identity.contractor_registration == "TO_BE_FILLED"
    assert identity.classification == "TO_BE_FILLED"
    assert identity.registration_status == "pending"


def test_load_contractor_identity_from_dict_and_json_file(tmp_path: Path):
    """Verify load_contractor_identity loads from dict and JSON file without hardcodes."""
    sample = {
        "legal_name": "TO_BE_FILLED LLC",
        "location_city": "City",
        "location_state": "Washington",
        "wa_ubi": "000000000",
        "contractor_registration": "XXXXXX000XX",
        "classification": "GENERAL",
        "registration_status": "Active",
    }
    from_dict = load_contractor_identity(sample)
    assert from_dict.legal_name == "TO_BE_FILLED LLC"
    assert from_dict.format_full_location() == "City, Washington"
    assert from_dict.wa_ubi == "000000000"
    assert from_dict.contractor_registration == "XXXXXX000XX"
    assert from_dict.classification == "GENERAL"
    assert from_dict.registration_status == "Active"

    json_file = tmp_path / "contractor.json"
    json_file.write_text(json.dumps(sample), encoding="utf-8")
    from_file = load_contractor_identity(str(json_file))
    assert from_file == from_dict


def test_load_compliance_requirements_and_helpers(tmp_path: Path):
    """Verify compliance loader and helper functions work with default and custom sources."""
    default_reqs = load_compliance_requirements(None)
    assert len(default_reqs) > 0
    assert all(isinstance(r, ComplianceRequirement) for r in default_reqs)
    assert all(r.status == "pending" for r in default_reqs)

    blocking = get_blocking_requirements(default_reqs)
    assert len(blocking) == len(default_reqs)

    custom_data = {
        "compliance": [
            {
                "requirement_name": "Bid Security",
                "category": "bid_security",
                "status": "pending",
                "notes": "5% bid bond required",
            },
            {
                "requirement_name": "Contractor Registration",
                "category": "bidder_responsibility",
                "status": "verified",
                "evidence_file": "registration_proof.png",
                "notes": "Verified from official record",
            },
        ]
    }
    comp_file = tmp_path / "compliance.json"
    comp_file.write_text(json.dumps(custom_data), encoding="utf-8")

    loaded = load_compliance_requirements(str(comp_file))
    assert len(loaded) == 2
    assert len(get_blocking_requirements(loaded)) == 1
    summary = format_compliance_summary(loaded)
    assert "Verified: 1" in summary
    assert "Pending: 1" in summary
    assert "registration_proof.png" in summary
