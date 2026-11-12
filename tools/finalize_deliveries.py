"""Build and package ONLY the four supplied real expedients, using existing PDF caches."""
from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
import shutil
import sys
from unittest.mock import patch
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bidkit.__main__ import main as cli
from bidkit.audit import load_audit, normalize, sha256
from bidkit.config import ProjectConfig
from bidkit.costing import initialize
from bidkit.data_store import read_json, write_json
from bidkit.project_schema import load_analysis
from bidkit.reports import _write_csv

NAMES = ("Gonyea Playfield", "Orangegate Park Phase 1", "REBID - Meridian", "W Seattle Junction Landbank Park")
FOLDERS = ("00_LEEME_Y_RESUMEN", "01_ESTIMADO_DE_COSTOS", "02_TAKEOFF_Y_MATERIALES", "03_LICITACION_Y_FORMULARIOS", "04_REQUISITOS_Y_ADENDAS", "05_AUDITORIA_Y_EVIDENCIAS", "06_DOCUMENTOS_ORIGINALES")
QA = ROOT / "data/qa/phase-d"


def source(config, name, page, anchor):
    doc = next(d for d in load_audit(config)["documents"] if d["name"] == name)
    cache = read_json(config.data_dir / "extractions" / f"{doc['sha256']}.json")
    text = normalize(cache["pages"][page-1]["text"])
    start = text.casefold().find(anchor.casefold())
    if start < 0: raise ValueError((name, page, anchor))
    return {"document": name, "page": page, "sha256": doc["sha256"], "excerpt": text[start:start+min(len(anchor)+120, 450)]}


def setup(config):
    if config.project_name == NAMES[3]:
        metadata = dict(config.metadata);metadata["historical_test"] = True
        write_json(config.project_dir / "project.json", metadata)
    analysis = load_analysis(config)
    initialize(config, analysis)
    pricing_path = config.project_dir / "pricing.json"
    pricing = read_json(pricing_path)
    if config.metadata.get("historical_test"):
        pricing["historical_test"] = True
        write_json(pricing_path, pricing)
    form_path = config.project_dir / "bid_form.json"
    if form_path.exists(): return
    form = {"schema_version": 1, "project_id": config.id, "historical_test": config.metadata.get("historical_test", False),
            "current_official_form_verified": False, "form_status": "OFFICIAL_FORM_NOT_AVAILABLE_IN_SUPPLIED_RECORDS", "sources": [], "lines": [], "totals": [], "pending_decisions": []}
    if config.id == "orangegate-park-phase-1":
        doc = "SPECS DIV 00 - Cover and Pages 1-112.pdf"
        form.update(form_status="LOCAL_BASE_FORM_AVAILABLE; ADDENDUM_2_REVISED_FORM_MISSING",
                    sources=[source(config, doc, 18, "BID FORM"), source(config, "Addendum_2.pdf", 1, "Bid Form updated")])
        descriptions = [
            ("1", "BASIC BID (Orangegate Park Phase 1 Site Improvements)", "base"),
            ("A1", "Substitutive Alternate 01: Picnic Shelter 1", "alternate_1_substitutive"),
            ("A2", "Additive Alternate 02: OLA (Off Leash Area) Loop Trail", "alternate_2"),
            ("A3", "Additive Alternate 03: OLA Clearing", "alternate_3"),
            ("A4", "Additive Alternate 04: Split Rail Fence Along 84th St E", "alternate_4"),
            ("A5", "Additive Alternate 05: Contractor Furnish, Owner Install Trail Directional Signs", "alternate_5_supply_only"),
            ("A6", "Additive Alternate 06: Contractor Furnish, Owner Install Trail Entry-Large Signage in Greater Orangegate Park Land", "alternate_6_supply_only"),
        ]
        form["lines"] = [{"id": lid, "description": text, "scope": scope, "quantity_ids": [q["id"] for q in analysis["quantities"] if q.get("pricing_scope") == scope], "mapping_status": "PROVISIONAL", "sources": [source(config, doc, 18, text)]} for lid, text, scope in descriptions]
        form["totals"] = [{"id": "BASIC BID SUBTOTAL", "line_ids": ["1"]}, {"id": "ALTERNATE BID SUBTOTAL", "line_ids": ["A1", "A2", "A3", "A4", "A5", "A6"]}, {"id": "TOTAL BID PRICE - ALL FORM ALTERNATES", "line_ids": ["1", "A1", "A2", "A3", "A4", "A5", "A6"]}]
        form["pending_decisions"] = ["Obtener formulario revisado A2 y renglón Unit Price No.1 Unsuitable Soils; no inventar su número, unidad ni cantidad.", "Conciliar A1 neto sustitutivo y A2-A4 contra base; cercas 494/335 LF siguen sin asignar.", "Subtotal oficial suma A1-A6; selección interna de alternativos no sustituye esa regla del formulario.", "Confirmar salarios aplicables, clasificación, beneficios y cuadrilla antes de cargar mano de obra."]
    elif config.id in ("rebid-meridian", "w-seattle-junction-landbank-park"):
        form.update(form_status="BID_FORM_PDF_AVAILABLE; OFFICIAL_OPENGOV_PRICING_TABLE_NOT_SUPPLIED",
                    sources=[source(config, "Specs - Unlocked.pdf", 30, "BID FORM"), source(config, "Specs - Unlocked.pdf", 31, "BIDDERS MUST COMPLETE PRICING TABLE IN OPENGOV")])
        form["pending_decisions"] = ["Obtener tabla oficial de precios OpenGov para mapear renglones; el PDF ordena completarla, pero no contiene sus renglones.", "Revisar bond, licencias, firmas y anexos con el contratista; documentos requeridos no equivalen a documentos cumplidos.", "Confirmar salarios/clasificaciones y tratamiento fiscal propios del expediente; no copiar tasas de otros proyectos."]
        if config.metadata.get("historical_test"):
            form["pending_decisions"].insert(0, "EXPEDIENTE HISTÓRICO DE PRUEBA; no presentado como licitación actualmente abierta.")
    else:
        form["pending_decisions"] = ["El expediente disponible no incluye formulario oficial completo ni Division 00; obtenerlos antes de definir renglones, bonds, anexos o firmas exigibles.", "La invitación y especificaciones disponibles se conservan intactas; no se reconstruye un formulario inexistente."]
    write_json(form_path, form)


