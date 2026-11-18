"""Supplier logistics for alkan-package/1 estimates: directory, re-pricing and supplier swaps.

What it does (all on the package JSON, before the 3 documents are rendered):

* ``load_directory``      supplier directory (knowledge table ``suppliers``; an edited copy in
                          ``data/knowledge/suppliers.json`` wins over the built-in one).
* ``auto_assign``         suggests a supplier for every material line that has none, from the
                          directory keywords.  Marked ``supplier_source: "auto"`` — a suggestion.
* ``apply_changes``       applies a change file (CSV or JSON): new price, % adjustment and/or new
                          supplier for the lines that match a filter.
* ``apply_price_list``    re-prices lines from supplier price lists (one supplier, or the best offer).
* ``reprice``             runs the steps above, recomputes the estimate and returns before/after.

Rules it never breaks:

* It never invents a price: every new number comes from the change file or a price list.
* A QUOTE needs a supplier and a quote number.  Changing the supplier of a quoted line without a
  new price turns it back into BUDGET (the quote belonged to the previous supplier).
* A filter that matches nothing, an unknown supplier or a unit mismatch stops the run with a
  message — nothing is applied silently or halfway.
* The input file is never overwritten.
"""
from __future__ import annotations

import copy
import csv
import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .estimator_v1 import _cash, _fmt

KB_DIR = Path(__file__).resolve().parent / "estimator_agent" / "knowledge"
NO_SUPPLIER = "(sin proveedor)"
MAX_PCT_CHANGE = Decimal("50")          # mayor diferencia entre proveedores que ha visto Don Miguel
BASES = ("QUOTE", "CATALOG", "BUDGET")
_BASIS_RANK = {"QUOTE": 0, "CATALOG": 1, "BUDGET": 2}
FILTERS = ("id", "section", "item_contains", "current_supplier", "current_basis")
ACTIONS = ("supplier", "unit_price", "pct_change", "price_basis", "quote_ref", "quote_date", "price_source", "note")
CHANGE_FIELDS = FILTERS + ("unit",) + ACTIONS
PRICE_LIST_FIELDS = ("supplier", "match", "unit", "unit_price", "price_basis", "quote_ref", "quote_date",
                     "valid_until", "description")


class SupplierError(ValueError):
    """A change that cannot be applied safely (nothing is written)."""


# ───────────────────────────────────────────────────────────── directory

def load_directory(knowledge_dir: str | Path | None = None) -> list[dict]:
    """Supplier directory; ``data/knowledge/suppliers.json`` (edited in the app) wins over the built-in."""
    candidates = []
    if knowledge_dir:
        candidates.append(Path(knowledge_dir) / "suppliers.json")
    candidates += [Path.cwd() / "data" / "knowledge" / "suppliers.json", KB_DIR / "suppliers.json"]
    for path in candidates:
        if path.exists():
            rows = json.loads(path.read_text(encoding="utf-8"))
            seen = set()
            for r in rows:
                sid = str(r.get("id", "")).strip()
                if not sid or sid in seen:
                    raise SupplierError(f"Directorio de proveedores: id vacío o repetido «{sid}» en {path}")
                seen.add(sid)
            return rows
    return []


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def resolve_supplier(value: str, directory: list[dict]) -> dict:
    """Find a supplier by id or name (case/punctuation-insensitive).  Unknown → error with the options."""
    key = _norm(value)
    if not key:
        raise SupplierError("Proveedor vacío")
    for s in directory:
        if key in (_norm(s["id"]), _norm(s["name"])):
            return s
    close = [s["id"] for s in directory if key in _norm(s["name"]) or _norm(s["name"]) in key]
    hint = f" ¿Quiso decir: {', '.join(close)}?" if close else ""
    raise SupplierError(f"Proveedor desconocido: «{value}».{hint} Agréguelo en Administrador → Proveedores "
                        f"(o data/knowledge/suppliers.json). Disponibles: {', '.join(s['id'] for s in directory)}")


def supplier_name(sid: str, directory: list[dict]) -> str:
    for s in directory:
        if s["id"] == sid:
            return s["name"]
    return sid or NO_SUPPLIER


