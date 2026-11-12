#!/usr/bin/env python3
"""S&S internal Cost Analysis — Metal Fabrications Only (seven-section, WSJ-style).

Reuses the reportlab helpers from ``tools/ss_commercial_deliveries`` so the PDF
styling is not duplicated.  This document is **always internal and DRAFT**; it is
never authorized or submitted by itself.  The client-facing total lives in
:mod:`tools.a1_proposal` and shows only the single Lump Sum.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, Spacer, PageBreak

import ss_commercial_deliveries as ss  # sibling helpers (_pdf, _table, _p, DRAFT)


def _fmt(n) -> str:
    return "—" if n is None else f"${n:,.2f}"


def build_internal(envelope: dict, project_name: str, out_dir: Path,
                   contractor: dict | None = None) -> str:
    styles = getSampleStyleSheet()
    story = []
    ss._story_header(story, styles, contractor or {},
                     project_name, "Cost Analysis — Internal · Metal Fabrications Only")
    ss._p(story, styles, ss.DRAFT, "Title")
    ss._p(story, styles, f"As of: {envelope.get('as_of')} · Envelope: {envelope.get('envelope')}")
    ss._p(story, styles, f"Delivery state: {envelope.get('delivery_state')} — {envelope.get('state_reason')}")
    ss._p(story, styles, "Interne. No distribuir al cliente. No se autoriza ni se envía automáticamente.")
    story.append(PageBreak())

    sec = envelope["sections"]
    tot = envelope["totals"]

    # 1. Scope ------------------------------------------------------------------
    ss._p(story, styles, "1. Full Scope of Work — Metal (Base Bid Only)", "Heading2")
    ss._p(story, styles, f"Scope status: {sec['1_scope']['scope_status'] or '—'}")
    for it in sec["1_scope"]["metal_items"]:
        ss._p(story, styles, f"{it['id']} — {it['item']}: {it['quantity'] or 'PENDING MEASUREMENT'} "
                             f"{it.get('unit') or ''} [{it['measurement_status']}] ({it.get('pricing_scope') or ''})")

    # 2. Quantity take-off --------------------------------------------------------
    ss._p(story, styles, "2. Quantity Take-off & Correct Measurements", "Heading2")
    tq = sec["2_quantity_takeoff"]
    rows = []
    for it in tq["measured"]:
        rows.append([it["id"], it["item"], it.get("unit"), it["quantity"], "MEASURED"])
    for it in tq["pending_measurement"]:
        rows.append([it["id"], it["item"], it.get("unit"), "PENDING", "PENDING MEASUREMENT"])
    ss._table(story, styles, ["ID", "Item", "Unit", "Qty", "Status"], rows, widths=[70, 230, 50, 60, 90])
    ss._p(story, styles, f"Metal identified: {tq['count_identified']} · measured: "
                         f"{tq['count_measured']} · pending: {tq['count_pending_measurement']}")

    # 3. Material pricing ----------------------------------------------------------
    ss._p(story, styles, "3. Material Pricing", "Heading2")
    mrows = []
    for m in sec["3_material_pricing"]:
        mrows.append([m["id"], m["item"], m.get("unit"), m.get("quantity"),
                      m["price_class"] or "—", _fmt(m["unit_price"]), _fmt(m["extended"]),
                      m["status"]])
    ss._table(story, styles, ["ID", "Item", "Unit", "Qty", "Class", "Unit", "Extended", "Status"],
              mrows, widths=[60, 170, 40, 50, 90, 60, 70, 60])
    ss._p(story, styles, f"Materials subtotal (complete only): {_fmt(tot['materials_total'])}")

    # 4. Labor ---------------------------------------------------------------------
    ss._p(story, styles, "4. Labor — Prevailing Wage", "Heading2")
    lab = sec["4_labor"]
    ss._p(story, styles, f"Labor status: {lab['status']} · cost: {_fmt(lab['cost'])}")
    ss._p(story, styles, f"Wage basis / evidence: {lab['wage_basis'] or 'PENDING'}")
    ss._p(story, styles, f"Evidence present: {lab['evidence_present']}")

    # 5. Office, Fees & Equipment --------------------------------------------------
    ss._p(story, styles, "5. Office, Fees & Equipment", "Heading2")
    eq = sec["5_office_fees_equipment"]
    ss._p(story, styles, f"Equipment status: {eq['status']} · cost: {_fmt(eq['cost'])}")
    ss._p(story, styles, f"Equipment documented as: {eq.get('state') or eq['status']}")

    # 6. Price build-up (internal) ---------------------------------------------------
    ss._p(story, styles, "6. Price Build-up (internal)", "Heading2")
    pb = sec["6_price_buildup"]
    b_rows = [
        ["Materials", _fmt(pb.get("materials_total"))],
        ["Labor (loaded)", _fmt(pb.get("labor_cost"))],
        ["Equipment", _fmt(pb.get("equipment_cost"))],
        ["Direct cost", _fmt(pb.get("direct_cost"))],
        ["Contingency", _fmt(pb.get("contingency"))],
        ["Overhead", _fmt(pb.get("overhead"))],
        ["Profit", _fmt(pb.get("profit"))],
        ["Markup basis", pb.get("markup_basis") or "PENDING"],
        ["Cost-based total", _fmt(pb.get("cost_based_total"))],
        ["Price adjustment (owner-directed)", _fmt(pb.get("price_adjustment"))],
    ]
    ss._table(story, styles, ["Component", "Amount"], b_rows, widths=[260, 120])

    # 7. Risks & checks ---------------------------------------------------------------
    ss._p(story, styles, "7. Risks & Checks Before Sending", "Heading2")
    for b in envelope["blockers"]:
        ss._p(story, styles, "• " + b)
    ss._p(story, styles, f"Provisional reference prices used: {envelope['provisional_used'] or 'none'}")
    ss._p(story, styles, f"Final releasable: {envelope['final_releasable']} · Authorized: {envelope['authorized']}")
    ss._p(story, styles, "Este documento es un borrador interno (DRAFT). No constituye oferta.")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "Cost_Analysis_Internal_Metal_Fab.pdf"
    return ss._pdf(out, f"{project_name} — Cost Analysis (Internal)", story)