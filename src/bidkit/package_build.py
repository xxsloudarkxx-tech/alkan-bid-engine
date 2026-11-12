"""Build + QA for the ALKAN three-document estimate package.

Usage:
    python -m bidkit.package_build examples/packages/wsj.json --out ENTREGAS/WSJ
    python -m bidkit.package_build examples/packages/*.json --out ENTREGAS/PAQUETES
    bidkit package --input examples/packages/wsj.json --out ENTREGAS/WSJ
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from .estimator_v1 import _cash, _fmt
from .package_method import compute, load_package, result_json
from .package_render import money, render_all


def _text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _keywords(path: Path) -> dict:
    meta = PdfReader(str(path)).metadata or {}
    kw = meta.get("/Keywords", "") or ""
    return dict(part.split("=", 1) for part in kw.split(";") if "=" in part)


def qa(pkg, r: dict, files: dict) -> dict:
    """Independent cross-checks: arithmetic, totals and the same price in every document."""
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})

    # 1. Line arithmetic recomputed from raw inputs (not from the model's cached values).
    bad = [m.id for m in pkg.materials if _cash(m.qty * m.unit_price) != m.extended]
    check("material lines: qty × unit price = extended", not bad, ", ".join(bad))
    msum = _cash(sum((m.qty * m.unit_price for m in pkg.materials), Decimal(0)))
    check("material sum = materials total", msum == r["materials"], f"{msum} vs {r['materials']}")
    secsum = _cash(sum(r["sections"].values(), Decimal(0)))
    check("section subtotals add to materials total", secsum == r["materials"], f"{secsum}")
    lsum = _cash(sum((_cash(l.hours * pkg.rates[l.rate_key].loaded) for l in pkg.labor), Decimal(0)))
    # printed line costs are rounded per line; the total must equal the sum of what is printed
    check("labor hours × loaded rate = labor total", lsum == r["labor"], f"{lsum} vs {r['labor']}")
    check("direct = materials + labor + other", r["direct"] == _cash(r["materials"] + r["labor"] + r["other"]))
    check("total = direct + contingency + overhead + profit",
          r["total"] == _cash(r["direct"] + r["contingency"] + r["overhead"] + r["profit"]))
    check("sell price within rounding step of computed total", abs(r["price"] - r["total"]) <= pkg.rounding / 2,
          f"{r['price']} vs {r['total']}")
    # 2. Documents agree with the model and with each other.
    price_txt = money(r["price"], False)
    for kind, path in files.items():
        kw = _keywords(path)
        check(f"{kind}: embedded price = model price", kw.get("price") == _fmt(r["price"]), kw.get("price", "missing"))
        txt = _text(path)
        if kind in ("cost_analysis", "proposal"):
            check(f"{kind}: sell price printed ({price_txt})", price_txt in txt.replace(".00", ""))
    if "material_list" in files:
        txt = _text(files["material_list"])
        check("material list: total materials printed", money(r["materials"]) in txt, money(r["materials"]))
        printed = [Decimal(x.replace(",", "")) for x in re.findall(r"\$([\d,]+\.\d\d)", txt)]
        check("material list: every extended amount printed", all(m.extended in printed for m in pkg.materials))
    status = "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL"
    return {"status": status, "checks": checks}


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(input_path: str | Path, out_dir: str | Path) -> dict:
    pkg = load_package(input_path)
    r = compute(pkg)
    out_dir = Path(out_dir)
    rendered = render_all(pkg, r, out_dir)
    report = qa(pkg, r, rendered["files"])
    manifest = {
        "input": str(input_path),
        "computation": result_json(pkg, r),
        "proposal_release": rendered["release"],
        "qa": report,
        "files": {k: {"path": str(v), "sha256": _sha(v)} for k, v in rendered["files"].items()},
    }
    (out_dir / f"{pkg.project['key']}_package_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bidkit-package", description="Paquete ALKAN de 3 documentos (costos, materiales, propuesta)")
    ap.add_argument("inputs", nargs="+", help="Archivo(s) JSON alkan-package/1")
    ap.add_argument("--out", required=True, help="Carpeta de salida; con varios inputs se crea una subcarpeta por proyecto")
    args = ap.parse_args(argv)
    inputs = []
    for pattern in args.inputs:  # PowerShell does not expand wildcards for native programs
        matches = sorted(glob.glob(pattern)) if any(ch in pattern for ch in "*?[") else [pattern]
        if not matches:
            ap.error(f"Sin archivos para: {pattern}")
        inputs += matches
    rc = 0
    for inp in inputs:
        pkg_key = json.loads(Path(inp).read_text(encoding="utf-8"))["project"]["key"]
        out = Path(args.out) / pkg_key if len(inputs) > 1 else Path(args.out)
        try:
            m = build(inp, out)
        except ValueError as exc:
            print(json.dumps({"input": inp, "status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
            rc = 1
            continue
        t = m["computation"]["totals"]
        print(json.dumps({"project": pkg_key, "status": m["computation"]["status"], "sell_price": t["price"],
                          "direct_cost": t["direct"], "qa": m["qa"]["status"],
                          "proposal": m["proposal_release"]["label"] or m["proposal_release"]["reason"],
                          "files": [f["path"] for f in m["files"].values()]}, ensure_ascii=False, indent=2))
        if m["qa"]["status"] != "PASS":
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
