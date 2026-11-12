# ALKAN Bid Engine — Exportaciones por destinatario (V3.1A)

Fecha: 2026-11-06 · Alcance: tres tipos de documento desde un mismo expediente persistido, cambio mínimo funcional.

## Qué se hizo

Un mismo expediente (dossier) de proyecto genera ahora tres tipos de documento **profesionales y separados por destinatario**, sin volver a capturar información, reutilizando exportadores, cálculos y componentes de V3.1 existentes:

1. **Análisis interno de costos (PDF)** — reemplaza el reporte de flujo por un documento de 7 secciones estilo WSJ, marcado **CONFIDENCIAL — USO INTERNO**, con encabezados oscuros, tablas ordenadas, subtotales destacados, numeración y pie de página.
2. **Propuesta comercial (PDF)** — documento para el cliente con identificación, alcance, precio de venta aprobado, inclusiones/exclusiones, condiciones comerciales, vigencia y **espacio de autorización**; **no revela costos internos, tarifas internas ni márgenes**.
3. **Materiales / Proveedores (CSV o Excel)** — reutiliza el centro de exportación de proveedores (V3.1) para emitir el listado de materiales con cantidades, unidades, especificaciones, proveedores y cotizaciones realmente disponibles; separa el **directorio de proveedores** del **listado de materiales** para solicitar cotizaciones.

### Datos dinámicos
Empresa, proyecto, licencia/registro, fechas y responsable se leen del expediente (`state.project`). **No se fijan a S&S Custom Iron Works** ni a otro contratista; los campos ausentes se muestran como “No registrado”, nunca se inventan.

### Siete secciones del análisis interno
1. Alcance completo del trabajo.
2. Cuantificación y mediciones (Material Takeoff).
3. Materiales, especificaciones, cantidades y precios.
4. Mano de obra, horas, tarifas y costos.
5. Oficina, permisos, equipos y movilización.
6. Desglose final (costo directo, contingencia, overhead, utilidad / ajuste comercial y precio final).
7. Riesgos, observaciones y verificaciones pendientes.

## Archivos modificados / añadidos

| Archivo | Cambio |
|---|---|
| `src/bidkit/intelligence_reports.py` | `render_document` ahora genera el análisis interno profesional (7 secciones, CONFIDENCIAL, pie de página), la propuesta con bloque de autorización y sin fugas internas, y conserva la solicitud de materiales a proveedores. `_build` añade pie/paginación (CONFIDENCIAL solo en el documento interno). |
| `src/bidkit/intelligence_ui.html` | Sección de exportaciones ahora presenta **únicamente tres acciones**: “Análisis interno (PDF)”, “Propuesta comercial (PDF)” y “Materiales / Proveedores (CSV o Excel)”. |
| `src/bidkit/contractor_workflow.js` | Etiquetas de los tres documentos actualizadas (modo contratista). |
| `tests/test_v31_documents.py` | Nuevo módulo de pruebas de los tres tipos de documento. |

**Reutilizado (sin cambios):** `supplier_exports.py` (CSV/PDF de directorio/proyecto/comparativo), `estimate_workflow.py`, `estimator_v1`, `intelligence.py`, `intelligence_ui.py` (endpoints `/api/export` y `/api/supplier-export`), `export_document`.

## Pruebas ejecutadas

Ejecutadas localmente con unittest (pytest no está instalado en este runtime):

- `test_v31_documents.py` — **5/5 PASS**: 7 secciones internas presentes y totales coinciden con el expediente; propuesta sin fuga de texto confidencial y con espacio de autorización; los tres documentos del mismo dossier no mutan la revisión; CSV solo registros reales del proyecto; PDF byte-idéntico al repetir.
- `test_intelligence_v2.py`, `test_supplier_exports.py`, `test_estimate_workflow.py` — **PASS** (regresión; incluye el DRAFT que se esperaba en la solicitud a proveedores).
- Descubrimiento completo: **77 pruebas PASS**. 5 módulos no importan porque requieren `pytest` (`test_bid_preparation`, `test_costing`, `test_metal_analysis`, `test_purchase_workbook`, `test_ss_deliveries`); no están relacionados con este cambio y fallan solo por entorno (falta el paquete `pytest`).

Verificación de validación solicitada:
1. **Totales coinciden** — el documento interno incrusta `estimated_all_in_cost`, `proposed_price...` y `estimated_gross_profit` del expediente y el test los confirma.
2. **Propuesta sin info confidencial** — el test niega la presencia de `CONFIDENCIAL`, costo directo, indirectos, margen, tarifas, precios unitarios, etc.
3. **CSV solo registros reales** — el test verifica que cada fila pertenece al `project_id` y que todo proveedor no vacío está registrado.
4. **No modifica el expediente** — el test compara el dossier completo (incluida la revisión) antes/después de exportar.
5. **PDF se visualizan** — se generaron tres PDF reales en `data/v31_documents/demo_*.pdf` (interno ES 2 páginas, propuesta ES 1, interno EN 2); `PdfReader` los abre y extrae texto de todas las páginas. Artefactos de inspección:
   - `data/v31_documents/demo_internal_es.pdf`
   - `data/v31_documents/demo_proposal_es.pdf`
   - `data/v31_documents/demo_internal_en.pdf`
6. **Funciones existentes** — suite de regresión PASS (estimación, aprobación, export histórico, centro de proveedores, flujo de trabajo).

## Límites y notas

- El modelo V3 no almacena horas ni tarifas de mano de obra por separado; la sección 4 muestra cantidad y costo y advierte que horas/tarifas deben documentarse por partida (nunca se infieren).
- Permisos, movilización y oficina aparecen solo si están documentados/parametrizados en el expediente; de lo contrario quedan pendientes. No se inventan.
- No hay logo, licencia ni registro estructurado en el esquema actual: se muestran desde `project` como dinámicos; los campos ausentes aparecen como “No registrado”.
- No se alteraron expedientes históricos, cotizaciones aprobadas ni revisiones; la exportación es de solo lectura y determinista por versión.
- No se ejecutaron operaciones externas, OCR ni integraciones.