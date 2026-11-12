#!/usr/bin/env python3
"""ALKAN — Metal Fabrications Only renderer (internal Cost Analysis + A-1 proposal).

Computes the envelope with :mod:`bidkit.lumpsum_cost` and, when ``--out-dir`` is
given, renders the two DRAFT documents with :mod:`tools.wsj_cost_analysis` and
:mod:`tools.a1_proposal` into ``data/ss_metal_analysis/<project>/``.

Safety:
* No catalog —> everything is PENDING QUOTE.  No authorization is ever invented.
* ``--params-json`` may carry documented evidence (wage basis, markup basis,
  equipment state, percentages, adjustment) and *only then* an explicit
  ``authorized`` decision supplied by a human.  Without it, `authorized=False`.
* Rendered documents are always **DRAFT — NOT FOR SUBMISSION** and nothing is
  dispatched automatically.

Usage (from repo root):
  python tools/metal_render.py --project orangegate-park-phase-1 \
      --registry <path>/A1_METAL_SUPPLIER_REFERENCE_PRICES.xlsx \
      --out-dir data/ss_metal_analysis            # renders PDFs (draft)
  python tools/metal_render.py --project orangegate-park-phase-1   # dry summary
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bidkit.audit import sha256 as file_sha256
from bidkit.lumpsum_cost import CostParams, analyze_project, load_registry
from bidkit.metal_scope import metal_scope
from bidkit.data_store import read_json
from bidkit.config import ProjectConfig

import a1_proposal
import wsj_cost_analysis


def main() -> int:
    parser = argparse.ArgumentParser(description="Metal Fab Only lump-sum analysis + draft render")
    parser.add_argument("--project", default="orangegate-park-phase-1")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--registry", default=None)
    parser.add_argument("--params-json", default=None,
                        help="Opt-in documented CostParams/authorization (human-provided).")
    parser.add_argument("--out-dir", default=None,
                        help="Render DRAFT PDFs into <root>/<out-dir>/<project>/ (never submits).")
    args = parser.parse_args()

    root = Path(args.root)
    registry = load_registry(args.registry) if args.registry else []

    params = CostParams()
    if args.params_json:
        data = json.loads(Path(args.params_json).read_text(encoding="utf-8"))
        allowed = {k: v for k, v in CostParams().__dict__.items() if not k.startswith("_")}
        params = CostParams(**{k: data[k] for k in allowed if k in data})

    config = ProjectConfig(root, args.project)
    analysis = read_json(config.project_dir / "analysis.json")
    scope = metal_scope(analysis)
    print(f"[{args.project}] metal identified={scope['count_identified']} "
          f"measured={scope['count_measured']} pending={scope['count_pending_measurement']}")

    envelope = analyze_project(root, args.project, registry=registry, params=params)
    t = envelope["totals"]
    print(f"  registry rows     : {len(registry)}")
    print(f"  materials/subtotal: {_f(t['materials_total'])}  equipment={t['equipment_status']}")
    print(f"  direct            : {_f(t['direct_cost'])}  cost-based {_f(t['cost_based_total'])}")
    print(f"  client lump sum   : {_f(t['client_lump_sum'])}  authorized={envelope['authorized']}")
    print(f"  final_releasable  : {envelope['final_releasable']}")
    for b in envelope["blockers"]:
        print("  blocker:", b)

    view = __import__("bidkit.lumpsum_cost", fromlist=["client_view"]).client_view(envelope)
    print(f"  A-1 view status   : {view['status']}")

    if args.out_dir:
        out = (root / args.out_dir / args.project).resolve()
        project_name = config.project_name
        h_in = wsj_cost_analysis.build_internal(envelope, project_name, out)
        print("   ", out / "Cost_Analysis_Internal_Metal_Fab.pdf", h_in[:12])
        h_p = a1_proposal.build_proposal(envelope, project_name, out)
        if h_p:
            print("   ", out / "Bid_Proposal_A1_Metal_Fab.pdf", h_p[:12])
        else:
            print("   commercial proposal: SKIPPED (delivery_state=INTERNAL_BLOCKED)")
    return 0


def _f(v) -> str:
    return "—" if v is None else f"${v:,.2f}"


if __name__ == "__main__":
    raise SystemExit(main())