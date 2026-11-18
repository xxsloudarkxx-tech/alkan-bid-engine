# ALKAN Bid Engine — Auditoría Inicial del Sistema Existente (Stage A)

**Fecha de auditoría:** 2026-11-12  
**Repositorio auditado:** `c:\Users\diana\OneDrive\Desktop\bidengine-code-v3.3`  
**Versión empaquetada (`pyproject.toml`):** `bidkit` `3.6.0` (`src/bidkit/__init__.py` reporta `__version__ = "3.5.0"`)  
**Línea base de pruebas ejecutadas:** `304 passed, 8 skipped, 12 subtests passed in 146.16s` (`pytest tests/`)

---

## 1. Arquitectura General e Inventario de Subsistemas

La inspección del código fuente (`src/bidkit/`, `tools/`, `tests/`, `examples/`, `profiles/`) muestra que ALKAN Bid Engine evolucionó incrementalmente a través de múltiples versiones (v3.1 a v3.6), acumulando **cuatro subsistemas internos que coexisten** con esquemas de datos incompatibles entre sí:

| Subsistema | Módulos Principales | Ruta Web / CLI | Contrato de Datos | Estado Actual |
| :--- | :--- | :--- | :--- | :--- |
| **A. Paquete Unificado y Agente v3.6** | `package_method.py`, `package_build.py`, `package_render.py`, `app_api.py`, `agent_jobs.py`, `delivery.py`, `app_settings.py`, `estimator_agent/*` | `/` (`app.html`, `app.js`), `bidkit package`, `bidkit estimate-agent` | `"alkan-package/1"` | Activo y funcional para flujo principal de 3 PDFs + resumen agente. |
| **B. Inteligencia de Expedientes v2** | `intelligence.py`, `intelligence_store.py`, `intelligence_documents.py`, `intelligence_reports.py`, `intelligence_ui.py` | `/expedientes`, `bidkit build/takeoff/audit` (V2) | `"schema_version": "2.0"` | Funcional de forma paralela para gestión documental por expediente. |
| **C. Motor Clásico y Costeo Explícito** | `config.py`, `audit.py`, `takeoff.py`, `estimate.py`, `costing.py`, `cost_workbooks.py`, `lumpsum_cost.py`, `alkan_method.py`, `records.py` | `bidkit cost-init`, `bidkit cost-import`, `bidkit takeoff` | `ProjectConfig` + `"schema_version": 1` | Conservado por compatibilidad con expedientes antiguos y Excel. |
| **D. Orquestador RFQ 6-Fases y Medición** | `rfq_engine.py`, `rfq_documents.py`, `rfq_agent.py`, `rfq_tools.py`, `rfq_cli.py`, `plan_measurement.py`, `units.py`, `supplier_exports.py`, `price_catalog.py`, `price_registry.py` | `/herramientas`, `bidkit-rfq` | Esquema JSON de 6 fases | Contiene utilidades sólidas (conversión de unidades, exportadores RFQ), parcialmente aisladas del motor principal. |

Además existen módulos heredados en `src/bidkit/legacy_port/` y scripts auxiliares históricos en `tools/`.

---

## 2. Evaluación Detallada por Capacidad Requerida

### 2.1 Motor de Estimación y Takeoff
- **Fortalezas existentes:** `audit.py` realiza extracción acotada con `pypdfium2` + `pypdf`, calcula SHA-256 por documento y marca páginas con poco texto (`needs_visual_review < 40 chars`). `units.py` y `plan_measurement.py` implementan conversiones imperiales/métricas (`Decimal`) y calibración básica de escala. `estimator_agent/docindex.py` indexa planos, specs y addenda por páginas.
- **Brechas críticas:**
  - `package_method.MaterialLine` carece de campos estructurados para código de partida, material base separado de especificación/norma, dimensiones explícitas, porcentaje de desperdicio separado de cantidad neta (`net_qty` vs `waste_pct` vs `final_qty`), referencia exacta de hoja/detalle, nivel de confianza numérico, etiqueta probatoria (`medido`, `declarado`, `estimado_con_supuestos`, `no_determinado`), estado de revisión y respaldo inmutable del valor original ante corrección manual.
  - No existe motor de comparación visual/textual de revisiones y addenda contra planos base (`revision_diff`) ni detector automático de contradicciones entre especificaciones y planos.
  - Falta visor interactivo de planos en la UI unificada (`app.html`) con calibración de escala visual y marcadores de medición.

