"""ALKAN three-document estimate package — PDF rendering.

01 COST ANALYSIS (internal), 02 MATERIAL LIST & PRICE LIST, 03 ESTIMATE / PROPOSAL.
All figures come from ``package_method.compute``; nothing is recalculated here.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, KeepTogether, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from .alkan_method import RELATIONSHIPS, TIERS
from .package_method import Package, proposal_release

RED = colors.HexColor("#B3121B")
INK = colors.HexColor("#222222")
GREY = colors.HexColor("#6B6B6B")
LIGHT = colors.HexColor("#F4EFEF")
LINE = colors.HexColor("#D9CFCF")

SS = dict(
    h1=ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=INK, spaceAfter=2),
    sub=ParagraphStyle("sub", fontName="Helvetica", fontSize=8.5, leading=11, textColor=GREY),
    h2=ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=RED, spaceBefore=10, spaceAfter=4),
    body=ParagraphStyle("body", fontName="Helvetica", fontSize=8.6, leading=11.6, textColor=INK),
    small=ParagraphStyle("small", fontName="Helvetica", fontSize=7.4, leading=9.6, textColor=GREY),
    cell=ParagraphStyle("cell", fontName="Helvetica", fontSize=7.6, leading=9.4, textColor=INK),
    cellb=ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=7.6, leading=9.4, textColor=INK),
    cellr=ParagraphStyle("cellr", fontName="Helvetica", fontSize=7.6, leading=9.4, textColor=INK, alignment=TA_RIGHT),
    cellrb=ParagraphStyle("cellrb", fontName="Helvetica-Bold", fontSize=7.6, leading=9.4, textColor=INK, alignment=TA_RIGHT),
    hdr=ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=colors.white),
    hdrr=ParagraphStyle("hdrr", fontName="Helvetica-Bold", fontSize=7.4, leading=9, textColor=colors.white, alignment=TA_RIGHT),
    big=ParagraphStyle("big", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=RED, alignment=TA_RIGHT),
    lab=ParagraphStyle("lab", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=GREY),
    val=ParagraphStyle("val", fontName="Helvetica", fontSize=8.4, leading=10.8, textColor=INK),
    center=ParagraphStyle("center", fontName="Helvetica", fontSize=7.4, leading=9.6, textColor=GREY, alignment=TA_CENTER),
)

# Default Washington public-works terms (overridable through package.terms).
DEFAULT_TERMS = {
    "payment": [
        "Monthly progress billing against an approved schedule of values, submitted by the 25th of each month; materials "
        "fabricated or stored on site/in shop are billable with proof of insurance and title.",
        "Payment due within 10 days after the prime contractor receives payment from the Owner (RCW 39.04.250), and in no case more than 30 days after invoice.",
        "Retainage of 5% may be withheld per RCW 60.28; retainage to be released within 60 days of acceptance of the work, or earlier by retainage bond.",
        "No deposit is required on public works. Late payments accrue interest at 1% per month as allowed by RCW 39.04.250.",
        "Changes, extra work and unforeseen conditions billed only by written change order signed before the work is performed.",
    ],
    "warranty": [
        "One (1) year warranty on workmanship and installation from the date of Substantial Completion, or longer if required by the Contract Documents.",
        "Manufacturer warranties on supplied products are passed through to the Owner.",
        "Hot-dip galvanizing per ASTM A123/A153; field repair of damaged coatings per ASTM A780.",
        "Warranty excludes damage from vandalism, vehicle impact, misuse, improper maintenance, settlement of work by others, or acts of nature.",
    ],
    "general": [
        "Prevailing wages: all on-site and project-specific shop work paid at Washington prevailing wage rates; Intents and Affidavits filed with L&I (RCW 39.12).",
        "Schedule: shop drawings submitted within 10 working days of subcontract and receipt of complete documents; fabrication lead time 3–5 weeks after approval; site work per the prime contractor's schedule with 5 working days' notice.",
        "Site conditions: proposal assumes clear, compacted and accessible work areas at finish grade, staked alignment, and staging space. Rock, roots, buried debris or utilities requiring hand digging or relocation are extra.",
        "Steel price escalation: if the subcontract is executed more than 30 days after this proposal, or mill/supplier prices increase more than 5% before material release, the price will be adjusted by documented cost.",
        "Insurance: commercial general liability, auto and Washington L&I coverage carried; additional insured endorsements provided as required by the prime contract.",
        "Back-charges must be submitted in writing with 48 hours' prior notice and opportunity to cure. The contractor is not responsible for delays caused by others, Owner changes, weather or material shortages beyond its control.",
        "Lien and bond rights under RCW 39.08 and RCW 60.28 are reserved. Disputes resolved per the prime contract dispute procedure; venue in the county of the project.",
        "This proposal, when accepted, becomes part of the subcontract; conflicting terms in the subcontract are subject to mutual written agreement.",
    ],
}

TAX_LINE = {
    "excluded_resale": "Washington sales tax not included — collected by prime contractor (WAC 458-20-171)",
    "excluded": "Sales tax not included",
    "included": "Sales tax included",
}


def money(v, cents=True) -> str:
    return ("${:,.2f}" if cents else "${:,.0f}").format(Decimal(v))


def fq(v) -> str:
    v = Decimal(v)
    return f"{v:,.0f}" if v == v.to_integral() else f"{v:,.2f}".rstrip("0").rstrip(".")


def pct(v) -> str:
    return fq(v) + "%"


def P(t, s="cell"):
    return Paragraph(t, SS[s])


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


class _Doc(BaseDocTemplate):
    def __init__(self, path, pkg: Package, doctitle: str, conf: str, keywords: str):
        super().__init__(str(path), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                         topMargin=1.45 * inch, bottomMargin=0.7 * inch,
                         title=f"{pkg.project['short']} — {doctitle}", author=pkg.contractor["name"],
                         subject=pkg.estimate_id, keywords=keywords, invariant=1)
        self.pkg, self.doctitle, self.conf = pkg, doctitle, conf
        logo = pkg.contractor.get("logo")
        self.logo = None
        if logo:
            lp = Path(logo)
            if not lp.is_absolute() and pkg.base_dir:
                lp = pkg.base_dir / lp
            self.logo = lp if lp.exists() else None
        f = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([PageTemplate(id="pg", frames=[f], onPage=self._deco)])

    def _deco(self, c, d):
        W, H = letter
        co = self.pkg.contractor
        c.saveState()
        x = 0.6 * inch
        if self.logo:
            c.drawImage(str(self.logo), 0.6 * inch, H - 1.12 * inch, width=1.08 * inch, height=0.72 * inch,
                        mask="auto", preserveAspectRatio=True)
            x = 1.82 * inch
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 13); c.drawString(x, H - 0.62 * inch, co["name"])
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 7.5); c.drawString(x, H - 0.77 * inch, co.get("tag", ""))
        c.setFillColor(GREY); c.setFont("Helvetica", 7.3)
        c.drawString(x, H - 0.91 * inch, co["address"] + "  ·  " + co["phone"])
        c.drawString(x, H - 1.03 * inch, co["license"] + ("  ·  " + co["email"] if co.get("email") else ""))
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 10.5)
        c.drawRightString(W - 0.6 * inch, H - 0.62 * inch, self.doctitle.upper())
        c.setFillColor(GREY); c.setFont("Helvetica", 7.5)
        c.drawRightString(W - 0.6 * inch, H - 0.77 * inch, f"{self.pkg.estimate_id}  ·  {_fmt_date(self.pkg.date)}")
        if self.conf.startswith("DRAFT"):
            c.setFillColor(RED); c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(W - 0.6 * inch, H - 0.89 * inch, self.conf)
        c.setStrokeColor(RED); c.setLineWidth(1.6); c.line(0.6 * inch, H - 1.22 * inch, W - 0.6 * inch, H - 1.22 * inch)
        c.setStrokeColor(LINE); c.setLineWidth(0.5); c.line(0.6 * inch, 0.55 * inch, W - 0.6 * inch, 0.55 * inch)
        c.setFillColor(GREY); c.setFont("Helvetica", 7)
        c.drawString(0.6 * inch, 0.4 * inch, f"{co['name']}  ·  {self.pkg.project['short']}  ·  {self.doctitle}")
        c.drawRightString(W - 0.6 * inch, 0.4 * inch, f"Page {d.page}")
        if self.conf.startswith("DRAFT"):
            c.setFillColor(colors.Color(0.7, 0.07, 0.1, alpha=0.08)); c.setFont("Helvetica-Bold", 90)
            c.translate(W / 2, H / 2); c.rotate(35); c.drawCentredString(0, 0, "DRAFT")
        c.restoreState()


def _grid(rows, widths, header=True, total_rows=()):
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
          ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), INK))
    for i in range(1 if header else 0, len(rows)):
        if i % 2 == 0:
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FAF7F7")))
    for r in total_rows:
        st += [("BACKGROUND", (0, r), (-1, r), LIGHT), ("LINEABOVE", (0, r), (-1, r), 0.8, RED)]
    t.setStyle(TableStyle(st))
    return t


def _project_block(pkg: Package):
    p, co = pkg.project, pkg.contractor
    rows = [
        [P("PROJECT", "lab"), P(p["title"], "val"), P("PROJECT NO.", "lab"), P(p.get("project_no", "—"), "val")],
        [P("OWNER", "lab"), P(p["owner"] + ("<br/>" + p["owner_contact"] if p.get("owner_contact") else ""), "val"),
         P("LOCATION", "lab"), P(p["site"], "val")],
        [P("CONTRACTOR", "lab"), P(f"{co['name']}<br/>{co['contact']} · {co['phone']}", "val"),
         P("PRIME / GC", "lab"), P(p.get("prime_contractor", "To be confirmed at award"), "val")],
        [P("WAGES", "lab"), P(p.get("wage_basis", "—"), "val"), P("BID DATE", "lab"), P(p.get("bid_date", "—"), "val")],
    ]
    t = Table(rows, colWidths=[0.9 * inch, 3.05 * inch, 0.85 * inch, 2.5 * inch])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE), ("BACKGROUND", (0, 0), (0, -1), LIGHT),
                           ("BACKGROUND", (2, 0), (2, -1), LIGHT),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _kpis(items):
    cells = [[P(l, "lab") for l, _ in items], [P(f"<b>{v}</b>", "val") for _, v in items]]
    w = 7.3 * inch / len(items)
    t = Table(cells, colWidths=[w] * len(items))
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                           ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                           ("BACKGROUND", (-1, 0), (-1, -1), colors.HexColor("#FBEAEA"))]))
    return t


def _keywords(r):
    return (f"price={r['price']};materials={r['materials']};labor={r['labor']};other={r['other']};"
            f"direct={r['direct']};status={r['status']}")


# ───────────────────────────────────────────────────────── 01 cost analysis

def render_cost_analysis(pkg: Package, r: dict, path: Path) -> Path:
    d = _Doc(path, pkg, "Cost Analysis", "INTERNAL · CONFIDENTIAL", _keywords(r))
    s = [P(pkg.project["title"], "h1"),
         P("Complete cost analysis: materials, labor, equipment and other costs — "
           + pkg.project.get("scope_label", "metal fabrication scope only"), "sub"),
         Spacer(1, 6), _project_block(pkg), Spacer(1, 8),
         _kpis([("MATERIALS", money(r["materials"])), ("LABOR", money(r["labor"])), ("EQUIP. & OTHER", money(r["other"])),
                ("DIRECT COST", money(r["direct"])), ("SELL PRICE", money(r["price"], False))])]

    s.append(P("1. Basis of estimate", "h2"))
    basis = [f"Quantities taken off from: {'; '.join(pkg.project['documents'])}."]
    for x in pkg.rates.values():
        if x.kind == "prevailing_wage":
            basis.append(f"{x.label}: ${x.rate:,.2f}/hr prevailing wage (wage + fringe; {x.source}) + {pct(x.burden_pct)} burden "
                         f"(payroll taxes, L&I workers' comp, liability) = ${x.loaded:,.2f}/hr loaded.")
        else:
            basis.append(f"{x.label}: ${x.loaded:,.2f}/hr loaded{(' (' + x.source + ')') if x.source else ''}.")
    bases = sorted({m.price_basis for m in pkg.materials})
    basis.append(f"Material price basis: {', '.join(bases)} "
                 f"({len(r['validation']['unquoted_lines'])} of {len(pkg.materials)} lines not yet supplier-quoted). "
                 + ("Purchases for resale — sales tax not included." if pkg.tax.get("mode") == "excluded_resale" else ""))
    basis.append(f"Markups: contingency {pct(pkg.contingency_pct)} of direct cost; overhead {pct(pkg.overhead_pct)} and "
                 f"profit {pct(pkg.profit_pct)} applied sequentially. Sell price rounded to the nearest ${fq(pkg.rounding)}.")
    basis.append(f"Estimate tier: {pkg.tier} ({TIERS[pkg.tier]['precision']}). Relationship: {RELATIONSHIPS[pkg.relationship]['label']}.")
    basis += pkg.assumptions
    for b in basis:
        s.append(P("• " + b, "body"))

    s.append(P("2. Materials by section", "h2"))
    rows = [[P("Section", "hdr"), P("Lines", "hdrr"), P("Extended", "hdrr"), P("% of materials", "hdrr")]]
    for k, v in r["sections"].items():
        n = sum(1 for m in pkg.materials if m.section == k)
        rows.append([P(k), P(str(n), "cellr"), P(money(v), "cellr"), P(f"{v / r['materials'] * 100:.1f}%", "cellr")])
    rows.append([P("Total materials (see 02 Material List for every item)", "cellb"), P(str(len(pkg.materials)), "cellrb"),
                 P(money(r["materials"]), "cellrb"), P("100.0%", "cellrb")])
    s.append(_grid(rows, [4.2 * inch, 0.7 * inch, 1.2 * inch, 1.2 * inch], total_rows=[len(rows) - 1]))

    s.append(P("3. Labor", "h2"))
    rows = [[P("Task", "hdr"), P("Trade", "hdr"), P("Hours", "hdrr"), P("Rate", "hdrr"), P("Cost", "hdrr")]]
    for x in r["labor_rows"]:
        rows.append([P(x["task"]), P(x["trade"]), P(fq(x["hours"]), "cellr"), P(money(x["rate"]), "cellr"), P(money(x["cost"]), "cellr")])
    th = sum((x["hours"] for x in r["labor_rows"]), Decimal(0))
    rows.append([P("Total labor", "cellb"), P(""), P(fq(th), "cellrb"), P(""), P(money(r["labor"]), "cellrb")])
    s.append(_grid(rows, [3.55 * inch, 1.2 * inch, 0.7 * inch, 0.85 * inch, 1.0 * inch], total_rows=[len(rows) - 1]))
    s.append(Spacer(1, 3))
    s.append(P("Hours by trade — " + " · ".join(f"{k}: {fq(v)} hr" for k, v in r["hours"].items()), "small"))

    s.append(P("4. Equipment, mobilization, fees and other costs", "h2"))
    rows = [[P("Item", "hdr"), P("Category", "hdr"), P("Qty", "hdrr"), P("Unit", "hdr"), P("Rate", "hdrr"), P("Cost", "hdrr")]]
    for o in pkg.other:
        rows.append([P(o.item), P(o.category), P(fq(o.qty), "cellr"), P(o.unit), P(money(o.rate), "cellr"), P(money(o.extended), "cellr")])
    rows.append([P("Total equipment & other", "cellb"), P(""), P(""), P(""), P(""), P(money(r["other"]), "cellrb")])
    s.append(_grid(rows, [3.1 * inch, 1.1 * inch, 0.55 * inch, 0.55 * inch, 0.9 * inch, 1.1 * inch], total_rows=[len(rows) - 1]))

    s.append(CondPageBreak(2.8 * inch))
    s.append(P("5. Cost summary and markups", "h2"))
    rows = [[P("Line", "hdr"), P("Basis", "hdr"), P("Amount", "hdrr")],
            [P("Materials"), P("Section 2 / document 02"), P(money(r["materials"]), "cellr")],
            [P("Labor"), P("Section 3"), P(money(r["labor"]), "cellr")],
            [P("Equipment, mobilization, fees, other"), P("Section 4"), P(money(r["other"]), "cellr")],
            [P("Direct cost", "cellb"), P(""), P(money(r["direct"]), "cellrb")],
            [P("Contingency"), P(f"{pct(pkg.contingency_pct)} of direct cost"), P(money(r["contingency"]), "cellr")],
            [P("Overhead"), P(f"{pct(pkg.overhead_pct)} of direct + contingency"), P(money(r["overhead"]), "cellr")],
            [P("Profit"), P(f"{pct(pkg.profit_pct)} of direct + contingency + overhead"), P(money(r["profit"]), "cellr")],
            [P("Computed total"), P(""), P(money(r["total"]), "cellr")],
            [P(f"SELL PRICE (rounded to ${fq(pkg.rounding)})", "cellb"), P("Carried to 03 Estimate / Proposal"), P(money(r["price"]), "cellrb")]]
    s.append(_grid(rows, [2.6 * inch, 3.0 * inch, 1.7 * inch], total_rows=[4, 9]))
    s.append(Spacer(1, 4))
    s.append(P(f"Gross margin over direct cost: {money(r['gross_margin'])} ({r['gross_margin'] / r['price'] * 100:.1f}% of sell price). "
               f"Break-even (direct + contingency + overhead): {money(r['break_even'])}.", "small"))
    if r["commission"]:
        sch = r["commission"]["schedule"]
        s.append(P(f"Alkan commission per services agreement: {money(r['commission']['total'])} "
                   f"({money(sch['at_contract_signing'])} at contract signing + {money(sch['on_first_payment'])} on first payment). "
                   f"Net margin after commission: {money(r['commission']['net_margin'])}.", "small"))

    s.append(P("6. Scope carried and exclusions", "h2"))
    for sc in pkg.scope:
        s.append(P(f"<b>{sc['title']}.</b> {sc['text']}", "body")); s.append(Spacer(1, 2))
    s.append(Spacer(1, 3))
    for e in pkg.exclusions:
        s.append(P("<b>Excluded:</b> " + e, "body"))
    v = r["validation"]
    if v["warnings"]:
        s.append(P("7. Review flags before release", "h2"))
        for w in v["warnings"]:
            s.append(P("• " + w, "body"))
    s.append(Spacer(1, 6))
    s.append(P(f"Internal working document prepared for {pkg.contractor['name']}. Status: {r['status']}. Prices are budgetary "
               "until supplier quotes are received; verify prevailing wage rates on L&I for the bid/award date.", "small"))
    d.build(s)
    return Path(path)


# ───────────────────────────────────────────────────────── 02 material list

def render_material_list(pkg: Package, r: dict, path: Path) -> Path:
    d = _Doc(path, pkg, "Material List & Price List", "BILL OF MATERIALS", _keywords(r))
    s = [P(pkg.project["title"], "h1"),
         P("Complete bill of materials with unit and extended prices — every component, fastener and consumable", "sub"),
         Spacer(1, 6), _project_block(pkg), Spacer(1, 8)]
    n = 1
    for sec in r["sections"]:
        s.append(P(sec, "h2"))
        rows = [[P("#", "hdr"), P("Item", "hdr"), P("Specification", "hdr"), P("Qty", "hdrr"), P("Unit", "hdr"),
                 P("Unit price", "hdrr"), P("Extended", "hdrr"), P("Ref.", "hdr")]]
        for m in pkg.materials:
            if m.section != sec:
                continue
            basis = "" if m.price_basis == "QUOTE" else f" <font color='#B3121B' size=6>[{m.price_basis}]</font>"
            rows.append([P(str(n)), P(m.item + basis), P(m.spec), P(fq(m.qty), "cellr"), P(m.unit),
                         P(money(m.unit_price), "cellr"), P(money(m.extended), "cellr"), P(m.qty_source or "—")])
            n += 1
        rows.append([P(""), P("Section subtotal", "cellb"), P(""), P(""), P(""), P(""), P(money(r["sections"][sec]), "cellrb"), P("")])
        s.append(_grid(rows, [0.3 * inch, 2.05 * inch, 1.85 * inch, 0.45 * inch, 0.45 * inch, 0.75 * inch, 0.8 * inch, 0.65 * inch],
                       total_rows=[len(rows) - 1]))
    s.append(Spacer(1, 8))
    rows = [[P("Material summary", "hdr"), P("Amount", "hdrr")]]
    for sec, v in r["sections"].items():
        rows.append([P(sec), P(money(v), "cellr")])
    tax_txt = "before tax — purchase for resale" if pkg.tax.get("mode") == "excluded_resale" else "before tax"
    rows.append([P(f"TOTAL MATERIALS ({tax_txt})", "cellb"), P(money(r["materials"]), "cellrb")])
    s.append(KeepTogether(_grid(rows, [5.6 * inch, 1.7 * inch], total_rows=[len(rows) - 1])))
    s.append(Spacer(1, 6))
    s.append(P("Ref. = drawing detail, spec section or RFQ line the quantity comes from. [BUDGET]/[CATALOG] = price not yet "
               "supplier-quoted. Quantities include normal cutting waste; verify field dimensions before ordering.", "small"))
    d.build(s)
    return Path(path)


# ───────────────────────────────────────────────────────── 03 proposal

def render_proposal(pkg: Package, r: dict, path: Path, label: str) -> Path:
    d = _Doc(path, pkg, "Estimate / Proposal", label, _keywords(r))
    co = pkg.contractor
    valid = date.fromisoformat(pkg.date) + timedelta(days=pkg.validity_days)
    s = [P(pkg.project["title"], "h1"),
         P(f"Proposal valid {pkg.validity_days} days — through {_fmt_date(valid.isoformat())}", "sub"),
         Spacer(1, 6), _project_block(pkg), Spacer(1, 10)]
    scope_label = pkg.project.get("scope_label", "metal fabrication scope")
    tot = Table([[P(f"<b>TOTAL LUMP-SUM PRICE</b><br/><font size=7.5 color='#6B6B6B'>{scope_label.capitalize()} described below — "
                    "furnish, fabricate, deliver and install</font>", "val"), P(money(r["price"], False), "big")]],
                colWidths=[4.6 * inch, 2.7 * inch])
    tot.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, RED), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDF6F6")),
                             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 8),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
    s.append(tot)

    s.append(P("1. Scope of work", "h2"))
    s.append(P(f"{co['name']} proposes to furnish all labor, materials, equipment, shop fabrication, finishes, delivery "
               f"and installation for the following work, in accordance with: {'; '.join(pkg.project['documents'])}.", "body"))
    s.append(Spacer(1, 4))
    for i, sc in enumerate(pkg.scope, 1):
        s.append(P(f"<b>1.{i} {sc['title']}.</b> {sc['text']}", "body")); s.append(Spacer(1, 3))

    s.append(P("2. Price", "h2"))
    tax = TAX_LINE.get(pkg.tax.get("mode", "excluded_resale"), pkg.tax.get("note", ""))
    rows = [[P("Description", "hdr"), P("Amount", "hdrr")],
            [P(f"{scope_label.capitalize()} — {pkg.project['short']} (Section 1, complete)"), P(money(r["price"], False), "cellr")],
            [P(f"TOTAL LUMP SUM ({tax})", "cellb"), P(money(r["price"], False), "cellrb")]]
    s.append(_grid(rows, [5.6 * inch, 1.7 * inch], total_rows=[2]))

    s.append(P("3. Exclusions and clarifications", "h2"))
    for e in pkg.exclusions:
        s.append(P("• " + e, "body"))
    terms = {**DEFAULT_TERMS, **(pkg.terms or {})}
    for num, (title, key) in enumerate((("Payment terms", "payment"), ("Warranty", "warranty"),
                                        ("General terms and conditions", "general")), 4):
        s.append(P(f"{num}. {title}", "h2"))
        for i, t in enumerate(terms[key], 1):
            s.append(P(f"{num}.{i} {t}", "body"))

    s.append(CondPageBreak(2.2 * inch))
    s.append(P("7. Acceptance", "h2"))
    s.append(P(f"The above price, scope, terms and conditions are accepted. {co['name']} is authorized to proceed.", "body"))
    s.append(Spacer(1, 10))
    sig = Table([[P(f"SUBMITTED BY — {co['name']}", "lab"), P("ACCEPTED BY — OWNER / PRIME CONTRACTOR", "lab")],
                 [P("<br/><br/>_______________________________<br/>" + co["contact"] + "<br/>Date: ______________", "val"),
                  P("<br/><br/>_______________________________<br/>Name / Title<br/>Date: ______________", "val")]],
                colWidths=[3.65 * inch, 3.65 * inch])
    sig.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                             ("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
    s.append(sig)
    d.build(s)
    return Path(path)


def render_all(pkg: Package, r: dict, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    key = pkg.project["key"]
    files = {"cost_analysis": render_cost_analysis(pkg, r, out_dir / f"{key}_01_COST_ANALYSIS.pdf"),
             "material_list": render_material_list(pkg, r, out_dir / f"{key}_02_MATERIAL_LIST.pdf")}
    rel = proposal_release(pkg, r)
    if rel["produce"]:
        files["proposal"] = render_proposal(pkg, r, out_dir / f"{key}_03_ESTIMATE_PROPOSAL.pdf", rel["label"])
    return {"files": files, "release": rel}
