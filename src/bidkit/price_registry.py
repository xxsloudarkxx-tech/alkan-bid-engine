"""A1 Metal Supplier reference-price registry (importable, read-only pricing source).

This module lets S&S load metal-fabrication material prices from an external
catalog (e.g. ``A1_METAL_SUPPLIER_REFERENCE_PRICES.xlsx``) into a reusable,
class-labelled registry.  It never generates a price by itself:

* A record may carry a price only when it has a verifiable **price_class**,
  a **unit**, a **supplier** and a **source**.
* ``PUBLIC_CATALOG``, ``BUDGET_REFERENCE`` and ``FIRM_SUPPLIER_QUOTE`` are kept
  distinct so a preliminary figure is never presented as a firm quote.
* A line without a usable price stays **PENDING QUOTE** (unit_price ``None``).

It reuses the decimal/date validators from ``estimator_v1`` and the
deterministic fingerprint from ``data_store``.  No document, quote or dossier is
modified by this module.
"""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

from openpyxl import load_workbook
from zipfile import ZipFile, BadZipFile

from .estimator_v1 import _date, _decimal
from .data_store import fingerprint

# Canonical price classes -------------------------------------------------------
PRICE_CLASSES = {
    "PUBLIC_CATALOG": "public_catalog",
    "BUDGET_REFERENCE": "budget_reference",
    "FIRM_SUPPLIER_QUOTE": "firm_quote",
}
# Resolution confidence: higher wins when prices overlap.
_PRIORITY = {"public_catalog": 1, "budget_reference": 2, "firm_quote": 3}

# Expected/tolerant columns -----------------------------------------------------
_COLUMN_MAP = {
    "material_code": ("material_code", "code", "sku", "part"),
    "description": ("description", "item", "material"),
    "specification": ("specification", "spec", "specs"),
    "unit": ("unit", "uom"),
    "supplier": ("supplier", "vendor", "proveedor"),
    "price_class": ("price_class", "class", "price_classification", "tipo"),
    "unit_price": ("unit_price", "price", "unit_cost"),
    "currency": ("currency", "moneda"),
    "quoted_on": ("quoted_on", "date", "fecha", "quoted"),
    "valid_until": ("valid_until", "valid_until_date", "vigencia", "expiry"),
    "source": ("source", "ref", "reference", "reference_uri", "fuente"),
    "page": ("page", "pagina"),
    "notes": ("notes", "notas", "comment"),
}
_REQUIRED = ("material_code", "supplier", "unit", "price_class")


class CatalogError(ValueError):
    """Invalid/missing data in an imported metal price catalog."""


def _normalize_header(text: str) -> str:
    return str(text or "").strip().lower().replace(" ", "_").replace("-", "_")


def _map_header(raw: str) -> str | None:
    key = _normalize_header(raw)
    for canonical, aliases in _COLUMN_MAP.items():
        if key == canonical or key in aliases:
            return canonical
    return None


