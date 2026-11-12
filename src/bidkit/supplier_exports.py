"""Read-only supplier export center for one persisted V3 dossier.

This module formats existing supplier records, project relationships and quote
versions. It never appends a dossier revision, changes a selection or infers a
supplier from a legacy pricing reference.
"""
from __future__ import annotations

import csv
from datetime import UTC, datetime
from decimal import Decimal
import os
from hashlib import sha256
from io import StringIO, BytesIO
from pathlib import Path
import re
import tempfile

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfgen.canvas import Canvas

EXPORT_KINDS = {"directory", "project", "comparison"}
FORMATS = {"csv", "pdf", "both"}
LANGUAGES = {"en", "es"}
MISSING = "No registrado"
UNVERIFIED = "No verificado"
_DIGEST_RE = re.compile(r"^supplier-(?:directory|project|comparison)-(?:en|es)-r\d{6}-[0-9a-f]{12}\.(?:csv|pdf)$")


def _text(value, missing=MISSING):
    if value is None or value == "":
        return missing
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return str(value)


def _date(value):
    return _text(value)


def _evidence(record):
    ev=record.get("evidence_reference") or {}
    if not ev:
        return {"document":MISSING,"page":MISSING,"excerpt":MISSING,"sha256":MISSING}
    return {"document":_text(ev.get("source_document") or ev.get("original_name")),
            "page":_text(ev.get("page")),"excerpt":_text(ev.get("excerpt")),"sha256":_text(ev.get("sha256"))}


def _version_status(record, records):
    rid=record.get("quote_id") or record.get("entry_id")
    later=any(r.get("supersedes")==rid for r in records)
    if later:return "SUPERSEDED"
    return "CURRENT_VERSION" if not record.get("supersedes") else "CURRENT_REVISED_VERSION"


def _supplier_provenance(supplier, state):
    sid=supplier.get("supplier_id")
    quotes=[q for q in state.get("quotes",[]) if q.get("supplier_id")==sid]
    catalog=[r for r in state.get("catalog_entries",[]) if str(r.get("supplier"))==str(supplier.get("name")) and str(r.get("location"))==str(supplier.get("location"))]
    refs=[q.get("catalog_reference") for q in quotes if q.get("catalog_reference")]
    if refs:
        source="IDENTIFIED_FROM_CATALOG_REFERENCE"
    elif quotes:
        source="REGISTERED_RECORD_WITH_QUOTE_ORIGIN_NOT_RECORDED"
    elif catalog:
        source="IDENTIFIED_FROM_LOCAL_CATALOG_RECORD"
    else:
        source="REGISTERED_RECORD_ORIGIN_NOT_RECORDED"
    verified = bool(supplier.get("reviewed_by") and supplier.get("reviewed_at"))
    missing=[]
    for field in ("company","specialty","city","contact_name","contact_email","phone"):
        if not supplier.get(field):missing.append(field)
    return source, ("VERIFIED_BY_REVIEW_RECORD" if verified else UNVERIFIED), missing, quotes, catalog


def _base(service, project_id):
    row=service.store.load(project_id)
    service.check_originals(project_id,row["state"])
    state=row["state"];project=state["project"]
    return row,state,project


def _meta(row, project, kind, language, coverage):
    return {"project_id":project.get("project_id"),"project_name":project.get("name"),"source_revision":row["revision"],
            # A revision timestamp keeps repeated exports byte-identical.  The
            # artifact represents this immutable snapshot, not an audit event.
            "generated_at":row.get("created_at") or datetime.now(UTC).isoformat(),"export_kind":kind,"language":language,
            "coverage":coverage,"external_discovery":"NOT_AVAILABLE; NO_EXTERNAL_DIRECTORY_OR_CONNECTOR"}