def _keywords(s: dict) -> list[tuple[str, bool]]:
    """(keyword, prefix?) — a trailing * matches the start of a word («galvaniz*» → galvanizing, galvanized)."""
    out = []
    for raw in str(s.get("keywords", "")).split(","):
        k = _norm(raw)
        if k:
            out.append((k, raw.strip().endswith("*")))
    return out


def suggest_supplier(material: dict, directory: list[dict]) -> str | None:
    """Supplier whose keyword appears first in the item name (items lead with what the thing is); on the
    same position the longer keyword wins.  Whole words only.  The specification column is not used."""
    hay = _norm(material.get("item", ""))
    best = None
    for order, s in enumerate(directory):
        for k, prefix in _keywords(s):
            hit = re.search(r"(?<![a-z0-9])" + re.escape(k) + ("" if prefix else r"(?![a-z0-9])"), hay)
            if hit:
                rank = (hit.start(), -len(k), order)
                if best is None or rank < best[0]:
                    best = (rank, s["id"])
    return best[1] if best else None


def auto_assign(package: dict, directory: list[dict]) -> list[dict]:
    """Fill ``supplier`` on lines that have none.  Prices and price basis are not touched."""
    log = []
    for m in _materials(package):
        if m.get("supplier"):
            continue
        sid = suggest_supplier(m, directory)
        if sid:
            m["supplier"], m["supplier_source"] = sid, "auto"
            log.append({"id": m["id"], "item": m["item"], "change": "proveedor sugerido",
                        "supplier_before": "", "supplier_after": sid})
    return log


# ───────────────────────────────────────────────────────────── helpers

def _materials(package: dict) -> list[dict]:
    """Material lines with stable ids (same default ids the package loader uses)."""
    for i, m in enumerate(package["materials"], 1):
        m.setdefault("id", f"M{i:03d}")
    return package["materials"]


def _dec(value: Any, what: str, *, negative: bool = False) -> Decimal:
    text = str(value).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        n = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise SupplierError(f"{what}: número inválido «{value}»") from exc
    if not n.is_finite() or (n < 0 and not negative):
        raise SupplierError(f"{what}: valor fuera de rango «{value}»")
    return n


def _iso(value: str, what: str) -> str:
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError as exc:
        raise SupplierError(f"{what}: fecha inválida «{value}» (use AAAA-MM-DD)") from exc


def _source_text(basis: str, name: str, ref: str, when: str, note: str) -> str:
    if basis == "QUOTE":
        text = f"{name} quote #{ref}" + (f" {when}" if when else "")
    elif basis == "CATALOG":
        text = f"{name} price list" + (f" {ref}" if ref else "") + (f" {when}" if when else "")
    else:
        text = f"Budget pricing — {name}" + (f" {when}" if when else "")
    return text + (f" — {note}" if note else "")


def read_table(path: str | Path, fields: tuple[str, ...]) -> list[dict]:
    """Rows from a CSV (header row) or a JSON list.  Unknown columns stop the run (typos are not ignored)."""
    path = Path(path)
    if not path.exists():
        raise SupplierError(f"No existe el archivo: {path}")
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(rows, dict):
            rows = rows.get("changes") or rows.get("rows") or []
    else:
        text = path.read_text(encoding="utf-8-sig")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    clean = []
    for n, row in enumerate(rows, 1):
        item = {str(k).strip().lower(): ("" if v is None else str(v).strip()) for k, v in row.items() if k is not None}
        unknown = sorted(k for k in item if k not in fields)
        if unknown:
            raise SupplierError(f"{path.name} fila {n}: columna desconocida {unknown}. Columnas válidas: {', '.join(fields)}")
        if any(item.values()):
            clean.append(item)
    if not clean:
        raise SupplierError(f"{path.name}: sin filas")
    return clean


# ───────────────────────────────────────────────────────────── change file

def _match(m: dict, ch: dict) -> bool:
    ids = [x.strip().upper() for x in re.split(r"[;|]", ch.get("id", "")) if x.strip()]
    if ids and ids != ["*"] and m["id"].upper() not in ids:
        return False
    if ch.get("section") and _norm(ch["section"]) not in _norm(m.get("section", "")):
        return False
    if ch.get("item_contains") and _norm(ch["item_contains"]) not in _norm(m.get("item", "") + " " + m.get("spec", "")):
        return False
    if ch.get("current_supplier"):
        want = _norm(ch["current_supplier"])
        have = _norm(m.get("supplier", ""))
        if want in ("none", "ninguno", "sin proveedor"):
            if have:
                return False
        elif have != want:
            return False
    if ch.get("current_basis") and m.get("price_basis", "BUDGET").upper() != ch["current_basis"].upper():
        return False
    return True


