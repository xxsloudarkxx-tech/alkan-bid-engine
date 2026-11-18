"""Real-project precision benchmark for ALKAN Bid Engine v4 against historical reference packages."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile

from bidkit.cost_engine import analyze_package_costs
from bidkit.deliverables_v4 import generate_all_deliverables
from bidkit.package_method import compute, load_package
from bidkit.review_engine import run_independent_review
from bidkit.rfi_rfq import RFIRFQWorkspace

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PACKAGES: tuple[str, ...] = ("wsj.json", "gonyea.json", "meridian.json", "orangegate.json")


def run_benchmark(out_dir: Path | None = None) -> dict:
    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="alkan_bench_") as tmp:
        work = Path(tmp)
        for name in REFERENCE_PACKAGES:
            pkg_path = ROOT / "examples" / "packages" / name
            pkg = load_package(pkg_path)
            ref = compute(pkg)
            v4 = analyze_package_costs(pkg)
            b13 = v4["breakdown_13"]["buckets"]

            ref_price = Decimal(ref["price"])
            v4_price = Decimal(b13["13_final_bid_price"])
            diff = abs(v4_price - ref_price)
            pct_err = float((diff * Decimal("100") / ref_price)) if ref_price > 0 else 0.0

            ref_mat = Decimal(ref["materials"])
            v4_mat = Decimal(b13["1_material_cost"])
            mat_err = float((abs(v4_mat - ref_mat) * Decimal("100") / ref_mat)) if ref_mat > 0 else 0.0

            ref_lab = Decimal(ref["labor"])
            v4_lab = Decimal(b13["2_labor_cost"])
            lab_err = float((abs(v4_lab - ref_lab) * Decimal("100") / ref_lab)) if ref_lab > 0 else 0.0

            ref_dir = Decimal(ref["direct"])
            v4_dir = Decimal(b13["9_direct_cost"])
            dir_err = float((abs(v4_dir - ref_dir) * Decimal("100") / ref_dir)) if ref_dir > 0 else 0.0

            scenarios = {s["scenario"]: Decimal(s["final_bid_price"]) for s in v4["scenarios"]}
            monotonic = scenarios["Aggressive"] <= scenarios["Expected"] <= scenarios["Conservative"]

            review = run_independent_review(pkg, prepared_by="estimator_bench", reviewer_id="reviewer_bench")
            ws = RFIRFQWorkspace(work / f"{name}_rfq.json")
            ws.build_rfqs_from_package(pkg)
            deliv = generate_all_deliverables(
                pkg,
                work / name.replace(".json", ""),
                version=1,
                status="Review Required",
                reviewer="reviewer_bench",
                review_report=review,
                rfq_snapshot=ws.snapshot(),
            )
            all_6_ok = len(deliv["files"]) == 6 and all(
                Path(deliv["files"][k][fmt]["path"]).exists()
                for k in deliv["files"]
                for fmt in ("pdf", "xlsx", "docx")
            )

            passed = (pct_err <= 0.01) and (mat_err <= 0.01) and (lab_err <= 0.01) and (dir_err <= 0.01) and monotonic and all_6_ok
            results.append({
                "package": name,
                "estimate_id": pkg.estimate_id,
                "project": pkg.project.get("short") or pkg.project.get("key"),
                "material_lines": len(pkg.materials),
                "labor_lines": len(pkg.labor),
                "ref_materials": str(ref_mat),
                "v4_materials": str(v4_mat),
                "mat_error_pct": round(mat_err, 6),
                "ref_labor": str(ref_lab),
                "v4_labor": str(v4_lab),
                "lab_error_pct": round(lab_err, 6),
                "ref_direct": str(ref_dir),
                "v4_direct": str(v4_dir),
                "dir_error_pct": round(dir_err, 6),
                "ref_final_price": str(ref_price),
                "v4_final_price": str(v4_price),
                "price_error_pct": round(pct_err, 6),
                "scenarios": {k: str(v) for k, v in scenarios.items()},
                "scenario_monotonic": monotonic,
                "review_discrepancies": review["total_discrepancies"],
                "deliverables_6x3_ok": all_6_ok,
                "status": "PASS" if passed else "FAIL",
            })

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "packages_evaluated": len(results),
        "all_passed": all(r["status"] == "PASS" for r in results),
        "tolerance_pct": 0.01,
        "results": results,
    }
    target_dir = out_dir or (ROOT / "benchmark")
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "benchmark_results.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    res = run_benchmark()
    print(json.dumps(res, indent=2))
    raise SystemExit(0 if res["all_passed"] else 1)