def directory_data(service, project_id, language="en"):
    row,state,project=_base(service,project_id);rows=[];all_missing=set()
    suppliers=state.get("suppliers",[])
    for s in suppliers:
        provenance,verification,missing,quotes,catalog=_supplier_provenance(s,state);all_missing.update(missing)
        evidence=_evidence(quotes[-1] if quotes else (catalog[-1] if catalog else {}))
        rows.append({"project_id":project.get("project_id"),"project_name":project.get("name"),"supplier_id":_text(s.get("supplier_id")),
          "supplier_name":_text(s.get("name")),"company":_text(s.get("company")),"specialty":_text(s.get("specialty")),
          "city":_text(s.get("city")),"location":_text(s.get("location")),"contact_name":_text(s.get("contact_name")),
          "contact_email":_text(s.get("contact_email")),"phone":_text(s.get("phone")),"verification_status":verification,
          "verified_by":_text(s.get("reviewed_by")),"verified_at":_date(s.get("reviewed_at")),
          "provenance":provenance,"missing_fields":", ".join(missing) if missing else "None recorded",
          "quote_count":len(quotes),"catalog_record_count":len(catalog),"last_recorded_at":_date(s.get("reviewed_at") or (quotes[-1].get("recorded_at") if quotes else None)),
          "evidence_document":evidence["document"],"evidence_page":evidence["page"],"evidence_sha256":evidence["sha256"],"row_status":"REGISTERED_SUPPLIER"})
    if not rows:
        rows=[{"project_id":project.get("project_id"),"project_name":project.get("name"),"supplier_id":"","supplier_name":MISSING,
          "company":MISSING,"specialty":MISSING,"city":MISSING,"location":MISSING,"contact_name":MISSING,"contact_email":MISSING,"phone":MISSING,
          "verification_status":UNVERIFIED,"verified_by":MISSING,"verified_at":MISSING,"provenance":"NO_REGISTERED_SUPPLIER_RECORD","missing_fields":"supplier record","quote_count":0,
          "catalog_record_count":0,"last_recorded_at":MISSING,"evidence_document":MISSING,"evidence_page":MISSING,"evidence_sha256":MISSING,
          "row_status":"NO_REGISTERED_RECORDS"}]
    coverage={"registered_supplier_records":len(suppliers),"contact_fields_available":False,"company_specialty_city_fields_available":False,
              "verified_records":sum(1 for r in rows if r["verification_status"]=="VERIFIED_BY_REVIEW_RECORD"),
              "missing_fields":sorted(all_missing) if suppliers else ["supplier directory"]}
    return _meta(row,project,"directory",language,coverage),rows


