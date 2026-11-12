from __future__ import annotations

import json
from datetime import UTC, datetime

from .config import ProjectConfig


ESTIMATE_ROWS = [
    ("Mobilization and safety", "Safety and mobilization", "LS", None, "PENDING QUOTE"),
    ("Project administration", "Supervision and administration", "LS", None, "PENDING QUOTE"),
    ("Building 1 roof installation", "Materials", "LS", None, "PENDING QUOTE"),
    ("Building 1 roof installation", "Labor", "LS", None, "PENDING QUOTE"),
    ("Building 1 gutters and downspouts", "Materials", "LS", None, "PENDING QUOTE"),
    ("Building 2 roof installation", "Materials", "LS", None, "PENDING QUOTE"),
    ("Building 2 roof installation", "Labor", "LS", None, "PENDING QUOTE"),
    ("Building 2 gutters and downspouts", "Materials", "LS", None, "PENDING QUOTE"),
    ("Both buildings", "Equipment", "LS", None, "PENDING QUOTE"),
    ("Both buildings", "Demolition and disposal", "LS", None, "PENDING QUOTE"),
    ("Both buildings", "Subcontracts", "LS", None, "PENDING QUOTE"),
    ("Both buildings", "Insurance and warranties", "LS", None, "PENDING QUOTE"),
    ("Both buildings", "Overhead and profit", "LS", None, "PENDING APPROVAL"),
    ("Unforeseen Conditions Allowance", "Allowance", "LS", 25000.0, "VERIFIED BID FORM"),
]


def estimate_data(config: ProjectConfig) -> dict:
    payload = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "tax_rate": 0.105,
        "tax_rate_status": "VERIFIED BID FORM",
        "allowance": 25000.0,
        "allowance_status": "VERIFIED BID FORM",
        "price_policy": "No vendor-backed price has been entered. Unit prices remain blank.",
        "rows": [dict(zip(("bid_item", "cost_class", "uom", "fixed_amount", "status"), row, strict=True)) for row in ESTIMATE_ROWS],
    }
    directory = config.root / "data" / "estimate"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "estimate_inputs.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
