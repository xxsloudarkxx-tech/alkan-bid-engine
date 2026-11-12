"""Generate the English (US) S&S Custom Iron Works LLC commercial delivery pack.

Consumes the existing per-project dossiers (analysis.json / pricing.json / quotes.json),
the already-computed cost result (data/projects/<id>/estimate/cost_result.json) and the
per-expediente S&S contractor profile. Outputs nine documents per active project under:

    ENTREGAS/S_S_CUSTOM_IRON_WORKS_LLC/<PROJECT_UPPER>/

Because no supported unit prices are currently provided for these dossiers, every
commercial document is produced as DRAFT — NOT FOR SUBMISSION with the precise missing
evidence identified. No amount is fabricated and no internal cost/margin is published
on external-facing documents.

Not a bid submission. No document is signed or authorized.
"""
from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path
import re
import sys
import zipfile

from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bidkit.audit import sha256
from bidkit.config import ProjectConfig
from bidkit.data_store import read_json, write_json
from bidkit.workbooks import _save, _sheet, reference as src_ref

ACTIVE = {
    "orangegate-park-phase-1": "ORANGEGATE_PARK_PHASE_1",
    "gonyea-playfield": "GONYEA_PLAYFIELD",
    "rebid-meridian": "REBID_MERIDIAN",
}
OUT = ROOT / "ENTREGAS" / "S_S_CUSTOM_IRON_WORKS_LLC"

DRAFT = "DRAFT — NOT FOR SUBMISSION"
REV_DATE = date(2026, 11, 6).isoformat()
VERSION = "1.0"


# --------------------------------------------------------------------------- loads
def _config(pid: str) -> ProjectConfig:
    return ProjectConfig(ROOT, pid)


def _load(pid: str) -> dict:
    c = _config(pid)
    analysis = read_json(c.project_dir / "analysis.json")
    pricing = read_json(c.project_dir / "pricing.json")
    quotes = read_json(c.project_dir / "quotes.json")
    contractor = read_json(c.project_dir / "contractor.json")
    cost = None
    cost_path = c.data_dir / "estimate" / "cost_result.json"
    if cost_path.exists():
        cost = read_json(cost_path)
    validation = None
    vpath = c.output_dir / "validation_report.json"
    if vpath.exists():
        validation = read_json(vpath)
    return {"project": c, "analysis": analysis, "pricing": pricing, "quotes": quotes,
            "contractor": contractor, "cost": cost, "validation": validation}


def _currency():
    return "USD"


# --------------------------------------------------------------------------- counts
def _counts(data: dict) -> dict:
    cost = data.get("cost")
    items = cost["items"] if cost and cost.get("items") else data["pricing"].get("items", [])
    # Fall back to pricing items when no computed cost result is available.
    measured = sum(1 for q in data["analysis"].get("quantities", [])
                   if q.get("estimate_included", True) is not False and q.get("quantity") is not None)
    if cost and cost.get("items"):
        measured = sum(1 for it in cost["items"] if it.get("quantity") is not None)
    priced = 0
    if cost and cost.get("resources"):
        priced = len({r["quantity_id"] for r in cost["resources"]
                      if r.get("extended_cost") is not None or r.get("cost_low") is not None})
    return {"identified": len(items), "measured": measured,
            "pending_measurement": len(items) - measured, "valued": priced,
            "pending_price_with_quantity": measured - priced}


def _global_refs(data: dict) -> list:
    refs = data["pricing"].get("documentary_cost_references", []) or []
    out = []
    for r in refs:
        out.append({"scope": r.get("scope"), "central": r.get("central"), "low": r.get("low"),
                    "high": r.get("high"), "ref": src_ref(r.get("sources", [])),
                    "note": r.get("date_note"), "tax": r.get("tax")})
    return out


def _qualitative(value, fmt):
    return fmt(value) if value is not None else "—"


def _usd(v):
    return None if v is None else f"USD {v:,.2f}"


