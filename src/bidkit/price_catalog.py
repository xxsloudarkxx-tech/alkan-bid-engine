"""Local tabular price evidence and catalog projections; no independent price database."""
from __future__ import annotations

import csv
from io import BytesIO, StringIO
import json
from zipfile import ZipFile, BadZipFile

from openpyxl import load_workbook

from .estimator_v1 import _decimal, _date

PRICE_TYPES = {"HISTORICAL_PRICE": "historical", "CATALOG_REFERENCE": "catalog",
               "PHONE_QUOTE": "phone_confirmed", "FORMAL_QUOTE": "formal_quote", "PURCHASE_INVOICE": "invoice_actual"}
FIELDS = ("product_name", "category", "trade", "brand", "sku", "specification", "unit", "pack_size",
          "supplier", "location", "minimum_quantity", "unit_price", "currency", "discount_percent", "delivery",
          "tax_total", "tax_conditions", "quoted_on", "valid_until", "availability", "kind", "whole_packs")
NUMBERS = ("pack_size", "minimum_quantity", "unit_price", "discount_percent", "delivery", "tax_total")


def table_pages(name, raw):
    """Return textual pages plus original row locations. Formula cells are never evaluated."""
    tables = []
    if name.lower().endswith(".csv"):
        text = raw.decode("utf-8-sig")
        if "\x00" in text: raise ValueError("CSV binario inválido")
        try: dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
        except csv.Error as exc: raise ValueError("CSV inválido; utilice la plantilla con encabezados") from exc
        tables = [("CSV", list(csv.reader(StringIO(text), dialect)))]
    else:
        try:
            with ZipFile(BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 50*1024*1024:
                    raise ValueError("XLSX descomprimido excede 50 MB")
            book = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                for sheet in book:
                    rows = []
                    for index, cells in enumerate(sheet.iter_rows(), 1):
                        if index > 5001 or len(cells) > 50: raise ValueError("Límite: 5000 filas de datos y 50 columnas")
                        if any(c.data_type == "f" for c in cells): raise ValueError("Fórmulas no admitidas en catálogo; exporte valores")
                        rows.append([c.value.isoformat()[:10] if hasattr(c.value, "isoformat") else str(c.value) if c.value is not None else "" for c in cells])
                    tables.append((sheet.title, rows))
            finally: book.close()
        except (BadZipFile, KeyError) as exc: raise ValueError("XLSX inválido") from exc
    pages, records = [], []
    for page, (sheet, rows) in enumerate(tables, 1):
        if not rows: continue
        headers = [str(x).strip().lower() for x in rows[0]]
        if len(headers) > 50 or not all(headers) or len(set(headers)) != len(headers): raise ValueError("Encabezados vacíos o duplicados")
        if not {"product_name", "supplier", "unit", "unit_price"}.issubset(headers):
            raise ValueError("Columnas requeridas: product_name, supplier, unit, unit_price")
        texts = []
        for number, values in enumerate(rows[1:], 2):
            if number > 5001: raise ValueError("Máximo 5000 filas por hoja")
            if not any(str(v).strip() for v in values): continue
            if len(values) != len(headers): raise ValueError(f"Fila {number}: columnas incompatibles")
            if any(str(v).lstrip().startswith(("=", "@", "+")) for v in values): raise ValueError("Contenido de fórmula no admitido")
            record = {h: str(v).strip() for h, v in zip(headers, values)}
            excerpt = json.dumps(record, ensure_ascii=False, sort_keys=True)
            texts.append(excerpt)
            records.append({"page": page, "sheet": sheet, "row": number, "values": record, "excerpt": excerpt})
        pages.append({"page": page, "text": "\n".join(texts), "error": None, "needs_ocr_or_visual_review": False})
    if not records: raise ValueError("Catálogo sin filas de precios")
    return pages, records


def price_record(values):
    row = {key: values.get(key) or None for key in FIELDS}
    for key in NUMBERS:
        if row[key] is not None:
            _decimal(row[key], key)
    if row["pack_size"] is not None and _decimal(row["pack_size"], "pack_size") <= 0: raise ValueError("Presentación debe ser positiva")
    if row["discount_percent"] and _decimal(row["discount_percent"], "discount") > 100: raise ValueError("Descuento inválido")
    for key in ("quoted_on", "valid_until"):
        if row[key] is not None: _date(row[key], key)
    if row["quoted_on"] and row["valid_until"] and row["valid_until"] < row["quoted_on"]: raise ValueError("Vigencia inválida")
    kind = row["kind"] or "CATALOG_REFERENCE"
    row["kind"] = PRICE_TYPES.get(kind, kind)
    if row["kind"] not in PRICE_TYPES.values(): raise ValueError("Clase de precio inválida")
    row["price_type"] = next(k for k,v in PRICE_TYPES.items() if v==row["kind"])
    row["whole_packs"] = str(row["whole_packs"]).lower() in ("true", "1", "yes", "sí")
    row.update(confirmed=False, technical_match=False, availability_confirmed=False, review_status="PENDING_HUMAN_REVIEW")
    return row
