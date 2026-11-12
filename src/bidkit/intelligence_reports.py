"""Separate audiences; client proposals never include supplier/internal margins.

One persisted dossier revision yields three different, professional documents so
that a single project can address different recipients without re-entering data:

* ``internal``  -> "Análisis interno de costos" (CONFIDENCIAL — USO INTERNO).
* ``proposal``  -> "Propuesta comercial" (no internal costs, prices or margins).
* ``supplier``  -> Material/supplier request for quotation.

All company, project, license/registration and date data are read from the
dossier (state.project); nothing is hard-coded to a specific contractor.
Every table is automatically fitted to the printable width so columns are never
clipped, long text wraps within its cell, and the English output is fully
translated.
"""
from __future__ import annotations

from io import BytesIO
from decimal import Decimal
from pathlib import Path
import os
import tempfile
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .data_store import fingerprint
from .estimator_v1 import _fmt

PLACEHOLDER = "No registrado"
# letter page (612 pt) minus two 0.6" margins.
USABLE = 612 - 2 * 0.6 * 72

_DARK = colors.HexColor("#1F3864")
_ACCENT = colors.HexColor("#DEEBF7")
_GRID = colors.grey
_SECT = colors.HexColor("#103E43")

CATEGORY_LABELS = {
    "material": ("Materials", "Materiales"),
    "labor": ("Labor", "Mano de obra"),
    "equipment": ("Equipment", "Equipo"),
    "subcontract": ("Subcontract", "Subcontrato"),
    "logistics": ("Logistics / transport", "Logística / transporte"),
    "disposal": ("Waste disposal", "Disposición de residuos"),
    "tax": ("Documented tax", "Impuesto documentado"),
    "other": ("Other", "Otro"),
}


# --------------------------------------------------------------------------- helpers
def _money(value):
    if value in (None, ""):
        return "—"
    try:
        return f"USD {float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def _text(value, missing=PLACEHOLDER):
    if value in (None, ""):
        return missing
    return str(value)


def _tr(language, en, es):
    return en if language == "en" else es


def _cat(language, key):
    return CATEGORY_LABELS.get(key, (str(key), str(key)))[0 if language == "en" else 1]


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("TRed", parent=styles["Heading2"], textColor=colors.HexColor("#9B1F1F"),
                              fontSize=11, spaceBefore=4, spaceAfter=6))
    return styles


def _fit(widths):
    if not widths:
        return widths
    total = sum(0 if w is None else w for w in widths)
    if total <= USABLE:
        return widths
    scale = USABLE / total
    return [None if w is None else w * scale for w in widths]


def _p(story, styles, text, style="BodyText"):
    story.append(Paragraph(escape(str(text)).replace("\n", "<br/>"), styles[style]))
    if style not in ("Sec", "Title", "TRed", "Heading2", "Heading3"):
        story.append(Spacer(1, 4))


