"""Drawing revision comparison and specification-vs-drawing inconsistency detector."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

_FINISH_TOKENS: dict[str, tuple[str, ...]] = {
    "hot_dip_galvanized": ("hot-dip galv", "hot dip galv", "astm a123", "astm a153", "galvanized"),
    "painted_enamel": ("powder coat", "shop paint", "alkyd enamel", "painted finish"),
    "stainless_316": ("stainless steel 316", "type 316", "316 ss"),
    "aluminum": ("aluminum", "6061-t6", "5052-h32"),
}

_BID_DATE_RE = re.compile(r"(?i)(?:bids?\s+due|bid\s+opening|receipt)[:\s]+([A-Za-z]+\s+\d{1,2},\s+\d{4}(?:\s*,?\s*\d{1,2}:\d{2}\s*(?:AM|PM))?)")


@dataclass(frozen=True)
class RevisionFinding:
    finding_type: str
    severity: str
    sheet_or_section: str
    base_value: str
    revised_value: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compare_sheet_sets(
    base_sheets: list[dict[str, Any]],
    revised_sheets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare two inspected drawing sets (by sheet_id) and report added, removed, and changed sheets."""
    base_map = {str(s.get("sheet_id") or f"P{s.get('page')}"): s for s in base_sheets}
    rev_map = {str(s.get("sheet_id") or f"P{s.get('page')}"): s for s in revised_sheets}

    added = sorted(set(rev_map) - set(base_map))
    removed = sorted(set(base_map) - set(rev_map))
    findings: list[dict[str, Any]] = []

    for sid in added:
        findings.append(RevisionFinding(
            finding_type="sheet_added",
            severity="MEDIUM",
            sheet_or_section=sid,
            base_value="",
            revised_value=sid,
            detail=f"Sheet {sid} added in revised set.",
        ).to_dict())

    for sid in removed:
        findings.append(RevisionFinding(
            finding_type="sheet_removed",
            severity="HIGH",
            sheet_or_section=sid,
            base_value=sid,
            revised_value="",
            detail=f"Sheet {sid} present in base set is missing from revised set.",
        ).to_dict())

    for sid in sorted(set(base_map) & set(rev_map)):
        b, r = base_map[sid], rev_map[sid]
        for field_name, ftype, sev in (
            ("revisions_detected", "revision_tag_changed", "MEDIUM"),
            ("scales_detected", "scale_changed", "HIGH"),
            ("spec_refs", "spec_reference_changed", "MEDIUM"),
            ("dimensions_sample", "dimension_callout_changed", "HIGH"),
        ):
            bv = sorted(set(b.get(field_name) or []))
            rv = sorted(set(r.get(field_name) or []))
            if bv != rv:
                findings.append(RevisionFinding(
                    finding_type=ftype,
                    severity=sev,
                    sheet_or_section=sid,
                    base_value=", ".join(bv),
                    revised_value=", ".join(rv),
                    detail=f"Sheet {sid} changed {field_name} between revisions.",
                ).to_dict())

    return {
        "added_sheets": added,
        "removed_sheets": removed,
        "common_sheets": len(set(base_map) & set(rev_map)),
        "findings": findings,
    }


def _detect_finishes(text: str) -> set[str]:
    low = (text or "").lower()
    found: set[str] = set()
    for tag, needles in _FINISH_TOKENS.items():
        if any(n in low for n in needles):
            found.add(tag)
    return found


def detect_spec_drawing_inconsistencies(
    spec_sections: list[dict[str, Any]],
    drawing_notes: list[dict[str, Any]],
    addenda: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Detect conflicts between specs, drawing notes, and addenda (finish, quantities, bid deadline)."""
    conflicts: list[dict[str, Any]] = []

    for spec in spec_sections:
        spec_key = str(spec.get("section") or spec.get("id") or "SPEC")
        spec_finishes = _detect_finishes(str(spec.get("text") or ""))
        if not spec_finishes:
            continue
        for note in drawing_notes:
            note_key = str(note.get("sheet") or note.get("id") or "DWG")
            # Match by explicit shared topic/scope keyword if present
            topic = str(note.get("scope") or "").lower()
            spec_scope = str(spec.get("scope") or "").lower()
            if topic and spec_scope and topic != spec_scope:
                continue
            note_finishes = _detect_finishes(str(note.get("text") or ""))
            if note_finishes and not (spec_finishes & note_finishes):
                conflicts.append(RevisionFinding(
                    finding_type="spec_vs_drawing_conflict",
                    severity="HIGH",
                    sheet_or_section=f"{spec_key} vs {note_key}",
                    base_value=", ".join(sorted(spec_finishes)),
                    revised_value=", ".join(sorted(note_finishes)),
                    detail=f"Finish/material mismatch between specification {spec_key} and drawing {note_key}.",
                ).to_dict())

            spec_qty = spec.get("declared_qty")
            note_qty = note.get("declared_qty")
            if spec_qty is not None and note_qty is not None and str(spec_qty) != str(note_qty):
                conflicts.append(RevisionFinding(
                    finding_type="quantity_conflict",
                    severity="CRITICAL",
                    sheet_or_section=f"{spec_key} vs {note_key}",
                    base_value=str(spec_qty),
                    revised_value=str(note_qty),
                    detail=f"Declared quantity mismatch between {spec_key} ({spec_qty}) and {note_key} ({note_qty}).",
                ).to_dict())

    addenda_dates: list[tuple[str, str]] = []
    for add in addenda or []:
        text = str(add.get("text") or "")
        m = _BID_DATE_RE.search(text)
        if m:
            addenda_dates.append((str(add.get("name") or add.get("addendum") or "Addendum"), m.group(1)))
    if len({d for _, d in addenda_dates}) > 1:
        conflicts.append(RevisionFinding(
            finding_type="addendum_bid_date_supersession",
            severity="MEDIUM",
            sheet_or_section="Addenda",
            base_value=f"{addenda_dates[0][0]}: {addenda_dates[0][1]}",
            revised_value=f"{addenda_dates[-1][0]}: {addenda_dates[-1][1]}",
            detail="Multiple bid due dates appear across addenda; verify latest governing addendum.",
        ).to_dict())

    return conflicts
