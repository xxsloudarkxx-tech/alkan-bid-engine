"""Metal Fabrications Only scope extraction from a dossier's analysis.json.

Conservative, keyword-based classification of line items as metal-fabrication
scope, keeping a strict guard against false positives (e.g. ``bench`` or
``split rail fence`` that may be wood).  Items that match are tagged; their
measured documentary quantity is taken from the dossier, and anything without
a quantity stays **PENDING MEASUREMENT**.  No measurement or price is invented.
"""
from __future__ import annotations

import re

# Terms that indicate a metal-fabrication line item.  Short/ambiguous terms are
# matched as whole words to avoid catching unrelated items.
_METAL_TERMS = (
    "fence", "gate", "railing", "handrail", "guardrail", "bollard",
    "receptacle", "bike", "sign", "steel", "metal", "chain-link", "structural",
    "canopy", "grating", "waste",
)

# Terms that, even when a metal term is present, indicate a NON-metal scope
# (e.g. wood fence, soft landscaping) for this subcontractor.
_EXCLUDE_HINTS = (
    "plant", "tree", "seed", "mulch", "shrub", "turf", "sod", "irrigation",
    "soil", "boulder", "log", "brush", "paving", "catch basin", "storm",
    "concrete", "curb", "asphalt", "gravel", "rock", "grout",
    "split rail", "post-and-rail", "post & rail", "wood", "lumber",
)

_PATTERNS = [re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in _METAL_TERMS]
_EXCLUDE = [re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE) for t in _EXCLUDE_HINTS]


def is_metal(text: str | None) -> bool:
    """Return True if the line-item text indicates metal-fabrication scope."""
    if not text:
        return False
    if any(p.search(text) for p in _EXCLUDE):
        return False
    return any(p.search(text) for p in _PATTERNS)


def tag_items(analysis: dict) -> list[dict]:
    """Tag every dossier quantity record with its metal classification."""
    out = []
    for q in analysis.get("quantities", []):
        item = (q.get("item") or "")
        matched = is_metal(item)
        measured = q.get("quantity") is not None
        out.append({
            "id": q.get("id"),
            "item": item,
            "unit": q.get("unit"),
            "quantity": q.get("quantity"),
            "quantity_status": q.get("quantity_status"),
            "pricing_scope": q.get("pricing_scope"),
            "package": q.get("package"),
            "basis": q.get("basis"),
            "metal": matched,
            "matched_term": _matched_terms(item),
            "measured": measured,
            "measurement_status": "MEASURED" if measured else "PENDING MEASUREMENT",
        })
    return out


def _matched_terms(text: str) -> list[str]:
    terms = []
    for t, pat in zip(_METAL_TERMS, _PATTERNS):
        if pat.search(text):
            terms.append(t)
    return terms


def metal_scope(analysis: dict) -> dict:
    """Split a dossier into metal scope (measured / pending) and excluded items."""
    items = tag_items(analysis)
    metals = [i for i in items if i["metal"]]
    return {
        "items": items,
        "metal_items": metals,
        "metal_measured": [i for i in metals if i["measured"]],
        "metal_pending_measurement": [i for i in metals if not i["measured"]],
        "count_identified": len(metals),
        "count_measured": sum(1 for i in metals if i["measured"]),
        "count_pending_measurement": sum(1 for i in metals if not i["measured"]),
    }