#!/usr/bin/env python3
"""S&S -> A-1 proposal — Metal Fabrications Only, client-safe.

The client-facing document reveals **only** the commercial scope (Metal
Fabrications Only) and the price:

* FINAL_RELEASED        -> a single **Total Lump Sum** (authorized, validated).
* BUDGETARY_PRELIMINARY -> an evidence-based **range**, clearly labelled
  "NOT A FIRM QUOTE".
* INTERNAL_BLOCKED      -> no commercial document is produced (returns None).

No unit prices, no margins, no internal costs and no technical/internals status
(PENDING QUOTE / PENDING MEASUREMENT / PENDING SOURCE, nulls, empty fields) are
ever written into the client PDF.  Reuses the reportlab helpers from
``tools/ss_commercial_deliveries`` and the clean ``client_view`` projection.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.styles import getSampleStyleSheet

import ss_commercial_deliveries as ss


def _fmt(n) -> str:
    return "—" if n is None else f"${n:,.2f}"


def build_proposal(envelope: dict, project_name: str, out_dir: Path,
                   contractor: dict | None = None) -> str | None:
    from bidkit.lumpsum_cost import client_view

    view = client_view(envelope)
    if view["delivery_state"] == "INTERNAL_BLOCKED":
        return None  # no commercial emission for a blocked dossier

    styles = getSampleStyleSheet()
    story = []
    ss._story_header(story, styles, contractor or {},
                     project_name, "Bid Proposal — A-1 Landscaping")

    ss._p(story, styles, view["status"], "Title")
    ss._p(story, styles, f"Scope: {view['scope']}")
    ss._p(story, styles, f"For: {view['proposal_for']} · {view['contractor']}")

    ss._p(story, styles, "Included scope (Metal Fabrications Only)", "Heading2")
    scope_s = envelope.get("sections", {}).get("2_quantity_takeoff", {}).get("measured", [])
    for it in scope_s:
        ss._p(story, styles, f"{it['id']} — {it['item']}: {it['quantity']} {it.get('unit') or ''}")

    ss._p(story, styles, "Total", "Heading2")
    if view["delivery_state"] == "FINAL_RELEASED":
        ss._p(story, styles, f"TOTAL LUMP SUM TO {view['proposal_for'].upper()}: "
                             f"{view['total_lump_sum_display']}")
    elif view["delivery_state"] == "BUDGETARY_PRELIMINARY":
        ss._p(story, styles, "BUDGETARY ESTIMATE (NOT A FIRM QUOTE): "
                             f"{view['budget_display']}")
        ss._p(story, styles, "This is an indicative range for planning only and shall "
                             "not be treated as a binding quotation.")

    ss._p(story, styles, "This document does not grant any right and is not a binding "
                         "offer; it is provided for review purposes only.")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "Bid_Proposal_A1_Metal_Fab.pdf"
    return ss._pdf(out, f"{project_name} — Proposal to A-1", story)