def apply_changes(package: dict, changes: list[dict], directory: list[dict], *,
                  max_pct: Decimal | None = MAX_PCT_CHANGE) -> list[dict]:
    """Apply change rows in order.  Returns one log entry per line touched.  Raises before any partial write
    is visible to the caller only if the caller works on a copy (``reprice`` does)."""
    log = []
    mats = _materials(package)
    for n, ch in enumerate(changes, 1):
        where = f"Cambio {n}"
        if not any(ch.get(f) for f in FILTERS):
            raise SupplierError(f"{where}: falta el filtro (id, section, item_contains, current_supplier o current_basis; id=* para todas)")
        if not any(ch.get(a) for a in ACTIONS if a != "note"):
            raise SupplierError(f"{where}: no indica qué cambiar (supplier, unit_price, pct_change, price_basis...)")
        if ch.get("unit_price") and ch.get("pct_change"):
            raise SupplierError(f"{where}: use unit_price o pct_change, no los dos")
        hit = [m for m in mats if _match(m, ch)]
        if not hit:
            raise SupplierError(f"{where}: ningún renglón coincide con el filtro "
                                f"{ {f: ch[f] for f in FILTERS if ch.get(f)} }")
        if ch.get("unit_price") and len(hit) > 1:
            raise SupplierError(f"{where}: unit_price se aplicaría a {len(hit)} renglones ({', '.join(m['id'] for m in hit[:8])}...). "
                                f"Un precio unitario va a un solo renglón; use el id.")
        new_sup = resolve_supplier(ch["supplier"], directory) if ch.get("supplier") else None
        basis = ch.get("price_basis", "").upper()
        if basis and basis not in BASES:
            raise SupplierError(f"{where}: price_basis debe ser {', '.join(BASES)}")
        if ch.get("unit_price") and not basis:
            raise SupplierError(f"{where}: un precio nuevo necesita price_basis (QUOTE, CATALOG o BUDGET)")
        when = _iso(ch["quote_date"], f"{where} quote_date") if ch.get("quote_date") else ""
        for m in hit:
            before = {"unit_price": str(m["unit_price"]), "price_basis": m.get("price_basis", "BUDGET").upper(),
                      "supplier": m.get("supplier", "")}
            if ch.get("unit") and ch["unit"].upper() != str(m["unit"]).upper():
                raise SupplierError(f"{where}: unidad «{ch['unit']}» no coincide con {m['id']} ({m['unit']}). "
                                    f"Convierta el precio a {m['unit']} antes de aplicarlo.")
            notes = []
            sid = new_sup["id"] if new_sup else m.get("supplier", "")
            supplier_changed = bool(new_sup) and new_sup["id"] != m.get("supplier", "")
            if new_sup:
                m["supplier"] = new_sup["id"]
                m.pop("supplier_source", None)
            if ch.get("unit_price"):
                m["unit_price"] = str(_dec(ch["unit_price"], f"{where} unit_price"))
            elif ch.get("pct_change"):
                pct = _dec(ch["pct_change"], f"{where} pct_change", negative=True)
                if pct <= -100:
                    raise SupplierError(f"{where}: pct_change no puede ser -100% o menos")
                if max_pct is not None and abs(pct) > max_pct:
                    raise SupplierError(f"{where}: pct_change {pct}% pasa del tope de ±{max_pct}% "
                                        f"(¿error de dedo?). Si es correcto, repita con --force-pct.")
                m["unit_price"] = str(_cash(Decimal(str(m["unit_price"])) * (1 + pct / 100)))
            price_changed = str(m["unit_price"]) != before["unit_price"]
            new_basis = basis or before["price_basis"]
            if not basis and before["price_basis"] == "QUOTE" and (price_changed or supplier_changed):
                new_basis = "BUDGET"
                notes.append("dejó de ser QUOTE: " + ("precio ajustado por porcentaje" if price_changed
                                                       else "la cotización era del proveedor anterior"))
            if new_basis == "QUOTE":
                ref = ch.get("quote_ref") or ("" if (price_changed or supplier_changed) else m.get("quote_ref", ""))
                if not sid:
                    raise SupplierError(f"{where}: {m['id']} QUOTE necesita proveedor")
                if not ref:
                    raise SupplierError(f"{where}: {m['id']} QUOTE necesita quote_ref (número de cotización)")
                m["quote_ref"] = ref
                if when:
                    m["quote_date"] = when
            elif price_changed or supplier_changed or basis:
                m.pop("quote_ref", None)
                m.pop("quote_date", None)
                if ch.get("quote_ref") and new_basis == "CATALOG":
                    m["quote_ref"] = ch["quote_ref"]
                if when and new_basis == "CATALOG":
                    m["quote_date"] = when
            m["price_basis"] = new_basis
            if ch.get("price_source"):
                m["price_source"] = ch["price_source"]
            elif sid and (price_changed or supplier_changed or basis):
                m["price_source"] = _source_text(new_basis, supplier_name(sid, directory), m.get("quote_ref", ""),
                                                 m.get("quote_date", when), ch.get("note", ""))
            log.append(_log_entry(m, before, f"cambio {n}", "; ".join(notes)))
    return log