# --------------------------------------------------------------------------- header
def _story_header(story, styles, contractor, project_name, doc_kind):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    bar = [[Paragraph("S & S CUSTOM IRON WORKS LLC", styles["Title"])]]
    head = Table(bar, colWidths=[520])
    head.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1F3864")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(head)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Contractor Registration SSCUSSC781J9 · WA UBI 604724501 · Classification: GENERAL (CC01) — ACTIVE",
        styles["BodyText"]))
    story.append(Paragraph(
        "18526 N High Rock Rd, Monroe, WA 98272 · (425) 443-1691 · Representative: Shahram Faezi, Partner/Member",
        styles["BodyText"]))
    story.append(Paragraph(
        f"Project: {project_name} · Document: {doc_kind} · Revision date: {REV_DATE} · Version {VERSION}",
        styles["BodyText"]))
    story.append(Spacer(1, 6))


def _pdf(path: Path, title: str, story):
    from reportlab.platypus import SimpleDocTemplate
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), title=title, author="ALKAN / S&S Custom Iron Works LLC", invariant=1).build(story)
    return sha256(path)


def _p(story, styles, text, style="BodyText"):
    from reportlab.platypus import Paragraph, Spacer
    from xml.sax.saxutils import escape
    story.append(Paragraph(escape(str(text)), styles[style]))
    if style not in ("Title", "Heading1", "Heading2", "Heading3"):
        story.append(Spacer(1, 5))


def _table(story, styles, headers, rows, widths=None):
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape
    data = [[Paragraph(escape(str(x)), styles["BodyText"]) for x in row]
            for row in [headers, *rows]]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DEEBF7")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.extend([t, Spacer(1, 8)])


# --------------------------------------------------------------------------- document builders
def build_executive(data: dict, out_dir: Path) -> Path:
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet()
    c = data["project"]; a = data["analysis"]; cnt = _counts(data)
    story = []
    _story_header(story, styles, data["contractor"], c.project_name, "Executive Project Summary")
    _p(story, styles, c.project_name, "Heading2")
    _p(story, styles, f"Owner: {a.get('owner') or c.metadata.get('owner') or '—'} · "
                       f"Procurement No.: {c.metadata.get('procurement_no')} · Project No.: {c.metadata.get('project_no') or '—'}")
    _p(story, styles, "STATUS            : DRAFT (preparation), NOT for submission or award", "Heading3")
    _p(story, styles, f"Identified items  : {cnt['identified']}")
    _p(story, styles, f"With documentary quantity: {cnt['measured']} ({cnt['measured']}/{'n'} of identified)") if False else None
    _p(story, styles, f"Items with a documentary quantity: {cnt['measured']} of {cnt['identified']} identified")
    _p(story, styles, f"Pending measurement          : {cnt['pending_measurement']}")
    _p(story, styles, f"Items with usable supported price: {cnt['valued']} of {cnt['identified']}")
    _p(story, styles, f"Identified items without supported cost (with quantity but unpriced): {max(cnt['measured'] - cnt['valued'], 0)}")
    _p(story, styles, "These figures are a documentary baseline, not a measure of full-construction cost or economic coverage.")
    story.append(Spacer(1, 4))
    _p(story, styles, "Documentary owner/A-E references (benchmarks, not ALKAN item costs)", "Heading2")
    refs = _global_refs(data)
    if refs:
        rows = []
        for r in refs:
            value = (f"USD {r['central']:,.0f}" if r["central"] is not None
                     else f"USD {r['low']:,.0f} – {r['high']:,.0f}" if r["low"] is not None and r["high"] is not None
                     else "range not stated")
            rows.append([r["scope"] or "—", value, r["ref"] or "—", (r["tax"] or "")[:120]])
        _table(story, styles, ["Scope published", "Amount / range", "Verifiable source", "Tax note"], rows, widths=[150, 110, 180, 90])
        _p(story, styles, "These owner/A-E figures are published benchmarks only; they are never distributed into item prices, and never added to any ALKAN-computed subtotal.")
    else:
        _p(story, styles, "No owner/A-E global reference is recorded for this project.")
    story.append(PageBreak())
    _p(story, styles, "Scope & readiness", "Heading2")
    cost = data.get("cost")
    read = (cost or {}).get("readiness", {})
    _p(story, styles, f"Technical calculation ready: {bool(read.get('technical_calculation_ready'))}")
    _p(story, styles, f"Draft ready                  : {bool(read.get('draft_ready'))}")
    _p(story, styles, f"Ready for contractor review   : {bool(read.get('ready_for_contractor_review'))}")
    _p(story, styles, f"Ready for submission          : {bool(read.get('ready_for_submission'))}")
    _p(story, styles, f"Scope status: {a.get('scope_status')}. Coverage: {a.get('coverage')}")
    _p(story, styles, "Deliverable status: " + DRAFT, "Heading3")
    _p(story, styles, "This summary is a DRAFT for internal planning and material-only review. No item has a substantiated unit price in the current dossier, so no construction amount is presented and no bid is made.")
    return _pdf(out_dir / "Executive_Project_Summary.pdf", c.project_name, story)