def _read_rows(path) -> list[tuple[str, list[list]]]:
    """Return [(sheet_name, rows)] from an .xlsx or text (csv/tsv) file."""
    path = Path(path)
    if path.is_dir() or not path.exists():
        raise CatalogError(f"Catálogo no encontrado: {path}")
    if path.suffix.lower() == ".xlsx":
        try:
            with ZipFile(path) as archive:
                if sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024:
                    raise CatalogError("XLSX descomprimido excede 50 MB")
        except BadZipFile as exc:
            raise CatalogError("XLSX inválido") from exc
        try:
            book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
            try:
                pages = []
                for sheet in book:
                    rows = []
                    for index, cells in enumerate(sheet.iter_rows(), 1):
                        if index > 5001 or len(cells) > 60:
                            raise CatalogError("Límite: 5000 filas y 60 columnas por hoja")
                        if any(c.data_type == "f" for c in cells):
                            raise CatalogError("Fórmulas no admitidas en el catálogo; exporte valores")
                        rows.append([str(c.value) if c.value is not None else "" for c in cells])
                    pages.append((sheet.title, rows))
                return pages
            finally:
                book.close()
        except (BadZipFile, KeyError, ValueError) as exc:
            raise CatalogError("XLSX inválido") from exc
    # Text file (csv / tsv / tab)
    raw = path.read_bytes().decode("utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(raw[:8192], delimiters=",\t;")
    except csv.Error as exc:
        raise CatalogError("CSV inválido; utilice la plantilla con encabezados") from exc
    return [("CSV", list(csv.reader(StringIO(raw), dialect)))]


def normalize_record(values: dict) -> dict:
    """Validate one catalog row -> canonical record (no fabrication)."""
    canonical = {field: (values.get(field) or None) for field in _COLUMN_MAP}
    missing = [f for f in _REQUIRED if not canonical[f]]
    if missing:
        raise CatalogError(f"Faltan columnas obligatorias: {', '.join(missing)}")

    price_class = str(canonical["price_class"]).strip().upper().replace("-", "_")
    mapped_class = PRICE_CLASSES.get(price_class)
    if not mapped_class:
        raise CatalogError(f"Clase de precio inválida: {canonical['price_class']!r}")

    unit_price = None
    if canonical["unit_price"] not in (None, "", "-", "--"):
        unit_price = _decimal(canonical["unit_price"], "unit_price")
    currency = (canonical["currency"] or "USD").strip().upper()
    if currency != "USD":
        raise CatalogError("El catálogo A1 solo admite USD; no se convierten monedas")

    quoted_on = _date(canonical["quoted_on"], "quoted_on") if canonical["quoted_on"] else None
    valid_until = _date(canonical["valid_until"], "valid_until") if canonical["valid_until"] else None
    if quoted_on and valid_until and valid_until < quoted_on:
        raise CatalogError("Vigencia inválida: valid_until anterior a quoted_on")

    if mapped_class == "firm_quote":
        missing_firm = [f for f in ("quoted_on", "valid_until", "source") if not canonical[f]]
        if unit_price is None:
            missing_firm.append("unit_price")
        if missing_firm:
            raise CatalogError("FIRM SUPPLIER QUOTE exige quoted_on, valid_until, unit_price y source")
    elif mapped_class in ("public_catalog", "budget_reference"):
        if not canonical["source"]:
            raise CatalogError("PUBLIC CATALOG / BUDGET REFERENCE exigen una fuente (source)")
        if mapped_class == "budget_reference" and not quoted_on:
            # Budget references need at least a date basis; allow quoted_on to come
            # from a YYYY or leave it None only if the source states/implies it.
            pass

    return {
        "material_code": str(canonical["material_code"]).strip(),
        "description": (canonical["description"] or "").strip(),
        "specification": (canonical["specification"] or "").strip(),
        "unit": str(canonical["unit"]).strip(),
        "supplier": str(canonical["supplier"]).strip(),
        "price_class": mapped_class,
        "unit_price": ("%.2f" % unit_price) if unit_price is not None else None,
        "currency": currency,
        "quoted_on": quoted_on.isoformat() if quoted_on else None,
        "valid_until": valid_until.isoformat() if valid_until else None,
        "source": (canonical["source"] or "").strip(),
        "page": (canonical["page"] or "").strip(),
        "notes": (canonical["notes"] or "").strip(),
        "status": "PENDING QUOTE" if unit_price is None else "PRICED",
    }


def import_catalog(path) -> list[dict]:
    """Import an A1 metal supplier reference-prices catalog (xlsx/csv/tsv)."""
    records: list[dict] = []
    for sheet, rows in _read_rows(path):
        if not rows:
            continue
        headers = [_map_header(h) for h in rows[0]]
        if not all(headers):
            raise CatalogError(f"Hoja {sheet!r}: encabezados inválidos o desconocidos")
        if len(set(headers)) != len(headers):
            raise CatalogError(f"Hoja {sheet!r}: columnas duplicadas")
        for number, values in enumerate(rows[1:], 2):
            if not any(str(v).strip() for v in values):
                continue
            if len(values) != len(headers):
                raise CatalogError(f"Hoja {sheet!r}, fila {number}: columnas incompatibles")
            row = dict(zip(headers, values))
            try:
                records.append(normalize_record(row))
            except CatalogError as exc:
                raise CatalogError(f"Hoja {sheet!r}, fila {number}: {exc}") from exc
    if not records:
        raise CatalogError("El catálogo no contiene filas de precios")
    return records


def catalog_hash(records: list[dict]) -> str:
    """Deterministic SHA-256 over a normalized registry (sorted)."""
    records = sorted(records, key=lambda r: (r["material_code"], r["supplier"], r["price_class"]))
    return fingerprint(records)


def resolve(records: list[dict], material_code: str, *, on_date: date | None = None,
            unit: str | None = None) -> dict | None:
    """Best usable price for a material code (class priority; ignores PENDING QUOTE).

    When ``unit`` is given it must match the registry record's unit, so a price
    is never associated with an item of a different unit of measure.
    """
    priced = available_prices(records, material_code, on_date=on_date, unit=unit)
    if not priced:
        return None
    priced.sort(key=lambda r: _PRIORITY[r["price_class"]], reverse=True)
    return priced[0]


def available_prices(records: list[dict], material_code: str, *, on_date: date | None = None,
                     unit: str | None = None) -> list[dict]:
    """All still-valid, PRICED registry records for a material (for low/high range).

    Returns only records with a unit_price and (when given) a matching unit;
    expired records are excluded.  Used to derive an evidence-based budgetary
    range — never any arbitrary number.
    """
    unit = (unit or "").strip().lower()
    usable = []
    for rec in records:
        if rec["material_code"] != material_code:
            continue
        if rec["unit_price"] is None:
            continue
        if unit and rec["unit"].strip().lower() != unit:
            continue
        if rec["valid_until"] and on_date and _date(rec["valid_until"], "valid_until") < on_date:
            continue
        usable.append(rec)
    return usable