def _log_entry(m: dict, before: dict, origin: str, note: str = "") -> dict:
    qty = Decimal(str(m["qty"]))
    ext_b, ext_a = _cash(qty * Decimal(before["unit_price"])), _cash(qty * Decimal(str(m["unit_price"])))
    return {"id": m["id"], "item": m["item"], "qty": str(m["qty"]), "unit": m["unit"], "origin": origin,
            "supplier_before": before["supplier"], "supplier_after": m.get("supplier", ""),
            "basis_before": before["price_basis"], "basis_after": m["price_basis"],
            "unit_price_before": _fmt(Decimal(before["unit_price"])), "unit_price_after": _fmt(Decimal(str(m["unit_price"]))),
            "extended_before": _fmt(ext_b), "extended_after": _fmt(ext_a), "delta": _fmt(ext_a - ext_b), "note": note}


# ───────────────────────────────────────────────────────────── price lists

def load_price_lists(paths: list[str | Path], directory: list[dict], today: str | None = None) -> list[dict]:
    """Supplier price-list rows.  ``match`` = words that must ALL appear in the line's item + spec."""
    today = today or date.today().isoformat()
    rows = []
    for path in paths:
        for n, r in enumerate(read_table(path, PRICE_LIST_FIELDS), 1):
            where = f"{Path(path).name} fila {n}"
            for f in ("supplier", "match", "unit", "unit_price"):
                if not r.get(f):
                    raise SupplierError(f"{where}: falta «{f}»")
            basis = (r.get("price_basis") or "CATALOG").upper()
            if basis not in BASES:
                raise SupplierError(f"{where}: price_basis debe ser {', '.join(BASES)}")
            if basis == "QUOTE" and not r.get("quote_ref"):
                raise SupplierError(f"{where}: QUOTE necesita quote_ref")
            valid = _iso(r["valid_until"], f"{where} valid_until") if r.get("valid_until") else ""
            rows.append({"supplier": resolve_supplier(r["supplier"], directory)["id"],
                         "words": [w for w in _norm(r["match"]).split() if w], "match": r["match"],
                         "unit": r["unit"].upper(), "unit_price": _dec(r["unit_price"], f"{where} unit_price"),
                         "price_basis": basis, "quote_ref": r.get("quote_ref", ""),
                         "quote_date": _iso(r["quote_date"], f"{where} quote_date") if r.get("quote_date") else "",
                         "valid_until": valid, "expired": bool(valid and valid < today), "where": where})
    return rows


def offers(material: dict, price_rows: list[dict]) -> list[dict]:
    """Price-list rows that fit a line: every match word present and the same unit.  Expired rows excluded."""
    hay = " " + _norm(material.get("item", "") + " " + material.get("spec", "")) + " "
    out = [r for r in price_rows if not r["expired"] and r["unit"] == str(material["unit"]).upper()
           and r["words"] and all((" " + w) in hay for w in r["words"])]
    return sorted(out, key=lambda r: (_BASIS_RANK[r["price_basis"]], r["unit_price"]))


