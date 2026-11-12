# ALKAN Bid Engine — Cierre funcional V3.1A

Fecha: 2026-11-06 · Modo: implementación enfocada y económica, sobre el repositorio actual. No se reconstruyó el sistema; no se crearon aplicaciones, dashboards, agentes ni sistemas paralelos. No se borraron, movieron ni consolidaron archivos duplicados (los resolverá el propietario).

---

## 1. Resumen exacto de modificaciones

### FASE 1 — Exportaciones PDF corregidas
- **Tablas/columnas cortadas:** detectada la causa real: las sumas de anchos de varias tablas superaban el ancho imprimible (612 pt − 86 pt de márgenes ≈ 526 pt). Añadido `_fit()` en `intelligence_reports.py` que escala proporcionalmente cada tabla al ancho útil. **Toda tabla cabe dentro de márgenes.**
- **Textos largos:** las celdas usan `Paragraph` (con ajuste de línea); verificado que descripciones largas envuelven dentro de la celda (el n.º de páginas creció al envolver un texto largo de prueba).
- **Traducciones incompletas en PDF inglés:** encabezados, etiquetas, estados, pie de página y banner ahora son bilingües vía `_tr()`. El PDF en inglés genera íntegramente en inglés (incluido “Page” y la nota CONFIDENCIAL en inglés).
- **Estados técnicos → etiquetas:** el desglose y secciones muestran etiquetas comprensibles (Costo directo, Contingencia, Overhead, Utilidad estimada, Precio propuesto, etc.) con los valores del expediente.
- **Datos ausentes:** se muestran como `No registrado` / `PENDIENTE` / `—`; nunca se inventan.
- Se **conservan las 7 secciones** del análisis interno y la **separación CONFIDENCIAL** respecto a la propuesta (el pie CONFIDENCIAL aparece solo en el documento interno; la propuesta no incluye costos internos ni márgenes, y añade bloque de autorización).

### FASE 2 — Pruebas y cálculos
- Resuelto el entorno: `pytest 9.2` instalado únicamente en el intérprete del runtime (no existe venv en el repo; era el único paquete faltante y no hay instalación global nueva de dependencias del proyecto).
- Los **5 módulos que antes no importaban** (`test_bid_preparation`, `test_costing`, `test_metal_analysis`, `test_purchase_workbook`, `test_ss_deliveries`) ya se ejecutan.
- La suite completa pasó: **181 tests + 12 subtests PASS**.
- Cobertura de la validación pedida (cantidades/unidades, subtotales y totales, fórmulas de contingencia/overhead/margen, diferencia costo interno vs precio comercial, redondeo monetario, aprobaciones/revisiones, exportaciones deterministas y sin mutar el expediente) ya está cubierta por `test_costing.py`, `test_bid_preparation.py` y `test_v31_documents.py`, todos PASS. **No se alteró ninguna fórmula comercial.**

### FASE 3 — Integración de materiales reales
- **No existía un adaptador** para el formato de listas de materiales de `data/Imports/materiales` (el importador de catálogo requiere `product_name, supplier, unit, unit_price`; no aplica). Se creó **solo el adaptador mínimo** `src/bidkit/material_import.py`.
- Comportamiento: lee CSV/XLSX de la lista (whitelist de 5 archivos), produce una **revisión de diferencias de solo lectura** (`preview`) y una **incorporación controlada** (`apply`) que:
  - mapea `CANTIDAD DOCUMENTAL` y `CÁLCULO DEL ANÁLISIS INTERNO` → `PENDING_VERIFICATION` (nunca verificación de campo);
  - mantiene `PENDIENTE DE MEDICIÓN` con `quantity = None`;
  - conserva proyecto, partida (ID), descripción, cantidad, unidad y fuente documental;
  - **no crea cotizaciones, proveedores ni precios**;
  - no edita/sobrescribe registros existentes (los registros ya importados se omiten por firma `material_import_sig`);
  - mantiene trazabilidad al archivo/origen vía `material_import_source`;
  - **exige confirmación explícita si el expediente tiene una aprobación registrada**;
  - alimenta las exportaciones existentes (las líneas nuevas aparecen en análisis interno y en el CSV de materiales/proveedores).
- Endpoints reutilizando la UI local: `GET /api/material-preview` (solo lectura) y `POST /api/material-apply` (con confirmación).

