# BID ENGINE — MAPA DE CARPETAS

Última revisión: 2026-11-06. Organización conservadora: no modificar rutas sin revisar el código.

## 1. Código activo y ejecución
- `src/`: motor Bid Kit, cálculo, precio y reportes.
- `tools/`: scripts de informes, verificaciones, generación de PDF y auditorías.
- `tests/`: pruebas automáticas.
- `run_bidkit.py`, `Start-BidEngine.ps1`, `pyproject.toml`: entradas y dependencias del proyecto.
- `Start-Contrato.ps1` / `Import-Logos.ps1` (`src/bidkit/contrato.py`): contrato con alcance preconfigurado por cliente y pack de logos; ver `docs/CONTRATO_POR_CLIENTE.md`.
- Especialidades (metal, techado, tablaroca, pintura, carpintería/molduras, cubiertas) en el knowledge base; ver `docs/ESPECIALIDADES.md`.
- `templates/`: plantillas. `.git/`: historial y preparación local de Git.

## 2. Insumos documentales y expedientes
- `docs/<nombre del proyecto>/`: planos, especificaciones, adendas y fuentes originales. **Carpeta maestra documental: conservar.**
- `projects/<slug>/`: análisis, mediciones, entradas y datos estructurados de cada proyecto. **No mover.**
- `sources/`: fuentes adicionales; no tocar sin revisión.

## 3. Datos y resultados
- `data/projects/`: cálculos, extracciones, revisiones y QA internos.
- `data/contractors/`: perfiles de empresas y documentos de identidad.
- `data/brand_assets_2026-11-06/`: logos usados en los PDFs.
- `ENTREGAS/`: resultados preparados para revisión o entrega. Algunos incluyen copia de los planos bajo `06_DOCUMENTOS_ORIGINALES/` **para que cada paquete sea autosuficiente**. Son duplicados de bytes respecto a `docs/`, pero no se quitaron, para no romper la integridad de las entregas.
- `ENTREGAS/COST_ANALYSIS_6_PRELIMINARY_2026-11-06/`: seis presupuestos preliminares de metal (S&S y The Fabricator, tres proyectos cada uno), sin autorización de envío.
- `ENTREGAS/COST_ANALYSIS_6_PRELIMINARY_2026-11-06_BRANDED/` (solo si existe): versiones con marca; ver carpeta exacta antes de usar.
- `output/` y `build/`: salidas y compilaciones; revisar antes de borrar.

## 4. Herramientas y temporales: no equivalen a duplicados prescindibles
- `node_modules/`: dependencias JavaScript.
- `tmp/`: herramientas de QA Python y otros archivos temporales.
- `.test-tmp/`, `.pytest_cache/`, `__pycache__/`: archivos técnicos, regenerables, pero **no se borraron** porque la instrucción fue eliminar solo copias repetidas.

## 5. Limpieza exacta realizada
Se auditaron 24,636 archivos, con aproximadamente 2.84 GiB lógicos antes de limpiar.
Se verificó por SHA-256 que todos los archivos de estos ZIP también existían, byte por byte, en las carpetas maestras extraídas:
- `docs/Gonyea Playfield.zip` → enviado a Papelera (167.55 MiB).
- `docs/Orangegate Park Phase 1.zip` → enviado a Papelera (440.60 MiB).
- `docs/REBID - Meridian.zip` → enviado a Papelera (77.31 MiB).
- `docs/W Seattle Junction Landbank Park.zip` → enviado a Papelera (74.62 MiB).

**Total retirado de la carpeta de trabajo: 760.08 MiB (~0.742 GiB).**
Quedan presentes sus 21 archivos fuente extraídos; no se borró nada dentro de esas carpetas.
Los ZIP se enviaron a la Papelera, no se borraron permanentemente. El espacio en el disco puede no liberarse hasta vaciarla; no hacerlo sin nueva autorización.

## 6. Bitácoras de auditoría
- `issues/bidengine_duplicate_audit_2026-11-06.json`: 93 grupos de archivos idénticos >=64 KiB, por hashes, antes de la limpieza.
- `issues/bidengine_archives_extracted_hash_audit_2026-11-06.json`: verificación criptográfica de los ZIP vs carpetas extraídas.
- `issues/bidengine_zip_recycle_log_2026-11-06.json`: archivos trasladados a la Papelera.

**Regla:** no eliminar documentos de `ENTREGAS/`, `docs/`, `src/` ni `projects/` sin revisar sus referencias y propósito. No hacer deduplicación NTFS por enlaces duros en carpeta OneDrive.
