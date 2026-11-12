"""Delivery of an estimate run: report PDF, ZIP, human authorization and re-branding.

The rules are the ones ALKAN follows by hand: three documents from one
computation, the proposal is a DRAFT until a named person authorizes it, and
re-branding a package for another contractor recomputes it with that
contractor's own rates and markups (never a find-and-replace on a PDF).
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .estimator_agent.tools import merge_profile
from .package_build import build


def _inline(text: str) -> str:
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"(?<![\w*])_(\(.+?\))_(?!\w)", r"<i>\1</i>", text)


def report_pdf(md_path: Path, pdf_path: Path | None = None) -> Path:
    """Plain, readable PDF of the agent report (headings, paragraphs and bullets)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

    md_path = Path(md_path)
    pdf_path = Path(pdf_path) if pdf_path else md_path.with_suffix(".pdf")
    base = getSampleStyleSheet()
    ink = colors.HexColor("#103e43")
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.5)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=ink, spaceAfter=8)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=ink, spaceBefore=10, spaceAfter=4)
    flow, bullets = [], []

    def flush():
        if bullets:
            flow.append(ListFlowable([ListItem(Paragraph(b, body), leftIndent=12) for b in bullets],
                                     bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8))
            bullets.clear()

    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("- "):
            bullets.append(_inline(line[2:]))
            continue
        flush()
        if line.startswith("# "):
            flow.append(Paragraph(_inline(line[2:]), h1))
        elif line.startswith("## "):
            flow.append(Paragraph(_inline(line[3:]), h2))
        elif line:
            flow.append(Paragraph(_inline(line), body))
        else:
            flow.append(Spacer(1, 4))
    flush()
    SimpleDocTemplate(str(pdf_path), pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                      topMargin=0.8 * inch, bottomMargin=0.8 * inch, title=md_path.stem, author="ALKAN Bid Engine").build(flow)
    return pdf_path


def deliverables(run_dir: Path) -> list[Path]:
    """Files a person receives: the PDFs first, in document order."""
    run_dir = Path(run_dir)
    pdfs = sorted(p for p in run_dir.glob("*.pdf"))
    return pdfs + sorted(run_dir.glob("*_REPORTE_AGENTE.md"))


def make_zip(run_dir: Path, key: str, *, package_json: bool = True, log: bool = False) -> Path:
    run_dir = Path(run_dir)
    files = deliverables(run_dir)
    if package_json:
        files += [p for p in sorted(run_dir.glob("*.json")) if p.name != "run.json"]
    if log:
        files += sorted(run_dir.glob("*_agent_log.jsonl"))
    if not files:
        raise ValueError("La corrida no tiene archivos para entregar")
    target = run_dir / f"{key}_ENTREGA.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.name)
    return target


def authorize(package_path: Path, out_dir: Path, actor: str, note: str = "") -> dict:
    """A named person releases the proposal: DRAFT → LUMP-SUM PROPOSAL, rebuilt and re-verified."""
    actor = (actor or "").strip()
    if not actor:
        raise ValueError("Indique quién autoriza")
    package_path = Path(package_path)
    pkg = json.loads(package_path.read_text(encoding="utf-8"))
    release = dict(pkg.get("release") or {})
    release.update({"authorized": True, "authorized_by": actor,
                    "authorized_at": datetime.now().astimezone().isoformat(timespec="seconds")})
    if note.strip():
        release["note"] = note.strip()
    pkg["release"] = release
    package_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = build(package_path, out_dir)
    if manifest["qa"]["status"] != "PASS":
        raise ValueError("La verificación cruzada falló al regenerar; no se autorizó")
    return manifest


def rebrand(package_path: Path, profile: dict, profiles_dir: Path, out_dir: Path) -> tuple[Path, dict]:
    """Same takeoff, another contractor: recompute with that profile and rebuild the three documents."""
    source = json.loads(Path(package_path).read_text(encoding="utf-8"))
    keep = set(profile.get("labor_rates", {}))
    draft = {k: source[k] for k in ("project", "materials", "labor", "other", "scope", "exclusions")}
    draft["assumptions"] = source.get("assumptions", [])
    draft["labor_rates"] = {k: {x: y for x, y in r.items() if x != "burden_pct"}
                            for k, r in source["labor_rates"].items() if k not in keep}
    missing = {l["rate"] for l in draft["labor"]} - set(draft["labor_rates"]) - keep
    if missing:
        raise ValueError(f"El perfil no define las tarifas {sorted(missing)} que usa este paquete")
    pkg = merge_profile(draft, profile, profiles_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / Path(package_path).name
    target.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    return target, build(target, out_dir)
