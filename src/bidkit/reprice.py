"""Change prices or suppliers on an estimate and rebuild it.

    python -m bidkit.reprice examples/packages/hc3_ss.json --changes examples/cambios/hc3_ss_cambios.csv --out ENTREGAS/HC3_R1 --build
    python -m bidkit.reprice examples/packages/wsj.json --price-list examples/cambios/lista_precios_demo.csv --best --out ENTREGAS/WSJ_R1
    python -m bidkit.reprice examples/packages/wsj.json --auto-assign --out ENTREGAS/WSJ_PROV
    python -m bidkit.reprice --list-suppliers

Writes <name>_repriced.json (the input is never touched), <name>_cambios.csv and <name>_cambios.json
(line by line: before/after), and with --build the 3 documents plus the purchase list by supplier.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .suppliers import (CHANGE_FIELDS, SupplierError, load_directory, load_price_lists, log_csv, purchasing_csv,
                        read_table, reprice)


def run(input_path: str | Path, out_dir: str | Path, *, changes: str | None = None, price_lists: list[str] | None = None,
        supplier: str | None = None, best: bool = False, assign: bool = False, build: bool = False,
        today: str | None = None, force_pct: bool = False) -> dict:
    input_path, out_dir = Path(input_path), Path(out_dir)
    package = json.loads(input_path.read_text(encoding="utf-8"))
    directory = load_directory()
    rows = load_price_lists(price_lists, directory, today) if price_lists else None
    label = " + ".join(Path(x).name for x in ([changes] if changes else []) + list(price_lists or [])) or "auto-assign"
    res = reprice(package, changes=read_table(changes, CHANGE_FIELDS) if changes else None, price_rows=rows,
                  supplier=supplier, best=best, assign=assign, directory=directory, label=label, today=today, force_pct=force_pct)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem.removesuffix("_repriced")
    new_json = out_dir / f"{stem}_repriced.json"
    if new_json.resolve() == input_path.resolve():
        raise SupplierError("La carpeta de salida sobrescribiría el archivo de entrada; use otra carpeta --out")
    logo = package.get("contractor", {}).get("logo")
    if logo and not Path(logo).is_absolute() and (input_path.parent / logo).exists():
        res["package"]["contractor"]["logo"] = str((input_path.parent / logo).resolve())
    new_json.write_text(json.dumps(res["package"], indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"{stem}_cambios.csv").write_text(log_csv(res["log"]), encoding="utf-8-sig")
    (out_dir / f"{stem}_cambios.json").write_text(json.dumps(
        {"input": str(input_path), "summary": res["summary"], "skipped": res["skipped"], "log": res["log"],
         "comparison": res["comparison"]}, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"{stem}_compras_por_proveedor.csv").write_text(purchasing_csv(res["package"], directory), encoding="utf-8-sig")
    out = {"input": str(input_path), "repriced": str(new_json), **res["summary"], "skipped": res["skipped"]}
    from .criterio import review, write_report
    crit = review(res["package"], today=today)
    write_report(crit, out_dir, stem)
    out["criterio"] = {"verdict": crit["verdict"], **crit["counts"],
                       "altos": [f["message"] for f in crit["findings"] if f["level"] == "ALTO"]}
    if build:
        from .package_build import build as build_package
        m = build_package(new_json, out_dir)
        out["qa"] = m["qa"]["status"]
        out["proposal"] = m["proposal_release"]["label"] or m["proposal_release"]["reason"]
        out["files"] = [f["path"] for f in list(m["files"].values()) + list(m["extras"].values())]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bidkit-reprice", description="Cambiar precios o proveedores de un estimado alkan-package/1")
    ap.add_argument("input", nargs="?", help="Estimado JSON alkan-package/1")
    ap.add_argument("--out", help="Carpeta de salida")
    ap.add_argument("--changes", help="Archivo de cambios (CSV o JSON): por renglón, sección o proveedor")
    ap.add_argument("--price-list", action="append", help="Lista de precios de proveedor (CSV); se puede repetir")
    ap.add_argument("--supplier", help="Con --price-list: usar solo las filas de este proveedor")
    ap.add_argument("--best", action="store_true", help="Con --price-list: tomar la mejor oferta por renglón")
    ap.add_argument("--auto-assign", action="store_true", help="Sugerir proveedor a los renglones que no tienen")
    ap.add_argument("--build", action="store_true", help="Generar los 3 documentos con el resultado")
    ap.add_argument("--force-pct", action="store_true", help="Permitir ajustes porcentuales mayores a ±50%%")
    ap.add_argument("--list-suppliers", action="store_true", help="Mostrar el directorio de proveedores")
    args = ap.parse_args(argv)
    try:
        if args.list_suppliers:
            for s in load_directory():
                print(f"{s['id']:<20} {s['name']:<28} {s.get('categories', '')}")
            return 0
        if not args.input or not args.out:
            ap.error("indique el estimado y --out")
        if not (args.changes or args.price_list or args.auto_assign):
            ap.error("indique --changes, --price-list o --auto-assign")
        out = run(args.input, args.out, changes=args.changes, price_lists=args.price_list, supplier=args.supplier,
                  best=args.best, assign=args.auto_assign, build=args.build, force_pct=args.force_pct)
    except (SupplierError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("qa", "PASS") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
