from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .contractor import PJ_ROOFING
from .records import AMENDMENTS, REQUIREMENTS, RISKS, TAKEOFF


def _source(row: dict) -> str:
    ref = row.get("source", {})
    return f"{ref.get('document', 'n/a')} p. {ref.get('page', 'n/a')} ({ref.get('confidence', 'n/a')})"


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    body = ParagraphStyle("TableBody", fontName="Helvetica", fontSize=7.2, leading=8.5, textColor=colors.black)
    heading = ParagraphStyle("TableHeading", fontName="Helvetica-Bold", fontSize=7.2, leading=8.5, textColor=colors.white)
    wrapped = [[Paragraph(str(cell), heading if row_index == 0 else body) for cell in row] for row_index, row in enumerate(rows)]
    t = Table(wrapped, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D9D9D9")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FB")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _document(path: Path, title: str):
    styles = getSampleStyleSheet()
    styles["Title"].fontName = "Helvetica-Bold"
    styles["Title"].fontSize = 16
    styles["Title"].leading = 20
    styles["Heading2"].fontName = "Helvetica-Bold"
    styles["Heading2"].fontSize = 11
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 12
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.55*inch, rightMargin=0.55*inch, topMargin=0.55*inch, bottomMargin=0.55*inch, title=title)
    return doc, styles


def executive_summary(path: Path) -> None:
    doc, styles = _document(path, "Executive Project Summary")
    story = [Paragraph("Executive Project Summary", styles["Title"]), Spacer(1, 8)]
    story += [Paragraph("5301 8th St E Roof Replacement | Project 101716.01 | Procurement 072026-1044 | Port of Tacoma", styles["BodyText"]), Spacer(1, 8)]

    # Contractor identity
    story += [Paragraph(f"<b>Prepared for:</b> {PJ_ROOFING.legal_name}, {PJ_ROOFING.format_full_location()}", styles["BodyText"]), Spacer(1, 4)]
    story += [Paragraph(f"<b>WA Contractor Registration:</b> {PJ_ROOFING.contractor_registration} (Active)", styles["BodyText"]), Spacer(1, 8)]

    story += [Paragraph("Status: NOT READY FOR BID. This is a source-backed internal review draft prepared by ALKAN (estimation tool). It does not constitute a bid submission and does not replace any Port form. All pending compliance requirements must be satisfied by the contractor before bid submission.", styles["BodyText"]), Spacer(1, 8)]
    story += [Paragraph("Verified procurement controls", styles["Heading2"])]
    controls = [
        ["Control", "Finding", "Source"],
        ["Bid receipt", "Addendum 04 sets sealed bid receipt for 29 Oct 2026, 2:00 PM, Front Reception Desk, Port Administration Office, One Sitcum Plaza, Tacoma WA 98421.", "Addendum 04 p. 1"],
        ["Bid security", "At least 5% of Base Bid Subtotal; compliant check or bond.", "Specs 00 21 00 p. 5"],
        ["Allowance", "Unforeseen Conditions Allowance is shown as $25,000.", "Specs 00 41 00 p. 1"],
        ["Sales tax", "Bid Form shows 10.5% Washington State Sales Tax on Base Bid Subtotal.", "Specs 00 41 00 p. 1"],
        ["Contract time", "180 days to Substantial Completion from execution; Final Completion within 30 days.", "Specs 00 52 00 p. 2"],
    ]
    story += [_table(controls, [1.1*inch, 4.3*inch, 1.5*inch]), Spacer(1, 10)]
    story += [Paragraph("Critical blockers", styles["Heading2"])]
    blockers = [["ID", "Blocking item", "Required action", "Source"]] + [[r["id"], r["risk"], r["action"], _source(r)] for r in RISKS if r["status"] == "BLOCKING"]
    story += [_table(blockers, [0.48*inch, 2.65*inch, 2.65*inch, 1.12*inch]), Spacer(1, 10)]
    story += [Paragraph("Addenda application", styles["Heading2"])]
    addenda = [["No.", "Disposition", "Change", "Source"]] + [[r["addendum"], r["precedence"], r["change"], _source(r)] for r in AMENDMENTS]
    story += [_table(addenda, [0.38*inch, 1.05*inch, 4.4*inch, 1.1*inch])]
    doc.build(story)