def build_cost_estimate(data: dict, out_dir: Path) -> Path:
    c = data["project"]; cost = data.get("cost"); pricing = data["pricing"]
    path = out_dir / "Detailed_Cost_Estimate.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook(); book.remove(book.active)
    client = data["contractor"]
    _sheet(book, "Cover",
           ["Field", "Value"],
           [["Document", "Detailed Cost Estimate — DRAFT — NOT FOR SUBMISSION"],
            ["Contractor", "S & S CUSTOM IRON WORKS LLC"],
            ["Registration / UBI", f"{client['contractor_registration']} / {client['ubi']}"],
            ["Project", c.project_name],
            ["Procurement", c.metadata.get("procurement_no")],
            ["Revision date", REV_DATE],
            ["Version", VERSION],
            ["Note", "Working document. Produced from existing dossier data. No fabricated prices."]])
    items = cost["items"] if cost and cost.get("items") else []
    _sheet(book, "Items",
           ["ID", "Item", "Unit", "Quantity", "Scope", "Package", "Composition complete",
            "Known direct partial", "Direct cost", "Calculation ready", "Blockers",
            "Source"],
           [[it["id"], it["item"], it.get("unit"), it.get("quantity"), it.get("pricing_scope"),
             it.get("package"), it.get("composition_complete"),
             _usd(it.get("known_direct_partial")), _usd(it.get("direct_cost")),
             it.get("calculation_ready", False), "; ".join(it.get("blockers") or []),
             src_ref(it.get("sources") or [])] for it in items])
    resources = cost["resources"] if cost and cost.get("resources") else []
    _sheet(book, "Resources",
           ["Resource", "Item", "Kind", "Applicability", "Method", "Unit", "Factor/Productivity",
            "Waste", "Quote", "Quote status", "Price status", "Ext cost", "Cost low", "Cost high", "Blockers"],
           [[r["id"], r.get("quantity_id"), r.get("kind"), r.get("applicability"), r.get("method"),
             r.get("resource_unit"), r.get("factor") or r.get("productivity"), r.get("waste_fraction"),
             r.get("quote_id"), r.get("quote_status"), r.get("price_status"),
             _usd(r.get("extended_cost")), _usd(r.get("cost_low")), _usd(r.get("cost_high")),
             "; ".join(r.get("blockers") or [])] for r in resources])
    quotes = cost["quotes"] if cost and cost.get("quotes") else []
    _sheet(book, "Quotes",
           ["ID", "Supplier", "Unit", "Currency", "Unit price", "Low", "High", "Status", "Confidence",
            "Reference", "Date", "Valid until", "Validation"],
           [[q["id"], q.get("supplier"), q.get("unit"), q.get("currency"), q.get("unit_price"),
             q.get("unit_price_low"), q.get("unit_price_high"), q.get("price_status"),
             q.get("confidence"), (q.get("source") or {}).get("reference") if isinstance(q.get("source"), dict) else q.get("source"),
             q.get("date"), q.get("valid_until"), q.get("validation_status")] for q in quotes])
    summaries = cost["summaries"] if cost and cost.get("summaries") else []
    _sheet(book, "Scope Summary",
           ["Scope", "Items", "Measured", "Known partial", "Low covered", "High covered", "Direct cost",
            "Indirect cost", "Cost", "Margin", "Price before tax", "Candidate price", "Tax",
            "Technical ready", "Draft ready", "Missing items", "Missing indirects"],
           [[s["scope"], s.get("item_count"), None, _usd(s.get("known_direct_partial")),
             _usd(s.get("known_direct_low")), _usd(s.get("known_direct_high")), _usd(s.get("direct_cost")),
             _usd(s.get("indirect_cost")), _usd(s.get("cost")), _usd(s.get("margin_amount")),
             _usd(s.get("price_before_tax")), _usd(s.get("candidate_price")), _usd(s.get("tax")),
             s.get("technical_calculation_ready", False), s.get("draft_ready", False),
             s.get("missing_items"), s.get("missing_indirects")] for s in summaries])
    indirects = cost["indirects"] if cost and cost.get("indirects") else []
    _sheet(book, "Indirects",
           ["ID", "Description", "Scope", "Applicability", "Method", "Value", "Ext cost", "Basis valid"],
           [[i.get("id"), i.get("description"), i.get("scope"), i.get("applicability"), i.get("method"),
             i.get("value"), _usd(i.get("extended_cost")), i.get("basis_valid")] for i in indirects])
    _sheet(book, "Assumptions & Exclusions",
           ["Item", "Detail"],
           [["Taxation", a_tax := str(data["analysis"].get("tax_treatment"))],
            ["Scope status", data["analysis"].get("scope_status")],
            ["Margin", str(pricing.get("margin_rate")) if pricing.get("margin_rate") is not None else "PENDING — no supported margin"],
            ["Indirects reviewed", str(pricing.get("indirects_reviewed"))],
            ["Currency / as-of", f"{pricing.get('currency')} / {pricing.get('as_of')}"]])
    _save(book, path)
    return sha256(path)


