"""Update only the three requested economic/material deliveries from current built costs."""
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import shutil
import sys
from xml.sax.saxutils import escape

from openpyxl import Workbook

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bidkit.audit import sha256
from bidkit.config import ProjectConfig
from bidkit.data_store import read_json,write_json
from bidkit.purchase_workbook import material_resources
from bidkit.reports import _write_csv
from bidkit.workbooks import _sheet,_save,reference
from finalize_deliveries import FOLDERS
from update_economic_inputs import IDS

QA=ROOT/'data/qa/economic'
MEASUREMENT_NEEDS={
    'gonyea-playfield': {
        'P-Q-01':'Conteos del resto de plantación sin repetir GP-PL-01 a 15; áreas de siembra/césped; áreas y espesores de suelo/mulch; trazados, diámetros, sectores y componentes de riego.',
        'P-Q-02':'Polígonos de desmonte, superficies existente/propuesta y balance de tierras; longitudes/diámetros/profundidades de redes, estructuras y conexiones.',
        'P-Q-03':'Áreas por pavimento/cancha/superficie de juego, espesores y capas; modelos y cantidades de equipos; asignación base/alternativos y límites de demolición.',
        'P-Q-04':'Despiece de estación sanitaria y refugio: cimentación/rebar, estructura/cubierta, acabados y MEP; medición separada de base y alternativos, sin inferir unidades.',
        'P-Q-06':'Longitudes/áreas de protección y obras temporales, tráfico/acceso, movilización, duración justificada, ensayos y cierre; cantidades/plazo por actividad.',
    },
    'rebid-meridian': {
        'P-Q-01':'Áreas/unidades de demolición; longitud de cerramiento temporal; acceso, staging y secuencia según L2.1 revisado por ADD 1.',
        'P-Q-02':'Áreas y espesores de pavimento, rampas/bordillos, longitudes de barandilla y drenaje; separar reparación base de sustitución de acera en Alternate 1 y evitar duplicarla.',
        'P-Q-03':'Modelos/cantidades de equipo de juego y cimentaciones; áreas de EWF/PIP, espesor por altura de caída y losa; cuantificar el cambio neto de Alternate 2 frente a base.',
        'P-Q-04':'Áreas/espesores y volúmenes de suelo/mulch; composición y medición de riego si aplica; protección de raíces; aclarar tallas de árboles donde el cuadro muestra 0 pulgadas.',
        'P-Q-05':'Áreas de acabados ADA, cuadros de accesorios/aparatos, demolición y conexiones de fontanería/electricidad; medición de tubería, conducto y circuitos.',
        'P-Q-06':'Conteos por modelo/tamaño de mobiliario, señales, bancos y recipientes; pads/anclajes y límites entre suministro e instalación.',
    },
}


def valued_items(cost):
    return {r['quantity_id'] for r in cost['resources'] if r['extended_cost'] is not None or r['cost_low'] is not None}