def project_data(service, project_id, language="en"):
    row,state,project=_base(service,project_id);rows=[];quotes=state.get("quotes",[]);suppliers={s.get("supplier_id"):s for s in state.get("suppliers",[])}
    active=[l for l in state.get("lines",[]) if l.get("active",True)]
    for line in active:
        line_quotes=[q for q in quotes if q.get("line_id")==line.get("line_id")]
        if not line_quotes:
            rows.append({"project_id":project.get("project_id"),"project_name":project.get("name"),"line_id":_text(line.get("line_id")),"description":_text(line.get("description")),
              "category":_text(line.get("category")),"quantity":_text(line.get("quantity")),"unit":_text(line.get("unit")),"specification":_text(line.get("specification")),
              "supplier_id":"","supplier_name":MISSING,"supplier_location":MISSING,"supplier_status":"NO_SUPPLIER_REGISTERED",
              "request_status":"NO_QUOTE_REGISTERED","coverage_status":"NO_DOCUMENTED_QUOTE","quote_id":"","quote_kind":"",
              "quote_date":MISSING,"valid_until":MISSING,"version_status":"", "evidence_document":MISSING,"evidence_page":MISSING,"evidence_sha256":MISSING})
            continue
        for q in line_quotes:
            s=suppliers.get(q.get("supplier_id"));ev=_evidence(q)
            rows.append({"project_id":project.get("project_id"),"project_name":project.get("name"),"line_id":_text(line.get("line_id")),"description":_text(line.get("description")),
              "category":_text(line.get("category")),"quantity":_text(line.get("quantity")),"unit":_text(line.get("unit")),"specification":_text(line.get("specification")),
              "supplier_id":_text(q.get("supplier_id")),"supplier_name":_text(q.get("provider")),"supplier_location":_text(q.get("location")),
              "supplier_status":"REGISTERED_SUPPLIER" if s else "QUOTE_PROVIDER_WITHOUT_SUPPLIER_RECORD","request_status":"QUOTE_RECEIVED",
              "coverage_status":"SELECTED_QUOTE" if line.get("selected_quote_id")==q.get("quote_id") else "QUOTE_ON_FILE",
              "quote_id":_text(q.get("quote_id")),"quote_kind":_text(q.get("kind")),"quote_date":_date(q.get("quoted_on")),"valid_until":_date(q.get("valid_until")),
              "version_status":_version_status(q,quotes),"evidence_document":ev["document"],"evidence_page":ev["page"],"evidence_sha256":ev["sha256"]})
    if not rows:
        rows=[{"project_id":project.get("project_id"),"project_name":project.get("name"),"line_id":"", "description":MISSING,"category":MISSING,"quantity":MISSING,"unit":MISSING,"specification":MISSING,
          "supplier_id":"","supplier_name":MISSING,"supplier_location":MISSING,"supplier_status":"NO_REGISTERED_SUPPLIER_RECORD","request_status":"NO_LINES_REGISTERED","coverage_status":"NO_PROJECT_DATA",
          "quote_id":"","quote_kind":"","quote_date":MISSING,"valid_until":MISSING,"version_status":"","evidence_document":MISSING,"evidence_page":MISSING,"evidence_sha256":MISSING}]
    coverage={"active_project_lines":len(active),"lines_with_quotes":sum(bool([q for q in quotes if q.get("line_id")==l.get("line_id")]) for l in active),"quote_rows":len(quotes),
              "registered_suppliers":len(state.get("suppliers",[])),"missing_supplier_records":sum(1 for r in rows if r["supplier_status"]=="NO_SUPPLIER_REGISTERED")}
    return _meta(row,project,"project",language,coverage),rows


