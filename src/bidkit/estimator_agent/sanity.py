"""Deterministic sanity checks on a saved package (no API involved).

These are the questions a senior estimator asks before a number leaves the
office.  They never change the package: they return findings that go back to
the agent (so it can fix them) and into the report (so a human sees them).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "per", "each", "of", "to", "in", "x", "ea", "lf", "sf", "galv", "steel"}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 1 and w not in _STOP}


def _dec(value) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _book_match(item: str, unit: str, book: list[dict]) -> dict | None:
    """Closest price-book row with the same unit (word overlap ≥ 60 % of the shorter name)."""
    words, best, score = _words(item), None, 0.0
    if len(words) < 2:
        return None
    for row in book:
        if row.get("unit", "").upper() != unit.upper():
            continue
        other = _words(row.get("item", ""))
        if len(other) < 2:
            continue
        s = len(words & other) / min(len(words), len(other))
        if s > score:
            best, score = row, s
    return best if score >= 0.6 else None


def sanity_checks(package: dict, totals: dict, price_book: list[dict], deviation_pct: int = 35) -> list[dict]:
    """Findings as {level: 'warning'|'info', code, text}."""
    out: list[dict] = []

    def add(level, code, text):
        out.append({"level": level, "code": code, "text": text})

    mats, labor, other = package.get("materials", []), package.get("labor", []), package.get("other", [])
    rates = package.get("labor_rates", {})
    seen: dict[tuple, str] = {}
    budget_value = total_value = Decimal(0)
    for m in mats:
        mid = m.get("id", "?")
        qty, price = _dec(m.get("qty")), _dec(m.get("unit_price"))
        ext = (qty or 0) * (price or 0)
        total_value += ext
        basis = str(m.get("price_basis", "BUDGET")).upper()
        if basis != "QUOTE":
            budget_value += ext
        if price is not None and price == 0:
            add("warning", "zero_price", f"{mid} «{m.get('item', '')[:60]}»: precio unitario en cero.")
        if basis != "QUOTE" and not m.get("price_source"):
            add("warning", "no_price_source", f"{mid}: precio {basis} sin fuente; anote de dónde salió.")
        key = (m.get("item", "").strip().lower(), m.get("spec", "").strip().lower(), m.get("section", ""))
        if key in seen:
            add("warning", "duplicate", f"{mid} repite el renglón {seen[key]} («{m.get('item', '')[:50]}»); confirme que no esté doble.")
        else:
            seen[key] = mid
        ref = _book_match(m.get("item", ""), m.get("unit", ""), price_book)
        ref_price = _dec(ref.get("unit_price")) if ref else None
        if price and ref_price and ref_price > 0:
            dev = (price - ref_price) / ref_price * 100
            if abs(dev) > deviation_pct:
                add("warning", "price_deviation",
                    f"{mid} «{m.get('item', '')[:50]}»: ${price}/{m.get('unit')} está {dev:+.0f}% contra el libro de precios "
                    f"(${ref_price}, {ref.get('price_basis')}, {str(ref.get('source', ''))[:60]}).")
    if total_value > 0 and budget_value / total_value > Decimal("0.5"):
        add("warning", "budget_share", f"{budget_value / total_value * 100:.0f}% del valor de materiales no está cotizado "
                                       "(CATALOG/BUDGET): pida cotizaciones de los renglones grandes antes de enviar.")
    M, L = _dec(totals.get("materials")), _dec(totals.get("labor"))
    if M and L is not None and M > 0:
        ratio = L / M
        if ratio < Decimal("0.15"):
            add("warning", "labor_low", f"Mano de obra = {ratio * 100:.0f}% del material: revise horas de instalación y taller.")
        elif ratio > 4:
            add("warning", "labor_high", f"Mano de obra = {ratio:.1f}× el material: revise horas o material faltante.")
    pw_keys = {k for k, r in rates.items() if r.get("kind") == "prevailing_wage"}
    pw_hours = sum((_dec(l.get("hours")) or 0) for l in labor if l.get("rate") in pw_keys)
    if not pw_keys or pw_hours == 0:
        add("warning", "no_field_labor", "Sin horas de campo a prevailing wage: confirme si es solo suministro o falta la instalación.")
    text_other = " ".join(str(o.get("item", "")) for o in other).lower()
    if pw_keys and not re.search(r"intent|affidavit", text_other):
        add("warning", "no_li_fees", "Obra con prevailing wage sin cuotas de L&I (Intent + Affidavit).")
    if not any(o.get("category") == "Mobilization" for o in other) and "mobiliz" not in text_other:
        add("warning", "no_mobilization", "Sin renglón de movilización.")
    excl = " ".join(package.get("exclusions", [])).lower()
    if "alternate" not in excl:
        add("info", "alternates", "Las exclusiones no mencionan alternates: confirme que el bid form no tenga.")
    if package.get("tax", {}).get("mode") == "excluded_resale" and "tax" not in excl:
        add("info", "tax", "Impuesto excluido por reventa, pero las exclusiones no lo dicen.")
    if not package.get("project", {}).get("bid_date"):
        add("warning", "no_bid_date", "El paquete no trae fecha de entrega del bid.")
    return out
