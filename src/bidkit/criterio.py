"""Criterio de Don Miguel: el vigilante que revisa un estimado antes de que salga.

No cambia precios.  Lee un estimado ``alkan-package/1`` y aplica las reglas que Don Miguel usa de memoria
(entrevista nov 2026); cada hallazgo sale con nivel ALTO / AVISO / INFO / PENDIENTE y con la accion a tomar.

    ALTO       no debe salir asi
    AVISO      revisar antes de mandar
    INFO       dato util, no detiene
    PENDIENTE  la regla existe pero falta un numero de Don Miguel (``criterio.json`` lo tiene en null)

Veredicto: DETENER (hay ALTO), REVISAR (hay AVISO) o LISTO.

Los parametros viven en ``estimator_agent/knowledge/criterio.json``; ``data/knowledge/criterio.json`` gana si existe.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from .package_method import compute, package_from_dict

KB_DIR = Path(__file__).resolve().parent / "estimator_agent" / "knowledge"
LEVELS = ("ALTO", "AVISO", "INFO", "PENDIENTE")
OWNER_DIRECT = ("prime_to_owner", "gc_to_owner", "direct_homeowner")


def load_criterio(knowledge_dir: str | Path | None = None) -> dict:
    candidates = []
    if knowledge_dir:
        candidates.append(Path(knowledge_dir) / "criterio.json")
    candidates += [Path.cwd() / "data" / "knowledge" / "criterio.json", KB_DIR / "criterio.json"]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("criterio.json no encontrado")


def _norm(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower())


def _money(x: Decimal) -> str:
    return f"${x:,.0f}"


def _days(d: str, today: date) -> int | None:
    try:
        return (today - date.fromisoformat(str(d)[:10])).days
    except ValueError:
        return None


def familia(material: Any, crit: dict) -> str | None:
    g = material.get if isinstance(material, dict) else (lambda k, d="": getattr(material, k, d))
    text = _norm(f"{g('section', '')} {g('item', '')} {g('spec', '')}")
    for fam, words in crit.get("familias", {}).items():
        if any(re.search(rf"\b{re.escape(_norm(w))}", text) for w in words):
            return fam
    return None


def review(package: dict, crit: dict | None = None, today: str | None = None) -> dict:
    """Aplica el criterio.  ``package`` es el dict del estimado; no se modifica."""
    crit = crit or load_criterio()
    now = date.fromisoformat(today) if today else date.today()
    pkg = package_from_dict(package)
    r = compute(pkg)
    out: list[dict] = []

    def add(level: str, rule: str, msg: str, action: str = "", lines: list[str] | None = None) -> None:
        out.append({"level": level, "rule": rule, "message": msg, "action": action, "lines": lines or []})

    mats = pkg.materials
    M, D, price = r["materials"], r["direct"], r["price"]
    mult = (price / D) if D else Decimal(1)
    authorized = package.get("release", {}).get("authorized") is True

    # 1. Cotizacion real de proveedor ------------------------------------------------------------
    cq = crit["cotizacion"]
    unq = [m for m in mats if m.price_basis != "QUOTE"]
    unq_amt = sum((m.extended for m in unq), Decimal(0))
    unq_pct = (unq_amt / M * 100) if M else Decimal(0)
    swing = unq_amt * Decimal(str(cq["diferencia_max_pct"])) / 100 * mult
    exposure = {"unquoted_lines": len(unq), "unquoted_amount": str(unq_amt), "unquoted_pct": str(round(unq_pct, 1)),
                "price_low": str(round(price - swing, 0)), "price_high": str(round(price + swing, 0))}
    if unq:
        level = "ALTO" if (authorized and unq_pct >= Decimal(str(cq["detener_si_sin_cotizar_pct"]))) else "AVISO"
        add(level, "cotizacion",
            f"{len(unq)} de {len(mats)} renglones ({_money(unq_amt)}, {unq_pct:.0f}% del material) llevan precio generico, "
            f"sin cotizacion de proveedor. Con la diferencia de hasta {cq['diferencia_max_pct']}% que se ha visto, "
            f"el precio de venta podria moverse entre {_money(price - swing)} y {_money(price + swing)}.",
            "Pedir cotizacion con la lista de materiales y cargarla con Start-Reprice.",
            [m.id for m in sorted(unq, key=lambda m: -m.extended)])

    # 2. Vigencia: los precios cambian cada 15 dias o cada mes -----------------------------------
    vg = crit["vigencia"]
    old, aging = [], []
    for m in mats:
        if m.price_basis == "QUOTE" and m.quote_date:
            age = _days(m.quote_date, now)
            if age is None:
                continue
            (old if age > vg["vencido_dias"] else aging if age > vg["aviso_dias"] else []).append(f"{m.id} ({age} d)")
    if old:
        add("ALTO", "vigencia", f"Cotizaciones con mas de {vg['vencido_dias']} dias: {', '.join(old)}.",
            "Pedir precio actualizado al proveedor.", [x.split()[0] for x in old])
    if aging:
        add("AVISO", "vigencia", f"Cotizaciones con mas de {vg['aviso_dias']} dias: {', '.join(aging)}.",
            "Confirmar con el proveedor que el precio sigue vigente.", [x.split()[0] for x in aging])
    est_age = _days(package.get("date", ""), now)
    if unq and est_age is not None and est_age > vg["vencido_dias"]:
        add("AVISO", "vigencia", f"El estimado tiene {est_age} dias y aun lleva precios genericos.",
            "Revalidar precios antes de reutilizarlo.")

    # 3. Proveedor base por tipo de material -----------------------------------------------------
    base = crit.get("proveedores_base", {})
    by_fam: dict[str, list[str]] = {}
    for m in mats:
        if not m.supplier:
            fam = familia(m, crit)
            if fam and base.get(fam):
                by_fam.setdefault(fam, []).append(m.id)
    for fam, ids in by_fam.items():
        add("INFO", "proveedor_base", f"{len(ids)} renglones de {fam} sin proveedor. Proveedor base: {' o '.join(base[fam])}.",
            "Asignar proveedor y pedir cotizacion.", ids)

    # 4. Overhead y profit -----------------------------------------------------------------------
    mk = crit["markup"]
    rel = package.get("relationship", "")
    target = mk.get("objetivo_por_relacion", {}).get(rel) or mk["objetivo_pct"]
    op = pkg.overhead_pct + pkg.profit_pct
    tol = Decimal(str(mk["tolerancia_pct"]))
    if pkg.profit_pct <= 0:
        add("ALTO", "markup", "El estimado no lleva profit.", "Agregar profit antes de mandar.")
    elif op < Decimal(str(target)) - tol:
        add("AVISO", "markup", f"Overhead + profit = {op}% (objetivo ~{target}%). El margen queda en {_money(r['gross_margin'])}.",
            "Subir el markup o dejar por escrito por que se baja.")
    elif op > Decimal(str(target)) + tol:
        add("INFO", "markup", f"Overhead + profit = {op}%, arriba del ~{target}% habitual.")
    if mk.get("objetivo_por_relacion", {}).get(rel) is None:
        add("PENDIENTE", "relacion", f"Falta el markup de Don Miguel para «{rel}» (directo con dueno vs. para GC); se uso {mk['objetivo_pct']}%.")
    if rel in OWNER_DIRECT and package.get("tax", {}).get("mode", "excluded_resale") == "excluded_resale":
        add("AVISO", "relacion", "Trabajo directo con el dueno pero el impuesto esta como reventa a GC (excluded_resale).",
            "Revisar tax.mode: al dueno se le cobra sales tax.")

    # 5. Condado ---------------------------------------------------------------------------------
    cd = crit["condados"]
    county = str(package.get("project", {}).get("county", "")).strip()
    factors = cd.get("factor", {})
    if county not in factors:
        add("AVISO", "condado", f"Condado «{county}» no esta en la tabla del criterio.", "Agregarlo en criterio.json.")
    elif factors[county] is None:
        add("PENDIENTE", "condado", f"Obra en {county}: {cd['base']} es mas caro, pero falta el factor de {county} contra {cd['base']}.",
            "Preguntar a Don Miguel el porcentaje y capturarlo en criterio.json.")
    public = "prevailing" in _norm(package.get("project", {}).get("wage_basis", "")) or package.get("project", {}).get("public_works") is True
    rates = package.get("labor_rates", {})
    for key, rt in rates.items():
        if rt.get("kind") == "prevailing_wage" and county and _norm(county) not in _norm(rt.get("source", "")):
            add("ALTO", "condado", f"La tarifa {key} es prevailing wage pero su fuente no menciona {county}: «{rt.get('source', '')}».",
                f"Tomar la tarifa de L&I para {county}.")

    # 6. Public works / prevailing wage ----------------------------------------------------------
    labor = pkg.labor
    hours = sum((l.hours for l in labor), Decimal(0))
    if public:
        pw = [k for k, rt in rates.items() if rt.get("kind") == "prevailing_wage"]
        non = sum((l.hours for l in labor if pkg.rates[l.rate_key].kind != "prevailing_wage"), Decimal(0))
        if not pw:
            add("ALTO", "prevailing_wage", "Obra publica sin ninguna tarifa prevailing wage.", "Cargar tarifas de L&I.")
        elif non:
            keys = sorted({l.rate_key for l in labor if pkg.rates[l.rate_key].kind != "prevailing_wage"})
            add("INFO", "prevailing_wage", f"{non} de {hours} horas van a tarifa propia ({', '.join(keys)}), no prevailing.",
                "Confirmar que es trabajo de taller u oficina y no trabajo en obra.")

    # 7. Calidad de material permitida -----------------------------------------------------------
    nospec = [m.id for m in mats if not str(m.spec).strip()]
    if nospec:
        add("AVISO", "calidad", f"{len(nospec)} renglones sin especificacion: no se puede saber que calidad de material se permite.",
            "Capturar la spec (grado, calibre, acabado) para que el proveedor cotice lo mismo.", nospec)

    # 8. Distancia / viaje -----------------------------------------------------------------------
    if not any(o.category == "Mobilization" for o in pkg.other):
        add("AVISO", "distancia", "No hay renglon de movilizacion / viaje a la obra.", "Agregar movilizacion segun la distancia.")
    if not package.get("project", {}).get("distance_miles"):
        add("INFO", "distancia", "No esta capturada la distancia del taller a la obra (project.distance_miles).")

    # 9. Horas: la senal de riesgo ---------------------------------------------------------------
    hr = crit["horas"]
    L = r["labor"]
    share = (L / D * 100) if D else Decimal(0)
    if share < Decimal(str(hr["mano_obra_min_pct_directo"])):
        add("AVISO", "horas", f"La mano de obra es solo {share:.0f}% del costo directo ({hours} h). Horas cortas es el error que mas mueve el precio.",
            "Revisar horas renglon por renglon con el contratista.")
    conf = package.get("release", {}).get("hours_confirmed")
    if not (isinstance(conf, dict) and conf.get("by") and conf.get("date")):
        add("ALTO" if authorized else "AVISO", "horas",
            f"El contratista no ha confirmado las {hours} horas.",
            "Confirmar horas con el contratista y registrar release.hours_confirmed = {by, date}.")
    rounds = len(package.get("revision_log", []))
    if rounds > hr["vueltas_max"]:
        add("AVISO", "horas", f"El estimado lleva {rounds} revisiones (maximo {hr['vueltas_max']} vueltas con el GC).",
            "Cerrar numero con el contratista antes de otra vuelta.")

    counts = {lv: sum(1 for f in out if f["level"] == lv) for lv in LEVELS}
    verdict = "DETENER" if counts["ALTO"] else "REVISAR" if counts["AVISO"] else "LISTO"
    out.sort(key=lambda f: LEVELS.index(f["level"]))
    return {"estimate_id": package.get("estimate_id", ""), "date": now.isoformat(), "verdict": verdict, "counts": counts,
            "price": str(price), "direct": str(D), "materials": str(M), "labor": str(L), "hours": str(hours),
            "overhead_profit_pct": str(op), "exposure": exposure, "findings": out}


def report_md(res: dict) -> str:
    e = res["exposure"]
    lines = [f"# Criterio de Don Miguel — {res['estimate_id']}", "",
             f"**Veredicto: {res['verdict']}**  ({res['counts']['ALTO']} altos, {res['counts']['AVISO']} avisos, "
             f"{res['counts']['PENDIENTE']} pendientes de Don Miguel)", "",
             f"- Precio de venta: ${Decimal(res['price']):,.2f}",
             f"- Costo directo: ${Decimal(res['direct']):,.2f} (material ${Decimal(res['materials']):,.2f}, "
             f"mano de obra ${Decimal(res['labor']):,.2f}, {res['hours']} h)",
             f"- Overhead + profit: {res['overhead_profit_pct']}%",
             f"- Material sin cotizar: {e['unquoted_lines']} renglones, ${Decimal(e['unquoted_amount']):,.2f} ({e['unquoted_pct']}%)",
             f"- Rango de precio si las cotizaciones se mueven: ${Decimal(e['price_low']):,.0f} a ${Decimal(e['price_high']):,.0f}", ""]
    for lv in LEVELS:
        rows = [f for f in res["findings"] if f["level"] == lv]
        if not rows:
            continue
        lines += [f"## {lv}", ""]
        for f in rows:
            lines.append(f"- **{f['rule']}**: {f['message']}" + (f" → {f['action']}" if f["action"] else "")
                         + (f" [{', '.join(f['lines'][:12])}{'…' if len(f['lines']) > 12 else ''}]" if f["lines"] else ""))
        lines.append("")
    lines.append(f"Revisado {res['date']}. Este reporte es interno: no va al cliente.")
    return "\n".join(lines) + "\n"


def write_report(res: dict, out_dir: str | Path, stem: str) -> list[str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    a, b = out_dir / f"{stem}_criterio.md", out_dir / f"{stem}_criterio.json"
    a.write_text(report_md(res), encoding="utf-8")
    b.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    return [str(a), str(b)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bidkit-criterio", description="Revisar un estimado con el criterio de Don Miguel")
    ap.add_argument("input", help="Estimado JSON alkan-package/1")
    ap.add_argument("--out", help="Carpeta donde guardar el reporte (.md y .json)")
    ap.add_argument("--today", help="Fecha de revision AAAA-MM-DD (por omision, hoy)")
    args = ap.parse_args(argv)
    try:
        package = json.loads(Path(args.input).read_text(encoding="utf-8"))
        res = review(package, today=args.today)
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    if args.out:
        write_report(res, args.out, Path(args.input).stem.removesuffix("_repriced"))
    print(report_md(res))
    return 1 if res["verdict"] == "DETENER" else 0


if __name__ == "__main__":
    raise SystemExit(main())