def comparison_data(service, project_id, language="en"):
    row,state,project=_base(service,project_id);result=service.evaluate(state,include_impacts=False);rows=[];quotes=state.get("quotes",[]);suppliers={s.get("supplier_id"):s for s in state.get("suppliers",[])}
    line_by_id={l.get("line_id"):l for l in state.get("lines",[])}
    normalized={}
    for line_id,options in result.get("comparisons",{}).items():
        normalized.update({o.get("quote_id"):o for o in options})
    for q in quotes:
        line=line_by_id.get(q.get("line_id"));ev=_evidence(q);n=normalized.get(q.get("quote_id"),{});later=any(x.get("supersedes")==q.get("quote_id") for x in quotes)
        eligible=not n.get("issues")
        currency=_text(q.get("currency"))
        rows.append({"project_id":project.get("project_id"),"project_name":project.get("name"),"line_id":_text(q.get("line_id")),"description":_text(line.get("description") if line else None),
          "quantity":_text(line.get("quantity") if line else q.get("quoted_quantity")),"unit":_text(line.get("unit") if line else q.get("quoted_quantity_unit")),"specification":_text(q.get("specification")),
          "supplier_id":_text(q.get("supplier_id")),"supplier_name":_text(q.get("provider")),"supplier_location":_text(q.get("location")),
          "quote_id":_text(q.get("quote_id")),"quote_kind":_text(q.get("kind")),"version_status":"SUPERSEDED" if later else ("CURRENT_REVISED_VERSION" if q.get("supersedes") else "CURRENT_VERSION"),
          "supersedes_quote_id":_text(q.get("supersedes")),"quote_date":_date(q.get("quoted_on")),"valid_until":_date(q.get("valid_until")),"currency":currency,
          "unit_price":_text(q.get("unit_price")),"pack_size":_text(q.get("pack_size")),"discount_percent":_text(q.get("discount_percent")),"delivery":_text(q.get("delivery")),"tax_total":_text(q.get("tax_total")),
          "normalized_material_total":_text(n.get("goods_total") if currency=="USD" and eligible else None),"effective_total":_text(n.get("effective_total") if currency=="USD" and eligible else None),
          "total_status":"ELIGIBLE_USD_TOTAL" if currency=="USD" and eligible else ("NOT_AGGREGATED_CURRENCY_OR_INELIGIBLE"),
          "selected":"Yes" if line and line.get("selected_quote_id")==q.get("quote_id") else "No","technical_match":_text(q.get("technical_match")),"availability_confirmed":_text(q.get("availability_confirmed")),"confirmed":_text(q.get("confirmed")),
          "eligibility_issues":"; ".join(n.get("issues",[])) or "None recorded","evidence_document":ev["document"],"evidence_page":ev["page"],"evidence_sha256":ev["sha256"],
          "source_type":"CATALOG_REFERENCE" if q.get("catalog_reference") else ("PHONE_QUOTE_NO_DOCUMENT" if not q.get("evidence_reference") else "QUOTE_RECEIVED")})
    if not rows:
        rows=[{"project_id":project.get("project_id"),"project_name":project.get("name"),"line_id":"","description":MISSING,"quantity":MISSING,"unit":MISSING,"specification":MISSING,"supplier_id":"","supplier_name":MISSING,"supplier_location":MISSING,"quote_id":"","quote_kind":"","version_status":"NO_QUOTES_REGISTERED","supersedes_quote_id":"","quote_date":MISSING,"valid_until":MISSING,"currency":MISSING,"unit_price":MISSING,"pack_size":MISSING,"discount_percent":MISSING,"delivery":MISSING,"tax_total":MISSING,"normalized_material_total":MISSING,"effective_total":MISSING,"total_status":"NO_QUOTES_REGISTERED","selected":"No","technical_match":UNVERIFIED,"availability_confirmed":UNVERIFIED,"confirmed":UNVERIFIED,"eligibility_issues":"No quote records in this dossier","evidence_document":MISSING,"evidence_page":MISSING,"evidence_sha256":MISSING,"source_type":"NO_DOCUMENTED_QUOTE"}]
    currencies=sorted({r["currency"] for r in rows if r["currency"] not in (MISSING,"")})
    coverage={"quote_records":len(quotes),"currencies_present":currencies,"currency_totals_not_mixed":True,"eligible_usd_rows":sum(r["total_status"]=="ELIGIBLE_USD_TOTAL" for r in rows),"quote_versions_included":True}
    return _meta(row,project,"comparison",language,coverage),rows


_FIELDS={
"directory":["project_id","project_name","supplier_id","supplier_name","company","specialty","city","location","contact_name","contact_email","phone","verification_status","verified_by","verified_at","provenance","missing_fields","quote_count","catalog_record_count","last_recorded_at","evidence_document","evidence_page","evidence_sha256","row_status"],
"project":["project_id","project_name","line_id","description","category","quantity","unit","specification","supplier_id","supplier_name","supplier_location","supplier_status","request_status","coverage_status","quote_id","quote_kind","quote_date","valid_until","version_status","evidence_document","evidence_page","evidence_sha256"],
"comparison":["project_id","project_name","line_id","description","quantity","unit","specification","supplier_id","supplier_name","supplier_location","quote_id","quote_kind","version_status","supersedes_quote_id","quote_date","valid_until","currency","unit_price","pack_size","discount_percent","delivery","tax_total","normalized_material_total","effective_total","total_status","selected","technical_match","availability_confirmed","confirmed","eligibility_issues","evidence_document","evidence_page","evidence_sha256","source_type"]}


def _safe_csv(value):
    value=_text(value)
    stripped=value.lstrip()
    if stripped and stripped[0] in "=+-@":return "'"+value
    return value


