"""Phase C engineering QA helpers for the frozen Phase B Orangegate result."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bidkit.audit import sha256
from bidkit.data_store import write_json
from bidkit.data_store import read_json
from bidkit.config import ProjectConfig
from bidkit.audit import audit, normalize

QA = ROOT / "data/qa/phase-c"
PROJECT = "orangegate-park-phase-1"
SNAPSHOT = ROOT / "data/snapshots/phase_b_state_20261026T154754.manifest.json"

MISSING = {
    "P-Q-01": "Poligonos de desmonte; superficies existentes/propuestas; estratos y balance corte/relleno; limites de suelos inadecuados y disposicion.",
    "P-Q-02": "Areas por tipo de pavimento; espesores y capas; limites base/alternativos; secciones y unidades de compra.",
    "P-Q-03": "Trazados y longitudes por diametro/profundidad; perfiles y conexiones; inventario de estructuras fuera de CB21-38 sin repetir esas 18.",
    "P-Q-04": "Longitudes y diametros de agua potable; acometidas, medidores, valvulas y backflow; separar red de riego.",
    "P-Q-05": "Perfiles e invertidas; longitudes de gravedad/impulsion; especificacion de bombeo; dimensiones del sistema septico y zanjas.",
    "P-Q-06": "Circuitos, diametros y recorridos; cabezales, valvulas y controladores; conexiones y cableado; separar de agua potable.",
    "P-Q-07": "Paquete estructural y MEP; cimentaciones; limites suministro Romtec/instalador/otros y carta de alcance del proveedor (2B es preliminar).",
    "P-Q-08": "Geometria, acero, cubierta y cimentaciones de cada shelter; comparar adicion/sustraccion del alternativo 1 con la base.",
    "P-Q-09": "Lista y geometria del equipo de juego; cimentaciones de fabricante; estructura y dimensiones del boardwalk; separar superficies ya tabuladas.",
    "P-Q-10": "Conteos de luminarias, postes, RRFB y gabinetes; longitudes de conduit/cable y circuitos; limites contratista/propietario.",
    "P-Q-11": "Longitudes/areas TESC; fases, duracion y mantenimiento; accesos, trafico, protecciones y restauracion por area.",
    "P-Q-12": "Areas/espesores de losas y pads; dimensiones de zapatas; despiece de acero; evitar repetir cimentaciones de otras partidas.",
    "P-Q-13": "Poligonos separados de alternativos 2 y 3; medir cerca de 84th St E del alternativo 4; conciliar 494/335 LF sin sumar o asignar automaticamente.",
}


def source(document, page, anchor=None, sheet=None):
    inventory = read_json(ROOT / f"data/projects/{PROJECT}/audit/document_inventory.json")
    doc = next(d for d in inventory["documents"] if d["name"] == document)
    cache = read_json(ROOT / f"data/projects/{PROJECT}/extractions/{doc['sha256']}.json")
    text = normalize(cache["pages"][page-1]["text"])
    start = text.casefold().find((anchor or text[:15]).casefold())
    if start < 0:
        raise ValueError((document, page, anchor))
    ref = {"document": document, "page": page, "sha256": doc["sha256"], "excerpt": text[start:start+650]}
    if sheet:
        ref["sheet"] = sheet
    return ref


def correct_inputs():
    path = ROOT / f"projects/{PROJECT}/analysis.json"
    data = read_json(path)
    rows = {r["id"]: r for r in data["quantities"]}
    tech = "SPECS TECH SPECS - Cover and Pages 1-412.pdf"
    for key in ("LS-B-09", "LS-B-10"):
        rows[key]["estimate_included"] = False
        rows[key]["basis"] = "Supply only including signs, posts, hardware and delivery; Owner installs; no foundations. Installation cost row excluded, material retained. LS01 and 01 23 00."
        ref = source(tech, 10, "E. Additive Alternate 05")
        rows[key]["sources"] = [rows[key]["sources"][0], ref]
    for key in ("LS-A-15", "LS-B-08"):
        rows[key]["pricing_scope"] = "unallocated"
        rows[key]["basis"] = "Schedule quantity verified; base/Alternate 4 split NOT measured. LS05 excludes all split rail adjacent to 84th St E from base. Do not assign the whole schedule quantity to base or alternate without spatial reconciliation."
        visual = source("Addendum_4.pdf", 73, "LS05")
        review = ROOT / f"data/projects/{PROJECT}/review/Addendum_4-73.png"
        visual.update(evidence_type="visual_transcription", review_image=review.relative_to(ROOT).as_posix(), review_image_sha256=sha256(review), region="LS05 top left fence scope note", region_bbox=[0.20, 0.12, 0.40, 0.22], sheet="LS05", transcription="ALL SPLIT RAIL FENCE ADJACENT TO 84TH ST E, TYP: ADD ALT 4: SPLIT RAIL FENCE")
        rows[key]["sources"] = [rows[key]["sources"][0], source(tech, 10, "D. Additive Alternate 04"), visual]
    for key, text in (("LP-A-11", 'A | 2911 SF | MULCH AND SOIL PREP ONLY | 4 inch DEPTH'),
                      ("LP-B-13", 'B | 6397 SF | MULCH ONLY | MIN 4 inch DEPTH'),
                      ("LP-C-02", 'A | 2911 SF | MULCH AND SOIL PREP ONLY | 4 inch DEPTH'),
                      ("LP-C-03", 'B | 6397 SF | MULCH ONLY | MIN 4 inch DEPTH')):
        rows[key]["sources"][0]["transcription"] = text
    rows["P-Q-03"]["sources"] = [source("Addendum_1.pdf", 27, "SECTION 33 40 00")]
    rows["P-Q-04"]["sources"] = [source(tech, 394, "SECTION 33 10 00")]
    rows["P-Q-09"]["sources"] = [source(tech, 128, "SECTION 11 68 13"), source("Addendum_4.pdf", 15, "BOARDWALK")]
    rows["P-Q-10"]["sources"] = [source("Addendum_2.pdf", 33, "The Contractor shall furnish")]
    rows["P-Q-12"]["sources"] = [source("Addendum_1.pdf", 9, "SECTION 03 30 00"), source(tech, 115, "SECTION 03 20 00"), source("Addendum_4.pdf", 16, "3.04 CAST-IN-PLACE CONCRETE")]
    for key, missing in MISSING.items():
        rows[key]["basis"] = "PENDING; document establishes scope, no measurement: " + missing
    for material in data["materials"]:
        key = material.get("quantity_id", "")
        if key in MISSING or key in ("LS-A-15", "LS-B-08", "LS-B-09", "LS-B-10", "LP-A-11", "LP-B-13"):
            material["sources"] = rows[key]["sources"]
        anchors = {"LS-A-07": "2.09 PICNIC TABLE A", "LS-A-08": "2.10 ACCESSIBLE PICNIC TABLE A", "LS-A-09": "2.11 PICNIC TABLE B", "LS-A-10": "2.12 ACCESSIBLE PICNIC TABLE B", "LS-A-11": "2.13 BENCH", "LS-A-12": "REMOVABLE BOLLARD", "LS-A-13": "Include additional sleeves"}
        if key in anchors:
            material["sources"] = [rows[key]["sources"][0], source("Addendum_4.pdf", 10, anchors[key])]
    risk = {"id": "R-12", "severity": "HIGH", "risk": "Split rail schedules 494/335 LF were assigned to base without reconciling Alternate 4. Quantities retained; both moved to unallocated pending spatial measurement.", "action": "Measure 84th St E segments on latest LS05 and reconcile Schedule A/B plus 01 23 00; do not add to base automatically.", "sources": [source(tech, 10, "D. Additive Alternate 04"), rows["LS-A-15"]["sources"][-1]]}
    data["risks"] = [r for r in data["risks"] if r["id"] != "R-12"] + [risk]
    data["coverage"] += " Phase C QA: quantities are schedule transcriptions, not full independent geometric remeasurement; 5 auxiliaries excluded from coverage denominator. Supply-only installation excluded; split rail base/Alt4 allocation pending."
    # Keep this operation idempotent when rerunning QA.
    data["coverage"] = data["coverage"].split(" Phase C QA:")[0] + " Phase C QA: schedule transcriptions, not full geometric remeasurement; 5 auxiliaries excluded from coverage denominator. Supply-only installation excluded; split rail base/Alt4 allocation pending."
    write_json(path, data)
    QA.mkdir(parents=True, exist_ok=True)
    write_json(QA / "corrections.json", {"engine_source_modified": False, "installation_rows_removed": ["INSTALL-LS-B-09", "INSTALL-LS-B-10"], "scope_quarantined": ["LS-A-15", "LS-B-08"], "wrong_discipline_sources_replaced": ["P-Q-03", "P-Q-04"], "sources_strengthened": ["P-Q-09", "P-Q-10", "P-Q-12", "LP-C-02", "LP-C-03", "Material LS-A-07 through LS-A-13"], "real_quantities_changed": [], "real_prices_inserted": []})


def synthetic():
    from reportlab.pdfgen import canvas
    folder = ROOT / "docs/QA Synthetic Phase C"
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / "QA_SYNTHETIC_ONLY.pdf"
    c = canvas.Canvas(str(pdf), invariant=1)
    c.drawString(50, 780, "FICTITIOUS QA ONLY - NOT A REAL BID OR QUOTATION")
    for y, text in enumerate(("QA01: 7 test panels EA.", "QA02: 12 test beam LF.", "QA03: 2 assemblies with 3 inserts each = 6 inserts EA.", "QA04: Test cable length is UNKNOWN; do not infer.", "No contractor, tax, dates or unit prices supplied.")):
        c.drawString(50, 740-y*25, text)
    c.save()
    config = ProjectConfig(ROOT, "QA Synthetic Phase C")
    manifest = audit(config)
    digest = manifest["documents"][0]["sha256"]
    def ref(text):
        return {"document": pdf.name, "page": 1, "sheet": "QA-S1", "sha256": digest, "excerpt": text}
    quantities = []
    for key, item, unit, value, quote in (("QA01", "FICTITIOUS test panels", "EA", 7, "QA01: 7 test panels EA."), ("QA02", "FICTITIOUS test beam", "LF", 12, "QA02: 12 test beam LF."), ("QA03", "FICTITIOUS inserts - auxiliary", "EA", 6, "QA03: 2 assemblies with 3 inserts each = 6 inserts EA."), ("QA04", "FICTITIOUS cable - pending", "LF", None, "QA04: Test cable length is UNKNOWN; do not infer.")):
        row = {"id": key, "package": "SYNTHETIC QA ONLY", "pricing_scope": "base", "item": item, "unit": unit, "quantity": value, "quantity_status": "PENDING_MEASUREMENT" if value is None else "DOCUMENT_QUANTITY", "basis": "FICTITIOUS explicit QA PDF; isolated from real projects", "estimate_included": key != "QA03", "sources": [ref(quote)]}
        if key == "QA03":
            row.update(quantity_status="CALCULATED_FROM_DOCUMENT", pricing_scope="included_component_check", calculation={"operation": "product", "operands": [2, 3]})
        quantities.append(row)
    data = {"schema_version": 1, "project_id": config.id, "scope_status": "SYNTHETIC_QA_ONLY_PARTIAL", "coverage": "FICTITIOUS 2 documented, 1 auxiliary, 1 pending; not a commercial project.", "quantities": quantities, "materials": [{"id": "MAT-"+r["id"], "description": r["item"], "unit": r["unit"], "quantity_id": r["id"], "specification": "FICTITIOUS QA ONLY", "sources": r["sources"]} for r in quantities if r["id"] != "QA03"], "requirements": [], "amendments": [], "risks": [], "pending": [{"id": "QA-P1", "issue": "FICTITIOUS cable unknown; all prices/tax/allowance absent", "action": "QA ONLY; retain null values"}], "tax_rate": None, "allowance": None}
    metadata = dict(config.metadata)
    metadata.update(synthetic=True, contractor=None, owner=None, project_no=None, procurement_no=None)
    write_json(config.project_dir / "project.json", metadata)
    write_json(config.project_dir / "analysis.json", data)


def evidence():
    data = read_json(ROOT / f"projects/{PROJECT}/analysis.json")
    rows = {r["id"]: r for r in data["quantities"]}
    # Independently read visually from the current PDF sheets, not copied from engine output.
    expected = {"LS-A-02": (5470, "SF"), "LS-A-14": (2100, "LF"), "LS-A-15": (494, "LF"), "LS-A-18": (12, "EA"), "LS-B-08": (335, "LF"), "LS-B-09": (15, "EA"), "LS-B-10": (4, "EA"), "LS-C-01": (2*4, "EA"), "LS-C-02": (2*3, "EA"), "LP-A-01": (52, "EA"), "LP-A-11": (2911, "SF"), "LP-A-20": (84321, "SF"), "LP-B-13": (6397, "SF"), "LP-C-01": (5*4, "EA"), "LP-C-02": (round(2911/81, 4), "CY"), "LP-C-03": (round(6397/81, 4), "CY"), "CD03-CB-21": (1, "EA"), "CD03-CB-31": (1, "EA"), "CD03-CB-33": (1, "EA")}
    checks = []
    notes = {"LS-A-14": "Combined fence and gate LF; not a gate or post count.", "LS-A-15": "Schedule quantity confirmed; base/Alt4 allocation unresolved.", "LS-B-08": "Separate grant schedule; base/Alt4 allocation unresolved, do not automatically sum with A.", "LS-B-09": "Alt5 supply only; owner installation; no foundation supplies.", "LS-B-10": "Alt6 supply only; owner installation; no foundation supplies.", "LP-A-01": "Restoration zone; separate from 50 bitter cherry in wetland C buffer.", "LP-A-20": "Seed coverage area, not seed weight.", "LP-C-02": "2911 SF x 4/12 ft / 27 = 35.9383 CY, excludes waste/settlement; auxiliary.", "LP-C-03": "6397 SF x minimum 4/12 ft / 27 = minimum 78.9753 CY; auxiliary.", "CD03-CB-31": "Quantity 1 confirmed; vaned grate conflicts with keynote 5 herringbone. Grate specification unresolved."}
    for key, (qty, unit) in expected.items():
        row = rows[key]
        assert (row["quantity"], row["unit"]) == (qty, unit), key
        refs = row["sources"]
        for ref in refs:
            assert sha256(ROOT / f"docs/Orangegate Park Phase 1/{ref['document']}") == ref["sha256"]
        checks.append({"id": key, "item": row["item"], "quantity": qty, "unit": unit, "quantity_check": "PASS", "engineering_note": notes.get(key, "Count/unit confirmed; auxiliary components remain excluded from pricing." if row["quantity_status"] == "CALCULATED_FROM_DOCUMENT" else "Schedule transcription confirmed; no purchase/waste factor inferred."), "sources": refs, "current_local_revision": "Addendum 2, LP02 rev2 10/16/2026" if key.startswith("LP-") else "Addendum 4, rev3 10/22/2026"})
    document = [r for r in rows.values() if r["quantity_status"] == "DOCUMENT_QUANTITY"]
    auxiliary = [r for r in rows.values() if r["quantity_status"] == "CALCULATED_FROM_DOCUMENT"]
    pending = [dict(r, missing_information=MISSING[r["id"]]) for r in rows.values() if r["quantity"] is None]
    assert (len(document), len(auxiliary), len(pending)) == (94, 5, 13)
    signatures = [(r["package"], r["item"].casefold(), r["unit"], r["quantity"]) for r in rows.values()]
    assert len(signatures) == len(set(signatures))
    write_json(QA / "engineering_evidence.json", {"sample": checks, "sample_count": len(checks), "primary_sample_count": 14, "auxiliary_sample_count": 5, "primary_identified_concepts": 107, "document_quantity_concepts": 94, "pending_measurement_concepts": 13, "quantity_population_percent": 100*94/107, "auxiliary_rows_excluded_from_denominator": 5, "coverage_limit": "Identified concepts only, not full scope; sample verifies schedule transcriptions, not independent geometric remeasurement of all plans. Source-current means latest in local supplied addenda 1-4, not confirmation of later external issuances.", "exact_duplicate_signatures": 0, "pending_measurement": pending})


def versions():
    base = read_json(SNAPSHOT)
    changes = []
    for relative, before in base["files"].items():
        p = ROOT / relative
        after = sha256(p) if p.exists() else None
        if after != before["sha256"]:
            changes.append({"path": relative, "before_sha256": before["sha256"], "after_sha256": after})
    assert not any(c["path"].startswith(("src/", "docs/")) for c in changes), changes
    new = {p.relative_to(ROOT).as_posix(): sha256(p) for p in all_workspace_files(ROOT / base["snapshot_name"]) if p.relative_to(ROOT).as_posix() not in base["files"] and p.name != "versions.json" and "snapshots" not in p.parts}
    write_json(QA / "versions.json", {"baseline_manifest": SNAPSHOT.relative_to(ROOT).as_posix(), "baseline_archive_sha256": sha256(ROOT/base["snapshot_name"]), "changed_existing_files": changes, "new_files": new, "engine_source_unchanged": True, "all_original_documents_unchanged": True})


def verify():
    """Rerun existing checks; retain Phase B evidence without rewriting its report."""
    from contextlib import redirect_stdout
    import importlib.util
    from importlib.metadata import version
    import subprocess
    from unittest.mock import patch
    QA.mkdir(parents=True, exist_ok=True)
    (ROOT / ".test-tmp").mkdir(exist_ok=True)
    results = []
    def run(label, arguments):
        log = QA / (label+".log")
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.run([sys.executable, *arguments], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        assert process.returncode == 0, log.read_text(encoding="utf-8")
        results.append({"check": label, "exit_code": process.returncode, "log": log.relative_to(ROOT).as_posix()})
        print(label+": PASS", flush=True)
    run("compile", ["-m", "compileall", "-q", "src", "tests", "tools", "run_bidkit.py"])
    run("pytest", ["-m", "pytest", "-q", "--basetemp", ".test-tmp/phase-c-final"])
    assert "31 passed" in (QA / "pytest.log").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("phase_b_verifier", ROOT / "tools/verify_projects.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def redirect_report(path, payload):
        assert Path(path) == ROOT / "data/phase_b_validation.json"
        write_json(QA / "integration_results.json", payload)
    with patch.object(sys, "argv", ["verify_projects.py"]), patch.object(module, "write_json", redirect_report), (QA / "integration.log").open("w", encoding="utf-8") as stream, redirect_stdout(stream):
        module.main()
    integration = read_json(QA / "integration_results.json")
    assert len(integration["projects"]) == 5
    print("CLI + byte reproduction + cache + original ZIP integrity: PASS (5 projects)", flush=True)
    for project in integration["projects"]:
        run("integration-"+project["project_id"], ["tests/run_integration_checks.py", "--project", project["project_id"]])
    run("list-projects", ["run_bidkit.py", "list-projects"])
    run("inventory", ["run_bidkit.py", "inventory"])
    base = read_json(SNAPSHOT)
    preserved = {p: details["sha256"] for p, details in base["files"].items() if p.startswith("output/") and not p.startswith("output/"+PROJECT+"/")}
    assert all(sha256(ROOT/p) == digest for p, digest in preserved.items())
    src = {p: details["sha256"] for p, details in base["files"].items() if p.startswith("src/")}
    assert all(sha256(ROOT/p) == digest for p, digest in src.items())
    synthetic_data = read_json(ROOT / "data/projects/qa-synthetic-phase-c/estimate/estimate_inputs.json")
    assert synthetic_data["tax_rate"] is None and synthetic_data["allowance"] is None
    assert all(r["unit_price"] is None and r["quote_reference"] is None for r in synthetic_data["rows"])
    assert read_json(ROOT / "projects/qa-synthetic-phase-c/project.json")["contractor"] is None
    write_json(QA / "test_summary.json", {"checks": results, "pytest_passed": 31, "integration_projects": 5, "commands_per_project": ["audit", "takeoff", "estimate", "build", "validate"], "other_real_projects_artifacts_unchanged": True, "engine_files_unchanged": len(src), "synthetic_no_inherited_prices_tax_allowance_contractor": True, "python": platform.python_version(), "dependencies": {name: version(name) for name in ("openpyxl", "pypdf", "pypdfium2", "reportlab", "pytest")}})


SNAPSHOT_MEMBERS = (
    "src",
    "tests",
    "tools",
    "projects",
    "output",
    "README.md",
    "LEEME_SEPARACION.md",
    "PRE_COMMIT_AUDIT.md",
    "pyproject.toml",
    "run_bidkit.py",
    "sources",
    "templates",
    "data/PHASE_B_REPORT.md",
    "data/phase_b_validation.json",
    "data/projects_inventory.json",
)


def included_files() -> list[Path]:
    files: list[Path] = []
    for member in SNAPSHOT_MEMBERS:
        path = ROOT / member
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    return sorted(set(files), key=lambda p: p.relative_to(ROOT).as_posix())


def all_workspace_files(snapshot: Path) -> list[Path]:
    ignored_parts = {".test-tmp", ".pytest_cache", "__pycache__"}
    return sorted(
        (
            p
            for p in ROOT.rglob("*")
            if p.is_file()
            and p != snapshot
            and not any(part in ignored_parts for part in p.relative_to(ROOT).parts)
            and not p.name.endswith((".pyc", ".tmp"))
        ),
        key=lambda p: p.relative_to(ROOT).as_posix(),
    )


def freeze() -> None:
    destination = ROOT / "data" / "snapshots"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "phase_b_state_20261026T154754.zip"
    if archive.exists():
        raise FileExistsError("Frozen baseline already exists; do not overwrite.")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in included_files():
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), (2026, 10, 26, 15, 47, 54))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, path.read_bytes())

    files = all_workspace_files(archive)
    manifest = {
        "snapshot_name": archive.relative_to(ROOT).as_posix(),
        "snapshot_sha256": sha256(archive),
        "snapshot_scope": "Code, tests, tools, project inputs, generated outputs and Phase B reports. Source documents are represented by hashes and remain in docs/ and their supplied ZIP archives.",
        "captured_utc": datetime.now(UTC).isoformat(),
        "declared_reference_time": "2026-10-26T15:47:54",
        "python": sys.version,
        "platform": platform.platform(),
        "files": {
            path.relative_to(ROOT).as_posix(): {
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        },
    }
    write_json(destination / "phase_b_state_20261026T154754.manifest.json", manifest)
    print(json.dumps({"snapshot": str(archive), "sha256": manifest["snapshot_sha256"], "files": len(files)}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "correct", "synthetic", "evidence", "versions", "verify"])
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    else:
        {"correct": correct_inputs, "synthetic": synthetic, "evidence": evidence, "versions": versions, "verify": verify}[args.command]()


if __name__ == "__main__":
    main()