### FASE 4 — Validación de principio a fin (Gonyea, REBID Meridian, Orangegate)
Resultado **honesto**: los tres expedientes son **legacy sin expediente V3** (`integrated=False`), por lo que hoy **no pueden** generar los documentos V3 (análisis interno, propuesta, CSV) a través del exportador de Intelligence hasta que se incorporen (adopt/create + carga y revisión de documentos). Estado por caso:

| Expediente | analysis.json | Material list (fuente) | Documentos V3 generables hoy |
|---|---|---|---|
| `gonyea-playfield` | 25 cantidades (19 medidas) | `04_Tacoma_Gonyea.csv` (15 filas CANTIDAD DOCUMENTAL) | Ninguno (sin dossier V3) |
| `rebid-meridian` | 11 cantidades (5 medidas) | `03_Seattle_Meridian.csv` (5 filas CANTIDAD DOCUMENTAL) | Ninguno (sin dossier V3) |
| `orangegate-park-phase-1` | 112 cantidades (99 medidas) | `05_Tacoma_Orangegate.csv` (12 filas PENDIENTE DE MEDICIÓN) | Ninguno (sin dossier V3) |
| `w-seattle-junction-landbank-park` | 24 cantidades (17 medidas) | `01_Seattle_WSJ_Metal.csv` (24) + `02_Seattle_WSJ_Paisaje.csv` (17) | Ninguno (sin dossier V3) |

La `preview` de materiales requiere un dossier V3 abierto (por diseño); los tests del adaptador validan el flujo preview→apply sobre dossiers controlados. **No se importó ni aprobó nada en producción.**

---

## 2. Archivos modificados/creados

- `src/bidkit/intelligence_reports.py` (F1) — ancho seguro, bilingüe, 7 secciones, propuesta con autorización, sin fugas internas.
- `src/bidkit/material_import.py` (NUEVO, F3) — adaptador mínimo preview/apply con guardas.
- `src/bidkit/intelligence_ui.py` (F1/F3) — import de `material_import` + endpoints `/api/material-preview`, `/api/material-apply`.
- `docs/reference_exports/demo_internal_es.pdf`, `demo_internal_en.pdf`, `demo_proposal_es.pdf` (regenerados).
- `tests/test_v31_documents.py`, `tests/test_material_import.py` (NUEVOS).

(Nota: en sesión previa también se modificaron `intelligence_ui.html` y `contractor_workflow.js` para presentar las tres acciones; se conservan.)

## 3. Pruebas ejecutadas

- `pytest` completo: **181 passed, 12 subtests passed** (incluye los 5 módulos antes bloqueados y los nuevos tests V3.1A).
- `test_v31_documents.py` 5/5 y `test_material_import.py` 4/4 PASS (validación puntual).
- Verificación PDF: las 3 demos regeneradas; todas las tablas quedan dentro del ancho útil (verificado geométricamente: suma de anchos ≤ 525.6 pt para todas las tablas usadas); el texto largo envuelve dentro de su celda.
- Falla honesta detectada y no ocultada: PDF/análisis no se pueden **inspeccionar visualmente por este modelo** (no admite imágenes/PDF); la verificación de márgenes es geométrica por construcción (`_fit`) y por conteo de páginas.

## 4. PDF y exportaciones de muestra

- `docs/reference_exports/demo_internal_es.pdf`, `demo_internal_en.pdf`, `demo_proposal_es.pdf`.

## 5. Situación de los tres expedientes reales

Son legacy y **no** están integrados al pipeline V3; **no pueden emitir oferta** por ausencia de: dossier V3 (documentos y revisión), cotizaciones/precios, verificación documental de cantidades, parámetros financieros y aprobación humana. El adaptador de materiales ya está listo para alimentarlos una vez integrados.

## 6. Pendientes restantes (por prioridad)

1. **Integrar los 4 expedientes legacy al pipeline V3** (adopt + subir documentos + analizar) — trabajo del estimador/operación.
2. **Importar los materiales** de `data/Imports/materiales` por archivo, revisando diferencias (preview) antes de aplicar, por cada expediente integrado.
3. **Prelado de precios/cotizaciones y parámetros financieros** (requiere datos comerciales reales; no se simulan).
4. **Verificación documental de cantidades, requisitos, seguros/fianzas, y aprobación humana** para desbloquear la propuesta.
5. Inspección visual por un humano de los PDF (este modelo no puede verlas).

## 7. Créditos consumidos

El proveedor **no expone** una consulta de saldo/créditos en este entorno; **no invento el número**. Trabajé por fases y verifiqué al cerrar cada una; la suite completa quedó en verde y el estado es seguro (la FASE 4 fue solo lectura sobre producción; no se modificó ningún expediente real).