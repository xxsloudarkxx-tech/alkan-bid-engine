#!/usr/bin/env python3
"""Internal, unpriced bid review packs. Does not submit or release a bid.

Sources only the common project dossiers, not another bidder's costs.
The Tirzo legal bidder identity is intentionally UNCONFIRMED.
"""
from __future__ import annotations
import csv
import json
from datetime import date
from pathlib import Path
import sys
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bidkit.metal_scope import metal_scope
from bidkit.data_store import read_json

PROJECTS = ("orangegate-park-phase-1", "gonyea-playfield", "rebid-meridian")
BIDDERS = {
    "S_S_CUSTOM_IRON_WORKS_LLC": "S & S CUSTOM IRON WORKS LLC",
    "TIRZO_IDENTIDAD_PENDIENTE": "TIRZO / LEGAL BIDDER IDENTITY UNCONFIRMED",
}
OUTPUT = ROOT / "ENTREGAS" / "CONTROL_COMPETENCIA_2026-11-06"
REQUIRED = (
    "Confirm legal bidder identity, license, UBI and permission to act",
    "Verify project bid date and tender status against current addenda",
    "Review contract drawings and specifications for actual metal trade limits",
    "Obtain final quantities and separate base bid from alternates",
    "Obtain own firm supplier quotes with specification, unit, tax, freight and validity",
    "Estimate own labor hours using applicable wage determination and productivity",
    "Validate own equipment, site conditions, subcontractors and lead times",
    "Approve own contingency, overhead, profit and commercial exclusions",
    "Have authorized company representative review and approve before any release",
)

def para(text, style):
    return Paragraph(escape(str(text)), style)

def make_pdf(out, company, project, scope, is_tirzo):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallReview", parent=styles["BodyText"], fontSize=7.5, leading=10))
    styles.add(ParagraphStyle(name="TinyReview", parent=styles["BodyText"], fontSize=6.5, leading=9))
    styles.add(ParagraphStyle(name="CautionReview", parent=styles["BodyText"], fontSize=10, leading=14, textColor=colors.HexColor("#8C2E1A")))
    doc = SimpleDocTemplate(str(out), pagesize=letter, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    story = [para("METAL FABRICATIONS — INTERNAL BID READINESS REVIEW", styles["Title"]),
             Spacer(1, 8), para("DRAFT — NOT FOR SUBMISSION — NO PRICES AUTHORIZED", styles["CautionReview"]),
             Spacer(1, 6), para("Bidder: " + company, styles["Heading2"]),
             para("Project: " + project["name"], styles["BodyText"]),
             para("Procurement reference: " + str(project.get("procurement_no") or "Not confirmed"), styles["BodyText"]),
             para("Owner from dossier: " + str(project.get("owner") or "Not confirmed"), styles["BodyText"]),
             para("Created: " + date.today().isoformat(), styles["BodyText"]),
             Spacer(1, 8)]
    if is_tirzo:
        story.append(para("BLOCKED: Tirzo's legal entity, license, UBI and authorized signatory must be confirmed. No unverified company registration or license has been inserted.", styles["CautionReview"]))
    else:
        story.append(para("S&S identity is held in its separate verified contractor file. Contractor information and bid approvals must still be checked before release.", styles["BodyText"]))
    story += [Spacer(1, 10),
              para("Common project scope (NOT a bidder-specific price schedule)", styles["Heading2"]),
              para("Automatic metal screening from the original project dossier; trade scope, quantities, packages and addenda require human confirmation.", styles["SmallReview"]),
              Spacer(1, 5)]
    headers = ["Item ID", "Item description", "Qty / unit", "Treatment"]
    rows = [[para(x,styles["TinyReview"]) for x in headers]]
    for item in scope["metal_items"]:
        ref = str(item.get("id") or "")
        qty = (str(item.get("quantity")) if item.get("quantity") is not None else "TBD") + " " + str(item.get("unit") or "")
        treatment = "UNMEASURED / SPLIT SCOPE" if not item["measured"] else "VERIFY SPEC"
        if "alt" in str(item.get("item") or "").lower() or "alt" in str(item.get("pricing_scope") or "").lower():
            treatment += " / ALTERNATE"
        if ref.startswith("P-Q-"):
            treatment += " / MIXED LS"
        rows.append([para(ref,styles["TinyReview"]), para(item["item"],styles["TinyReview"]),
                     para(qty,styles["TinyReview"]), para(treatment,styles["TinyReview"])])
    tbl = Table(rows, colWidths=[74,256,83,127],repeatRows=1,hAlign="LEFT")
    tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E3EDF7")),
                            ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#A6B1BB")),
                            ("VALIGN",(0,0),(-1,-1),"TOP"),
                            ("TOPPADDING",(0,0),(-1,-1),4),
                            ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.extend([tbl,Spacer(1,9),
                  para(f"Identified metal-screened lines: {scope['count_identified']}; measured: {scope['count_measured']}; unmeasured: {scope['count_pending_measurement']}.",styles["BodyText"]),
                  para("Missing evidence to authorize a price",styles["Heading2"])])
    for ix,task in enumerate(REQUIRED,1):
        story.append(para(f"{ix}. [ ] {task}",styles["SmallReview"]))
    story.extend([Spacer(1,10),para("STRICT BIDDER SEPARATION",styles["Heading2"]),
                  para("Use only this bidder's own supplier quotes, direct costs, labor assumptions, markup decisions and authorized instructions. Do not transfer confidential pricing, margin targets or bid strategy between competing companies.",styles["SmallReview"]),
                  Spacer(1,12),para("Status: INTERNAL_BLOCKED — NOT A QUOTE; NOT READY TO SEND.",styles["CautionReview"])])
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story)

