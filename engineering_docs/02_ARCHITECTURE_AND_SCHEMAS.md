# ALKAN Bid Engine v4 — Arquitectura Final, Módulos Modificados y Esquemas de Datos

**Versión del sistema:** `bidkit` `3.6.0` + capa empresarial `v4` (`api/v4/*`)  
**Workspace:** `C:\Users\diana\OneDrive\Desktop\bidengine-code-v3.3`

---

## 1. Arquitectura Modular Final

El sistema mantiene compatibilidad total con los cuatro flujos existentes (`v3.1`–`v3.6`, CLI `bidkit`, `/expedientes`, `/herramientas`, `examples/packages/*.json`) e incorpora una columna vertebral unificada y auditable:

### Módulos Nuevos (`src/bidkit/`)
1. `domain.py` — Estados canónicos unificados (`Draft`, `Processing`, `Review Required`, `Approved`, `Rejected`, `Exported`, `Error`), grafo de transiciones permitidas (`ALLOWED_TRANSITIONS`), mapeo de estados heredados (`LEGACY_STATUS_MAP`) y bitácora SHA-256 encadenada (`AuditLedger.verify_chain()`).
2. `security.py` — Aislamiento multitenant (`org_id` + `client_id`), RBAC (`admin`, `estimator`, `reviewer`, `operator`, `client`), `AuthStore` con PBKDF2-HMAC-SHA256 (`200,000` iteraciones), claves de servicio, firmas HMAC-SHA256 (`sign_payload`/`verify_hmac_signature`), limitador de tasa (`SlidingWindowRateLimiter`), bloqueo estricto de autoaprobación (`assert_independent_approver`), redacción de secretos y sanitización contra inyección de fórmulas Excel/CSV (`sanitize_spreadsheet_cell`).
3. `backup.py` — Respaldos verificables en ZIP con `BACKUP_MANIFEST.json` SHA-256 (`create_backup`, `verify_backup`, `restore_backup`), excluyendo secretos locales (`secrets.json`, `.vault-key`, `.quickbooks-key`, `.env`) y bloqueando path traversal.
4. `takeoff_engine.py` — Clasificación de planos PDF por disciplina (`Structural`, `Architectural`, `Civil`, `MEP`, `Landscape`), detección de páginas escaneadas (`is_scanned`), calibración de escala con confianza (`calibrate_drawing_scale`), medición de longitud/área/conteo/volumen (`compute_measurement`), esquema completo `MaterialTakeoffItem` con desperdicio, etiqueta documental (`medido | declarado | estimado_con_supuestos | no_determinado`), respaldo inmutable `original_measurement` y detector de brechas (`detect_takeoff_gaps`).
5. `revision_diff.py` — Comparación entre juegos de planos (`compare_sheet_sets`) y detector de contradicciones entre especificaciones, planos y adendas (`detect_spec_drawing_inconsistencies`).
6. `pricebook.py` — Base comercial unificada `PricebookStore` con clasificación obligatoria (`BUDGET`, `QUOTE`, `HISTORICAL`, `ALLOWANCE`, `VERIFIED`), prevención de promoción automática `BUDGET -> VERIFIED`, alertas y bloqueo de vigencia vencida, historial de precios, comparador multi-proveedor con flete/mínimos e importador CSV/XLSX/PDF con archivo original SHA-256 y cola `pending_review`.
7. `labor_engine.py` — Cadena salarial estructurada (`base_wage` + `fringe_benefits` -> `total_pw_package` + `burden_amount` -> `loaded_rate` -> `commercial_rate`), cuadrillas (`CrewComposition`), desglose de horas (`prep`, `fabrication`, `installation`, `mobilization`), parser determinista de `productivity.json` y bloqueo de multiplicadores arbitrarios sin justificación/fuente (`AdjustmentFactor`).
8. `cost_engine.py` — Cálculo transparente en 13 rubros (`compute_13_buckets`), distinción explícita `markup` vs `margin` sin doble conteo de desperdicio ni contingencias, perfiles por empresa/especialidad y análisis de 3 escenarios (`Conservative`, `Expected`, `Aggressive`).
9. `review_engine.py` — Validación determinista + hallazgos IA estructurados (`ReviewDiscrepancy`: `original_value`, `revised_value`, `reason`, `source`, `severity`, `recommendation`, `approval_status`), detección de duplicados/omisiones/desperdicios/márgenes y rechazo obligatorio de autoaprobación.
10. `rfi_rfq.py` — Generación de borradores RFI desde brechas de takeoff/conflictos, creación y exportación Excel de RFQ por proveedor (`export_rfq_xlsx`), comparador de cotizaciones recibidas con detección de partidas descubiertas y bloque de autorización humana antes de emitir (`authorize_dispatch`).
11. `deliverables_v4.py` — Generación normalizada de los **6 entregables** (`01_COST_ANALYSIS`, `02_MATERIAL_LIST`, `03_LABOR_BREAKDOWN`, `04_ESTIMATE_PROPOSAL`, `05_RFQ_PACKAGE`, `06_RISK_AND_EXCLUSIONS`) en **PDF + XLSX + DOCX** con encabezado normalizado y versionado inmutable (`ImmutableVersionError`).
12. `v4_api.py` & `v4_workspace.js` — Controlador `/api/v4/*` y las **13 vistas de trabajo** integradas en `app.html`.
13. `integrations/` (`workflow_studio.py`, `superbot_bridge.py`, `quickbooks_sync.py`, `common.py`).

