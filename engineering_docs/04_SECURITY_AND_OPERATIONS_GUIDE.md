# ALKAN Bid Engine v4 — Reporte de Seguridad, Guía de Instalación y Operación

## 1. Controles de Seguridad Implementados (Etapa B)

| Control | Implementación | Verificación |
| :--- | :--- | :--- |
| **Multitenancy (`org_id` + `client_id`)** | `SecurityContext.has_org()`, aislamiento por directorio `data/orgs/<org_id>/` y validación en `PricebookStore`, `SuperbotBridge`, `QuickBooksAdapter`, `AuditLedger` y `V4API`. | Pruebas automatizadas bloquean lecturas/escrituras entre `orgA`/`orgB` y `client_alpha`/`client_beta`. |
| **RBAC (5 roles)** | `ROLE_PERMISSIONS` (`admin`, `estimator`, `reviewer`, `operator`, `client`) con validación explícita en `require_permission()`. | `client` y `estimator` bloqueados en acciones de aprobación y administración. |
| **Anti-Autoaprobación** | `assert_independent_approver(prepared_by, approver)` rechaza `approver == prepared_by` y bloquea explícitamente actores automáticos (`agent*`, `ai`, `claude`, `auto`). | Validado en `delivery.authorize()`, `review_engine`, `SuperbotBridge`, `QuickBooksAdapter` y `/api/v4/bids/approve`. |
| **Protección de Versiones Aprobadas** | `delivery.authorize()` archiva copia en `approved_versions/vN/`; `deliverables_v4.py` lanza `ImmutableVersionError` (HTTP 409) si se intenta sobrescribir una versión `Approved` o `Exported`. | Validado en pruebas E2E y generación de 6 entregables. |
| **Autenticación y Rate Limiting** | Contraseñas PBKDF2-HMAC-SHA256 (`200,000` iteraciones), tokens Bearer/API-Key con hash SHA-256, firmas HMAC-SHA256 con ventana anti-replay (300s) y `SlidingWindowRateLimiter`. | Probado unitariamente y por HTTP (403/429). |
| **Redacción y Sanitización** | `redact_secrets()` en eventos/logs; `sanitize_spreadsheet_cell()` neutraliza `=`, `+`, `-`, `@` al exportar XLSX/RFQ; `sanitize_filename()` + `_safe_member_path()` contra path traversal. | Verificado en backups ZIP y exportaciones XLSX. |
| **Respaldo y Restauración** | `backup.py` crea ZIP con hashes SHA-256 en `BACKUP_MANIFEST.json`, excluye `secrets.json`/`.key`/`.env` y verifica integridad antes de restaurar. | Probado ciclo completo crear -> verificar -> restaurar. |

---

## 2. Guía Rápida de Instalación, Configuración y Operación

### Requisitos Previos
- Python `>=3.11` con dependencias de `pyproject.toml` (`pypdf`, `reportlab`, `pypdfium2`, `openpyxl`, `Pillow`, `python-docx`, `jsonschema`).
- Instalación editable:
  ```powershell
  python -m pip install -e "c:\Users\diana\OneDrive\Desktop\bidengine-code-v3.3" --no-build-isolation --no-deps
  ```

### Arranque del Sistema
- Interfaz Web Unificada (13 vistas + `/expedientes` + `/herramientas`):
  ```powershell
  .\Start-BidEngine.ps1
  ```
- CLI Paquete de Estimación:
  ```powershell
  python -m bidkit package --input examples/packages/wsj.json --out ENTREGAS/WSJ
  ```
- Benchmark de Precisión:
  ```powershell
  python benchmark/run_benchmark.py
  ```

### Respaldos y Recuperación
- Crear respaldo verificado desde la UI (`Audit Trail -> Crear Respaldo Verificado`) o vía API `POST /api/v4/backup/create`.
- Verificar y restaurar con `bidkit.backup.verify_backup(zip_path)` y `bidkit.backup.restore_backup(zip_path, target_root)`.