def compare_offers(package: dict, price_rows: list[dict], directory: list[dict]) -> list[dict]:
    """For every line with at least one offer: current price and each supplier's offer (cheapest first)."""
    table = []
    for m in _materials(package):
        found = offers(m, price_rows)
        if not found:
            continue
        table.append({"id": m["id"], "item": m["item"], "qty": str(m["qty"]), "unit": m["unit"],
                      "current_supplier": m.get("supplier", ""), "current_basis": m.get("price_basis", "BUDGET"),
                      "current_unit_price": _fmt(Decimal(str(m["unit_price"]))),
                      "offers": [{"supplier": r["supplier"], "supplier_name": supplier_name(r["supplier"], directory),
                                  "unit_price": _fmt(r["unit_price"]), "price_basis": r["price_basis"],
                                  "quote_ref": r["quote_ref"], "valid_until": r["valid_until"]} for r in found]})
    return table


def apply_price_list(package: dict, price_rows: list[dict], directory: list[dict], *, supplier: str | None = None,
                     best: bool = False) -> tuple[list[dict], list[str]]:
    """Re-price from price lists.  ``supplier``: only that supplier's rows.  ``best``: for each line the best
    offer (QUOTE before CATALOG before BUDGET, then lowest price).  Returns (log, skipped messages)."""
    if bool(supplier) == bool(best):
        raise SupplierError("Con listas de precios indique un proveedor (--supplier) o la mejor oferta (--best), uno de los dos")
    sid = resolve_supplier(supplier, directory)["id"] if supplier else None
    log, skipped = [], []
    for m in _materials(package):
        found = [r for r in offers(m, price_rows) if not sid or r["supplier"] == sid]
        if not found:
            continue
        top = found[0]
        same = [r for r in found if r["supplier"] == top["supplier"] and r is not top
                and (r["price_basis"], r["unit_price"]) != (top["price_basis"], top["unit_price"])]
        if same:
            skipped.append(f"{m['id']}: {len(same) + 1} filas de {top['supplier']} coinciden con precios distintos "
                           f"({top['where']}, {same[0]['where']}) — precise «match» o aplique por id en el archivo de cambios")
            continue
        before = {"unit_price": str(m["unit_price"]), "price_basis": m.get("price_basis", "BUDGET").upper(),
                  "supplier": m.get("supplier", "")}
        m["supplier"], m["unit_price"], m["price_basis"] = top["supplier"], str(top["unit_price"]), top["price_basis"]
        m.pop("supplier_source", None)
        for k in ("quote_ref", "quote_date"):
            if top[k]:
                m[k] = top[k]
            else:
                m.pop(k, None)
        m["price_source"] = _source_text(top["price_basis"], supplier_name(top["supplier"], directory),
                                         top["quote_ref"], top["quote_date"], "")
        if (before["unit_price"], before["price_basis"], before["supplier"]) != (str(m["unit_price"]), m["price_basis"], m["supplier"]):
            log.append(_log_entry(m, before, f"lista de precios ({top['where']})"))
    for r in price_rows:
        if r["expired"] and (not sid or r["supplier"] == sid):
            skipped.append(f"{r['where']}: precio vencido el {r['valid_until']} — no se usó")
    return log, skipped


# ───────────────────────────────────────────────────────────── purchasing

def purchasing(package: dict, directory: list[dict]) -> list[dict]:
    """Material lines grouped by supplier (what to request / buy from whom)."""
    groups: dict[str, dict] = {}
    for m in _materials(package):
        sid = m.get("supplier", "")
        g = groups.setdefault(sid, {"supplier": sid, "name": supplier_name(sid, directory), "lines": [],
                                    "total": Decimal(0), "unquoted": 0})
        ext = _cash(Decimal(str(m["qty"])) * Decimal(str(m["unit_price"])))
        g["lines"].append({"id": m["id"], "section": m["section"], "item": m["item"], "spec": m.get("spec", ""),
                           "qty": str(m["qty"]), "unit": m["unit"], "unit_price": _fmt(Decimal(str(m["unit_price"]))),
                           "extended": _fmt(ext), "price_basis": m.get("price_basis", "BUDGET").upper(),
                           "quote_ref": m.get("quote_ref", ""), "assigned": m.get("supplier_source", "manual" if sid else "")})
        g["total"] += ext
        g["unquoted"] += m.get("price_basis", "BUDGET").upper() != "QUOTE"
    out = sorted(groups.values(), key=lambda g: (g["supplier"] == "", -g["total"]))
    for g in out:
        g["total"] = _fmt(_cash(g["total"]))
    return out


