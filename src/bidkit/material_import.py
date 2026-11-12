"""Minimal adapter to incorporate project material lists into dossier lines.

Reads the ``ALKAN_listas_materiales_Seattle_Tacoma`` CSV sheets (or the mirror
.XLSX) that live under ``data/Imports/materiales`` and lets an estimator review a
read-only difference before appending documentary quantity lines to an open
dossier.

Security / rules:
* It never creates quotes, suppliers or prices.
* Documentary quantities are mapped to ``PENDING_VERIFICATION`` (pending human
  review); they are never treated as field-verified measurements.
* ``PENDIENTE DE MEDICIÓN`` keeps ``quantity = None`` (pending measurement).
* It does not edit, overwrite or delete existing lines (approved records are
  never touched). Appending new lines invalidates a stale approval exactly as the
  rest of the engine does; ``apply`` refuses that unless ``confirm=True``.
* It keeps full traceability to the source file/row via ``material_import_sig``
  and ``material_import_source`` and skips already-imported rows.
"""
from __future__ import annotations

import csv
from datetime import date
from hashlib import sha1
from io import BytesIO, StringIO
from pathlib import Path
from uuid import uuid4

from openpyxl import load_workbook
from zipfile import BadZipFile, ZipFile

from .data_store import fingerprint
from .intelligence_store import RevisionConflict

HDR = ("id", "package", "material", "specification", "quantity", "unit",
       "state", "evidence", "warning", "source_url")

_DOCUMENTARY = {"CANTIDAD DOCUMENTAL", "CALCULO DEL ANALISIS INTERNO",
                "CANTIDAD DOCUMENTAL", "CÁLCULO DEL ANÁLISIS INTERNO"}


def _norm(value):
    m = {"Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U", "Ñ": "N"}
    return "".join(m.get(ch, ch) for ch in str(value or "").strip().upper())


def _state(row):
    s = _norm(row.get("state"))
    if "PENDIENTE" in s or "MEDICION" in s:
        return None  # quantity must remain None (pending measurement)
    return "PENDING_VERIFICATION"


def _quantity(row, state):
    q = str(row.get("quantity") or "").strip()
    if state is None or not q:
        return None
    return q


def _rows(tables):
    """Yield normalized rows from a list of (sheet, rows) tables."""
    for sheet, rows in tables:
        if not rows:
            continue
        headers = [_norm(h) for h in rows[0]]
        def get(row, *names):
            for n in names:
                if n in row:
                    return row[n]
            return ""
        for number, values in enumerate(rows[1:], 2):
            if not any(str(v).strip() for v in values):
                continue
            cell = {h: (str(v).strip() if v is not None else "") for h, v in zip(headers, values)}
            yield {
                "source_sheet": sheet, "source_row": number,
                "id": get(cell, "ID"), "package": get(cell, "OFICIO/PAQUETE", "OFICIO / PAQUETE"),
                "material": get(cell, "MATERIAL O RECURSO"), "specification": get(cell, "ESPECIFICACION/PRESENTACION", "ESPECIFICACIÓN / PRESENTACIÓN"),
                "quantity": get(cell, "CANTIDAD"), "unit": get(cell, "UNIDAD"),
                "state": get(cell, "ESTADO DE CANTIDAD"), "evidence": get(cell, "EVIDENCIA/PLANO", "EVIDENCIA / PLANO"),
                "warning": get(cell, "PENDIENTE/ADVERTENCIA", "PENDIENTE / ADVERTENCIA"), "source_url": get(cell, "FUENTE (URL)", "FUENTE (URL)"),
            }