def output_hashes(config):
    return {p.relative_to(config.output_dir).as_posix(): sha256(p) for p in config.output_dir.rglob("*") if p.is_file()}


def build_all():
    QA.mkdir(parents=True, exist_ok=True)
    results = []
    for name in NAMES:
        c = ProjectConfig(ROOT, name);setup(c)
        cached = {p: (sha256(p), p.stat().st_mtime_ns) for p in (c.data_dir / "extractions").glob("*.json")}
        def no_reparse(*args, **kwargs): raise AssertionError("Completed source extraction must be reused")
        with patch("bidkit.audit.pdfium.PdfDocument", side_effect=no_reparse):
            with (QA / (c.id+"-build.log")).open("w", encoding="utf-8") as log, redirect_stdout(log):
                assert cli(["build", "--root", str(ROOT), "--project", c.id]) == 0
            before = output_hashes(c)
            with (QA / (c.id+"-rebuild.log")).open("w", encoding="utf-8") as log, redirect_stdout(log):
                assert cli(["build", "--root", str(ROOT), "--project", c.id]) == 0
                assert cli(["validate", "--root", str(ROOT), "--project", c.id]) == 0
            assert before == output_hashes(c), name
        assert cached == {p: (sha256(p), p.stat().st_mtime_ns) for p in cached}
        a = load_analysis(c)
        results.append({"project_id": c.id, "name": name, "technical_validation": "PASS", "byte_reproducible": True, "pdf_reextractions": 0, "cache_unchanged": True, "quantity_rows": len(a["quantities"]), "pending_measurement": sum(q["quantity"] is None for q in a["quantities"]), "cost_fingerprint": read_json(c.data_dir / "estimate/cost_result.json")["pricing_fingerprint"]})
        print(name+": build, validate and byte reproduction PASS", flush=True)
    write_json(QA / "integration_results.json", {"projects": results, "only_supplied_four_projects_processed": True})


