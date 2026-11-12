# ALKAN Bid Engine V3.1 — Supplier Export Center

Fecha de cierre: 2026-10-31  
Alcance: exportaciones locales y de solo lectura sobre el expediente V3 persistente. No se publicó ni se activó ningún servicio externo.

## Estado inicial auditado

Se leyó `ALKAN_BID_ENGINE_V3_DELIVERY.md`, el servicio `Intelligence`, `EstimateWorkflow`, la interfaz V2.1/V3, los reportes, el catálogo local y los tests. La carpeta no tiene repositorio Git (`git status` no pudo usarse como control de versión), por lo que se creó un respaldo verificable antes de editar:

- `data/v31_audit/before_v31_code.zip`: 89 archivos de código/documentación, SHA-256 `cb60b1b7c9673d708ab4139c7d74d7891e141845983f3580fb0994db10356754`.
- `data/v31_audit/before_v31_manifest.json`: hash individual de cada archivo respaldado.
- `data/v31_audit/historical_before_manifest.json`: 433 archivos históricos de `projects`, `docs`, `output` y `ENTREGAS`; no forman parte de la reversión de código.
- `data/v31_audit/pytest_baseline.xml`: línea base **115 pruebas, 7 subtests, PASS**.

Los proyectos heredados revisados conservan referencias documentales, pero sus `quotes.json` están vacíos y no existe un directorio público de proveedores. Por ello la implementación no crea un proveedor genérico ni descubre proveedores: exporta únicamente registros explícitos del expediente V3 abierto. En el modelo actual un proveedor registrado contiene `supplier_id`, `name` y `location`; `company`, `specialty`, `city`, nombre de contacto, correo y teléfono no existen. Se muestran como `No registrado`. La verificación solo se marca cuando hay `reviewed_by` y `reviewed_at`; en los fixtures controlados queda `No verificado`.

Las cotizaciones sí distinguen `supplier_id`, proveedor/sucursal, partida, descripción, fabricante/SKU cuando existan, especificación, unidad, presentación, precio unitario, flete, impuesto, descuento, moneda, fechas, vigencia, clase (`historical`, `catalog`, `formal_quote`, `phone_confirmed`, `invoice_actual`), confirmación, disponibilidad, coincidencia técnica, evidencia, versión y `supersedes`. Un registro de catálogo, una llamada, una cotización formal y una factura permanecen como clases distintas.

## Arquitectura implementada

`src/bidkit/supplier_exports.py` es una proyección inmutable del estado de una revisión. Carga el expediente canónico, verifica originales y produce tres vistas:

1. **Directory**: proveedores registrados, procedencia, verificación, campos faltantes, conteo de cotizaciones/catálogo y evidencia.
2. **Project**: relación de cada partida activa con las cotizaciones recibidas, estado de solicitud, proveedor registrado o proveedor ausente y evidencia. Las partidas sin cotización aparecen explícitamente.
3. **Comparison**: todas las versiones de cotización por partida, cantidad/unidad, precios, flete, impuestos, descuentos, moneda, vigencia, elegibilidad, selección, diferencias y evidencia. Los totales normalizados solo se emiten para USD elegible; no se mezclan monedas.

CSV usa BOM UTF-8, CRLF, comillas estándar y protección contra inyección de fórmulas (`=`, `+`, `-`, `@`). PDF usa ReportLab, una marca temporal de la revisión inmutable para que la repetición sea byte-identical, tablas legibles y el aviso bilingüe de cobertura. No incluye margen ni costo interno.

Los archivos se escriben con nombre determinista `supplier-{kind}-{language}-r{revision:06d}-{sha12}.{csv|pdf}`, publicación atómica y validación de hash al descargarse. Crear una exportación no agrega una revisión ni modifica aprobación, selección, conciliación o cotización.

Endpoints añadidos:

- `POST /api/supplier-export`: requiere sesión local, token existente, responsable y `project_id`, `revision`, `kind`, `language`, `formats`.
- `GET /api/supplier-export-file?project_id=...&name=...`: solo acepta nombres generados por el exportador, verifica que el archivo esté dentro del expediente y valida el hash embebido.