def scope_of_work(path: Path) -> None:
    doc, styles = _document(path, "Scope of Work by Building")
    story = [Paragraph("Scope of Work by Building", styles["Title"]), Spacer(1, 8)]
    story += [Paragraph(f"<b>Contractor:</b> {PJ_ROOFING.legal_name} | <b>Project:</b> Port of Tacoma 072026-1044", styles["BodyText"]), Spacer(1, 8)]
    story += [Paragraph("Draft scope derived from current drawing symbols, dimensions, notes and Section 07 41 00. Quantities identified as pending must be field measured; none are inferred from image scale.", styles["BodyText"]), Spacer(1, 8)]
    rows = [["Building", "Work item", "Unit", "Quantity", "Status", "Plan / source"]]
    for r in TAKEOFF:
        qty = "" if r["quantity"] is None else f"{r['quantity']:,.2f}" if isinstance(r["quantity"], float) else str(r["quantity"])
        rows.append([r["building"], r["item"], r["unit"], qty, r["quantity_status"], _source(r)])
    story += [_table(rows, [1.25*inch, 1.65*inch, 0.65*inch, 0.65*inch, 1.25*inch, 1.45*inch]), Spacer(1, 10)]
    story += [Paragraph("System controls", styles["Heading2"])]
    story += [Paragraph("The plans require 6 inch gutters and 4 inch by 4 inch minimum downspouts; roof details require manufacturer-specific floating clips, thermal blocks, fasteners and sealant. Plans require verification of dimensions, penetrations, utilities and conditions. Addendum 01 and Addendum 02 provide approved standing-seam substitutions subject to their stated conditions. Selection, system design, warranty and attachment spacing remain contractor responsibilities requiring human review.", styles["BodyText"])]
    doc.build(story)


def bid_review_report(path: Path) -> None:
    doc, styles = _document(path, "Bid Review Report")
    story = [Paragraph("Bid Review Report", styles["Title"]), Spacer(1, 8)]
    story += [Paragraph(f"<b>Contractor:</b> {PJ_ROOFING.legal_name}, {PJ_ROOFING.format_full_location()}", styles["BodyText"]), Spacer(1, 4)]
    story += [Paragraph(f"<b>Registration:</b> {PJ_ROOFING.contractor_registration} | <b>Classification:</b> {PJ_ROOFING.classification}", styles["BodyText"]), Spacer(1, 8)]
    story += [Paragraph("Outcome: BLOCKED. A valid bid cannot be prepared or presented until all blocking items are verified by an eligible bidder and the official Port forms are completed by authorized parties. See Compliance_Requirements_Status.txt for detailed compliance tracking.", styles["BodyText"]), Spacer(1, 8)]
    for status in ("BLOCKING", "PENDING"):
        story.append(Paragraph("Blockers" if status == "BLOCKING" else "Pending clarifications", styles["Heading2"]))
        rows = [["ID", "Issue", "Action", "Source"]] + [[r["id"], r["risk"], r["action"], _source(r)] for r in RISKS if r["status"] == status]
        story.extend([_table(rows, [0.45*inch, 2.75*inch, 2.75*inch, 1.1*inch]), Spacer(1, 10)])
    story.append(PageBreak())
    story.append(Paragraph("Submission-stage matrix", styles["Heading2"]))
    rows = [["Phase", "ID", "Requirement", "Status", "Source"]] + [[r["phase"], r["id"], r["requirement"], r["status"], _source(r)] for r in REQUIREMENTS]
    story.append(_table(rows, [0.8*inch, 0.55*inch, 3.65*inch, 0.65*inch, 1.3*inch]))
    doc.build(story)