### 2.2 Pricebook — Base de Datos Comercial
- **Fortalezas existentes:** `estimator_agent/knowledge/price_book.json` contiene referencias iniciales por condado (Pierce/King) con `price_basis`. `material_import.py`, `price_catalog.py` y `price_registry.py` manejan importación tabular básica.
- **Brechas críticas:**
  - Existen **3 esquemas separados** (`price_book.json`, `price_catalog.py`, `price_registry.py`).
  - `PACKAGE_SCHEMA` solo admite `("QUOTE", "CATALOG", "BUDGET")` en lugar de la taxonomía obligatoria (`BUDGET`, `QUOTE`, `HISTORICAL`, `ALLOWANCE`, `VERIFIED`).
  - Faltan campos obligatorios: fabricante, norma ASTM aplicable, dimensiones, unidad de compra vs estimación, moneda, proveedor, ciudad, estado, fechas (`consulted_date`, `quoted_date`, `valid_until`), disponibilidad, cantidad mínima, transporte (`freight`), impuestos, documento original archivado y estado de verificación.
  - No hay historial de precios por proveedor/ubicación, comparador multi-proveedor, alerta automática de cotización vencida, bloqueo contra promoción automática de `BUDGET` a `QUOTE`/`VERIFIED`, ni importador PDF/Excel/CSV con preservación de archivo original y cola de revisión humana.

### 2.3 Labor Cost y Productividad
- **Fortalezas existentes:** `package_method.Rate` diferencia `"prevailing_wage"` vs `"loaded"` con `burden_pct`, y `knowledge/wages.json` documenta fuentes L&I por condado (`verified: true/false`).
- **Brechas críticas:**
  - `knowledge/productivity.json` guarda fórmulas en texto libre no evaluables de forma determinista (ej. `"0.35 + 0.5/post"`, `"0.4–0.6"`).
  - No se separa salario base (`base_wage`), `fringe`, `burden`, tarifa cargada (`loaded_rate`) y tarifa comercial (`commercial_rate`), ni composición de cuadrillas (`crew composition`).
  - Falta desglose explícito de horas de preparación (`setup`), fabricación, instalación y movilización, equipo/maquinaria, overtime y ajustes justificados por complejidad, altura, accesibilidad o clima.

### 2.4 Cost Engine — Motor Financiero
- **Fortalezas existentes:** `package_method.compute()` utiliza aritmética `Decimal` exacta con redondeo bancario/comercial sin punto flotante y orden secuencial consistente (`D -> contingency -> overhead -> profit -> rounding`).
- **Brechas críticas:**
  - Solo agrupa en 3 rubros directos (`materials`, `labor`, `other`), sin desglose obligatorio de 13 rubros (Material, Labor, Equipment, Subcontractor, Freight, Mobilization, Permits/Other, Waste allowance, Direct cost, Overhead, Contingency, Profit, Final bid price).
  - No distingue explícitamente entre cálculo por `markup` y por `margin`, ni incluye análisis de escenarios (`Conservative`, `Expected`, `Aggressive`) mostrando qué supuestos cambian y su impacto financiero.

### 2.5 Independent Estimate Review
- **Fortalezas existentes:** `estimator_agent/review.py` y `sanity.py` ejecutan verificaciones deterministas de rangos/totales y una llamada de revisión con contexto separado si se configura cliente Anthropic.
- **Brechas críticas:**
  - **Falla grave de gobierno:** En `agent_jobs.py` y `delivery.py`, cualquier texto escrito en `#actor` puede ejecutar `authorize()` sin validar identidad, rol ni impedir autoaprobación (`preparador == aprobador`). Además en `estimator_agent/agent.py`, si `review_model` está vacío se reutiliza la misma instancia cliente sin restricción de independencia de actor.
  - `review.py` no genera discrepancias estructuradas con `original_value`, `revised_value`, `reason`, `source`, `severity`, `recommendation` y `approval_status`.

### 2.6 RFI y Supplier RFQ Engine
- **Fortalezas existentes:** `rfq_engine.py`, `rfq_documents.py` y `supplier_exports.py` ya validan entradas y exportan hojas para proveedores.
- **Brechas críticas:**
  - No están integrados en el flujo principal de paquetes/UI v3.6 (`package_build.py` y `app.html`).
  - Falta generador formal de borradores RFI a partir de datos faltantes/inconsistencias, comparador de cotizaciones recibidas con detección de partidas sin cobertura y desviación de especificaciones, bitácora de comunicaciones y bloqueo estricto contra envío automático sin autorización humana.

### 2.7 Generación de Documentos (6 Entregables)
- **Brecha:** `package_build.py` / `package_render.py` solo generan 3 PDFs (`01_COST_ANALYSIS`, `02_MATERIAL_LIST`, `03_ESTIMATE_PROPOSAL`) más un reporte de corrida agente. Faltan los entregables normalizados dedicados para **`Labor Breakdown`**, **`RFQ Package`** y **`Risk and Exclusions Report`**, faltan formatos editables (`.xlsx` / `.docx`), falta encabezado normalizado uniforme y, críticamente, `delivery.authorize()` **sobrescribe archivos en el mismo directorio** en vez de mantener versiones inmutables protegidas.