def requests_for(c,a,cost):
    grouped=defaultdict(list)
    for r in cost['resources']:grouped[r['quantity_id']].append(r)
    materials={m['quantity_id']:m for m in a['materials']}
    known=valued_items(cost);rows=[]
    for q in cost['items']:
        raw=next(x for x in a['quantities'] if x['id']==q['id'])
        m=materials[q['id']];components=grouped[q['id']]
        missing=f'Cotización identificable para {m["description"]}; especificación: {m["specification"]}. Precio por unidad indicada, proveedor, localidad/entrega, fecha, vigencia, moneda, flete, impuestos y límites de suministro. Confirmar merma solo si corresponde.'
        if q['id'].startswith('GP-SIGN-'):
            missing='ACLARACIÓN ECONÓMICA L1.00: el importe es ESTIMATED COST sin base por unidad/tipo/conjunto; confirmar base e inclusiones con diseñador/propietario antes de usarlo. Solicitar fabricación y suministro, cimentación/anclajes, instalación, permisos, flete e impuestos desglosados. S1 y S2 son tipos diferentes; S3 aparece dos veces en planta, pero su rango publicado no demuestra un precio por unidad. '+missing
        if q['quantity'] is None:missing='MEDICIÓN PRIMERO: '+MEASUREMENT_NEEDS.get(c.id,{}).get(q['id'],raw.get('missing_information',raw.get('basis','Medir desde planos vigentes y conciliar alcance.')))+' Después: '+missing
        elif any(x in m['specification'].lower() for x in ('0 inches','clarification required','no material quantities')):missing='ACLARACIÓN TÉCNICA: definir talla/calibre/altura real; el cuadro no define un tamaño utilizable. '+missing
        if 'seed mix' in m['description'].lower():missing+=' Dosificación y composición del mix, unidad de peso y tamaño de envase; el área SF no es peso para comprar.'
        if 'LP-A-11'==q['id'] or 'LP-B-13'==q['id']:missing+=' Confirmar material de mulch y precio por CY; volumen neto a 4 pulgadas; merma/compactación aparte. En LP-A-11 falta desglosar preparación de suelo.'
        if q['id'].startswith('CD03'):missing+=' Perfil por estructura: profundidad, risers, base, tapa/rejilla y conexiones. Solicitar paquete por tag; no asumir estructuras intercambiables.'
        if q['id'] not in known:missing+=' Para instalación: tarifa de cuadrilla con base/fringe/cargas, rendimiento verificable y equipo por actividad; no basta una tarifa salarial aislada.'
        rows.append({'proyecto':c.project_name,'partida':q['id'],'descripcion':q['item'],'alcance':q['pricing_scope'],'schedule':q['package'],'cantidad_documental':q['quantity'],'unidad':q['unit'],'pendiente_medicion':q['quantity'] is None,'pendiente_precio_sin_base':q['id'] not in known,'base_economica_actual':'ESTIMADO_DOCUMENTAL_PARCIAL' if q['id'] in known else 'PENDIENTE','prioridad_operativa':'Construcción principal: medir y cotizar paquete' if q['quantity'] is None else 'Cantidad disponible: solicitar precio y composición; confirmar especificación','informacion_exacta_necesaria':missing,'responsable_sugerido':'Diseñador / propietario + proveedor de señales' if q['id'].startswith('GP-SIGN-') else 'Ingeniero / estimador' if q['quantity'] is None or 'ACLARACIÓN TÉCNICA' in missing else 'Proveedor + contratista / estimador','recursos_presupuesto':', '.join(r['id'] for r in components),'campos_entrada':'Quotes: ID, Source, Date, Valid until, Currency, Unit, Unit price/Low/High; Resources: Quote ID, Factor/Productivity, Waste, Basis source','fuente_cantidad':reference(q['sources'])})
    return rows


