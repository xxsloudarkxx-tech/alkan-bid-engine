from __future__ import annotations

import csv
import json
from pathlib import Path

from .audit import load_audit, sha256, validate_extractions, validate_source_integrity
from .config import ProjectConfig
from .data_store import read_json, write_json
from .project_schema import input_fingerprint, load_analysis, require_valid_analysis, validate_analysis


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(dict.fromkeys(k for row in rows for k in row)) or ["id", "status"]
    with path.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(row.get(k), ensure_ascii=False, sort_keys=True) if isinstance(row.get(k), (list, dict)) else row.get(k) for k in fields})


def build_data_records(config: ProjectConfig) -> dict:
    manifest = load_audit(config)
    data = require_valid_analysis(config)
    payload = {"project": config.metadata, "input_fingerprint": input_fingerprint(config, data), "scope_status": data["scope_status"], "requirements": data["requirements"], "amendments": data["amendments"], "risks": data["risks"], "pending": data["pending"], "source_manifest": manifest["documents"]}
    write_json(config.audit_dir / "bid_audit.json", payload)
    return payload


def write_working_registers(config: ProjectConfig) -> None:
    data = require_valid_analysis(config)
    measured = read_json(config.data_dir / "takeoff" / "takeoff.json")
    for name, rows in {"takeoff_register.csv": measured["records"], "materials.csv": measured["materials"], "requirements.csv": data["requirements"], "amendments.csv": data["amendments"], "risks.csv": data["risks"], "pending.csv": data["pending"]}.items():
        _write_csv(config.output_dir / name, rows)


def write_build_manifest(config: ProjectConfig) -> None:
    paths = [config.data_dir / relative for relative in ("takeoff/takeoff.json", "estimate/estimate_inputs.json", "audit/bid_audit.json")]
    if (config.project_dir / "pricing.json").exists():
        paths.append(config.data_dir / "estimate/cost_result.json")
    if (config.project_dir / "bid_form.json").exists():
        paths.append(config.data_dir / "estimate/bid_preparation.json")
    paths += sorted(p for p in config.output_dir.rglob("*") if p.suffix in (".csv", ".xlsx", ".pdf"))
    write_json(config.output_dir / "build_manifest.json", {"project_id": config.id, "input_fingerprint": input_fingerprint(config, load_analysis(config)), "costing_enabled": (config.project_dir / "pricing.json").exists(), "bid_preparation_enabled": (config.project_dir / "bid_form.json").exists(), "artifacts": {p.relative_to(config.root).as_posix(): sha256(p) for p in paths}})


def validation_report(config: ProjectConfig) -> dict:
    # Validation never rebuilds artifacts or resets the source baseline.
    data = load_analysis(config)
    if not (config.audit_dir / "document_inventory.json").exists():
        payload = {"project_id": config.id, "technical_validation": "FAIL", "errors": ["Falta línea base de auditoría; ejecute audit antes de validar."]}
        write_json(config.output_dir / "validation_report.json", payload)
        return payload
    errors = validate_extractions(config)
    if not errors:
        errors.extend(validate_analysis(config, data))
    integrity = validate_source_integrity(config)
    if any(r["status"] != "PASS" for r in integrity):
        errors.append("El expediente no coincide con la línea base.")
    inventory = load_audit(config)
    for document in inventory["documents"]:
        if document["extraction_errors"]:
            errors.append(f"Errores de extracción: {document['name']}")
    for relative in ("takeoff/takeoff.json", "estimate/estimate_inputs.json", "audit/bid_audit.json"):
        path = config.data_dir / relative
        if not path.exists():
            errors.append(f"Resultado ausente: {relative}")
        else:
            result = read_json(path)
            if result.get("input_fingerprint") != input_fingerprint(config, data):
                errors.append(f"Resultado obsoleto: {relative}")
            if result.get("project_id", result.get("project", {}).get("id")) != config.id:
                errors.append(f"Resultado de otro proyecto: {relative}")
    build_path = config.output_dir / "build_manifest.json"
    if not build_path.exists():
        errors.append("Falta manifiesto de resultados")
    else:
        build = read_json(build_path)
        if build.get("costing_enabled", False) != (config.project_dir / "pricing.json").exists():
            errors.append("Cost input file added or removed; explicit rebuild required")
        if build.get("bid_preparation_enabled", False) != (config.project_dir / "bid_form.json").exists():
            errors.append("Bid form mapping added or removed; explicit rebuild required")
        if build.get("input_fingerprint") != input_fingerprint(config, data):
            errors.append("Manifiesto de resultados obsoleto")
        for relative, expected in build["artifacts"].items():
            path = (config.root / relative).resolve()
            if not (path.is_relative_to(config.data_dir.resolve()) or path.is_relative_to(config.output_dir.resolve())):
                errors.append(f"Resultado ajeno al proyecto: {relative}")
            elif not path.exists() or sha256(path) != expected:
                errors.append(f"Resultado ausente o modificado: {relative}")
    from .workbooks import validate_workbooks
    errors.extend(validate_workbooks(config))
    if (config.project_dir / "pricing.json").exists():
        from .costing import evaluate
        try:
            actual = evaluate(data, read_json(config.project_dir / "pricing.json"), read_json(config.project_dir / "quotes.json"), root=config.root)
            stored = read_json(config.data_dir / "estimate/cost_result.json")
            if stored != actual:
                errors.append("Cost result is stale or modified; rebuild after price edits")
            if not (config.output_dir / "Cost_Budget.xlsx").exists():
                errors.append("Missing Cost_Budget.xlsx")
        except (ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))
    if (config.project_dir / "bid_form.json").exists():
        from .bid_preparation import load_preparation
        try:
            if load_preparation(config, data) != read_json(config.data_dir / "estimate/bid_preparation.json"):
                errors.append("Bid preparation snapshot is stale or modified")
        except (ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))
    payload = {"project_id": config.id, "technical_validation": "PASS" if not errors else "FAIL", "validation_scope": "Integrity, source references, arithmetic and artifacts; does not certify full measurement, field conditions or bid readiness.", "errors": errors, "source_integrity": integrity, "scope_status": data["scope_status"], "scope_complete": False, "document_review_pending": [{"document": d["name"], "visual_review_pages": d["visual_review_pages"], "unextracted_asset": d["pages"] is None} for d in inventory["documents"] if d["visual_review_pages"] or d["pages"] is None], "measured_quantity_rows": sum(r["quantity"] is not None for r in data["quantities"]), "pending_quantity_rows": sum(r["quantity"] is None for r in data["quantities"]), "pending": data["pending"], "estimate_status": "INCOMPLETE_UNPRICED", "contractor": config.metadata.get("contractor"), "commercial_actions_performed": False}
    write_json(config.output_dir / "validation_report.json", payload)
    return payload