def make_csv(out, scope):
    cols = ["line_id","project_item","document_qty","unit","scope_type","scope_review","bidder_supplier",
            "bidder_unit_price_usd","quote_date","quote_valid_until","labor_hours","wage_basis",
            "equipment_cost_usd","freight_tax_basis","bidder_notes","reviewed_by"]
    with out.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols);w.writeheader()
        for it in scope["metal_items"]:
            req = "MIXED_LUMP_SUM_CONFIRM_METAL_PORTION" if str(it.get("id") or "").startswith("P-Q-") else ("PENDING_MEASUREMENT" if not it["measured"] else "CHECK_SPEC_AND_BASIS")
            w.writerow({"line_id":it.get("id"),"project_item":it.get("item"),"document_qty":it.get("quantity") if it["measured"] else "",
                        "unit":it.get("unit"),"scope_type":it.get("pricing_scope") or "REVIEW",
                        "scope_review":req})

def main():
    if OUTPUT.exists():
        raise RuntimeError(f"Output exists; refusing overwrite: {OUTPUT}")
    for bidder,company in BIDDERS.items():
        company_dir=OUTPUT/bidder
        company_dir.mkdir(parents=True,exist_ok=True)
        for slug in PROJECTS:
            project=read_json(ROOT/"projects"/slug/"project.json")
            analysis=read_json(ROOT/"projects"/slug/"analysis.json")
            scope=metal_scope(analysis)
            dest=company_dir/slug
            dest.mkdir(parents=True,exist_ok=True)
            make_pdf(dest/"01_SCOPE_READINESS_INTERNAL_DRAFT.pdf",company,project,scope,
                     bidder=="TIRZO_IDENTIDAD_PENDIENTE")
            make_csv(dest/"02_BIDDER_OWN_PRICING_INPUT_BLANK.csv",scope)
            with (dest/"03_REVIEW_STATUS.json").open("w",encoding="utf-8") as f:
                json.dump({"bidder":company,"project":project["name"],"project_id":slug,
                           "metal_lines":scope["count_identified"],
                           "measured_lines":scope["count_measured"],
                           "unmeasured_lines":scope["count_pending_measurement"],
                           "pricing_ready":False,"bid_authorized":False,
                           "status":"INTERNAL_BLOCKED",
                           "identity_confirmed":bidder=="S_S_CUSTOM_IRON_WORKS_LLC",
                           "note":"Unpriced drafts. Verify public source & addenda. No bid released."},f,indent=2)
    (OUTPUT/"README_LEEME.txt").write_text(
        "ALKAN — separate internal bidder workbooks, 2026-11-06.\n"
        "These files are NOT quotations or bids. No number has been guessed.\n"
        "S&S and Tirzo inputs are isolated: never move private pricing between them.\n"
        "Tirzo legal entity is NOT VERIFIED. Do not label as The Fabricator without checking.\n"
        "Original project, S&S exports, supplier reference zip and source documents are untouched.\n"
        "P-Q items are mixed lump-sum scopes and cannot be priced as all-metal.\n"
        "Check base vs alternates and all issued addenda against primary plans.\n"
        "Next action: own supplier RFQs, labor/equipment basis, verify quantities, approvals.\n",encoding="utf-8")
    for p in sorted(OUTPUT.rglob("*")):
        if p.is_file(): print(p.relative_to(ROOT),p.stat().st_size)
if __name__=="__main__":
    main()