def read_material_rows(path: Path):
    """Parse a material-list CSV or XLSX into normalized rows (no dossier change)."""
    path = Path(path)
    suffix = path.suffix.lower()
    tables = []
    if suffix == ".csv":
        text = path.read_text(encoding="utf-8-sig")
        if "\x00" in text:
            raise ValueError("CSV contiene datos binarios")
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
            tables = [("CSV", list(csv.reader(StringIO(text), dialect)))]
        except csv.Error as exc:
            raise ValueError("CSV inválido") from exc
    elif suffix in (".xlsx", ".xlsm"):
        raw = path.read_bytes()
        try:
            with ZipFile(BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024:
                    raise ValueError("XLSX excede 50 MB")
            book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                for sheet in book:
                    rows = []
                    for index, cells in enumerate(sheet.iter_rows(), 1):
                        if any(c.data_type == "f" for c in cells):
                            raise ValueError("Fórmulas no admitidas; exporte valores")
                        rows.append([c.value.isoformat()[:10] if hasattr(c.value, "isoformat") else (str(c.value) if c.value is not None else "") for c in cells])
                    tables.append((sheet.title, rows))
            finally:
                book.close()
        except (BadZipFile, KeyError) as exc:
            raise ValueError("XLSX inválido") from exc
    else:
        raise ValueError("Formato admitido: CSV o XLSX")
    return list(_rows(tables))


def _sig(source_file, source_row, import_id):
    return sha1((f"{source_file}|{source_row}|{import_id}").encode("utf-8")).hexdigest()


def preview(service, project_id, source_file, rows):
    """Read-only difference review: what would be added vs already present."""
    row = service.store.load(project_id)
    state = row["state"]
    existing = {l.get("material_import_sig") for l in state["lines"] if l.get("material_import_sig")}
    by_id = {l.get("import_id") for l in state["lines"] if l.get("import_id")}
    proposed, duplicate = [], []
    for r in rows:
        sig = _sig(source_file, r["source_row"], r["id"])
        if sig in existing or (r["id"] and r["id"] in by_id):
            duplicate.append(r)
            continue
        normalized = {
            "source_sheet": r["source_sheet"], "source_row": r["source_row"], "import_id": r["id"],
            "package": r["package"], "description": r["material"], "specification": r["specification"],
            "unit": r["unit"], "state": _state(r), "quantity": _quantity(r, _state(r)),
            "evidence": r["evidence"], "warning": r["warning"], "source_url": r["source_url"],
        }
        proposed.append(normalized)
    return {
        "project_id": project_id, "source_file": source_file,
        "total_rows": len(rows), "already_present": len(duplicate),
        "would_add": len(proposed),
        "warnings": [p["warning"] for p in proposed if p["warning"] and p["warning"] != "PENDIENTE"],
        "requires_confirmation": bool(state.get("current_approval")),
        "has_current_approval": bool(state.get("current_approval")),
        "proposed": proposed,
    }


def apply(service, project_id, revision, actor, source_file, rows, confirm=False, request_id=None):
    """Append documentary lines to the dossier after an explicit preview review."""
    if not actor:
        raise ValueError("Indique responsable de la revisión")
    normalized_rows = []
    for r in rows:
        st = _state(r); q = _quantity(r, st)
        if not r.get("material"):
            raise ValueError(f"Fila {r['source_row']}: falta 'Material o recurso'")
        if r.get("unit") and r.get("unit") == "()":
            r = {**r, "unit": ""}
        if not r["unit"]:
            raise ValueError(f"Fila {r['source_row']}: falta unidad")
        if q is not None:
            try:
                _num(q)
            except ValueError:
                raise ValueError(f"Fila {r['source_row']}: cantidad inválida '{q}'")
        normalized_rows.append({"source_sheet": r["source_sheet"], "source_row": r["source_row"],
                                "import_id": r["id"], "package": r["package"], "description": r["material"],
                                "specification": r["specification"], "unit": r["unit"], "state": st,
                                "quantity": q, "evidence": r["evidence"], "warning": r["warning"],
                                "source_url": r["source_url"]})
    with service.store.locked(project_id):
        previous = service.store.load(project_id)
        if previous["revision"] != revision:
            raise RevisionConflict("El expediente cambió; recargue y revise diferencias de nuevo")
        state = previous["state"]
        if state.get("current_approval") and confirm is not True:
            raise ValueError("El expediente tiene una aprobación registrada. Indique confirmación explícita para incorporar datos nuevos.")
        existing = {l.get("material_import_sig") for l in state["lines"] if l.get("material_import_sig")}
        by_id = {l.get("import_id") for l in state["lines"] if l.get("import_id")}
        added = 0
        for r in normalized_rows:
            sig = _sig(source_file, r["source_row"], r["import_id"])
            if sig in existing or (r["import_id"] and r["import_id"] in by_id):
                continue
            state["lines"].append({
                "line_id": str(uuid4()), "project_id": project_id, "import_id": r["import_id"],
                "description": r["description"], "trade": state["project"].get("trade", ""),
                "category": "material", "quantity": r["quantity"], "unit": r["unit"],
                "quantity_status": r["state"] or "PENDING_VERIFICATION", "specification": r["specification"],
                "scope_key": _slug(r["package"]), "evidence_reference": None, "source_document": r["evidence"],
                "source_page": None, "revision_id": str(uuid4()), "reviewed_by": None, "reviewed_at": None,
                "active": True, "selected_quote_id": None,
                "material_import_sig": sig, "material_import_source": {
                    "file": source_file, "sheet": r["source_sheet"], "row": r["source_row"],
                    "import_id": r["import_id"], "url": r["source_url"], "warning": r["warning"],
                    "imported_on": date.today().isoformat(), "imported_by": actor},
            })
            added += 1
        if added == 0:
            return {"project_id": project_id, "revision": revision, "added": 0, "skipped_already_present": len(normalized_rows), "duplicate_apply": True}
        state["result"] = service.evaluate(state)
        state["result"]["changes_since_previous"] = None
        appended = service.store.append(project_id, state, previous["revision"], actor, "MATERIAL_IMPORT:" + source_file)
        return {"project_id": project_id, "revision": appended["revision"], "added": added,
                "skipped_already_present": len(normalized_rows) - added, "row": appended}


MATERIAL_DIR = Path("data") / "Imports" / "materiales"
KNOWN_FILES = (
    "01_Seattle_WSJ_Metal.csv", "02_Seattle_WSJ_Paisaje.csv", "03_Seattle_Meridian.csv",
    "04_Tacoma_Gonyea.csv", "05_Tacoma_Orangegate.csv",
)


def load_material_rows(root, file):
    """Load a whitelisted material list by basename (read-only; never edits originals)."""
    base = (Path(root) / MATERIAL_DIR).resolve()
    target = (base / file).resolve()
    if file not in KNOWN_FILES or not target.is_relative_to(base):
        raise ValueError("Archivo de materiales no admitido")
    return file, read_material_rows(target)


def _slug(package):
    import re
    return re.sub(r"[^A-Za-z0-9_]+", "_", (package or "").strip().upper())[:40]


def _num(value):
    from decimal import Decimal
    n = Decimal(str(value))
    if not n.is_finite() or n < 0:
        raise ValueError("rango")
    return n