La sección `#supplierExportCenter` se añade al mismo `review` que Contractor Mode mueve a la etapa 5. Advanced Mode conserva los mismos controles. No hay un segundo almacén ni un estado paralelo.

## Archivos afectados

- Añadido: `src/bidkit/supplier_exports.py`.
- Modificados: `src/bidkit/intelligence_ui.py`, `src/bidkit/intelligence_ui.js`, `tools/verify_contractor_v3_ui.cjs`.
- Añadidos: `tests/test_supplier_exports.py`, `tools/rollback_bid_engine_v31.py`, este reporte.
- Evidencia: `data/v31_audit/` (pruebas, hashes, capturas y descargas de aceptación sintética).

Se reutilizaron `Intelligence.store`, las revisiones append-only, `check_originals`, `evaluate`, `EstimateWorkflow`, el token/host local de `intelligence_ui.py`, la interfaz Contractor Mode y el generador ReportLab existente. No se modificó `estimate.py`, el motor Decimal V1, los originales, los servicios remotos ni la carpeta hermana `ALKANbid`.

## Pruebas y demostración

La suite completa terminó en **121 pruebas, 7 subtests, PASS** (`data/v31_audit/pytest_v31_final3.xml`). La prueba específica terminó en **6/6 PASS** (`pytest_supplier.xml`). Cubren:

- dos proveedores registrados en un expediente controlado, campos ausentes visibles y procedencia;
- filtrado por expediente, partidas sin cotización y proyecto heredado sin expediente V3;
- versiones sustituidas, moneda, fecha, vigencia, flete, elegibilidad y evidencia;
- CSV con BOM, caracteres especiales, saltos de línea, campos vacíos, nombre largo y fórmula protegida;
- PDF con nombre/procedencia, sin campos de margen/costo interno;
- token inválido (403), ruta de archivo traversal (400), contenido real CSV/PDF y repetición sin mutar el estado;
- descarga HTTP de los seis artefactos y revisión de su firma (`EF BB BF`/`%PDF`).

El recorrido de navegador controlado (`tools/verify_contractor_v3_ui.cjs`) terminó **PASS** con Chrome 156.0.8078.76: dos documentos, análisis, corrección de cantidades, cotización versionada, cálculo, aprobación humana, reinicio del servidor, recuperación del mismo expediente, modo avanzado, escritorio 1440×1000 y móvil 390×844 sin overflow. Generó y comprobó los tres PDFs V3 más seis exportaciones V3.1 CSV/PDF. No hubo errores de página ni servicios externos. Evidencia en `data/v31_audit/guided_browser_results.json` y las capturas `guided_*.(png|pdf|csv)`.

Hashes SHA-256 de las descargas sintéticas comprobadas:

| Archivo | SHA-256 |
|---|---|
| `supplier_directory_csv_SYNTHETIC.csv` | `2f2c09e582eca0a2eabbced1f941776e6aea287b25189e1568abbad6c721157c` |
| `supplier_directory_pdf_SYNTHETIC.pdf` | `200b2d069337fac633a006cfadb106193b86e170f4d862adc4994caccda23969` |
| `supplier_project_csv_SYNTHETIC.csv` | `f827a824c0cd6b20e3239072cfe6653947cf1dc6c774ed9c0f6c7258d729b7f2` |
| `supplier_project_pdf_SYNTHETIC.pdf` | `410c14d4e4429482158d448c1be5a700f87f9bb1674d32dd7128367f885836ff` |
| `supplier_comparison_csv_SYNTHETIC.csv` | `7d3b0f46f820928e63d99668740f874eda0481845fadae41eee8ad8a57642215` |
| `supplier_comparison_pdf_SYNTHETIC.pdf` | `f0ef4f6b647a09f5a77f9f56c5987c4d12677ceddfefc16aa9b0bb66dbc3a6fb` |

