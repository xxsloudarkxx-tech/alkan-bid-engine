from __future__ import annotations

import argparse
import os
import shutil
import json
from pathlib import Path

import subprocess
import sys

from .audit import audit, validate_source_integrity
from .config import ProjectConfig, find_project_root
from .estimate import estimate_data
from .pdf_reports import bid_review_report, executive_summary, scope_of_work
from .reports import (
    build_data_records,
    validation_report,
    write_compliance_report,
    write_working_registers,
)
from .takeoff import takeoff


def main() -> None:
    parser = argparse.ArgumentParser(prog="bidkit")
    parser.add_argument("command", choices=["audit", "takeoff", "estimate", "build", "validate"])
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args()
    config = ProjectConfig((args.root or find_project_root()).resolve())
    if args.command == "audit":
        result = audit(config)
        print(json.dumps({"documents": len(result["documents"]), "manifest": str(config.audit_dir / "document_inventory.json")}, indent=2))
        return
    if args.command == "takeoff":
        result = takeoff(config)
        print(json.dumps({"records": len(result["records"]), "path": "data/takeoff/takeoff.json"}, indent=2))
        return
    if args.command == "estimate":
        result = estimate_data(config)
        print(json.dumps({"rows": len(result["rows"]), "path": "data/estimate/estimate_inputs.json"}, indent=2))
        return
    if args.command == "build":
        audit(config)
        takeoff(config)
        estimate_data(config)
        build_data_records(config)
        write_working_registers(config)
        write_compliance_report(config)
        config.output_dir.mkdir(parents=True, exist_ok=True)
        executive_summary(config.output_dir / "Executive_Project_Summary.pdf")
        scope_of_work(config.output_dir / "Scope_of_Work_by_Building.pdf")
        bid_review_report(config.output_dir / "Bid_Review_Report.pdf")
        node = os.environ.get("BIDKIT_NODE") or shutil.which("node")
        if not node: raise ValueError("Node no encontrado; instale Node o configure BIDKIT_NODE")
        subprocess.run([str(node), "tools/build_workbooks.mjs"], cwd=config.root, check=True)
        print(json.dumps({"output": str(config.output_dir)}, indent=2))
        return
    if args.command == "validate":
        print(json.dumps(validation_report(config), indent=2))
        return


if __name__ == "__main__":
    main()