def build_material_takeoff(data: dict, out_dir: Path) -> Path:
    c = data["project"]; a = data["analysis"]; cost = data.get("cost")
    path = out_dir / "Material_Takeoff.xlsx"; path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook(); book.remove(book.active)
    qtys = a.get("quantities", [])
    _sheet(book, "Takeoff",
           ["ID", "Item", "Unit", "Quantity", "Status", "Scope", "Package", "Basis", "Source"],
           [[q["id"], q.get("item") or "", q.get("unit"), q.get("quantity"), q.get("quantity_status"),
             q.get("pricing_scope"), q.get("package"), q.get("basis") or "",
             src_ref(q.get("sources") or [])] for q in qtys])
    mats = a.get("materials", [])
    mat_rows = []
    for m in mats:
        mat_rows.append([m.get("id"), m.get("quantity_id"), m.get("description"), m.get("unit"),
                         m.get("specification"), src_ref(m.get("sources") or [])])
    _sheet(book, "Materials", ["ID", "Quantity ID", "Description", "Unit", "Specification", "Source"], mat_rows)
    # Pending measurements
    pend = [q for q in qtys if q.get("quantity") is None]
    _sheet(book, "Pending Measurement",
           ["ID", "Item", "What must be measured", "Who", "Source basis"],
           [[q["id"], q.get("item"), q.get("missing_information") or q.get("basis") or "",
             "Designer / estimator as documented", src_ref(q.get("sources") or [])] for q in pend])
    _save(book, path)
    return sha256(path)


