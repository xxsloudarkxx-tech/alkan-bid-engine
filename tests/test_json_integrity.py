"""Test JSON integrity - no duplicate keys, valid structure."""

from __future__ import annotations

import json
from pathlib import Path


def test_no_duplicate_keys_in_audit():
    """Verify bid_audit.json has no duplicate keys."""
    audit_file = Path("data/audit/bid_audit.json")
    if not audit_file.exists():
        return  # File may not exist yet in clean environment

    # Read raw text and parse to detect duplicates
    text = audit_file.read_text(encoding="utf-8")

    # Python's json.loads silently overwrites duplicate keys,
    # so we need to use object_pairs_hook to detect them
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


def test_contractor_identity_in_audit():
    """Verify contractor identity is present and correct in audit."""
    audit_file = Path("data/audit/bid_audit.json")
    if not audit_file.exists():
        return

    data = json.loads(audit_file.read_text(encoding="utf-8"))

    assert "contractor_identity" in data, "Missing contractor_identity"
    contractor = data["contractor_identity"]["contractor"]

    assert contractor["legal_name"] == "P J ROOFING LLC"
    assert contractor["location"] == "Kent, Washington"
    assert contractor["wa_ubi"] == "604785233"
    assert contractor["contractor_registration"] == "PJROOJR747OT"
    assert contractor["classification"] == "GENERAL"
    assert contractor["status"] == "Active"


def test_compliance_requirements_not_verified_without_evidence():
    """Verify that no compliance requirement is marked verified without evidence."""
    audit_file = Path("data/audit/bid_audit.json")
    if not audit_file.exists():
        return

    data = json.loads(audit_file.read_text(encoding="utf-8"))
    compliance = data["contractor_identity"]["compliance"]

    for req in compliance:
        if req["status"] == "verified":
            assert req["evidence"] is not None, \
                f"Requirement '{req['requirement']}' is verified but has no evidence"
        elif req["status"] == "pending":
            # Pending items should not have evidence or should have null evidence
            assert req["evidence"] is None or req["evidence"] == "", \
                f"Requirement '{req['requirement']}' is pending but shows evidence"


def test_all_blocking_requirements_are_pending():
    """Verify compliance blocking requirements are in pending status."""
    validation_file = Path("output/validation_report.json")
    if not validation_file.exists():
        return

    data = json.loads(validation_file.read_text(encoding="utf-8"))
    blocking = data["compliance_summary"]["blocking_items"]

    # All blocking items should exist in the pending list
    pending_items = [
        item["item"] for item in data["status"]["PENDIENTE"]
        if "compliance requirements" in item.get("source", {}).get("document", "")
    ]

    for blocked in blocking:
        assert blocked in pending_items, \
            f"Blocking item '{blocked}' not found in pending status"