def professional_pdf(config, folder, cost, prep, analysis):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(config.project_name), styles["Title"]), Paragraph("Estimado preliminar y preparación interna de licitación", styles["Heading2"])]
    def para(text): story.append(Paragraph(escape(text), styles["BodyText"]));story.append(Spacer(1, 8))
    if config.metadata.get("historical_test"): para("EXPEDIENTE HISTÓRICO DE PRUEBA. No se presenta como licitación actualmente abierta.")
    primary = cost["items"]; known = sum(i["quantity"] is not None for i in primary)
    para(f"{known} conceptos principales con cantidad documental de {len(primary)} identificados; {len(primary)-known} pendientes de medición. No es un porcentaje de alcance total, avance físico ni valor económico. Las fuentes y los cálculos se conservan en el takeoff y auditoría.")
    quote_count = sum(q["validation_status"] == "VALID" for q in cost["quotes"])
    para(f"Referencias de precio utilizables: {quote_count}. Confirmados, estimados y pendientes se distinguen en Quotes/Resources. Los importes no estimados permanecen vacíos; no son cero. Los ejemplos ficticios de pruebas están separados de esta entrega productiva.")
    scope_labels = {"base": "Base", "unallocated": "Sin asignar", "alternate_1_substitutive": "Alternativo 1 sustitutivo", "alternate_5_supply_only": "Alternativo 5: solo suministro", "alternate_6_supply_only": "Alternativo 6: solo suministro", **{f"alternate_{n}": f"Alternativo {n}" for n in (2, 3, 4)}}
    table = [["Alcance", "Parcial cubierto", "Rango cubierto", "Partidas incompletas"]]
    for scope in cost["summaries"]:
        value = scope["known_direct_partial"]
        interval = "No estimado" if scope["known_direct_low"] is None else f"{scope['known_direct_low']:,.2f} - {scope['known_direct_high']:,.2f}"
        table.append([scope_labels.get(scope["scope"], scope["scope"]), "No estimado" if value is None else f"{value:,.2f} {cost['currency'] or ''}", interval, str(scope["missing_items"])])
    t = Table([[Paragraph(escape(str(v)), styles["BodyText"]) for v in row] for row in table], colWidths=[150, 100, 130, 95])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F1")), ("GRID", (0, 0), (-1, -1), .4, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([t, Spacer(1, 12)])
    para("Los subtotales cubiertos excluyen recursos sin precio y alcance sin medir. Los rangos solo agregan intervalos respaldados de los componentes cubiertos; no representan incertidumbre estadística ni una reserva inventada. La falta de una partida no elimina los costos parciales disponibles.")
    para("Material = cantidad × consumo × (1 + desperdicio) × conversión × precio. Mano de obra/equipo = cantidad ÷ productividad × tarifa horaria. Costo de venta = (directos + indirectos) ÷ (1 - margen bruto). No hay porcentajes, salarios o productividades por defecto.")
    tax_label = {"EXCLUDED_FROM_BID_ADDED_BY_OWNER_TO_PAYMENTS": "Excluido del precio de oferta; el propietario lo añade a los pagos", "EXCLUDED_FROM_ELECTRONIC_BID_CITY_APPLIES_AT_AWARD": "Excluido de la oferta electrónica; la ciudad lo aplica en adjudicación", "INCLUDED_IN_BID": "Incluido en el precio de oferta"}.get(cost["tax_treatment"], "Pendiente de determinar con los documentos específicos del proyecto")
    para("Tratamiento fiscal: "+tax_label+". Tasa, base imponible, margen gravable y aplicabilidad de allowances requieren fuentes propias y revisión. No se asume un allowance cero.")
    form_label = {"LOCAL_BASE_FORM_AVAILABLE; ADDENDUM_2_REVISED_FORM_MISSING": "Formulario base disponible; falta el formulario revisado por adenda 2", "BID_FORM_PDF_AVAILABLE; OFFICIAL_OPENGOV_PRICING_TABLE_NOT_SUPPLIED": "Formulario documental disponible; falta la tabla oficial de precios de OpenGov", "OFFICIAL_FORM_NOT_AVAILABLE_IN_SUPPLIED_RECORDS": "El formulario oficial completo no está en los documentos suministrados"}.get(prep["form_status"], prep["form_status"])
    para("Formulario y mapeo: "+form_label+". Los importes propuestos se generan solo cuando están sustentados y conciliados; un parcial de materiales no se convierte en precio de un renglón oficial.")
    for decision in prep["pending_decisions"]: para(str(decision))
    para("Siguiente responsable: abrir Presupuesto_Principal.xlsx; cargar referencias y rendimientos, revisar composiciones y alcances; importar cambios y reconstruir el presupuesto. El PDF es una instantánea, no el archivo de edición. Ver LEEME.md e instrucciones incluidas.")
    para("Estado de autorización: revisión técnica, revisión del estimador y autorización del contratista pendientes. Ningún documento se declara firmado, aprobado o presentado.")
    SimpleDocTemplate(str(folder/"Resumen_Profesional.pdf"), title=config.project_name, author="ALKAN", invariant=1).build(story)