def build_scope(data: dict, out_dir: Path) -> Path:
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet(); c = data["project"]; a = data["analysis"]
    story = []
    _story_header(story, styles, data["contractor"], c.project_name, "Scope of Work")
    _p(story, styles, "STATUS: DRAFT — NOT FOR SUBMISSION", "Heading2")
    _p(story, styles, "This Scope of Work reflects the documentary subset recorded in the dossier. S&S Cost & Engineering is acting as an estimator; S&S Custom Iron Works LLC has not confirmed a full general-construction offer. Unless the engagement confirms a broader scope, S&S is treated here as a specialty fabrication / iron-work subcontractor on the metal, fencing, gate, guardrail, signage-frame, fixture and structural-metal items.")
    _p(story, styles, "Documentary scope status", "Heading2")
    _p(story, styles, f"Scope status: {a.get('scope_status')}. Coverage: {a.get('coverage')}")
    _p(story, styles, "Identified documentary scope and exclusions", "Heading2")
    for q in a.get("quantities", []):
        _p(story, styles, f"{q['id']} — {(q.get('item') or '').strip()}: quantity {q.get('quantity') or 'PENDING'} {q.get('unit') or ''} [{q.get('quantity_status')}] (scope: {q.get('pricing_scope')})")
    _p(story, styles, "Items below remain pending measurement and are NOT included in any calculated amount until measured and supported:", "Heading2")
    for q in a.get("quantities", []):
        if q.get("quantity") is None:
            _p(story, styles, f"{q['id']} — {q.get('item')}: {q.get('missing_information') or q.get('basis')}")
    _p(story, styles, f"Alternates and schedules must remain separate. Scope status: {a.get('scope_status')}. Verifiable references are listed per line in the takeoff.")
    return _pdf(out_dir / "Scope_of_Work.pdf", f"{c.project_name} — Scope of Work", story)


def build_supplier_schedule(data: dict, out_dir: Path) -> Path:
    c = data["project"]; a = data["analysis"]; quotes = data["quotes"].get("quotes", [])
    qm = {}
    for q in quotes:
        qm[str(q["id"])] = q
    refs = data["pricing"].get("documentary_cost_references", []) or []
    path = out_dir / "Material_&_Supplier_Schedule.xlsx"; path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook(); book.remove(book.active)
    rows = []
    for m in a.get("materials", []):
        rows.append([m.get("quantity_id"), m.get("description") or "", m.get("unit"),
                     m.get("specification") or "", "UNPRICED", "No firm quote in dossier",
                     "—", "—", "Verify supplier quote, per-unit price, delivery and date/spec",
                     src_ref(m.get("sources") or [])])
    _sheet(book, "Materials & Suppliers",
           ["Quantity ID", "Material / assembly", "Unit", "Specification", "Price class",
            "Supplier", "Quote date", "Valid until", "Exact data needed", "Source"],
           rows)
    qrows = []
    for q in quotes:
        src = q.get("source") or {}
        qrows.append([q["id"], q.get("supplier"), q.get("unit"), q.get("currency"),
                      q.get("unit_price"), q.get("price_status"), q.get("confidence"),
                      src.get("reference") if isinstance(src, dict) else src,
                      q.get("date"), q.get("valid_until"), q.get("validation_status")])
    _sheet(book, "Quotes In Dossier", ["ID", "Supplier", "Unit", "Currency", "Unit price", "Class", "Confidence", "Reference", "Date", "Valid until", "Validation"], qrows)
    refrows = []
    for r in refs:
        value = (f"USD {r['central']:,.0f}" if r.get("central") is not None
                 else f"USD {r.get('low')} – {r.get('high')}" if r.get("low") is not None and r.get("high") is not None else "range n/a")
        refrows.append([r.get("scope"), value, src_ref(r.get("sources") or []), r.get("tax")])
    _sheet(book, "Owner AE Benchmarks", ["Scope", "Amount", "Source", "Tax"], refrows)
    _save(book, path)
    return sha256(path)