### 2.8 Seguridad, Autenticación, Multitenancy, Respaldos y Estados
- **Estado actual crítico:**
  - Servidor limitado a `127.0.0.1` con verificación de `Origin` y token de sesión CSRF (`X-ALKAN-Token`), lo cual mitiga CSRF local pero **carece por completo** de: autenticación de usuarios, RBAC por rol, aislamiento multitenant (`org_id`), autenticación HMAC/Bearer servicio-a-servicio, rate limiting, cifrado/redacción consistente de secretos (`secrets.json` en texto plano en `%APPDATA%\ALKAN\BidEngine`), bitácora de auditoría con cadena hash y sistema completo de backup/restore verificado.
  - Estados fragmentados e inconsistentes entre subsistemas (`queued/running/lista/autorizada/detenida/bloqueada`, `"2.0"`, fases 1..6). No existen los 7 estados canónicos requeridos (`Draft`, `Processing`, `Review Required`, `Approved`, `Rejected`, `Exported`, `Error`).

### 2.9 Integraciones del Ecosistema ALKAN
- **ALKAN Workflow Studio** (`ALKAN_Studio_0_6_5_QuickBooks_OAuth`): Expone `POST /api/automation/event` (`{ type, payload, source, entityType, entityId, metadata }`) y rutas `/api/quickbooks`. Bid Engine tiene actualmente **0% de implementación** para emitir eventos `bid.*`, validar firmas de servicio, manejar idempotencia o reintentos.
- **Contractor Superbot** (`contractor-bot-v2`): Opera con clientes (`am_clients`), mensajes (`am_messages`), aprobaciones (`am_approvals`) y skill `preparar-bid-engine.md`. Bid Engine no cuenta aún con puente de ingesta de oportunidades/expedientes ni aislamiento por cliente.
- **QuickBooks Online**: Studio solo implementa OAuth 2.0 y lectura de empresa/clientes (`readCompany('company'|'customers')`), documentando explícitamente que la creación de Estimates no está implementada. Bid Engine carece aún de adaptador QuickBooks Online (cliente, mapeo de Estimate, control de duplicados, `SyncToken`, idempotencia y autorización humana).

---

## 3. Verificación de Secretos y Línea Base de Pruebas

- Se inspeccionaron archivos de configuración y variables de entorno locales: **no se encontraron llaves reales ni secretos filtrados en el repositorio**. No existen credenciales vivas de QuickBooks (`QUICKBOOKS_*`), Supabase ni `ANTHROPIC_API_KEY` configuradas en esta sesión (solo `ANTHROPIC_BASE_URL` en el entorno).
- Ejecución de línea base (`pytest tests/`):
  - **Resultado:** `304 passed, 8 skipped, 12 subtests passed` (0 fallos).
  - *Nota técnica:* En esta máquina Windows el Python principal del sistema apuntaba a una copia antigua (`0.1.0`), mientras que el runtime con dependencias (`pypdf`, `pypdfium2`, `reportlab`, `openpyxl`, `python-docx`, `Pillow`) requirió instalar `pytest`, `jsonschema` y `bidkit` en modo editable (`-e .`). Además `AppData\Local\Temp\pytest-of-Andres` presentó restricciones ACL de NTFS, por lo que las pruebas se ejecutan con `--basetemp` dentro del espacio de trabajo.

---

## 4. Plan de Ejecución (Etapas B – F)

1. **Etapa B (Corrección y Seguridad):** Implementar `domain.py` (7 estados canónicos + bitácora hash-encadenada), `security.py` (multitenancy `org_id`, RBAC, PBKDF2 + tokens de servicio + HMAC, rate limit, bloqueo estricto de autoaprobación, sanitización Excel/CSV) y `backup.py`, e integrarlos en `app_api.py`, `agent_jobs.py`, `delivery.py` e `intelligence_ui.py`.
2. **Etapa C (Fortalecimiento Técnico):** Implementar `takeoff_engine.py`, `revision_diff.py`, `pricebook.py`, `labor_engine.py`, `cost_engine.py`, `review_engine.py`, `rfi_rfq.py` y `deliverables_v4.py` (6 entregables en PDF + XLSX + DOCX con versionado inmutable), conservando compatibilidad total con `alkan-package/1` y CLI existentes.
3. **Etapa D (Integraciones y UI 13 Vistas):** Implementar `src/bidkit/integrations/` (`workflow_studio.py`, `superbot_bridge.py`, `quickbooks_sync.py`) y actualizar `app.html` / `app.js` / endpoints `/api/v4/*` para exponer las 13 vistas y 7 estados canónicos.
4. **Etapa E (Validación y Benchmark Real):** Ampliar suite automatizada (unitaria, integración, anti-alucinación, regresión, E2E, seguridad, contratos de integración) y ejecutar benchmark contra los 4 proyectos reales (`wsj.json`, `gonyea.json`, `meridian.json`, `orangegate.json`).
5. **Etapa F (Documentación Final):** Entregar la documentación completa de ingeniería, seguridad, contratos, esquemas, operación y evaluación objetiva de madurez en `engineering_docs/`.