def purchasing_csv(package: dict, directory: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["supplier_id", "supplier", "contact", "phone", "email", "line_id", "section", "item", "specification",
                "qty", "unit", "unit_price", "extended", "price_basis", "quote_ref", "assigned"])
    info = {s["id"]: s for s in directory}
    for g in purchasing(package, directory):
        s = info.get(g["supplier"], {})
        for l in g["lines"]:
            w.writerow([g["supplier"], g["name"], s.get("contact", ""), s.get("phone", ""), s.get("email", ""), l["id"],
                        l["section"], l["item"], l["spec"], l["qty"], l["unit"], l["unit_price"], l["extended"],
                        l["price_basis"], l["quote_ref"], l["assigned"]])
        w.writerow([g["supplier"], g["name"], "", "", "", "", "", "SUBTOTAL", "", "", "", "", g["total"], "", "", ""])
    return buf.getvalue()


# ───────────────────────────────────────────────────────────── orchestration

def _totals(package: dict) -> dict:
    from .package_method import compute, package_from_dict
    r = compute(package_from_dict(package))
    return {"materials": r["materials"], "direct": r["direct"], "price": r["price"], "status": r["status"],
            "unquoted": len(r["validation"]["unquoted_lines"]), "lines": len(package["materials"])}


def reprice(package: dict, *, changes: list[dict] | None = None, price_rows: list[dict] | None = None,
            supplier: str | None = None, best: bool = False, assign: bool = False,
            directory: list[dict] | None = None, label: str = "", today: str | None = None,
            force_pct: bool = False) -> dict:
    """Work on a copy: auto-assign → change file → price lists → recompute.  Returns the new package,
    the line-by-line log and the before/after totals.  The original dict is not modified."""
    directory = load_directory() if directory is None else directory
    before = _totals(package)
    new = copy.deepcopy(package)
    log, skipped = [], []
    if assign:
        log += auto_assign(new, directory)
    if changes:
        log += apply_changes(new, changes, directory, max_pct=None if force_pct else MAX_PCT_CHANGE)
    if price_rows is not None and (supplier or best):
        l2, skipped = apply_price_list(new, price_rows, directory, supplier=supplier, best=best)
        log += l2
    after = _totals(new)                      # raises if the result is not a valid package
    summary = {"date": today or date.today().isoformat(), "label": label,
               "lines_changed": len({e["id"] for e in log}),
               "materials_before": _fmt(before["materials"]), "materials_after": _fmt(after["materials"]),
               "materials_delta": _fmt(after["materials"] - before["materials"]),
               "direct_before": _fmt(before["direct"]), "direct_after": _fmt(after["direct"]),
               "sell_price_before": _fmt(before["price"]), "sell_price_after": _fmt(after["price"]),
               "sell_price_delta": _fmt(after["price"] - before["price"]),
               "unquoted_before": before["unquoted"], "unquoted_after": after["unquoted"],
               "status_before": before["status"], "status_after": after["status"]}
    if log:
        new.setdefault("revision_log", []).append({k: summary[k] for k in (
            "date", "label", "lines_changed", "sell_price_before", "sell_price_after")})
    return {"package": new, "log": log, "skipped": skipped, "summary": summary,
            "comparison": compare_offers(new, price_rows, directory) if price_rows else []}


def log_csv(log: list[dict]) -> str:
    cols = ["id", "item", "qty", "unit", "origin", "supplier_before", "supplier_after", "basis_before", "basis_after",
            "unit_price_before", "unit_price_after", "extended_before", "extended_after", "delta", "note"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    for e in log:
        w.writerow({c: e.get(c, "") for c in cols})
    return buf.getvalue()