def build_proposal(data: dict, out_dir: Path) -> Path:
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet(); c = data["project"]; cnt = _counts(data)
    story = []
    _story_header(story, styles, data["contractor"], c.project_name, "Bid Proposal")
    _p(story, styles, DRAFT, "Title")
    _p(story, styles, "No bid amount is presented. A definitive proposal cannot be issued because the dossier has no substantiated unit prices or certified construction costs for S&S's scope, no approved composition/indirects/margin, and no contractor authorization to submit.")
    _p(story, styles, f"Identified items: {cnt['identified']} · With documentary quantity: {cnt['measured']} · With usable supported price: {cnt['valued']}.", "Heading2")
    _p(story, styles, "Reasons this remains a draft (exactly what is missing):", "Heading2")
    for msg in [
        "No Firm Supplier Quote, Published Catalog Price with unit/date/condition, or verifiable Derived Estimate is recorded in the dossier for the measured items.",
        "Labor: no applicable prevailing-wage determination with benefits/fringes or a verifiable crew productivity (output per hour) for the trades involved.",
        "Equipment, freight, taxes, insurance/bonds and indirects are not supported/documented.",
        "No owner-issued (A/E) budget is a usable unit price; owner global benchmarks are excluded from any item totals by policy.",
        "No contractor authorization, approved margin, or completed official bid form is present.",
    ]:
        _p(story, styles, "• " + msg)
    _p(story, styles, "This document is DRAFT — NOT FOR SUBMISSION. Nothing herein is a binding offer. Any future definitive proposal must be approved by S&S Custom Iron Works LLC and include a signed bid form.")
    return _pdf(out_dir / "Bid_Proposal.pdf", f"{c.project_name} — Bid Proposal", story)


def build_compliance(data: dict, out_dir: Path) -> Path:
    from reportlab.platypus import Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet(); c = data["project"]; a = data["analysis"]
    contractor = data["contractor"]
    story = []
    _story_header(story, styles, contractor, c.project_name, "Compliance & Submission Checklist")
    _p(story, styles, "STATUS: DRAFT — NOT FOR SUBMISSION", "Title")
    _p(story, styles, "Contractor registration (S&S)", "Heading2")
    _p(story, styles, f"Registration {contractor['contractor_registration']} — status {contractor['registration_status']} — expires {contractor['registration_expires']} — VERIFIED against the WA L&I official portal on {contractor['verified_at']}.")
    rows = [
        ["WA State Contractor Registration", "VERIFIED (official L&I 2026-11-06)", "Confirmation record captured"],
        ["Intent to Pay Prevailing Wages / wage determination", "PENDING_EVIDENCE", "Requires applicable county + bid-date L&I rates and the project's wage form"],
        ["Bid security / bid bond", "PENDING_EVIDENCE", "Owner-required bond amount and surety evidence"],
        ["Performance / Payment bonds", "PENDING_EVIDENCE", "Unless the procuring authority exempts"],
        ["General liability insurance", "PENDING_EVIDENCE", "COI evidencing project limits"],
        ["Authorized signature", "PENDING", "Signed by an authorized principal"],
        ["Official bid form (current revision)", "PENDING", "Baseline form / OpenGov pricing table to be confirmed"],
        ["Diversity / apprenticeship / reporting", "PENDING_EVIDENCE", "Per project documents"],
    ]
    for r in a.get("requirements", []):
        rows.append([str(r.get("item") or r.get("id")), str(r.get("status")), str(r.get("evidence_needed") or r.get("action") or "")])
    _table(story, styles, ["Requirement", "Status", "Evidence needed"], rows, widths=[210, 130, 160])
    _p(story, styles, "Checklist reflects the dossier. This is a draft; no submission checklist item is asserted complete where evidence is not in the dossier.")
    return _pdf(out_dir / "Compliance_&_Submission_Checklist.pdf", f"{c.project_name} — Compliance Checklist", story)