def _table(story, styles, headers, rows, widths=None, highlight_rows=()):
    data = [[Paragraph(escape(str(cell)), styles["BodyText"]) for cell in row]
            for row in ([headers, *rows] if rows else [headers])]
    t = Table(data, colWidths=_fit(list(widths)) if widths else None, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for r in highlight_rows:
        if r < len(data):
            style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#FFF1D4")))
    t.setStyle(TableStyle(style))
    story.extend([t, Spacer(1, 6)])


def _section(story, styles, number, title):
    sec = ParagraphStyle("Sec", parent=styles["Heading2"], fontSize=12.5, textColor=colors.white,
                         backColor=_SECT, borderPadding=(0, 5, 0, 5), spaceBefore=10, spaceAfter=5, leading=15)
    story.append(Paragraph(f"{number}. {title}", sec))
    story.append(Spacer(1, 2))


def _banner(story, styles, text, bg=_DARK, fg=colors.white, size=13, pad=7):
    bar = Table([[Paragraph(text, ParagraphStyle("Bar", fontName="Helvetica-Bold", fontSize=size,
                                                 textColor=fg, leading=size + 3))]], colWidths=[USABLE])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(bar)
    story.append(Spacer(1, 6))


def _build(title, author, story, confidential_note, page_word):
    from reportlab.pdfgen.canvas import Canvas
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=.6 * inch, rightMargin=.6 * inch,
                            topMargin=.6 * inch, bottomMargin=.6 * inch,
                            title=title, author=author or "ALKAN")
    footer_lines = [title, confidential_note]

    def foot(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#7A8A90"))
        y = 0.4 * inch
        canvas.drawString(.6 * inch, y, footer_lines[0])
        canvas.drawRightString(letter[0] - .6 * inch, y, f"{page_word} {doc_.page}")
        canvas.setFont("Helvetica-Bold", 7)
        canvas.drawCentredString(letter[0] / 2, y, footer_lines[1])
        canvas.restoreState()

    class InvariantCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            kwargs["invariant"] = 1
            super().__init__(*args, **kwargs)

    doc.build(story, onFirstPage=foot, onLaterPages=foot, canvasmaker=InvariantCanvas)
    return buffer.getvalue()


def _company(p):
    return _text(p.get("contractor"), "ALKAN")


def _meta_lines(state):
    return [l for l in state["lines"] if l.get("active", True)]


def _selected_quote(result, line):
    comps = result["comparisons"].get(line.get("line_id"), [])
    return next((n for n in comps if n["quote_id"] == line.get("selected_quote_id")), None)


def _quote_record(state, quote_id):
    return next((q for q in state["quotes"] if q.get("quote_id") == quote_id), None)


def _line_money(line, state, result, goods=False):
    q = _selected_quote(result, line)
    if not q or not q.get("eligible"):
        return None
    return q.get("goods_total") if goods else q.get("effective_total")


# --------------------------------------------------------------------------- internal
def _internal_story(state, result, row, language):
    tr = lambda en, es: _tr(language, en, es)
    styles = _styles(); p = state["project"]; story = []
    _banner(story, styles, f"{_company(p)}  ·  {tr('Internal cost analysis', 'Análisis interno de costos')}  ·  {tr('Revision', 'Revisión')} {row['revision']}")
    _p(story, styles, f"{p['name']} · {_text(p['project_id'])} | {_text(p['address'])} | {_text(p['state'])} | {_text(p['county'])} | {_text(p['jurisdiction'])}")
    _p(story, styles, f"{tr('Client', 'Cliente')}: {_text(p['client'])} | {tr('Estimator', 'Responsable')}: {_text(p['estimator'])} | {tr('Trade', 'Especialidad')}: {_text(p['trade'])} | {tr('Date', 'Fecha')}: {row['created_at'][:10]}")
    if not (state.get("current_approval") and not result["release_blockers"]):
        _p(story, styles, tr("DRAFT — incomplete or awaiting human approval. Not a final price.",
                             "BORRADOR — incompleto o pendiente de aprobación humana. No es precio definitivo."), "Heading2")
    _p(story, styles, tr("CONFIDENTIAL — INTERNAL USE ONLY. Do not distribute to the client.",
                         "CONFIDENCIAL — USO INTERNO. No distribuir al cliente."), "TRed")

    active = _meta_lines(state)

    _section(story, styles, "1", tr("Complete Scope of Work", "Alcance completo del trabajo"))
    _p(story, styles, f"{tr('Scope status', 'Estado del alcance')}: {'COMPLETE' if state['review'].get('scope_confirmed') else tr('PENDING REVIEW', 'PENDIENTE DE REVISIÓN')} · {tr('Work type', 'Tipo de obra')}: {_text(p['work_type'], tr('Pending', 'Pendiente'))} · {tr('Contractual relation', 'Relación contractual')}: {_text(p['contractual_relationship'], tr('Pending', 'Pendiente'))}")
    for ctrl in (result.get("classification_controls") or {}).get("review_focus", []):
        _p(story, styles, "• " + ctrl)
    if active:
        for i, l in enumerate(active, 1):
            _p(story, styles, f"{i}. {l['description']} · {_text(l.get('quantity'), tr('PENDING', 'PENDIENTE'))} {_text(l['unit'], '')} [{l.get('quantity_status')}] · ({_cat(language, l.get('category'))})")
    else:
        _p(story, styles, tr("No registered scope lines.", "No hay partidas registradas."))

    _section(story, styles, "2", tr("Quantification & Measurements (Material Takeoff)", "Cuantificación y mediciones (Material Takeoff)"))
    rows = []; pending = []
    for idx, l in enumerate(active):
        ev = l.get("evidence_reference") or {}
        src = f"{_text(ev.get('source_document'))} p. {_text(ev.get('page'), '—')}"
        rows.append([l.get("line_id", "—")[:8], l["description"], _text(l.get("quantity"), tr("PENDING", "PENDIENTE")),
                     _text(l["unit"], ""), l.get("quantity_status"), l.get("scope_key") or "—", src])
        if l.get("quantity") is None:
            pending.append(idx + 1)
    _table(story, styles, [tr("ID", "ID"), tr("Item", "Partida"), tr("Qty", "Cantidad"), tr("Unit", "Unidad"),
                           tr("Status", "Estado"), tr("Scope key", "Clave alcance"), tr("Evidence", "Evidencia")],
           rows, widths=[56, 160, 52, 40, 96, 84, 110], highlight_rows=pending)
    _p(story, styles, f"{tr('Lines', 'Partidas')}: {len(active)} · {tr('Pending measurement', 'Pendientes de medición')}: {len(pending)}")

    _section(story, styles, "3", tr("Materials, Specifications, Quantities & Prices", "Materiales, especificaciones, cantidades y precios"))
    mrows = []
    for l in active:
        if l.get("category") != "material":
            continue
        q = _selected_quote(result, l); rec = _quote_record(state, l.get("selected_quote_id"))
        mrows.append([l.get("line_id", "—")[:8], l["description"], _text(l.get("quantity"), tr("PENDING", "PENDIENTE")),
                      _text(l["unit"], ""), _text(rec.get("pack_size") if rec else None),
                      _text(q.get("provider") if q else None),
                      _text(q.get("normalized_unit_price") if q else None),
                      _line_money(l, state, result, goods=True),
                      _text((q.get("kind") if q else None)),
                      tr("Selected", "Seleccionada") if q else tr("No quote", "Sin cotización")])
    _table(story, styles, [tr("ID", "ID"), tr("Material / specification", "Material / especificación"), tr("Qty", "Cant."), tr("Unit", "Unid."),
                           tr("Pack", "Present."), tr("Provider", "Proveedor"), tr("Norm. unit price", "Precio unit normalizado"),
                           tr("Goods USD", "Total materiales USD"), tr("Class", "Clase"), tr("Status", "Estado")],
           mrows, widths=[52, 120, 38, 36, 42, 88, 66, 62, 52, 52])
    _p(story, styles, f"{tr('Materials subtotal (complete only)', 'Subtotal de materiales (solo completo)')}: {_money(result['totals'].get('material_cost'))}")

    _section(story, styles, "4", tr("Labor, Hours, Rates & Costs", "Mano de obra, horas, tarifas y costos"))
    lrows = []
    for l in active:
        if l.get("category") in ("material", "logistics", "disposal", "equipment", "other", "tax"):
            continue
        q = _selected_quote(result, l)
        lrows.append([l.get("line_id", "—")[:8], l["description"], _text(l.get("quantity"), tr("PENDING", "PENDIENTE")),
                      _text(l["unit"], ""), _text(l.get("specification")),
                      _text(q.get("provider") if q else None), _line_money(l, state, result),
                      tr("Selected", "Seleccionada") if q else tr("Pending", "Pendiente")])
    _table(story, styles, [tr("ID", "ID"), tr("Labor", "Mano de obra"), tr("Qty", "Cant."), tr("Unit", "Unid."),
                           tr("Specification", "Especificación"), tr("Provider", "Proveedor ejecutor"),
                           tr("Cost USD", "Costo USD"), tr("Status", "Estado")],
           lrows, widths=[52, 130, 38, 36, 90, 88, 64, 54])
    _p(story, styles, tr("Hours and rates must be documented per line; the system never infers a wage or productivity.",
                         "Las horas y tarifas deben documentarse por partida; el sistema no infiere salarios ni productividad."))

    _section(story, styles, "5", tr("Office, Permits, Equipment & Mobilization", "Oficina, permisos, equipos y movilización"))
    fin = state["financial"]
    _p(story, styles, f"{tr('Overhead', 'Indirectos')}: {_text(fin.get('overhead_percent'), tr('PENDING', 'PENDIENTE'))}% · {tr('Contingency', 'Contingencia')}: {_text(fin.get('contingency_percent'), tr('PENDING', 'PENDIENTE'))}% · {tr('Material sensitivity', 'Sensibilidad materiales')}: {_text(fin.get('sensitivity_percent'), tr('PENDING', 'PENDIENTE'))}%")
    erows = []
    for l in active:
        if l.get("category") not in ("equipment", "logistics", "disposal", "other", "tax"):
            continue
        q = _selected_quote(result, l)
        erows.append([l.get("line_id", "—")[:8], l["description"], _cat(language, l.get("category")),
                      _text(l.get("quantity"), tr("PENDING", "PENDIENTE")), _line_money(l, state, result)])
    _table(story, styles, [tr("ID", "ID"), tr("Concept", "Concepto"), tr("Category", "Categoría"), tr("Qty", "Cant."), tr("Cost USD", "Costo USD")],
           erows, widths=[56, 190, 110, 56, 90])
    _p(story, styles, tr("Permits, mobilization and office are shown only when documented/parameterized in the dossier.",
                         "Permisos, movilización y oficina se muestran solo si están documentados o parametrizados en el expediente."))

    _section(story, styles, "6", tr("Final Breakdown — direct cost, contingency, overhead, profit, adjustments & final price",
                                    "Desglose final — costo directo, contingencia, overhead, utilidad, ajustes comerciales y precio final"))
    t = result["totals"]
    rows6 = [
        [tr("Materials", "Materiales"), _money(t.get("material_cost"))],
        [tr("Direct cost", "Costo directo"), _money(t.get("direct_cost"))],
        [tr("Overhead", "Indirectos (overhead)"), _money(t.get("overhead_cost"))],
        [tr("Contingency", "Contingencia"), _money(t.get("contingency_cost"))],
        [tr("Estimated all-in internal cost", "Costo interno total"), _money(t.get("estimated_all_in_cost"))],
        [tr("Selling margin", "Margen sobre venta"), f"{_text(t.get('target_margin_percent'), tr('PENDING', 'PENDIENTE'))}%"],
        [tr("Estimated gross profit (commercial adjustment)", "Utilidad estimada (ajuste comercial)"), _money(t.get("estimated_gross_profit"))],
        [tr("Proposed selling price (before contract-specific taxes)", "Precio de venta propuesto (antes de impuestos de contrato)"), _money(t.get("proposed_price_before_contract_specific_taxes"))],
    ]
    approval = state.get("current_approval")
    if approval:
        rows6.append([tr("Approved selling price", "Precio de venta aprobado"), _money(approval.get("approved_price"))])
        rows6.append([tr("Approval reference", "Referencia aprobada"), f"{approval.get('approval_id', '—')[:8]} · {approval.get('approved_by')} · {approval.get('approved_at')}"])
    _table(story, styles, [tr("Concept", "Concepto"), "USD"], rows6, widths=[300, 130])
    _p(story, styles, tr("Any adjustment between calculated cost and offered price is the documented margin above plus any recorded approval; it is never modified automatically.",
                         "Cualquier ajuste entre costo calculado y precio ofertado es el margen documentado anterior más cualquier aprobación registrada; nunca se modifica automáticamente."))

    _section(story, styles, "7", tr("Risks, Observations & Pending Verifications", "Riesgos, observaciones y verificaciones pendientes"))
    blockers = result.get("release_blockers") or []
    if blockers:
        for b in blockers:
            _p(story, styles, "• " + b)
    else:
        _p(story, styles, tr("No pending verifications.", "No hay verificaciones pendientes."))
    for issue in [i for i in (result.get("issues") or []) if not i.get("resolved")]:
        _p(story, styles, "• " + tr("Pending contradiction/scope:", "Contradicción/alcance pendiente:") + f" {issue.get('issue_id')} ({issue.get('kind')})")
    for alert in (result.get("alerts") or []):
        _p(story, styles, "• " + alert)
    actual = result.get("actual_vs_estimated") or {}
    if actual.get("actual_documented_cost"):
        _p(story, styles, tr("Estimated vs documented actual cost", "Estimado frente a costo real documentado")
           + f": {_money(actual.get('estimated_cost'))} / {_money(actual.get('actual_documented_cost'))} · {tr('Variance', 'Diferencia')}: {_money(actual.get('variance'))}")
    _p(story, styles, tr("This internal analysis is a working document. It does not constitute an offer to the client.",
                         "Este análisis interno es documento de trabajo. No constituye una oferta al cliente."))
    return story


# --------------------------------------------------------------------------- proposal
def _proposal_story(state, result, row, language):
    tr = lambda en, es: _tr(language, en, es)
    styles = _styles(); p = state["project"]; approval = state["current_approval"]
    story = []
    _banner(story, styles, f"{_company(p)}  ·  {tr('Commercial proposal', 'Propuesta comercial')}  ·  {tr('Revision', 'Revisión')} {row['revision']}")
    _p(story, styles, f"{p['name']} · {_text(p['project_id'])}")
    _p(story, styles, f"{_text(p['address'])} | {_text(p['state'])} | {_text(p['county'])} | {_text(p['jurisdiction'])}")
    _p(story, styles, f"{tr('Date', 'Fecha')}: {row['created_at'][:10]} · {tr('Proposed to', 'Propuesta a')}: {_text(p['client'])}")
    _p(story, styles, f"{tr('Prepared by', 'Elaborada por')}: {_company(p)} · {tr('Estimator', 'Responsable')}: {_text(p['estimator'])}")
    _p(story, styles, tr("Commercial terms and selling price; this document does not disclose internal costs, prices, rates or margins.",
                         "Condiciones comerciales y precio de venta; este documento no revela costos internos, precios, tarifas ni márgenes."))

    if not approval or result["release_blockers"]:
        _p(story, styles, tr("PROPOSAL BLOCKED — requires a valid human approval and completed verifications. Not a final offer.",
                             "PROPUESTA BLOQUEADA — requiere una aprobación humana vigente y verificaciones completas. No es oferta definitiva."), "TRed")

    price = Decimal(approval["approved_price"]) if approval else None
    active = _meta_lines(state)
    _p(story, styles, tr("Scope of work and proposed selling prices (USD)", "Alcance del trabajo y precios de venta propuestos (USD)"), "Heading2")
    if price is not None:
        costs = {r["id"]: Decimal(r["line_cost"]) for r in result["lines"] if r.get("line_cost")}
        direct = sum(costs.values()); allocated = Decimal(0)
        for i, line in enumerate(active):
            if direct:
                value = price - allocated if i == len(active) - 1 else Decimal(_fmt(price * costs[line["line_id"]] / direct))
            else:
                value = Decimal(0)
            allocated += value
            _p(story, styles, f"{line['description']} · {line.get('quantity')} {line.get('unit')} · USD {_fmt(value)}")
            _p(story, styles, line.get("specification", ""))
        _p(story, styles, f"{tr('Proposed total', 'Total propuesto')}: USD {_fmt(price)}", "Heading2")
    else:
        _p(story, styles, "USD —")

    for key, label in (("assumptions", tr("Assumptions", "Supuestos")), ("exclusions", tr("Exclusions", "Exclusiones")),
                       ("terms", tr("Commercial terms", "Condiciones comerciales")), ("valid_until", tr("Validity", "Vigencia"))):
        _p(story, styles, f"{label}: {_text(state['review'].get(key))}")
    _p(story, styles, f"{tr('Tax treatment', 'Tratamiento tributario')}: {_text(state['review'].get('tax_basis'))}")
    if approval:
        _p(story, styles, f"{tr('Approved reference', 'Referencia aprobada')}: {approval['approval_id'][:8]} | {approval['approved_by']} | {approval['approved_at']}")
        _p(story, styles, tr("Internal approval for proposal issuance. Contract acceptance is recorded separately.",
                             "Aprobación interna para emisión de propuesta. La aceptación contractual se registra por separado."))

    _p(story, styles, tr("Authorization", "Autorización"), "Heading2")
    auth = Table([["      ", "", "      "], ["", "      ", ""]], colWidths=[1.5 * inch, 3.8 * inch, 1.5 * inch])
    auth.setStyle(TableStyle([
        ("GRID", (0, 1), (-1, -1), 0.4, _GRID),
        ("BOX", (0, 1), (-1, -1), 0.4, _GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 26),
    ]))
    story.append(auth)
    story.append(Spacer(1, 4))
    _p(story, styles, tr("Authorized by (name & title):", "Autorizado por (nombre y título):"))
    _p(story, styles, tr("Signature / Date:", "Firma / Fecha:"))
    _p(story, styles, tr("This authorization box is for contract/proposal acceptance when applicable; internal estimate approval is a separate, recorded human gate.",
                         "Este recuadro de autorización es para aceptación del contrato/propuesta cuando corresponda; la aprobación interna del estimado es una compuerta humana separada y registrada."))
    return story


def _contract_story(state, result, row, language):
    """Contract acceptance record: scope, amount and signatures only; never internal costs, rates or margins."""
    tr = lambda en, es: _tr(language, en, es)
    styles = _styles(); p = state["project"]
    accepted = state["contracts"][-1]
    evidence = accepted.get("evidence_reference") or {}
    story = []
    _banner(story, styles, f"{_company(p)}  ·  {tr('Construction contract acceptance record', 'Registro de aceptación de contrato de obra')}  ·  {tr('Revision', 'Revisión')} {row['revision']}")
    _p(story, styles, f"{p['name']} · {_text(p['project_id'])}")
    _p(story, styles, f"{_text(p['address'])} | {_text(p['state'])} | {_text(p['county'])} | {_text(p['jurisdiction'])}")
    _p(story, styles, f"{tr('Owner / client', 'Propietario / cliente')}: {_text(p['client'])} · {tr('Contractor', 'Contratista')}: {_company(p)}")
    _p(story, styles, f"{tr('Accepted contract amount', 'Monto contractual aceptado')}: {_money(accepted['amount'])}", "Heading2")
    _p(story, styles, f"{tr('Recorded by', 'Registrado por')}: {accepted['confirmed_by']} | {accepted['confirmed_at']}")
    _p(story, styles, f"{tr('Evidence', 'Evidencia')}: {_text(evidence.get('document_id'))} · p. {_text(evidence.get('page'))}")
    _p(story, styles, tr("Scope of work covered by the accepted contract", "Alcance del trabajo cubierto por el contrato aceptado"), "Heading2")
    for line in _meta_lines(state):
        _p(story, styles, f"{line['description']} · {_text(line.get('quantity'))} {line.get('unit', '')}")
        _p(story, styles, line.get("specification", ""))
    included = [c for c in state.get("change_orders", []) if c.get("status") == "REVIEWED_INCLUDED"]
    if included:
        _p(story, styles, tr("Reviewed change orders included in scope", "Cambios revisados incluidos en el alcance"), "Heading2")
        for change in included:
            _p(story, styles, f"{change['description']} · {_text(change.get('review_reason'))}")
    for key, label in (("assumptions", tr("Assumptions", "Supuestos")), ("exclusions", tr("Exclusions", "Exclusiones")),
                       ("terms", tr("Contract terms", "Condiciones del contrato"))):
        _p(story, styles, f"{label}: {_text(state['review'].get(key))}")
    _p(story, styles, f"{tr('Tax treatment', 'Tratamiento tributario')}: {_text(state['review'].get('tax_basis'))}")
    _p(story, styles, tr("Signatures", "Firmas"), "Heading2")
    _p(story, styles, tr("Contractor — name, title, signature, date: ______________________________",
                         "Contratista — nombre, cargo, firma, fecha: ______________________________"))
    _p(story, styles, tr("Owner / client — name, title, signature, date: ______________________________",
                         "Propietario / cliente — nombre, cargo, firma, fecha: ______________________________"))
    _p(story, styles, tr("This record documents the contract acceptance registered in ALKAN. It does not replace the construction contract signed by the parties; legal review is outside this document.",
                         "Este registro documenta la aceptación contractual registrada en ALKAN. No sustituye el contrato de obra firmado por las partes; la revisión legal queda fuera de este documento."))
    return story


# --------------------------------------------------------------------------- render
def _render_title(kind, language):
    titles = {"internal": ("Internal Cost Analysis", "Análisis interno de costos"),
              "supplier": ("Supplier Material Request / Material List", "Solicitud de materiales a proveedores"),
              "proposal": ("Formal Estimate / Bid Proposal", "Propuesta comercial"),
              "contract": ("Construction Contract Acceptance Record", "Registro de aceptación de contrato de obra")}
    return titles[kind][0 if language == "en" else 1]


def render_document(row, kind, language="en"):
    if language not in ("en", "es") or kind not in ("internal", "supplier", "proposal", "contract"):
        raise ValueError("Documento o idioma inválido")
    state = row["state"]; result = state["result"]; p = state["project"]
    if kind == "supplier":
        from .rfq_documents import dossier_rfq, rfq_bytes
        return rfq_bytes(dossier_rfq(row, language), idioma=language, borrador=True)
    tr = lambda en, es: _tr(language, en, es)
    if kind == "contract" and not state.get("contracts"):
        raise ValueError("Contrato no registrado: registre la aceptación contractual antes de generar este documento")
    if kind == "proposal" and (not state.get("current_approval") or result["release_blockers"] or result["status"] not in ("APPROVED", "PROPOSAL_ISSUED")):
        raise ValueError("Propuesta bloqueada: requiere aprobación humana vigente y verificaciones completas")

    if kind == "internal":
        story = _internal_story(state, result, row, language)
    elif kind == "proposal":
        story = _proposal_story(state, result, row, language)
    elif kind == "contract":
        story = _contract_story(state, result, row, language)
    else:
        styles = _styles()
        story = []
        _banner(story, styles, f"{_company(p)}  ·  {tr('Supplier material request', 'Solicitud de materiales a proveedores')}  ·  Rev. {row['revision']}")
        _p(story, styles, f"{p['name']} · {_text(p['project_id'])} | {tr('Date', 'Fecha')}: {row['created_at'][:10]}")
        if not state.get("current_approval") or result["release_blockers"]:
            _p(story, styles, tr("DRAFT — incomplete or awaiting human approval. Not a final price.",
                                 "BORRADOR — incompleto o pendiente de aprobación humana. No es precio definitivo."), "Heading2")
        _p(story, styles, tr("REQUEST FOR QUOTATION — quantities and specifications require supplier confirmation. This is not a purchase order.",
                             "SOLICITUD DE COTIZACIÓN — cantidades y especificaciones sujetas a confirmación. No es orden de compra."), "Heading2")
        for line in _meta_lines(state):
            if line["category"] != "material":
                continue
            _p(story, styles, f"{line['line_id'][:8]} | {line['description']} | {_text(line.get('quantity'), tr('PENDING', 'PENDIENTE'))} {line.get('unit', '')} | {line.get('specification', '')}")
            _p(story, styles, tr("Confirm manufacturer, SKU, package, availability, unit price, delivery, applicable tax and validity.",
                                 "Confirmar fabricante, SKU, presentación, disponibilidad, precio unitario, entrega, impuestos aplicables y vigencia."))
        _p(story, styles, tr("Return your quotation referencing project, revision and line ID. Revised quotes are retained as separate versions.",
                             "Responder indicando proyecto, revisión y partida. Cotizaciones revisadas se conservan como versiones separadas."))

    title = _render_title(kind, language)
    confidential_note = tr("CONFIDENTIAL — INTERNAL USE ONLY", "CONFIDENCIAL — USO INTERNO") if kind == "internal" else ""
    return _build(title, p["contractor"] or "ALKAN", story, confidential_note, tr("Page", "Página"))


def export_document(service, project_id, kind, language="en"):
    row = service.store.load(project_id)
    service.check_originals(project_id, row["state"])
    # Recheck dates and quote eligibility at export, even if snapshot was approved yesterday.
    row["state"]["result"] = service.evaluate(row["state"])
    raw = render_document(row, kind, language)
    directory = service.store.child(project_id, "exports"); directory.mkdir(exist_ok=True)
    name = f"{kind}-{language}-r{row['revision']:06d}-{fingerprint(list(raw))[:12]}.pdf"
    path = directory / name
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Exportación histórica ausente o modificada; concilie antes de regenerar")
    else:
        fd, staged = tempfile.mkstemp(dir=directory, suffix=".staged")
        try:
            with os.fdopen(fd, "wb") as fp: fp.write(raw); fp.flush(); os.fsync(fp.fileno())
            try: os.link(staged, path)
            except FileExistsError:
                if path.read_bytes() != raw: raise ValueError("Exportación histórica modificada")
        finally: Path(staged).unlink(missing_ok=True)
    return path