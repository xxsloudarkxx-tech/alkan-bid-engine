"""Portable Excel outputs, with blanks propagating through every cost formula."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import zipfile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import ProjectConfig
from .data_store import read_json
from .project_schema import require_valid_analysis


def reference(sources: list[dict]) -> str:
    return " | ".join(f"{s['document']} PDF {s['page']} / {s.get('sheet', '')} [{s['sha256'][:12]}] {s.get('region', '')}" for s in sources)


def _sheet(book, name, headers, rows):
    sheet = book.create_sheet(name)
    sheet.append(headers)
    for row in rows:
        sheet.append([json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in row])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
    for column in sheet.columns:
        letter = get_column_letter(column[0].column)
        sheet.column_dimensions[letter].width = min(75, max(14, max(len(str(c.value or "")) for c in column[:30]) + 2))
        for cell in column:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    return sheet


def _save(book, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    book.properties.created = book.properties.modified = datetime(2000, 1, 1)
    stream = BytesIO()
    book.save(stream)
    # Normalize archive timestamps and core modification date for byte reproduction.
    with zipfile.ZipFile(stream) as original, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as output:
        for name in original.namelist():
            content = original.read(name)
            if name == "docProps/core.xml":
                import re
                content = re.sub(rb"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)", rb"\g<1>2000-01-01T00:00:00Z\2", content)
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, content)


def build_workbooks(config: ProjectConfig) -> None:
    data = require_valid_analysis(config)
    measured = read_json(config.data_dir / "takeoff" / "takeoff.json")
    estimate = read_json(config.data_dir / "estimate" / "estimate_inputs.json")
    book = Workbook()
    book.remove(book.active)
    _sheet(book, "Takeoff", ["ID", "Package", "Item", "Unit", "Quantity", "Status", "Basis", "Calculation", "Source"], [[r["id"], r["package"], r["item"], r["unit"], r["quantity"], r["quantity_status"], r["basis"], r.get("calculation"), reference(r["sources"])] for r in measured["records"]])
    _sheet(book, "Materials", ["ID", "Description", "Unit", "Quantity", "Quantity ID", "Specification", "Status", "Source"], [[r["id"], r["description"], r["unit"], r["quantity"], r.get("quantity_id"), r["specification"], r["quantity_status"], reference(r["sources"])] for r in measured["materials"]])
    for key in ("requirements", "amendments", "risks", "pending"):
        rows = data[key]
        keys = list(dict.fromkeys(k for row in rows for k in row)) or ["id", "status"]
        _sheet(book, key.title(), keys, [[reference(r[k]) if k == "sources" else r.get(k) for k in keys] for r in rows])
    _save(book, config.output_dir / "Material_Takeoff.xlsx")

    book = Workbook()
    book.remove(book.active)
    rows = estimate["rows"]
    sheet = _sheet(book, "Estimate Inputs", ["ID", "Item", "Cost class", "Unit", "Quantity", "Unit price", "Quote reference", "Extended cost", "Status", "Source", "Pricing scope"], [[r["id"], r["item"], r["cost_class"], r["unit"], r["quantity"], r["unit_price"], r["quote_reference"], None, r["status"], reference(r["sources"]), r["pricing_scope"]] for r in rows])
    for number in range(2, len(rows)+2):
        sheet.cell(number, 8, f'=IF(OR(E{number}="",F{number}="",G{number}=""),"",E{number}*F{number})')
        for col in (5, 6, 7):
            sheet.cell(number, col).fill = PatternFill("solid", fgColor="FFF2CC")
    _sheet(book, "Assumptions", ["Parameter", "Value", "Status / basis"], [["Tax rate", estimate["tax_rate"], "PENDING rate; do not infer from another project"], ["Allowance", estimate["allowance"], "PENDING applicability; do not infer a fixed sum"], ["Scope complete", 0, data["scope_status"]], ["Tax treatment", data.get("tax_treatment", "PENDING"), "Bid vs payment tax must be reviewed in this project's documents"], ["Project", config.id, data["coverage"]]])
    end = len(rows)+1
    summary = _sheet(book, "Estimate Summary", ["Metric", "Value", "Status"], [["Base scope subtotal", None, "Separate from alternates; pending scope blocks subtotal"], ["Tax - see project treatment", None, "Only after documented rate and treatment per Assumptions"], ["Allowance", None, "Blank until applicability and amount documented"], ["Base cost including tax", None, "Internal cost only; confirm tax treatment before any bid pricing"], ["Unpriced / unmeasured rows", None, "Must reach zero"]])
    summary["B2"] = '=IF(OR(Assumptions!B4<>1,\'Scope Subtotals\'!B2=""),"",\'Scope Subtotals\'!B2)'
    summary["B3"] = '=IF(OR(B2="",Assumptions!B2="",LEFT(Assumptions!B5,7)="PENDING"),"",B2*Assumptions!B2)'
    summary["B4"] = '=IF(Assumptions!B3="","",Assumptions!B3)'
    summary["B5"] = '=IF(OR(B2="",B3="",B4="",Assumptions!B4<>1),"",SUM(B2:B4))'
    summary["B6"] = f'=ROWS(\'Estimate Inputs\'!H2:H{end})-COUNT(\'Estimate Inputs\'!H2:H{end})'
    scopes = ["base"] + sorted({r["pricing_scope"] for r in rows} - {"base"})
    scoped = _sheet(book, "Scope Subtotals", ["Scope", "Subtotal", "Missing rows", "Treatment"], [[scope, None, None, "Independent subtotal; do not add alternatives to base automatically"] for scope in scopes])
    for number in range(2, len(scopes)+2):
        scoped.cell(number, 3, f'=COUNTIFS(\'Estimate Inputs\'!K2:K{end},A{number},\'Estimate Inputs\'!H2:H{end},"")')
        scoped.cell(number, 2, f'=IF(OR(C{number}>0,COUNTIF(\'Estimate Inputs\'!K2:K{end},A{number})=0),"",SUMIF(\'Estimate Inputs\'!K2:K{end},A{number},\'Estimate Inputs\'!H2:H{end}))')
    _sheet(book, "Pending Scope", ["ID", "Issue", "Action"], [[r["id"], r["issue"], r["action"]] for r in data["pending"]])
    _save(book, config.output_dir / "Detailed_Cost_Estimate.xlsx")
    if (config.project_dir / "pricing.json").exists():
        from .cost_workbooks import build_cost_workbook
        build_cost_workbook(read_json(config.data_dir / "estimate/cost_result.json"), config.output_dir / "Cost_Budget.xlsx")


def validate_workbooks(config: ProjectConfig) -> list[str]:
    errors = []
    for name in ("Material_Takeoff.xlsx", "Detailed_Cost_Estimate.xlsx"):
        path = config.output_dir / name
        if not path.exists():
            errors.append(f"Falta {name}")
            continue
        try:
            book = load_workbook(path, data_only=False)
            if name.startswith("Detailed"):
                source = read_json(config.data_dir / "estimate" / "estimate_inputs.json")
                sheet = book["Estimate Inputs"]
                if sheet.max_row != len(source["rows"])+1:
                    errors.append("Filas de presupuesto incompletas")
                for index, row in enumerate(source["rows"], 2):
                    if sheet.cell(index, 5).value != row["quantity"] or sheet.cell(index, 6).value != row["unit_price"]:
                        errors.append(f"Presupuesto fila {index}: valor diferente del JSON")
                    if sheet.cell(index, 8).data_type != "f":
                        errors.append(f"Presupuesto fila {index}: falta fórmula")
                if book["Assumptions"]["B2"].value != source["tax_rate"] or book["Assumptions"]["B3"].value != source["allowance"]:
                    errors.append("Impuesto o allowance diferente del análisis")
            else:
                source = read_json(config.data_dir / "takeoff" / "takeoff.json")
                sheet = book["Takeoff"]
                if sheet.max_row != len(source["records"])+1:
                    errors.append("Filas de takeoff incompletas")
                for index, row in enumerate(source["records"], 2):
                    if sheet.cell(index, 1).value != row["id"] or sheet.cell(index, 5).value != row["quantity"]:
                        errors.append(f"Takeoff fila {index}: cantidad diferente del JSON")
            book.close()
        except (ValueError, KeyError, zipfile.BadZipFile) as exc:
            errors.append(f"{name}: {exc}")
    return errors