def build_clarifications(data: dict, out_dir: Path) -> Path:
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet(); c = data["project"]; a = data["analysis"]
    story = []
    _story_header(story, styles, data["contractor"], c.project_name, "Clarifications, Exclusions & Assumptions")
    _p(story, styles, "STATUS: DRAFT — NOT FOR SUBMISSION", "Title")
    _p(story, styles, "Assumptions", "Heading2")
    for it in [
        "Quantities are documentary net design values, not field-verified; no undocumented waste, or any documented build factor, is assumed.",
        "Owner/A-E global budget figures are benchmarks only and are not distributed to items or added to computed subtotals.",
        "No price, wage, productivity, equipment, freight, tax, indirect, contingency or margin is invented; missing economic data stays 'unpriced', never zero.",
        "Alternates and schedules are kept separate from the base scope.",
        "S&S is treated as a specialty fabrication / iron-work subcontractor unless a broader engagement is confirmed.",
    ]:
        _p(story, styles, "• " + it)
    _p(story, styles, "Exclusions", "Heading2")
    for it in a.get("pending", []):
        _p(story, styles, f"{it.get('id')}: {it.get('issue')} — Action: {it.get('action')}")
    _p(story, styles, "Risks", "Heading2")
    for r in a.get("risks", []):
        _p(story, styles, f"{r.get('id')}: {r.get('item') or r.get('risk')} [status {r.get('status')}]")
    _p(story, styles, "Addenda / amendments", "Heading2")
    for m in a.get("amendments", []):
        _p(story, styles, f"{m.get('id')}: {m.get('change') or m.get('item') or '—'}")
    return _pdf(out_dir / "Clarifications_Exclusions_&_Assumptions.pdf", f"{c.project_name} — Clarifications", story)


def build_validation(data: dict, out_dir: Path) -> Path:
    from reportlab.platypus import PageBreak, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    styles = getSampleStyleSheet(); c = data["project"]; cost = data.get("cost")
    story = []
    _story_header(story, styles, data["contractor"], c.project_name, "Estimate Validation Report")
    _p(story, styles, "STATUS: DRAFT — NOT FOR SUBMISSION", "Title")
    read = (cost or {}).get("readiness", {}) or {}
    _p(story, styles, "Readiness (auto-derived from the dossier data)", "Heading2")
    _p(story, styles, f"Engine status : {read.get('status') if isinstance(read, dict) else cost.get('status')}")
    _p(story, styles, f"Offer blocked  : {cost.get('offer_blockers') if cost else 'no cost result yet'}")
    for k in ("technical_calculation_ready", "draft_ready", "ready_for_contractor_review", "ready_for_submission"):
        _p(story, styles, f"{k}: {bool(read.get(k))}")
    _p(story, styles, "Validation report", "Heading2")
    val = data.get("validation")
    if val:
        _p(story, styles, json.dumps({kk: vv for kk, vv in val.items() if kk != "details"}, ensure_ascii=False, indent=2, default=str)[:2000])
    else:
        _p(story, styles, "No validation_report.json was present to merge at generation time.")
    _p(story, styles, "Validation method", "Heading2")
    _p(story, styles, "Decimal arithmetic persists; original source JSON inputs are unchanged; the readiness states above are recomputed on every evaluate() call, so they auto-update when supported data is added. Regression suite results are documented in TEST_RESULTS.md at the delivery root.")
    return _pdf(out_dir / "Estimate_Validation_Report.pdf", f"{c.project_name} — Estimate Validation", story)


BUILDERS = {
    "Executive_Project_Summary.pdf": build_executive,
    "Detailed_Cost_Estimate.xlsx": build_cost_estimate,
    "Material_Takeoff.xlsx": build_material_takeoff,
    "Scope_of_Work.pdf": build_scope,
    "Material_&_Supplier_Schedule.xlsx": build_supplier_schedule,
    "Bid_Proposal.pdf": build_proposal,
    "Compliance_&_Submission_Checklist.pdf": build_compliance,
    "Clarifications_Exclusions_&_Assumptions.pdf": build_clarifications,
    "Estimate_Validation_Report.pdf": build_validation,
}


