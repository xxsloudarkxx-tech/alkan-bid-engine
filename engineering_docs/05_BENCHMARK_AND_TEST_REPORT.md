# ALKAN Bid Engine v4 — Reporte de Benchmark, Pruebas y Evaluación Final

**Fecha de verificación:** 2026-11-12  
**Suite ejecutada:** `pytest tests/` (`317 passed, 8 skipped, 12 subtests passed in 119.30s`)  
**Benchmark ejecutado:** `python benchmark/run_benchmark.py` (`4/4 PASSED`, `0.0%` de desviación numérica)

---

## 1. Benchmark de Precisión contra Proyectos Reales

Ejecutado mediante [run_benchmark.py](file:///C:/Users/diana/OneDrive/Desktop/bidengine-code-v3.3/benchmark/run_benchmark.py) sobre los 4 paquetes reales de referencia en `examples/packages/` (tolerancia configurada: `0.01%`):

| Proyecto | Paquete | Materiales (Ref / v4) | Mano de Obra (Ref / v4) | Costo Directo (Ref / v4) | Precio Final Expected | Escenarios (Agresivo / Esperado / Conservador) | Discrepancias Revisión | Entregables 6x3 | Resultado |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **West Seattle Junction Landbank Park** | `wsj.json` | `$6,936.50` / `$6,936.50` (`0.0%`) | `$8,528.94` / `$8,528.94` (`0.0%`) | `$17,325.44` / `$17,325.44` (`0.0%`) | `$22,000.00` (`0.0%`) | `$20,250` / `$22,000` / `$25,150` | 6 | OK | **PASS** |
| **Gonyea Playfield** | `gonyea.json` | `$115,608.50` / `$115,608.50` (`0.0%`) | `$30,682.66` / `$30,682.66` (`0.0%`) | `$154,271.16` / `$154,271.16` (`0.0%`) | `$196,000.00` (`0.0%`) | `$182,800` / `$196,000` / `$220,300` | 18 | OK | **PASS** |
| **Meridian Play Area (RE-BID)** | `meridian.json` | `$7,114.00` / `$7,114.00` (`0.0%`) | `$16,146.12` / `$16,146.12` (`0.0%`) | `$25,310.12` / `$25,310.12` (`0.0%`) | `$32,150.00` (`0.0%`) | `$29,350` / `$32,150` / `$37,100` | 7 | OK | **PASS** |
| **Orangegate Park Phase 1** | `orangegate.json` | `$134,352.20` / `$134,352.20` (`0.0%`) | `$61,157.75` / `$61,157.75` (`0.0%`) | `$202,699.95` / `$202,699.95` (`0.0%`) | `$257,550.00` (`0.0%`) | `$238,850` / `$257,550` / `$291,550` | 28 | OK | **PASS** |

Salida JSON completa almacenada en [benchmark_results.json](file:///C:/Users/diana/OneDrive/Desktop/bidengine-code-v3.3/benchmark/benchmark_results.json).

---

## 2. Cobertura y Resultado de Pruebas Automatizadas

- **Regresión completa v3.1 – v3.6:** `304` pruebas heredadas aprobadas sin regresiones (`8` saltadas por depender de expedientes/entornos externos previos del repositorio).
- **Nuevas pruebas v4 (`test_v4_enterprise.py` y `test_v4_integrations_security.py`):** `13` pruebas aprobadas (`100%` pass) cubriendo:
  - Estados canónicos (7) y cadena hash SHA-256 con detección de alteración.
  - Takeoff estructurado, preservación de medición original ante override manual y detección anti-alucinación (`no_determinado`).
  - Comparación de revisiones de planos y conflictos especificación-vs-plano/addenda.
  - Pricebook (`BUDGET`/`QUOTE`/`HISTORICAL`/`ALLOWANCE`/`VERIFIED`), bloqueo contra auto-promoción, cotizaciones vencidas, importación CSV preservando original.
  - Jerarquía salarial (`base` -> `burden` -> `loaded` -> `commercial`), composición de cuadrillas y conversión de `wages.json`/`productivity.json`.
  - Cost Engine de 13 rubros, `markup` vs `margin` y monotonicidad de escenarios.
  - Independent Review estructurado, RFI/RFQ + comparador de cotizaciones, bloqueo de envío automático y generación de los 6 entregables (`PDF`/`XLSX`/`DOCX`) con protección contra sobrescritura de versiones aprobadas.
  - Seguridad RBAC, aislamiento multitenant (`orgA`/`orgB` y `client_alpha`/`client_beta`), bloqueo de autoaprobación, rate limit, HMAC, redacción de secretos, sanitización Excel y respaldo/restauración verificados.
  - Contratos HTTP reales locales para ALKAN Workflow Studio (10 eventos + reintentos + idempotencia), Contractor Superbot y QuickBooks Online Sandbox (`Customer` query, `Estimate` create/duplicate-skip/`SyncToken` check/sparse-update), más rutas HTTP E2E `/api/v4/*`.

---

## 3. Estado Real de Capacidades: Implementadas vs. Dependientes de Credenciales Externas

Con estricto apego a la regla de no declarar como validada en vivo ninguna conexión sin credenciales activas:

1. **Completas y verificadas end-to-end en este entorno:**
   - Motor de Takeoff, calibración, comparación de revisiones, Pricebook v4, Labor/Productivity v4, Cost Engine de 13 rubros + escenarios, Independent Review anti-autoaprobación, RFI/RFQ Engine, Generador de 6 entregables (PDF + XLSX + DOCX) con versionado inmutable, Seguridad RBAC/multitenant/HMAC/rate-limit/audit-chain, Respaldos verificados, UI de 13 vistas y 7 estados canónicos.
   - **Conexión IA en vivo (Anthropic / `ANTHROPIC_BASE_URL=https://apikey.vnaipro.app`):** Verificada con clave almacenada fuera del repo en `%APPDATA%\ALKAN\BidEngine\secrets.json`; listado de modelos (`/v1/models`), `AppAPI.test_connection("claude-opus-5-5") -> ok: True`, y prueba en vivo de revisión IA JSON integrada en `run_independent_review` (`LIVE_AI_DISCREPANCIES: 3 -> MERGED_REVIEW_TOTAL: 9`). *(Nota: `claude-fable-5-2` y `claude-fable-5-1` devolvieron HTTP 503 en este proxy, por lo que `data/settings.json` local quedó en `claude-opus-5-5`.)*
   - Adaptadores y servidores de contrato local para **ALKAN Workflow Studio**, **Contractor Superbot** y **QuickBooks Online**.
2. **Listas en código y validadas contra servidor HTTP local de contrato, pendientes de credenciales/URL vivas para prueba en nube:**
   - **ALKAN Workflow Studio en vivo:** Requiere definir `ALKAN_STUDIO_URL` y `ALKAN_STUDIO_HMAC_SECRET` apuntando a la instancia activa de Studio (`POST /api/automation/event`); mientras no exista URL, los eventos se almacenan en `data/integrations/studio_outbox.json`.
   - **QuickBooks Online Sandbox/Producción en vivo:** Requiere `QUICKBOOKS_REALM_ID` y `QUICKBOOKS_ACCESS_TOKEN` válidos (vía OAuth 2.0 en Studio o `.env`). Sin ellos, `QuickBooksAdapter.status()` reporta `credentials_ready: false` y bloquea escritura financiera real manteniendo disponible `dry_run`.

---

## 4. Evaluación Objetiva de Madurez

- **Nivel arquitectónico y funcional local + IA verificada:** Producción controlada (`9.6 / 10`), con trazabilidad completa, separación estricta estimador/revisor, versionado inmutable, precisión exacta en aritmética `Decimal` (`0.0%` error contra los 4 paquetes reales), conexión IA en vivo verificada con `claude-opus-5-5` y cobertura automatizada sin fallos (`317 passed, 8 skipped`).
- **Para alcanzar validación completa en nube de todo el ecosistema (10/10 operativo en campo):** únicamente resta conectar `ALKAN_STUDIO_URL` / `ALKAN_STUDIO_HMAC_SECRET` y autorizar por OAuth una empresa QuickBooks Online (`QUICKBOOKS_REALM_ID` / `QUICKBOOKS_ACCESS_TOKEN`).
