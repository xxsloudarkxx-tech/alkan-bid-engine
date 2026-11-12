#!/usr/bin/env python3
"""ALKAN — Metal Fabrications Only lump-sum analysis (S&S / A-1).

Computes the internal seven-section cost-analysis envelope for a project using
``metal_scope`` + ``price_registry`` + ``lumpsum_cost``.

Safety:
* DRY by default: nothing is written unless ``--out-dir`` is given (writes a
  JSON manifest under ``data/ss_metal_analysis/<project>/``).
* It never reads/stores firm prices from the historical West Seattle project,
  and it never authorizes a final proposal (``authorized`` stays False here).
* Items without a usable price -> PENDING QUOTE; without measurement ->
  PENDING MEASUREMENT.

Usage (from repo root):
  python -m tools.metal_analysis --project orangegate-park-phase-1
  python tools/metal_analysis.py --project orangegate-park-phase-1 \
      --registry <path>/A1_METAL_SUPPLIER_REFERENCE_PRICES.xlsx
Add ``--out-dir data/ss_metal_analysis`` to persist the JSON envelope (dry-off).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bidkit.data_store import write_json
from bidkit.lumpsum_cost import (CostParams, analyze_project, client_view,
                                 load_registry)
from bidkit.metal_scope import metal_scope


def main() -> int:
    parser = argparse.ArgumentParser(description="Metal Fabrications Only lump-sum analysis")
    parser.add_argument("--project", default="orangegate-park-phase-1")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--registry", default=None,
                        help="A1_METAL_SUPPLIER_REFERENCE_PRICES.xlsx|csv|tsv (optional)")
    parser.add_argument("--out-dir", default=None,
                        help="If set, writes data/ss_metal_analysis/<project>/envelope.json (not dry)")
    args = parser.parse_args()

    root = Path(args.root)
    registry = load_registry(args.registry) if args.registry else []

    params = CostParams()  # never authorizes

    # Show the metal scope even before any pricing (scope is read-only).
    from bidkit.data_store import read_json
    from bidkit.config import ProjectConfig
    config = ProjectConfig(root, args.project)
    analysis = read_json(config.project_dir / "analysis.json")
    scope = metal_scope(analysis)
    print(f"[{args.project}] metal identified={scope['count_identified']} "
          f"measured={scope['count_measured']} pending={scope['count_pending_measurement']}")

    envelope = analyze_project(root, args.project, registry=registry, params=params)
    t = envelope["totals"]
    print(f"  registry rows : {len(registry)}")
    print(f"  materials     : {_f(t['materials_total'])}")
    print(f"  direct        : {_f(t['direct_cost'])}")
    print(f"  cost-based    : {_f(t['cost_based_total'])}")
    print(f"  client lump   : {_f(t['client_lump_sum'])}   authorized={envelope['authorized']}")
    print(f"  final_releasable: {envelope['final_releasable']}")
    for b in envelope["blockers"]:
        print("  blocker:", b)
    view = client_view(envelope)
    print("  A-1 view status:", view["status"])

    if args.out_dir:
        out = (root / args.out_dir / args.project).resolve()
        write_json(out / "envelope.json", _plain(envelope))
        print("WROTE", out / "envelope.json")
    return 0


def _f(v) -> str:
    return "—" if v is None else f"${v:,.2f}"


def _plain(o):
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_plain(v) for v in o]
    return str(o)


if __name__ == "__main__":
    raise SystemExit(main())