La demostración usa datos sintéticos anonimizados y controlados porque los expedientes históricos disponibles no contienen cotizaciones reales: **documentos → partidas → proveedores → costos → aprobación → propuesta**, más directory/project/comparison. No se presenta como prueba de una fuente pública de proveedores ni como cotización comercial real.

## Limitaciones y datos pendientes

- No existe directorio global, descubrimiento externo, contacto, empresa, especialidad o ciudad en el esquema actual; no se inventan.
- No se agregaron OCR, IA pagada, scrapers, API de proveedores ni conectores parcelarios.
- Los PDFs escaneados siguen el estado de revisión manual existente.
- Los comparativos no agregan totales entre monedas. Una cotización no elegible o vencida permanece visible y no se suma.
- El archivo original de Alvarez/Alvarez Landscaping no está en la carpeta; su patrón debe validarse con el PDF original cuando se proporcione.
- La interfaz descarga enlaces en el mismo servidor loopback; no envía ni publica nada automáticamente.

## Reversión segura

La reversión es seca por defecto y no toca `projects`, documentos originales, revisiones ni exportaciones:

```powershell
Set-Location 'C:\Users\diana\OneDrive\Desktop\bidengine'
$py='C:\Users\diana\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH="$PWD\src;$PWD\tmp\v2-test-deps"
& $py tools\rollback_bid_engine_v31.py
# Solo tras revisar la lista y detener el servidor:
& $py tools\rollback_bid_engine_v31.py --apply
```

El script verifica el hash del respaldo, el manifiesto de release y cada archivo modificado. Antes de restaurar guarda una copia en `data/v31_audit/before_rollback_*`. Si detecta trabajo posterior, se detiene sin sobrescribir.

## Inicio local

```powershell
Set-Location 'C:\Users\diana\OneDrive\Desktop\bidengine'
$py='C:\Users\diana\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONPATH="$PWD\src;$PWD\tmp\v2-test-deps"
& $py run_bidkit.py estimate-ui --root "$PWD" --port 18905 --no-browser
Start-Process 'http://127.0.0.1:18905/?mode=contractor'
# Recorrido de aceptación Chromium (inicia/detiene su servidor temporal):
$env:ALKAN_AUDIT_DIR='data/v31_audit'
node tools\verify_contractor_v3_ui.cjs
# Regresión completa:
& $py -m pytest -q --disable-warnings --basetemp=.test-tmp/v31-final3
```

Estado V3.1: **IMPLEMENTADO** para exportaciones locales de lectura, con los campos y cobertura disponibles en el modelo. **PARCIAL/PENDIENTE** para directorio externo, OCR, contactos estructurados e integraciones de proveedores: requieren datos, credenciales o servicios autorizados adicionales.

## Matriz de trazabilidad

| Requisito | Código/evidencia | Prueba |
|---|---|---|
| Directorio CSV/PDF de registros reales | `supplier_exports.py:directory_data`, `/api/supplier-export` | `test_directory...`, browser seis descargas |
| Lista por proyecto sin mezclar expedientes | `project_data`, `Intelligence.store.load(project_id)` | `test_project_export...` |
| Comparativo versionado y por moneda | `comparison_data`, `_version_status`, `currency_totals_not_mixed` | `test_comparison...` |
| Evidencia, verificación y campos faltantes | `_supplier_provenance`, `_evidence`, sentinel rows | `test_directory...`, `test_csv...` |
| CSV Excel seguro | `_safe_csv`, BOM/CRLF | `test_csv...`, firma descargada |
| PDF legible sin margen interno | `pdf_bytes`, ReportLab | `test_csv...`, PDFs de navegador |
| Lectura sola/idempotencia | no se llama `store.append`; nombre/hashes deterministas | `test_repeating...` |
| Seguridad y autorización | token/host existentes, `validate_artifact_name`, hash | `test_http...` |
| Contractor/Advanced controls | `intelligence_ui.js`, `contractor_workflow.js` | recorrido Chrome desktop/mobile |
| Recuperación y reversión | revisiones existentes, `rollback_bid_engine_v31.py` | browser restart; dry-run verificable |