def package_all():
    test_file = QA / "test_summary.json"
    if not test_file.exists(): raise ValueError("Run final tests and save test_summary.json before packaging")
    exports = []
    for name in NAMES:
        c = ProjectConfig(ROOT, name);a = load_analysis(c)
        cost = read_json(c.data_dir/"estimate/cost_result.json");prep = read_json(c.data_dir/"estimate/bid_preparation.json")
        base = ROOT/"ENTREGAS"/name
        for sub in FOLDERS: (base/sub).mkdir(parents=True, exist_ok=True)
        f = [base/sub for sub in FOLDERS]
        def copy(src, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or sha256(src) != sha256(dest): shutil.copy2(src, dest)
        for src, dest in [(c.output_dir/"Cost_Budget.xlsx", f[1]/"Presupuesto_Principal.xlsx"), (c.project_dir/"pricing.json", f[1]/"Entradas_Precios.json"), (c.project_dir/"quotes.json", f[1]/"Fuentes_y_Cotizaciones.json"), (c.output_dir/"cost_sources.csv", f[1]/"Registro_Fuentes.csv"),
                          (c.output_dir/"Material_Takeoff.xlsx", f[2]/"Takeoff_y_Materiales.xlsx"), (c.output_dir/"materials.csv", f[2]/"Materiales.csv"), (c.output_dir/"takeoff_register.csv", f[2]/"Cantidades_y_Fuentes.csv"),
                          (c.output_dir/"bid-preparation/Internal_Bid_Package_DRAFT.xlsx", f[3]/"Preparacion_Licitacion_BORRADOR.xlsx"), (c.output_dir/"bid-preparation/bid_mapping.csv", f[3]/"Matriz_Renglones.csv"), (c.output_dir/"bid-preparation/draft_bid_amounts.csv", f[3]/"Importes_BORRADOR.csv"), (c.output_dir/"bid-preparation/compliance_checklist.csv", f[3]/"Checklist_Cumplimiento.csv"), (c.project_dir/"bid_form.json", f[3]/"Mapa_Formulario.json"),
                          (c.output_dir/"requirements.csv", f[4]/"Requisitos.csv"), (c.output_dir/"amendments.csv", f[4]/"Adendas_y_Cambios.csv"),
                          (c.output_dir/"risks.csv", f[5]/"Riesgos.csv"), (c.output_dir/"cost_unresolved.csv", f[5]/"Costos_y_Decisiones_Pendientes.csv"), (c.output_dir/"validation_report.json", f[5]/"Validacion.json"), (c.output_dir/"Technical_Review.pdf", f[5]/"Respaldo_Tecnico.pdf"), (c.project_dir/"analysis.json", f[5]/"Analisis_Documental.json"), (c.data_dir/"estimate/cost_result.json", f[5]/"Calculos_Costos.json"), (c.data_dir/"estimate/bid_preparation.json", f[5]/"Preparacion_Licitacion.json"), (c.audit_dir/"document_inventory.json", f[5]/"Inventario_Documental.json"), (test_file, f[5]/"Pruebas_y_Regresion.json"), (QA/"integration_results.json", f[5]/"Integracion_Reproduccion.json")]: copy(src, dest)
        _write_csv(f[2]/"Mediciones_Pendientes.csv", [q for q in a["quantities"] if q["quantity"] is None])
        _write_csv(f[0]/"Decisiones_Prioritarias.csv", [{"priority": n, "decision": str(d), "status": "PENDING"} for n, d in enumerate(prep["pending_decisions"], 1)])
        evidence_map = {}
        review = c.data_dir/"review"
        if review.exists():
            for asset in review.iterdir():
                if asset.is_file():
                    dest = f[5]/"Evidencias_Visuales"/asset.name;copy(asset, dest)
                    evidence_map[asset.relative_to(ROOT).as_posix()] = dest.relative_to(base).as_posix()
        write_json(f[5]/"Indice_Evidencias.json", evidence_map)
        # Preserve reusable extraction text, without duplicating PDF processing.
        for cache in (c.data_dir/"extractions").glob("*.json"):
            copy(cache, f[5]/"Extracciones_Reutilizables"/cache.name)
        if c.id == "orangegate-park-phase-1":
            for asset in ("engineering_evidence.json", "corrections.json"):
                copy(ROOT/"data/qa/phase-c"/asset, f[5]/"QA_Ingenieria_Fase_C"/asset)
            for asset in (ROOT/"data/qa/phase-c").glob("*.png"):
                copy(asset, f[5]/"QA_Ingenieria_Fase_C"/asset.name)
            copy(QA/"quantity_review.json", f[5]/"Revision_13_Mediciones.json")
        copy(QA/"versions.json", f[5]/"Versiones_Motor.json")
        copy(c.project_dir/"project.json", f[5]/"Configuracion_Proyecto.json")
        originals = []
        for src in c.source_assets:
            dest = f[6]/src.relative_to(c.source_root);copy(src, dest)
            assert sha256(src) == sha256(dest)
            originals.append({"file": src.relative_to(c.source_root).as_posix(), "sha256": sha256(src), "bytes": src.stat().st_size})
        write_json(f[5]/"Integridad_Originales.json", {"project": name, "originals": originals, "method": "Independent copies compared byte-for-byte via SHA256; docs/ never written"})
        professional_pdf(c, f[1], cost, prep, a)
        write_json(f[0]/"Estado_del_Proyecto.json", {"project": name, "historical_test": prep["historical_test"], "primary_identified_concepts": len(cost["items"]), "document_quantity_concepts": sum(q["quantity"] is not None for q in cost["items"]), "pending_measurement": sum(q["quantity"] is None for q in cost["items"]), "usable_price_sources": sum(q["validation_status"] == "VALID" for q in cost["quotes"]), "scope_complete": False, "form_status": prep["form_status"], "authorization": prep["authorization"]})
        text = f"""# {name}\n\n{'**EXPEDIENTE HISTÓRICO DE PRUEBA. No se presenta como licitación actualmente abierta.**' if prep['historical_test'] else '**Entrega documental preliminar. Confirmar vigencia y estado de la convocatoria con el responsable.**'}\n\nEl estimado principal es [Presupuesto_Principal.xlsx](01_ESTIMADO_DE_COSTOS/Presupuesto_Principal.xlsx). [Resumen profesional PDF](01_ESTIMADO_DE_COSTOS/Resumen_Profesional.pdf). Abra primero Summary, Scopes y Schedules; después Items, Resources y Quotes.\n\n- `00_LEEME_Y_RESUMEN`: estado del proyecto y decisiones prioritarias.\n- `01_ESTIMADO_DE_COSTOS`: Excel editable, entradas JSON y registro de fuentes/cotizaciones.\n- `02_TAKEOFF_Y_MATERIALES`: cantidades, unidades, materiales, fuentes y mediciones pendientes.\n- `03_LICITACION_Y_FORMULARIOS`: matriz y preparación **interna**, importes borrador y checklist; no reemplaza formularios oficiales.\n- `04_REQUISITOS_Y_ADENDAS`: requisitos y modificaciones documentadas.\n- `05_AUDITORIA_Y_EVIDENCIAS`: cálculos, riesgos, pruebas, validación y hashes.\n- `06_DOCUMENTOS_ORIGINALES`: copias intactas de los {len(originals)} archivos originales, verificadas por SHA-256.\n\n**Datos disponibles:** {sum(q['quantity'] is not None for q in cost['items'])} conceptos principales con cantidad documental; {sum(q['quantity'] is None for q in cost['items'])} sin medir. Es un subconjunto identificado, no cobertura completa. Las cantidades de cuadros y sus reservas se consultan en Takeoff_y_Materiales.xlsx.\n\n**Precios:** {sum(q['validation_status']=='VALID' for q in cost['quotes'])} referencias utilizables cargadas. Los expedientes suministrados no aportan cotizaciones/históricos de costo suficientes; no se rellenaron con precios ficticios. Confirmados y estimados se distinguen cuando se incorporan sus referencias, fechas y confianza. Los costos no estimados quedan vacíos, nunca se interpretan como cero. Las pruebas ficticias permanecen fuera de estas carpetas productivas.\n\n**Formulario:** {prep['form_status']}. Los originales están en 06; las páginas precisas y las modificaciones están en Mapa_Formulario.json y el paquete interno. No se inventaron renglones faltantes de OpenGov o formularios revisados.\n\n**Siguiente responsable:**\n\n1. Revisar los pendientes de medición y asignar base/Schedule A-B/alternativos sin duplicar alcance.\n2. Cargar fuente, fecha, moneda, unidad, confianza y precio o intervalo en Quotes; confirmar Source reviewed.\n3. En Resources, ingresar consumo o productividad, tarifa vinculada, desperdicio explícito y base técnica; confirmar Basis reviewed. No usar salarios ficticios: verificar clasificación, beneficios y publicación salarial aplicable.\n4. Revisar composiciones, indirectos, margen bruto, impuestos y allowances; faltantes no eliminan costos parciales ya sustentados.\n5. Guardar cambios y usar `cost-import --project {c.id} --workbook archivo.xlsx`; luego `build --project {c.id}`. Los JSON guardan las entradas y los PDFs no se reextraen. Si cambia una cantidad, actualizar primero analysis.json con evidencia.\n6. Completar el formulario vigente, checklist y autorizaciones con el contratista. Nada está firmado, aprobado ni presentado por ALKAN.\n\nEl PDF y el paquete de licitación son instantáneas enlazadas al presupuesto por ID y fingerprint. Tras cambiar precios, reconstruir y volver a preparar la entrega para mantenerlos sincronizados. Ver la guía común en ENTREGAS/GUIA_ESTIMADOR.md.\n"""
        (base/"LEEME.md").write_text(text, encoding="utf-8")
        # Do not hash the manifest into itself.
        manifest_path = f[5]/"MANIFIESTO_ENTREGA.json"
        files = {p.relative_to(base).as_posix(): sha256(p) for p in sorted(base.rglob("*")) if p.is_file() and p != manifest_path}
        write_json(manifest_path, {"project": name, "project_id": c.id, "files": files, "original_file_count": len(originals), "historical_test": prep["historical_test"], "cost_fingerprint": cost["pricing_fingerprint"]})
        exports.append({"project": name, "folder": base.relative_to(ROOT).as_posix(), "file_count": len(files)+1, "originals": len(originals), "manifest_sha256": sha256(manifest_path)})
        print(name+": self-contained delivery and original SHA256 PASS", flush=True)
    write_json(QA/"delivery_results.json", {"deliveries": exports})


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("build", "package"):
        raise SystemExit("Usage: finalize_deliveries.py build|package")
    (build_all if sys.argv[1] == "build" else package_all)()