### Módulos Modificados (Compatibles hacia atrás)
- `src/bidkit/delivery.py` — Agregado bloqueo de autoaprobación de agentes IA, snapshot inmutable en `approved_versions/vN/` y registro en `AuditLedger`.
- `src/bidkit/agent_jobs.py` — Agregados `canonical_state`, `org_id`, `reject()`, `export_v4()` y soporte `strict_separation` en `authorize()`.
- `src/bidkit/app_api.py` & `src/bidkit/intelligence_ui.py` — Enrutamiento `/api/v4/*`, autenticación por Bearer/API-Key de servicio, manejo HTTP 403/409/429 y servicio de `v4_workspace.js`.
- `src/bidkit/app.html` — Navegación unificada hacia las 13 vistas (`#dashboard`, `#docs`, `#viewer`, `#takeoff`, `#catalog`, `#quotes`, `#labor`, `#cost-analysis`, `#review`, `#rfq`, `#proposals`, `#integrations`, `#audit`).
- `.env.example` — Plantilla limpia de variables de entorno sin secretos.

---

## 2. Esquema Canónico de Estados y Transiciones

| Estado Canónico | Equivalentes Heredados | Siguientes Estados Válidos |
| :--- | :--- | :--- |
| `Draft` | `draft`, `borrador` | `Processing`, `Review Required`, `Error` |
| `Processing` | `en cola`, `indexando`, `estimando`, `queued`, `running` | `Review Required`, `Rejected`, `Error` |
| `Review Required` | `lista`, `incompleta`, `pendiente` | `Approved`, `Rejected`, `Processing`, `Draft`, `Error` |
| `Approved` | `autorizada`, `approved` | `Exported`, `Review Required`, `Rejected` |
| `Rejected` | `rechazada`, `no-go` | `Draft`, `Processing`, `Review Required` |
| `Exported` | `exportada` | `Approved`, `Review Required` |
| `Error` | `error`, `cancelada`, `interrumpida`, `detenida`, `bloqueada` | `Draft`, `Processing`, `Review Required` |

---

## 3. Esquemas Principales de Datos y Migración desde `alkan-package/1`

- **Compatibilidad `alkan-package/1`:** Todos los JSON existentes (`wsj.json`, `gonyea.json`, `meridian.json`, `orangegate.json`) cargan sin modificaciones mediante `package_method.load_package()`.
- **Migración no destructiva:**
  - `estimator_agent/knowledge/price_book.json` se importa automáticamente por organización en `data/orgs/<org_id>/pricebook_v4.json` mediante `PricebookStore.import_legacy_price_book()`, manteniendo la clasificación `BUDGET` o `HISTORICAL` y estado `unverified` hasta que un revisor humano adjunte documento y apruebe.
  - `estimator_agent/knowledge/wages.json` y `productivity.json` se cargan estructurados mediante `load_structured_wages()` y `parse_legacy_productivity()` preservando su fuente original.
