"""Normalized 6-deliverable generator (PDF + XLSX + DOCX) with immutable approved versions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .cost_engine import analyze_package_costs
from .domain import normalize_state
from .package_method import Package
from .security import sanitize_spreadsheet_cell


class ImmutableVersionError(RuntimeError):
    """Raised when attempting to overwrite an already Approved or Exported deliverable version."""


DELIVERABLE_TYPES: tuple[tuple[str, str, str], ...] = (
    ("cost_analysis", "01_COST_ANALYSIS", "Cost Analysis & Scenario Summary"),
    ("material_list", "02_MATERIAL_LIST", "Material Takeoff & Traceable Price List"),
    ("labor_breakdown", "03_LABOR_BREAKDOWN", "Labor & Productivity Breakdown"),
    ("proposal", "04_ESTIMATE_PROPOSAL", "Commercial Estimate / Proposal"),
    ("rfq_package", "05_RFQ_PACKAGE", "Supplier RFQ & Quote Coverage Package"),
    ("risk_exclusions", "06_RISK_AND_EXCLUSIONS", "Risk, RFI & Exclusions Report"),
)


@dataclass(frozen=True)
class DeliverableMetadata:
    project_name: str
    client_name: str
    location: str
    doc_date: str
    version: int
    status: str
    assumptions: list[str]
    exclusions: list[str]
    sources: list[str]
    reviewer: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _header_rows(meta: DeliverableMetadata, title: str) -> list[list[str]]:
    return [
        ["Document", title, "Status", meta.status],
        ["Project", meta.project_name, "Client", meta.client_name],
        ["Location", meta.location, "Date", meta.doc_date],
        ["Version", f"v{meta.version}", "Reviewer", meta.reviewer or "Pending Independent Review"],
    ]


def _write_pdf(path: Path, title: str, meta: DeliverableMetadata, columns: list[str], rows: list[list[Any]], footer_sections: list[tuple[str, list[str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#B3121B"))
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#222222"), spaceBefore=8, spaceAfter=4)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=colors.HexColor("#222222"))
    hdr = ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=colors.white)

    story: list[Any] = [Paragraph(f"ALKAN BID ENGINE — {title}", h1), Spacer(1, 6)]
    meta_tbl = Table(_header_rows(meta, title), colWidths=[0.85 * inch, 2.75 * inch, 0.75 * inch, 3.15 * inch])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4EFEF")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F4EFEF")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9CFCF")),
    ]))
    story.extend([meta_tbl, Spacer(1, 10)])

    data_rows = [[Paragraph(str(c), hdr) for c in columns]]
    for row in rows or [["(none)"] + [""] * (len(columns) - 1)]:
        data_rows.append([Paragraph(str(v).replace("&", "&amp;").replace("<", "&lt;"), cell) for v in row])
    col_w = (7.5 * inch) / max(1, len(columns))
    tbl = Table(data_rows, colWidths=[col_w] * len(columns), repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9CFCF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tbl)

    for sec_title, bullets in footer_sections:
        story.append(Paragraph(sec_title, h2))
        for b in bullets or ["None noted."]:
            story.append(Paragraph(f"• {str(b).replace('&', '&amp;').replace('<', '&lt;')}", cell))
    doc.build(story)


def _write_xlsx(path: Path, title: str, meta: DeliverableMetadata, columns: list[str], rows: list[list[Any]], footer_sections: list[tuple[str, list[str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Deliverable"
    for r in _header_rows(meta, title):
        ws.append([sanitize_spreadsheet_cell(x) for x in r])
    ws.append([])
    ws.append([sanitize_spreadsheet_cell(c) for c in columns])
    for row in rows:
        ws.append([sanitize_spreadsheet_cell(v) for v in row])
    ws.append([])
    for sec_title, bullets in footer_sections:
        ws.append([sanitize_spreadsheet_cell(sec_title)])
        for b in bullets or ["None noted."]:
            ws.append(["", sanitize_spreadsheet_cell(b)])
    wb.save(path)


def _write_docx(path: Path, title: str, meta: DeliverableMetadata, columns: list[str], rows: list[list[Any]], footer_sections: list[tuple[str, list[str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = DocxDocument()
    doc.add_heading(f"ALKAN BID ENGINE — {title}", level=1)
    for r in _header_rows(meta, title):
        doc.add_paragraph(f"{r[0]}: {r[1]}  |  {r[2]}: {r[3]}")
    tbl = doc.add_table(rows=1, cols=len(columns))
    for i, col in enumerate(columns):
        tbl.rows[0].cells[i].text = str(col)
    for row in rows:
        cells = tbl.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
    for sec_title, bullets in footer_sections:
        doc.add_heading(sec_title, level=2)
        for b in bullets or ["None noted."]:
            doc.add_paragraph(str(b), style="List Bullet")
    doc.save(path)


def _build_deliverable_tables(
    pkg: Package,
    cost_analysis: dict[str, Any],
    *,
    review_report: dict[str, Any] | None = None,
    rfq_snapshot: dict[str, Any] | None = None,
) -> dict[str, tuple[list[str], list[list[Any]]]]:
    b13 = cost_analysis["breakdown_13"]["buckets"]
    cost_rows = [[k.replace("_", " ").title(), f"${v}"] for k, v in b13.items()]
    cost_rows.append(["Profit Mode", f"{cost_analysis['breakdown_13']['profit_mode']} ({cost_analysis['breakdown_13']['configured_profit_pct']}%)"])
    cost_rows.append(["Achieved Markup % / Margin %", f"{cost_analysis['breakdown_13']['achieved_markup_pct']}% / {cost_analysis['breakdown_13']['achieved_margin_pct']}%"])
    for sc in cost_analysis["scenarios"]:
        cost_rows.append([f"Scenario: {sc['scenario']}", f"${sc['final_bid_price']} (delta ${sc['delta_vs_expected']}) — {sc['description']}"])

    mat_cols = ["ID", "Section", "Material / Item", "Spec", "Qty", "Unit", "Unit Price", "Extended", "Basis", "Source"]
    mat_rows = [
        [m.id, m.section, m.item, m.spec, str(m.qty), m.unit, f"${m.unit_price}", f"${m.extended}", m.price_basis, m.qty_source or m.price_source]
        for m in pkg.materials
    ]

    lab_cols = ["ID", "Task", "Rate Key", "Rate Kind", "Hours", "Loaded Rate", "Extended", "Source"]
    lab_rows = []
    for l in pkg.labor:
        r = pkg.rates[l.rate_key]
        ext = (l.hours * r.loaded).quantize(Decimal("0.01"))
        lab_rows.append([l.id, l.task, l.rate_key, r.kind, str(l.hours), f"${r.loaded}", f"${ext}", r.source])

    prop_cols = ["Scope Item / Description", "Type", "Amount"]
    prop_rows = [[pkg.project.get("title") or pkg.estimate_id, "Base Bid Lump Sum", f"${b13['13_final_bid_price']}"]]
    for o in pkg.other:
        prop_rows.append([f"{o.category}: {o.item}", f"{o.qty} {o.unit}", f"${o.extended}"])

    rfq_cols = ["RFQ ID", "Category", "Supplier", "Items", "Status", "Due Date"]
    rfq_rows = []
    for rfq in (rfq_snapshot or {}).get("rfqs", {}).values():
        rfq_rows.append([rfq["rfq_id"], rfq["supplier_category"], rfq["supplier_name"], len(rfq["items"]), rfq["status"], rfq["due_date"]])
    if not rfq_rows:
        for m in pkg.materials:
            if m.price_basis != "QUOTE":
                rfq_rows.append(["PENDING-RFQ", m.section or "General", "Unassigned", f"{m.qty} {m.unit} — {m.item}", m.price_basis, pkg.project.get("bid_date", "TBD")])

    risk_cols = ["Ref", "Category", "Severity", "Finding / Risk", "Recommendation", "Status"]
    risk_rows = []
    for d in (review_report or {}).get("discrepancies", []):
        risk_rows.append([d["discrepancy_id"], d["category"], d["severity"], d["reason"], d["recommendation"], d["approval_status"]])
    for rfi in (rfq_snapshot or {}).get("rfis", {}).values():
        risk_rows.append([rfi["rfi_id"], "RFI", rfi["priority"], rfi["question"], rfi["reference_doc"], rfi["status"]])
    for ex in pkg.exclusions:
        risk_rows.append(["EXCL", "Exclusion", "INFO", ex, "Excluded from base bid", "Active"])

    return {
        "cost_analysis": (["Line Item / Metric", "Value / Detail"], cost_rows),
        "material_list": (mat_cols, mat_rows),
        "labor_breakdown": (lab_cols, lab_rows),
        "proposal": (prop_cols, prop_rows),
        "rfq_package": (rfq_cols, rfq_rows),
        "risk_exclusions": (risk_cols, risk_rows),
    }


def generate_all_deliverables(
    pkg: Package,
    out_root: Path,
    *,
    version: int = 1,
    status: str = "Review Required",
    reviewer: str = "",
    profit_mode: str = "markup",
    review_report: dict[str, Any] | None = None,
    rfq_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate all 6 deliverables in PDF + XLSX + DOCX under immutable version folder."""
    canonical = normalize_state(status)
    out_root = Path(out_root)
    versions_file = out_root / "versions_manifest.json"
    history = json.loads(versions_file.read_text(encoding="utf-8")) if versions_file.exists() else {"versions": {}}
    vkey = f"v{version}"
    existing = history["versions"].get(vkey)
    if existing and existing.get("status") in ("Approved", "Exported"):
        raise ImmutableVersionError(
            f"Version {vkey} is locked ({existing['status']}) and cannot be overwritten; create v{version + 1}."
        )

    vdir = out_root / vkey
    vdir.mkdir(parents=True, exist_ok=True)
    cost_analysis = analyze_package_costs(pkg, profit_mode=profit_mode)
    meta = DeliverableMetadata(
        project_name=str(pkg.project.get("title") or pkg.project.get("short") or pkg.estimate_id),
        client_name=str(pkg.project.get("prime_contractor") or pkg.project.get("owner") or pkg.contractor.get("name") or "Client"),
        location=str(pkg.project.get("site") or pkg.project.get("county") or "Unspecified"),
        doc_date=pkg.date or date.today().isoformat(),
        version=version,
        status=canonical,
        assumptions=list(getattr(pkg, "assumptions", None) or getattr(pkg, "notes", None) or []),
        exclusions=list(getattr(pkg, "exclusions", None) or []),
        sources=list((pkg.project or {}).get("documents") or []),
        reviewer=reviewer,
    )
    footer_sections = [
        ("Assumptions", meta.assumptions),
        ("Exclusions", meta.exclusions),
        ("Documentary Sources", meta.sources),
    ]
    tables = _build_deliverable_tables(pkg, cost_analysis, review_report=review_report, rfq_snapshot=rfq_snapshot)

    files: dict[str, dict[str, dict[str, str]]] = {}
    for key, stem, title in DELIVERABLE_TYPES:
        cols, rows = tables[key]
        pdf_p = vdir / f"{stem}.pdf"
        xlsx_p = vdir / f"{stem}.xlsx"
        docx_p = vdir / f"{stem}.docx"
        _write_pdf(pdf_p, title, meta, cols, rows, footer_sections)
        _write_xlsx(xlsx_p, title, meta, cols, rows, footer_sections)
        _write_docx(docx_p, title, meta, cols, rows, footer_sections)
        files[key] = {
            "pdf": {"path": str(pdf_p), "sha256": _sha256(pdf_p)},
            "xlsx": {"path": str(xlsx_p), "sha256": _sha256(xlsx_p)},
            "docx": {"path": str(docx_p), "sha256": _sha256(docx_p)},
        }

    record = {
        "version": version,
        "status": canonical,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": reviewer,
        "final_bid_price": cost_analysis["breakdown_13"]["buckets"]["13_final_bid_price"],
        "files": files,
    }
    history["versions"][vkey] = record
    versions_file.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record