def cost_sources(c,cost):
    rows=[];quotes={q['id']:q for q in cost['quotes']}
    for r in cost['resources']:
        if r['extended_cost'] is None and r['cost_low'] is None:continue
        q=quotes[r['quote_id']]
        rows.append({'partida':r['quantity_id'],'recurso':r['id'],'tipo':'PAQUETE_INTEGRAL_SIN_DESGLOSE','alcance':r['pricing_scope'],'cantidad':r['item_quantity'],'unidad':r['quote_unit'],'valor_unitario_utilizado':r['unit_price'],'inferior_unitario':q.get('unit_price_low'),'superior_unitario':q.get('unit_price_high'),'extendido_puntual':r['extended_cost'],'extendido_inferior':r['cost_low'],'extendido_superior':r['cost_high'],'fuente_verificable':q['source']['reference'],'fecha':q['date'],'localidad':q['locality'],'clase':'ESTIMADO','confianza':q['confidence'],'observaciones':q['applicability_note']+' No se conoce desglose de materiales/labor/indirectos/margen del valor publicado.'})
    for r in cost['settings']['documentary_cost_references']:
        rows.append({'partida':r['id'],'recurso':'REFERENCIA_GLOBAL_NO_PARTIDA','tipo':'PRESUPUESTO_PROPIETARIO_AE_NO_SUMABLE','alcance':r['scope'],'valor_unitario_utilizado':None,'valor_global_central':r['central'],'valor_global_inferior':r['low'],'valor_global_superior':r['high'],'fuente_verificable':reference(r['sources']),'fecha':r['date'],'localidad':'Pierce County, Washington' if c.id!='rebid-meridian' else 'Seattle, King County, Washington','clase':'ESTIMADO','confianza':'No publicada por autor; no asignar precisión estadística','observaciones':r['date_note']+' '+r['tax']+' No distribuir en partidas ni sumar al parcial ya medido.'})
    for r in cost['settings'].get('conceptual_cost_references',[]):
        rows.append({'partida':r['quantity_id'],'recurso':r['id'],'tipo':'REFERENCIA_CONCEPTUAL_SIN_UNIDAD_NO_SUMABLE','alcance':'base / tipo '+r['tag'],'valor_unitario_utilizado':None,'importe_conceptual_aproximado':r['central'],'referencia_conceptual_inferior':r['low'],'referencia_conceptual_superior':r['high'],'unidad_economica':'NO DEFINIDA','fuente_verificable':reference(r['sources'])+'; detalles '+reference(r['detail_sources']),'fecha':r['date'],'localidad':'Parkland, Pierce County, Washington','clase':'PENDIENTE_ACLARACION_ECONOMICA','confianza':'Importe legible; base e inclusiones no determinadas','observaciones':r['note']+' No utilizado como precio ni multiplicado por cantidad; fabricación, suministro e instalación sin confirmar.'})
    if c.id=='orangegate-park-phase-1':
        rows.append({'partida':'RIESGO-EXCAVACION','tipo':'LIMITE_CONDICIONAL_NO_SUMADO','valor_global_superior':10000,'fuente_verificable':'SPECS TECH SPECS - Cover and Pages 1-412.pdf PDF 294, 31 20 00, 3.04','fecha':'2026-08 (pie de página); encabezado June 2025','localidad':'Pierce County, Washington','clase':'PENDIENTE_APLICABILIDAD','observaciones':'Extra Road Excavation: force account dirigido por el ingeniero, máximo $10,000 si se encuentran esos materiales. No es un costo incurrido ni allowance fijo automático. Conciliar con Unit Price No.1 revisado en A2.'})
    return rows


