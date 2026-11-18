# ALKAN Bid Engine v4 — Contratos de Integración del Ecosistema

## 1. Integración con ALKAN Workflow Studio

**Módulo:** `src/bidkit/integrations/workflow_studio.py`  
**Contrato compatible con:** `ALKAN_Studio_0_6_5_QuickBooks_OAuth/app/api/automation/event/route.ts`

### Variables de Entorno Requeridas
- `ALKAN_STUDIO_URL`: URL base del servidor Workflow Studio (ej. `http://localhost:3000`). Si está vacía, los eventos se encolan de forma duradera en `data/integrations/studio_outbox.json` sin simular entrega remota.
- `ALKAN_STUDIO_HMAC_SECRET`: Secreto compartido para firma `X-ALKAN-Signature: sha256=<hex>` sobre `<timestamp>.<body>`.

### Los 10 Eventos de Ciclo de Vida
1. `bid.created`
2. `bid.documents_parsed`
3. `bid.takeoff_completed`
4. `bid.pricing_completed`
5. `bid.review_flagged`
6. `bid.review_approved`
7. `bid.rfq_prepared`
8. `bid.rfi_prepared`
9. `bid.proposal_generated`
10. `bid.exported`

### Estructura de Payload Saliente (`POST {ALKAN_STUDIO_URL}/api/automation/event`)
```json
{
  "type": "bid.review_approved",
  "source": "alkan-bid-engine",
  "entityType": "bid",
  "entityId": "SS-EST-2026-WSJ-01",
  "payload": { "price": "38800" },
  "metadata": {
    "org_id": "default",
    "project_id": "WSJ",
    "version": 1,
    "actor": "reviewer_bob",
    "idempotency_key": "default:WSJ:SS-EST-2026-WSJ-01:bid.review_approved:v1",
    "emitted_at": "2026-11-12T18:50:00+00:00",
    "trace_id": "uuid"
  }
}
```
Incluye reintentos con backoff exponencial (`max_attempts=3`) ante errores transitorios/429/5xx e idempotencia persistente (`studio_idempotency.json`).

---

## 2. Integración con Contractor Superbot

**Módulo:** `src/bidkit/integrations/superbot_bridge.py`  
**Endpoint Bid Engine:** `POST /api/v4/integrations/superbot/intake`

- Recibe oportunidades desde Superbot (`org_id`, `client_id`/`client_slug`, `phone`, `project_title`, `county`, `trade`, `documents[]`, `idempotency_key`).
- Crea expediente aislado bajo `data/orgs/<org_id>/clients/<client_id>/projects/<project_id>/expediente/`.
- Aplica aislamiento estricto por `org_id` y `client_id` (`TenantIsolationError` ante lecturas cruzadas).
- Bloquea notificación automática al cliente (`ready_to_send_client=False`) hasta aprobación humana independiente (`transition_and_approve`).

---

## 3. Integración con QuickBooks Online

**Módulo:** `src/bidkit/integrations/quickbooks_sync.py`  
**Endpoint Bid Engine:** `POST /api/v4/integrations/quickbooks/sync`

### Variables de Entorno Requeridas para Sincronización Viva
- `QUICKBOOKS_ENV`: `sandbox` (default) o `production`
- `QUICKBOOKS_REALM_ID`: Company / Realm ID de Intuit
- `QUICKBOOKS_ACCESS_TOKEN`: Token Bearer OAuth 2.0 activo (obtenible desde el módulo OAuth de ALKAN Studio `/api/quickbooks`)
- Opcionales de referencia OAuth: `QUICKBOOKS_CLIENT_ID`, `QUICKBOOKS_CLIENT_SECRET`, `QUICKBOOKS_REFRESH_TOKEN`

### Controles Obligatorios Antes de Escribir en QuickBooks
1. **Preflight de estado:** Solo permite sincronizar estimados en estado `Approved` o `Exported`.
2. **Compuerta de autorización humana:** Exige `dry_run=false`, `confirm_financial_sync=true` y `authorized_by != prepared_by` (`SelfApprovalError`).
3. **Control de duplicados e idempotencia:** Consulta `select Id, DocNumber, SyncToken from Estimate where DocNumber = '...'` y compara contra `data/integrations/quickbooks_sync_ledger.json`.
4. **Control de versión `SyncToken`:** Rechaza actualización si `expected_sync_token` difiere del valor actual reportado por QuickBooks; ejecuta `sparse=true` cuando actualiza.

> **Estado actual de credenciales en este equipo:** No hay `QUICKBOOKS_REALM_ID` ni `QUICKBOOKS_ACCESS_TOKEN` cargados en el entorno local. El adaptador reporta `credentials_ready: false` y permite ejecución completa en `dry_run: true`, además de haber superado pruebas de contrato HTTP contra servidor Sandbox local simulando la API Intuit v3.