def csv_bytes(meta,rows,kind):
    stream=StringIO(newline="")
    writer=csv.writer(stream,quoting=csv.QUOTE_MINIMAL,lineterminator="\r\n")
    fields=_FIELDS[kind]
    writer.writerow(fields)
    for row in rows:writer.writerow([_safe_csv(row.get(f)) for f in fields])
    return ("\ufeff"+stream.getvalue()).encode("utf-8")


def _label(key,language):
    if language=="es":
        return {"project_id":"Expediente","project_name":"Proyecto","supplier_id":"ID proveedor","supplier_name":"Proveedor","company":"Empresa","specialty":"Especialidad","city":"Ciudad","location":"Ubicación","contact_name":"Contacto","contact_email":"Correo","phone":"Teléfono","verification_status":"Verificación","verified_by":"Verificado por","verified_at":"Fecha de verificación","provenance":"Procedencia","missing_fields":"Campos faltantes","quote_count":"Cotizaciones","catalog_record_count":"Registros de catálogo","last_recorded_at":"Último registro","evidence_document":"Documento evidencia","evidence_page":"Página evidencia","evidence_sha256":"Hash evidencia","row_status":"Estado del registro","line_id":"ID partida","description":"Descripción","category":"Categoría","quantity":"Cantidad","unit":"Unidad","specification":"Especificación","supplier_location":"Sucursal","supplier_status":"Estado del proveedor","request_status":"Estado de solicitud","coverage_status":"Cobertura","quote_id":"ID cotización","quote_kind":"Tipo de cotización","quote_date":"Fecha de cotización","valid_until":"Vigencia","version_status":"Versión","supersedes_quote_id":"Sustituye cotización","currency":"Moneda","unit_price":"Precio unitario","pack_size":"Presentación","discount_percent":"Descuento %","delivery":"Flete","tax_total":"Impuesto","normalized_material_total":"Total materiales normalizado","effective_total":"Costo efectivo","total_status":"Estado del total","selected":"Seleccionada","technical_match":"Coincidencia técnica","availability_confirmed":"Disponibilidad confirmada","confirmed":"Confirmada","eligibility_issues":"Pendientes de elegibilidad","source_type":"Tipo de fuente"}.get(key,key)
    return key.replace("_"," ").title()


def pdf_bytes(meta,rows,kind,language):
    title={"directory":("Registered Supplier Directory","Directorio de proveedores registrados"),"project":("Project Supplier List","Lista de proveedores por proyecto"),"comparison":("Internal Quote Comparison","Comparativo interno de cotizaciones")}[kind][language=="es"]
    styles=getSampleStyleSheet();small=ParagraphStyle("Small",parent=styles["BodyText"],fontSize=7.5,leading=9,alignment=TA_LEFT)
    story=[Paragraph(title,styles["Title"]),Paragraph(f"{_label('project_name',language)}: {_text(meta.get('project_name'))} · {_label('project_id',language)}: {_text(meta.get('project_id'))} · Rev. {meta.get('source_revision')} · {meta.get('generated_at')}",small),Paragraph("Fuente local del expediente. No existe directorio externo ni descubrimiento automático. Los campos faltantes permanecen visibles.",small),Spacer(1,8)]
    coverage="; ".join(f"{k}: {_text(v)}" for k,v in meta.get("coverage",{}).items())
    story += [Paragraph(("Cobertura: " if language=="es" else "Coverage: ")+coverage,small),Spacer(1,8)]
    fields=_FIELDS[kind]
    if rows and rows[0].get("row_status") in ("NO_REGISTERED_RECORDS","NO_LINES_REGISTERED") or rows and rows[0].get("version_status")=="NO_QUOTES_REGISTERED":
        story.append(Paragraph(("No hay registros correspondientes en este expediente." if language=="es" else "No corresponding records are registered in this dossier."),styles["Heading2"]))
    else:
        for index,row in enumerate(rows,1):
            story.append(Paragraph(f"{index}. "+_text(row.get("supplier_name") or row.get("description")),styles["Heading3"]))
            data=[]
            for f in fields:
                data.append([Paragraph(_label(f,language),small),Paragraph(_text(row.get(f)),small)])
            table=Table(data,colWidths=[1.55*inch,8.5*inch],repeatRows=0)
            table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.25,colors.HexColor("#c7d5d6")),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eef4f3")),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]))
            story += [table,Spacer(1,8)]
    story.append(Paragraph("Internal export. No margins or internal execution costs are included." if language=="en" else "Exportación interna. No incluye márgenes ni costos internos de ejecución.",small))
    output=BytesIO();doc=SimpleDocTemplate(output,pagesize=landscape(letter),leftMargin=.35*inch,rightMargin=.35*inch,topMargin=.35*inch,bottomMargin=.35*inch)
    class InvariantCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            kwargs["invariant"] = 1
            super().__init__(*args, **kwargs)
    doc.build(story, canvasmaker=InvariantCanvas);return output.getvalue()