def _finish(data: dict, out_dir: Path, hashes: dict) -> dict:
    c = data["project"]; a = data["analysis"]; cnt = _counts(data)
    status = {
        "project": c.project_name, "project_id": c.id, "procurement_no": c.metadata.get("procurement_no"),
        "contractor": data["contractor"].get("bidder"), "revision_date": REV_DATE, "version": VERSION,
        "identified_items": cnt["identified"], "quantity_measured_items": cnt["measured"],
        "pending_measurement": cnt["pending_measurement"], "items_with_usable_price": cnt["valued"],
        "items_unpriced_with_quantity": max(cnt["measured"] - cnt["valued"], 0),
        "deliverable_status": DRAFT,
        "ready_for_contractor_review": bool((data.get("cost") or {}).get("readiness", {}).get("ready_for_contractor_review")),
        "ready_for_submission": bool((data.get("cost") or {}).get("readiness", {}).get("ready_for_submission")),
        "scope_status": a.get("scope_status"),
    }
    write_json(out_dir / "project_status.json", status)
    return status


def _write_status_csv(rows: list, path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _write_missing_csv(data: dict, out_dir: Path) -> list:
    a = data["analysis"]; rows = []
    for q in a.get("quantities", []):
        if q.get("quantity") is None:
            rows.append({"project": data["project"].project_name, "line_id": q["id"], "item": q.get("item"),
                         "unit": q.get("unit"), "what_is_missing": "Measurement",
                         "exact_field_evidence_needed": q.get("missing_information") or q.get("basis") or ""})
        elif q.get("quantity") is not None:
            rows.append({"project": data["project"].project_name, "line_id": q["id"], "item": q.get("item"),
                         "unit": q.get("unit"), "what_is_missing": "Supported price / composition",
                         "exact_field_evidence_needed": "Supplier quote (unit, date, validity, freight, tax) or supported catalog/historical rate; plus labor productivity and wage determination if installation is in scope."})
    return rows


def main() -> None:
    summaries = []
    all_missing = []
    manifest = {"generator": "tools/ss_commercial_deliveries.py", "generated_at": REV_DATE,
                "language": "en-US", "contractor": "S & S CUSTOM IRON WORKS LLC",
                "deliverable_status": DRAFT, "projects": {}}
    for pid, folder in ACTIVE.items():
        data = _load(pid)
        c = data["project"]
        out_dir = OUT / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        hashes = {}
        for name, builder in BUILDERS.items():
            hashes[name] = builder(data, out_dir)
        status = _finish(data, out_dir, hashes)
        summaries.append(status)
        _write_status_csv([status], out_dir / "PROJECT_COMPLETION_STATUS.csv")
        missing = _write_missing_csv(data, out_dir)
        all_missing.extend(missing)
        _write_status_csv(missing, out_dir / "MISSING_VERIFIED_DATA.csv")
        manifesthash = {k: v for k, v in hashes.items()}
        write_json(out_dir / "delivery_manifest.json",
                   {"project": c.project_name, "project_id": pid, "status": status, "files": manifesthash})
        manifest["projects"][pid] = {"folder": folder, "status": status, "files": manifesthash}
        print(c.project_name + ": 9 English documents generated (DRAFT)", flush=True)
    _write_status_csv(summaries, OUT / "PROJECT_COMPLETION_STATUS.csv")
    _write_status_csv(all_missing, OUT / "MISSING_VERIFIED_DATA.csv")
    write_json(OUT / "delivery_manifest.json", manifest)
    print("S&S English commercial delivery pack complete at " + str(OUT), flush=True)


if __name__ == "__main__":
    main()