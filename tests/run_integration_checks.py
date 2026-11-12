"""Post-build checks for artifacts; uses generated files and exits nonzero on failure."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook
from pypdf import PdfReader


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "output"
    validation = json.loads((output / "validation_report.json").read_text(encoding="utf-8"))
    assert all(row["status"] == "PASS" for row in validation["source_integrity"]), "Source hash changed"
    assert validation["status"]["BLOQUEANTE"], "Bid must remain blocked without bidder inputs"
    for name in ("Executive_Project_Summary.pdf", "Scope_of_Work_by_Building.pdf", "Bid_Review_Report.pdf"):
        assert len(PdfReader(str(output / name)).pages) >= 1, f"Unreadable PDF: {name}"
    workbook = load_workbook(output / "Detailed_Cost_Estimate.xlsx", data_only=False)
    assert workbook["Assumptions"]["B4"].value == 0.105, "WSST control is incorrect"
    assert workbook["Assumptions"]["B5"].value == 25000, "Allowance control is incorrect"
    assert str(workbook["Estimate Summary"]["B5"].value).startswith("=IF("), "Tax formula is absent"
    takeoff = load_workbook(output / "Material_Takeoff.xlsx", data_only=False)
    assert takeoff["Takeoff"]["D4"].value == 8139.44, "Building 1 plan area trace is incorrect"
    assert takeoff["Takeoff"]["D10"].value == 4998, "Building 2 plan area trace is incorrect"
    print("integration checks: PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"integration checks: FAIL - {error}", file=sys.stderr)
        raise