def _write(service,project_id,meta,kind,language,ext,raw):
    digest=sha256(raw).hexdigest()[:12];filename=f"supplier-{kind}-{language}-r{int(meta['source_revision']):06d}-{digest}.{ext}"
    path=service.store.child(project_id,"exports",filename);path.parent.mkdir(exist_ok=True)
    if path.exists():
        if path.read_bytes()!=raw:raise ValueError("Exportación de proveedor existente alterada")
        return path
    fd,staged=tempfile.mkstemp(dir=path.parent,suffix=".staged")
    try:
        with os.fdopen(fd,"wb") as fp:fp.write(raw);fp.flush();os.fsync(fp.fileno())
        os.link(staged,path)
    finally:Path(staged).unlink(missing_ok=True)
    return path


def export_supplier_center(service,project_id,revision,kind,language="en",formats="both"):
    if kind not in EXPORT_KINDS:raise ValueError("Tipo de exportación de proveedores inválido")
    if language not in LANGUAGES:raise ValueError("Idioma inválido")
    if formats not in FORMATS:raise ValueError("Formato inválido")
    row=service.store.load(project_id)
    if row["revision"]!=revision:raise ValueError("El expediente cambió; recargue antes de exportar")
    if kind=="directory":meta,rows=directory_data(service,project_id,language)
    elif kind=="project":meta,rows=project_data(service,project_id,language)
    else:meta,rows=comparison_data(service,project_id,language)
    artifacts=[]
    if formats in ("csv","both"):
        path=_write(service,project_id,meta,kind,language,"csv",csv_bytes(meta,rows,kind));artifacts.append({"format":"csv","name":path.name,"size":path.stat().st_size,"sha256":sha256(path.read_bytes()).hexdigest(),"url":f"/api/supplier-export-file?project_id={project_id}&name={path.name}"})
    if formats in ("pdf","both"):
        path=_write(service,project_id,meta,kind,language,"pdf",pdf_bytes(meta,rows,kind,language));artifacts.append({"format":"pdf","name":path.name,"size":path.stat().st_size,"sha256":sha256(path.read_bytes()).hexdigest(),"url":f"/api/supplier-export-file?project_id={project_id}&name={path.name}"})
    return {"project_id":project_id,"revision":revision,"kind":kind,"language":language,"formats":formats,"metadata":meta,"row_count":len(rows),"artifacts":artifacts,"rows":rows}


def validate_artifact_name(name):
    if not isinstance(name,str) or Path(name).name!=name or not _DIGEST_RE.fullmatch(name):raise ValueError("Nombre de exportación de proveedores inválido")


def artifact(service,project_id,name):
    validate_artifact_name(name);path=service.store.child(project_id,"exports",name)
    if not path.exists():raise FileNotFoundError("Exportación no encontrada")
    digest=name.rsplit("-",1)[-1].rsplit(".",1)[0]
    if sha256(path.read_bytes()).hexdigest()[:12]!=digest:raise ValueError("Exportación de proveedores alterada")
    return path