def pdf_summary(c,a,cost,rows,path):
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph,SimpleDocTemplate,Spacer,Table,TableStyle
    styles=getSampleStyleSheet();story=[]
    def p(text,style='BodyText'):
        story.append(Paragraph(escape(text),styles[style]))
        if not style.startswith('Heading'):story.append(Spacer(1,6))
    def table(headers,data,widths):
        t=Table([[Paragraph(escape(str(x)),styles['BodyText']) for x in row] for row in [headers,*data]],colWidths=widths,repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#DCE6F1')),('GRID',(0,0),(-1,-1),.4,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')]))
        story.extend([t,Spacer(1,10)])
    def usd(value):return 'No estimado' if value is None else f'USD {value:,.0f}'
    valued=valued_items(cost);n=len(cost['items']);measured=sum(q['quantity'] is not None for q in cost['items'])
    p(c.project_name,'Title');p('Resumen económico preliminar — revisión, sin autorización de oferta','Heading2')
    p('Base global documentada (propietario/A-E)','Heading3')
    refs=cost['settings']['documentary_cost_references']
    table(['Alcance publicado','Importe o rango','Referencia'],[[r['scope'],usd(r['central']) if r['central'] is not None else f"USD {r['low']:,.0f} a {r['high']:,.0f}",reference(r['sources'])] for r in refs],[135,130,230])
    p('Estas cifras responden al orden de costo publicado del proyecto; no son un presupuesto de ALKAN calculado desde cantidades, una cotización vigente ni importes del formulario oficial. No se suman al subtotal por partidas. No se inventó fecha de emisión ni escalación.'+(' No está explícito el impuesto incluido en la referencia A/E; los alternativos se mantienen separados y no se presenta su combinación como rango de incertidumbre.' if c.id=='rebid-meridian' else ''))
    p('Estimado independiente ALKAN y subtotales parciales','Heading3')
    p(f'Cantidades documentales: {measured}/{n} conceptos identificados ({100*measured/n:.2f}%). Precios respaldados utilizables: {len(valued)}/{n} ({100*len(valued)/n:.2f}%). Pendientes de medición: {n-measured}. Los denominadores son partidas identificadas, con distinto tamaño de alcance; ninguno de estos indicadores representa cobertura total de obra o cobertura económica. Una partida con precio parcial tampoco supone composición completa.')
    table(['Alcance','Subtotal puntual cubierto','Inferior / superior cubiertos'],[[s['scope'],usd(s['known_direct_partial']), 'No estimado' if s['known_direct_low'] is None else f"USD {s['known_direct_low']:,.0f} / {s['known_direct_high']:,.0f}"] for s in cost['summaries']],[135,170,190])
    if valued:
        table(['Partida / cantidad','Costo publicado por unidad','Costo extendido'],[[r['quantity_id']+' / '+str(r['item_quantity'])+' '+r['item_unit'],usd(r['unit_price']) if r['unit_price'] is not None else f"USD {next(q for q in cost['quotes'] if q['id']==r['quote_id'])['unit_price_low']:,.0f} a {next(q for q in cost['quotes'] if q['id']==r['quote_id'])['unit_price_high']:,.0f}",usd(r['extended_cost']) if r['extended_cost'] is not None else f"USD {r['cost_low']:,.0f} a {r['cost_high']:,.0f}"] for r in cost['resources'] if r['quantity_id'] in valued and (r['extended_cost'] is not None or r['cost_low'] is not None)],[170,165,160])
    else:p('No hay precios o rendimientos locales suficientes para valorizar las partidas medidas. No se han usado los presupuestos globales para inventar precios unitarios. El subtotal no estimado es un valor desconocido, no cero.')
    conceptual=cost['settings'].get('conceptual_cost_references',[])
    if conceptual:
        p('Gonyea: referencias conceptuales, fuera de los costos','Heading3')
        table(['Tipo / cantidad física','Referencia publicada, NO precio unitario','Alcance monetario'],[[r['tag']+' / '+str(next(i['quantity'] for i in cost['items'] if i['id']==r['quantity_id']))+' EA',('~USD '+f"{r['central']:,.0f}") if r['central'] is not None else f"USD {r['low']:,.0f}–{r['high']:,.0f}",'Unidad/conjunto y fabricación/suministro/instalación no definidos'] for r in conceptual],[105,180,210])
        p('L1.00, PDF 46: S1 y S2 son dos renglones de tipos distintos bajo ESTIMATED COST; no es una prueba de precio unitario ni de duplicación del mismo alcance. L3.25–L3.26, PDF 67–68, detallan señales/cimentaciones, pero no explican qué paga cada importe. Se retiró la interpretación por unidad, el subtotal de USD 40,000 y el rango agregado USD 55,000–62,500. No se multiplicó el rango de S3 por sus dos señales. No hay subtotal monetario documental utilizable de estas referencias hasta aclaración. Los cinco conteos físicos siguen separados; L1.21 no se suma otra vez.')
    p('Materiales y parámetros','Heading3')
    p('Lista_Detallada_de_Materiales.xlsx contiene exactamente los recursos del presupuesto, con las mismas fórmulas de Resources/Items/Quotes. La cantidad neta puede estar calculada aunque compra, desperdicio y costo sigan pendientes. Se conserva la separación base, Schedule A/B y alternativos. No se infieren pesos de semillas ni componentes internos de conjuntos. Mano de obra, rendimientos, equipo, transporte, indirectos, contingencia y margen siguen sin valor donde no existe referencia aplicable; no se fijó un porcentaje por defecto.')
    p('Impuestos: '+('Orangegate excluye el impuesto del precio de oferta y el propietario lo añade a pagos; tasa y base aplicables por confirmar.' if c.id=='orangegate-park-phase-1' else 'La referencia global de Gonyea excluye impuesto; falta confirmar tratamiento del precio de oferta en su formulario completo.' if c.id=='gonyea-playfield' else 'Confirmar tratamiento del Bid Form/OpenGov y de la referencia A/E; no se aplica una tasa de otro expediente.'))
    p('Pendientes y riesgos','Heading3')
    for text in [f"{n-len(valued)} conceptos sin base económica suficiente; detalle por ID en Pendientes_para_Cotizar.csv. De ellos, {n-measured} necesitan medición antes de cotizar; los restantes requieren precios y composiciones.", 'Obtener tarifas salariales aplicables por oficio/condado/fecha, beneficios/cargas y rendimientos de cuadrilla. Una tarifa mínima sola no determina costo de instalación.', 'Obtener cotizaciones de proveedores y equipos con alcance, transporte, unidad, fecha y vigencia; completar espesores, geometrías, tallas y condiciones de sitio pendientes.', 'Riesgos: alcance sin medir, límites de alternativos, interferencias/terreno, costos de instalación no desglosados y actualización comercial de presupuestos documentales. No se asignó una contingencia numérica arbitraria.']:
        p(text)
    p('Acceso externo: un intento de búsqueda devolvió HTTP 500, "channel does not support /v1/alpha/search". No se repitió. La búsqueda local reutilizó las extracciones existentes; sources/ no contiene tarifas o catálogos licenciados utilizables. Fuentes exactas necesarias: ver Solicitudes_Fuentes_Consolidadas.xlsx en ENTREGAS.')
    p('Apto para revisión: SÍ, como referencia económica documental y parcial. Apto para oferta: NO. Ningún documento está firmado, aprobado o presentado. El responsable puede cargar cotizaciones en Quotes, ajustar consumos/rendimientos, importar el Excel y reconstruir sin repetir el análisis documental.')
    SimpleDocTemplate(str(path),title=c.project_name+' — Resumen económico',author='ALKAN',invariant=1).build(story)


def main():
    all_requests=[];decisions=[];summaries=[]
    for pid in IDS:
        c=ProjectConfig(ROOT,pid);a=read_json(c.project_dir/'analysis.json');cost=read_json(c.data_dir/'estimate/cost_result.json')
        assert cost['mode']=='REAL' and all(q['kind']=='REAL' for q in cost['quotes'])
        base=ROOT/'ENTREGAS'/c.project_name;f=[base/name for name in FOLDERS]
        def cp(src,dest):
            dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists() or sha256(src)!=sha256(dest):shutil.copy2(src,dest)
        for src,dest in [(c.output_dir/'Cost_Budget.xlsx',f[1]/'Presupuesto_Principal.xlsx'),(c.output_dir/'Lista_Detallada_de_Materiales.xlsx',f[2]/'Lista_Detallada_de_Materiales.xlsx'),(c.project_dir/'pricing.json',f[1]/'Entradas_Precios.json'),(c.project_dir/'quotes.json',f[1]/'Fuentes_y_Cotizaciones.json'),(c.output_dir/'cost_sources.csv',f[1]/'Registro_Fuentes.csv'),(c.output_dir/'Material_Takeoff.xlsx',f[2]/'Takeoff_y_Materiales.xlsx'),(c.output_dir/'materials.csv',f[2]/'Materiales.csv'),(c.output_dir/'takeoff_register.csv',f[2]/'Cantidades_y_Fuentes.csv'),(c.project_dir/'analysis.json',f[5]/'Analisis_Documental.json'),(c.data_dir/'estimate/cost_result.json',f[5]/'Calculos_Costos.json'),(c.data_dir/'estimate/bid_preparation.json',f[5]/'Preparacion_Licitacion.json'),(c.output_dir/'validation_report.json',f[5]/'Validacion.json'),(c.output_dir/'Technical_Review.pdf',f[5]/'Respaldo_Tecnico.pdf'),(c.output_dir/'cost_unresolved.csv',f[5]/'Costos_y_Decisiones_Pendientes.csv'),(c.output_dir/'bid-preparation/Internal_Bid_Package_DRAFT.xlsx',f[3]/'Preparacion_Licitacion_BORRADOR.xlsx'),(c.output_dir/'bid-preparation/bid_mapping.csv',f[3]/'Matriz_Renglones.csv'),(c.output_dir/'bid-preparation/draft_bid_amounts.csv',f[3]/'Importes_BORRADOR.csv'),(c.output_dir/'bid-preparation/compliance_checklist.csv',f[3]/'Checklist_Cumplimiento.csv')]:cp(src,dest)
        rows=requests_for(c,a,cost);all_requests.extend(rows)
        _write_csv(f[1]/'Pendientes_para_Cotizar.csv',rows)
        _write_csv(f[1]/'Fuentes_de_Costos.csv',cost_sources(c,cost))
        _write_csv(f[2]/'Mediciones_Pendientes.csv',[q for q in a['quantities'] if q['quantity'] is None])
        pdf_summary(c,a,cost,rows,f[1]/'Resumen_Economico.pdf')
        cp(f[1]/'Resumen_Economico.pdf',f[1]/'Resumen_Profesional.pdf')
        for filename in ('external_access.json','local_cost_reference_search.json','pytest.log'):
            cp(QA/filename,f[5]/'Revision_Economica'/filename)
        for filename in ('verification.json','versions.json','test_summary.json')+ (('gonyea_sign_interpretation.json',) if pid=='gonyea-playfield' else ()):
            if (QA/filename).exists():cp(QA/filename,f[5]/'Revision_Economica'/filename)
        if (QA/'versions.json').exists():cp(QA/'versions.json',f[5]/'Versiones_Motor.json')
        index=read_json(f[5]/'Indice_Evidencias.json')
        for img in (c.data_dir/'review').glob('Economic-*'):
            cp(img,f[5]/'Evidencias_Visuales'/img.name);index[img.relative_to(ROOT).as_posix()]=(f[5]/'Evidencias_Visuales'/img.name).relative_to(base).as_posix()
        write_json(f[5]/'Indice_Evidencias.json',index)
        priced=valued_items(cost);measured=sum(q['quantity'] is not None for q in cost['items'])
        summary={'project':c.project_name,'project_id':pid,'historical_test':False,'identified_items':len(cost['items']),'document_quantity_items':measured,'percentage_identified_items_with_quantity':round(100*measured/len(cost['items']),4),'valued_partial_items':len(priced),'unvalued_items':len(cost['items'])-len(priced),'pending_measurement':len(cost['items'])-measured,'pending_price_with_quantity':sum(q['quantity'] is not None and q['id'] not in priced for q in cost['items']),'percentage_identified_items_valued':round(100*len(priced)/len(cost['items']),4),'percentage_is_not_cost_or_full_scope_coverage':True,'cost_summaries':cost['summaries'],'documentary_global_references':cost['settings']['documentary_cost_references'],'conceptual_references_not_usable_prices':cost['settings'].get('conceptual_cost_references',[]),'independent_alkan_estimate_available':bool(priced),'review_ready':True,'offer_ready':False,'cost_fingerprint':cost['pricing_fingerprint']}
        summaries.append(summary);write_json(f[0]/'Estado_del_Proyecto.json',summary)
        text=f'''# {c.project_name}

Abra [Presupuesto_Principal.xlsx](01_ESTIMADO_DE_COSTOS/Presupuesto_Principal.xlsx): primero **Resumen_Economico** y **Referencia_Global**; luego Scopes, Items, Resources y Quotes. [Resumen_Economico.pdf](01_ESTIMADO_DE_COSTOS/Resumen_Economico.pdf) explica qué cifras se pueden usar y sus límites.

**Resultado:** cantidades documentales {measured}/{len(cost['items'])} ({summary['percentage_identified_items_with_quantity']:.2f}%); precios respaldados utilizables {len(priced)}/{len(cost['items'])} ({summary['percentage_identified_items_valued']:.2f}%); {len(cost['items'])-measured} pendientes de medición y {summary['pending_price_with_quantity']} con cantidad pero sin costo. No representa cobertura completa ni porcentaje del costo de obra. Los presupuestos globales del propietario/A-E están publicados en los documentos citados, separados del estimado independiente ALKAN y de los subtotales parciales calculados en Items/Resources/Scopes. Los costos sin referencia suficiente quedan pendientes, nunca cero. Referencias_Conceptuales no contiene precios utilizables ni se agrega al parcial. No se distribuyeron presupuestos globales para inventar precios.

- `00_LEEME_Y_RESUMEN`: estado y pendientes prioritarios.
- `01_ESTIMADO_DE_COSTOS`: presupuesto, resumen económico, JSON de entradas, Fuentes_de_Costos.csv y Pendientes_para_Cotizar.csv.
- `02_TAKEOFF_Y_MATERIALES`: [Lista_Detallada_de_Materiales.xlsx](02_TAKEOFF_Y_MATERIALES/Lista_Detallada_de_Materiales.xlsx), takeoff, cantidades/fuentes y mediciones pendientes. La lista abre en Materiales_Detalle e incluye Resumen_de_Compras.
- `03_LICITACION_Y_FORMULARIOS`: matriz y borrador interno; formularios/tablas faltantes siguen identificados. Nada firmado o aprobado.
- `04_REQUISITOS_Y_ADENDAS`: requisitos y modificaciones originales del análisis.
- `05_AUDITORIA_Y_EVIDENCIAS`: cálculos actuales, referencias, imágenes, validación y revisión económica.
- `06_DOCUMENTOS_ORIGINALES`: copias intactas verificadas por SHA-256; docs/ permanece intacto.

**Lista y presupuesto:** ambos contienen las mismas hojas de cálculo de recursos/entradas, con el mismo fingerprint de costos; la lista es una vista de entrega, no una segunda base de precios. Mantenga el presupuesto como maestro. Edite entradas amarillas de Resources/Quotes y observaciones AH de Materiales_Detalle. Tras guardar: `python run_bidkit.py cost-import --project {pid} --workbook archivo.xlsx`, luego `python run_bidkit.py build --project {pid}`. Se regeneran Cost_Budget.xlsx y Lista_Detallada_de_Materiales.xlsx en output/{pid}. Para actualizar esta entrega y sus PDF/CSV desde resultados validados: `python tools/economic_deliveries.py`. No vuelva a ejecutar la preparación inicial de datos para importar precios.

**Revisión siguiente:** atender Pendientes_para_Cotizar.csv y la [lista consolidada de fuentes](../Solicitudes_Fuentes_Consolidadas.xlsx). Faltan cotizaciones de suministro/paquetes, clasificación y tarifas salariales aplicables con beneficios/cargas, rendimientos verificables, equipos/flete e indirectos/riesgo/margen. Vacío significa no estimado, nunca cero. No se usaron precios ficticios. Las reservas de merma no documentadas permanecen pendientes; las cantidades netas sí se muestran cuando son calculables. En paquetes valorados, no duplique los materiales o instalación al añadir nuevos precios; sustituya y concilie la provisión.

**Apto para revisión preliminar; no apto para oferta.** Las referencias del propietario/A-E no sustituyen una composición de costos ni confirman vigencia comercial. El impuesto se trata por proyecto y no se heredan tasas. El acceso externo falló una sola vez; el bloqueo queda documentado en 05. No se presentó ninguna oferta.
'''
        (base/'LEEME.md').write_text(text,encoding='utf-8')
        for kind,needed,owner in [('SALARIO','Tabla L&I journey/apprentice por oficio y beneficios, condado y fecha aplicable al expediente; confirmar clasificación y cargas de empresa. No se suministró tabla numérica utilizable.','Contratista / estimador'),('RENDIMIENTO','Histórico identificable o metodología de cuadrilla por actividad: composición, horas/unidad o unidades/hora, equipo incluido y condiciones del trabajo.','Contratista / estimador'),('EQUIPO_FLETE','Proveedor/modelo/capacidad, costo horario/diario, horas/días justificados, combustible, operador incluido o excluido, movilización y entrega en obra.','Proveedor de equipo / contratista'),('INDIRECTOS_RIESGO_MARGEN','Desglose de administración de obra y plazo, seguros/bonds con cotización, contingencia ligada a riesgos y decisión documentada de margen bruto. No usar markups de cambios como margen de oferta.','Estimador / contratista'),('IMPUESTO','Tratamiento contractual, base y tasa de la localización/fecha; aclarar si referencias globales ya incluyen impuesto. No aplicar tasa de otro proyecto.','Estimador / contratista')]:
            wage_date={'orangegate-park-phase-1':'Pierce County; vencimiento local A3: 2026-11-10; fuente salarial por referencia Div00 PDF111.','gonyea-playfield':'Pierce County; invitación: 2026-11-18; confirmar fecha/regla aplicable en documentación contractual completa.','rebid-meridian':'King County; anuncio suministrado: apertura 2026-09-02; sección 00 73 43 PDF202-206. No afirmar convocatoria actualmente abierta.'}[pid]
            decisions.append({'proyecto':c.project_name,'fuente_id':pid+'-'+kind,'categoria':kind,'informacion_exacta':needed+(' '+wage_date if kind=='SALARIO' else ''),'responsable':owner,'partidas_afectadas':'Todas las actividades aplicables; ver detalle por ID en hoja Partidas'})
        print(c.project_name+': economic PDF, source register, RFQ detail and linked materials delivered',flush=True)
    book=Workbook();book.remove(book.active)
    _sheet(book,'Solicitudes',['Proyecto','Fuente ID','Categoría','Información exacta','Responsable','Partidas afectadas'],[[r[k] for k in ('proyecto','fuente_id','categoria','informacion_exacta','responsable','partidas_afectadas')] for r in decisions])
    headers=list(all_requests[0]);_sheet(book,'Partidas',headers,[[r.get(k) for k in headers] for r in all_requests])
    _save(book,ROOT/'ENTREGAS/Solicitudes_Fuentes_Consolidadas.xlsx')
    _write_csv(ROOT/'ENTREGAS/Solicitudes_Fuentes_Consolidadas.csv',decisions)
    write_json(QA/'economic_results.json',{'external_access_attempts':1,'projects':summaries})
    # Refresh hashes only for these three bundles; leave historical West Seattle untouched.
    for pid in IDS:
        c=ProjectConfig(ROOT,pid);base=ROOT/'ENTREGAS'/c.project_name;manifest_path=base/FOLDERS[5]/'MANIFIESTO_ENTREGA.json'
        manifest=read_json(manifest_path);manifest['files']={p.relative_to(base).as_posix():sha256(p) for p in sorted(base.rglob('*')) if p.is_file() and p!=manifest_path};manifest['cost_fingerprint']=next(r['cost_fingerprint'] for r in summaries if r['project_id']==pid)
        write_json(manifest_path,manifest)


if __name__=='__main__':main()
