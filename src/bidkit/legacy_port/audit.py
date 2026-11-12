from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .config import ProjectConfig


KEYWORDS = {
    "instructions_to_bidders": ["00 21 00", "INSTRUCTIONS TO BIDDERS"],
    "bid_form": ["00 41 00", "BID FORM"],
    "bid_security": ["00 43 13", "BID SECURITY"],
    "responsibility_detail": ["00 45 13", "RESPONSIBILITY DETAIL"],
    "standing_seam": ["07 41 00", "PREFORMED METAL STANDING SEAM"],
    "allowance": ["ALLOWANCE", "UNFORESEEN"],
    "sales_tax": ["SALES TAX", "10.5%", "10.50%"],
    "bid_deadline": ["BID OPENING", "OCTOBER 29, 2026", "2:00 PM"],
    "addendum": ["ADDENDUM", "ADDENDA"],
    "substitution": ["SUBSTITUTION", "APPROVED EQUAL"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(name: str) -> str:
    lowered = name.lower()
    for key in ("addendum", "drawings", "specs", "q_and_a", "prebid", "holders"):
        if key in lowered:
            return key
    return "other"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def evidence_for_document(path: Path) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    reader = PdfReader(str(path))
    evidence: dict[str, list[dict[str, Any]]] = {key: [] for key in KEYWORDS}
    extraction_errors: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # pypdf must never make the audit fail silently
            extraction_errors.append(f"p.{page_number}: {exc}")
            continue
        compact = normalize(text)
        upper = compact.upper()
        for key, needles in KEYWORDS.items():
            if any(needle.upper() in upper for needle in needles):
                idx = min((upper.find(needle.upper()) for needle in needles if needle.upper() in upper), default=0)
                quote = compact[max(0, idx - 180): idx + 420]
                evidence[key].append(
                    {
                        "document": path.name,
                        "page": page_number,
                        "excerpt": quote,
                        "confidence": "HIGH" if compact else "LOW",
                    }
                )
    return {key: value for key, value in evidence.items() if value}, extraction_errors


def audit(config: ProjectConfig) -> dict[str, Any]:
    if not config.source_files:
        raise FileNotFoundError("No se encontraron PDFs oficiales 072026-1044_*.pdf")
    documents = []
    all_evidence: dict[str, list[dict[str, Any]]] = {key: [] for key in KEYWORDS}
    for source in config.source_files:
        reader = PdfReader(str(source))
        evidence, extraction_errors = evidence_for_document(source)
        for key, rows in evidence.items():
            all_evidence[key].extend(rows)
        documents.append(
            {
                "name": source.name,
                "path": str(source.relative_to(config.root)),
                "kind": classify(source.name),
                "bytes": source.stat().st_size,
                "modified_utc": datetime.fromtimestamp(source.stat().st_mtime, tz=UTC).isoformat(),
                "pages": len(reader.pages),
                "sha256": sha256(source),
                "encrypted": reader.is_encrypted,
                "extraction_errors": extraction_errors,
            }
        )
    payload = {
        "project": {
            "project_name": "5301 8th St E Roof Replacement",
            "project_no": "101716.01",
            "procurement_no": "072026-1044",
            "owner": "Port of Tacoma",
            "stated_bid_time": "2026-10-29 14:00 America/Los_Angeles - pending source confirmation",
        },
        "generated_utc": datetime.now(UTC).isoformat(),
        "documents": documents,
        "evidence": {key: rows for key, rows in all_evidence.items() if rows},
    }
    config.audit_dir.mkdir(parents=True, exist_ok=True)
    (config.audit_dir / "document_inventory.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_audit(config: ProjectConfig) -> dict[str, Any]:
    path = config.audit_dir / "document_inventory.json"
    if not path.exists():
        return audit(config)
    return json.loads(path.read_text(encoding="utf-8"))


def validate_source_integrity(config: ProjectConfig) -> list[dict[str, str]]:
    manifest = load_audit(config)
    results = []
    for item in manifest["documents"]:
        current = config.root / item["path"]
        actual = sha256(current) if current.exists() else "MISSING"
        results.append({"document": item["name"], "expected": item["sha256"], "actual": actual, "status": "PASS" if actual == item["sha256"] else "FAIL"})
    return results
