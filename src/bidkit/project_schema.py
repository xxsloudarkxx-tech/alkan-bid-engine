"""Small explicit project input contract; references are checked against cached pages."""
from __future__ import annotations

from decimal import Decimal
import math

from .audit import load_audit, normalize, sha256
from .config import ProjectConfig
from .data_store import fingerprint, read_json

SCHEMA_VERSION = 1


def input_fingerprint(config: ProjectConfig, data: dict) -> str:
    return fingerprint({"project": config.metadata, "analysis": data})


def load_analysis(config: ProjectConfig) -> dict:
    path = config.project_dir / "analysis.json"
    if not path.exists():
        raise ValueError(f"Falta el análisis documental independiente: {path}")
    data = read_json(path)
    if data.get("schema_version") != SCHEMA_VERSION or data.get("project_id") != config.id:
        raise ValueError("Versión o identidad del análisis incompatible con el proyecto seleccionado.")
    for key in ("scope_status", "coverage"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise ValueError(f"Falta {key} en el análisis.")
    for key in ("quantities", "materials", "requirements", "amendments", "risks", "pending"):
        if not isinstance(data.get(key), list):
            raise ValueError(f"El análisis requiere una lista {key}.")
        ids = [r.get("id") for r in data[key]]
        if None in ids or len(ids) != len(set(ids)):
            raise ValueError(f"Identificadores ausentes o duplicados en {key}.")
    return data


def calculated_quantity(calculation: dict) -> float:
    operands = [Decimal(str(n)) for n in calculation["operands"]]
    if not operands or any(not n.is_finite() or n < 0 for n in operands):
        raise ValueError("Operandos inválidos.")
    operation = calculation["operation"]
    if operation == "product":
        result = math.prod(operands)
    elif operation == "sum":
        result = sum(operands)
    else:
        raise ValueError(f"Operación no admitida: {operation}")
    return float(result.quantize(Decimal("0.0001")))


def validate_analysis(config: ProjectConfig, data: dict | None = None) -> list[str]:
    data = data or load_analysis(config)
    documents = {d["name"]: d for d in load_audit(config)["documents"]}
    errors = []
    cache = {}

    def check_source(source: dict, label: str) -> None:
        doc = documents.get(source.get("document"))
        if not doc:
            errors.append(f"{label}: documento ajeno o inexistente")
            return
        if source.get("sha256") != doc["sha256"]:
            errors.append(f"{label}: SHA-256 de referencia incorrecto")
        page = source.get("page")
        if type(page) is not int or not doc["pages"] or not 1 <= page <= doc["pages"]:
            errors.append(f"{label}: página PDF inválida (numeración desde 1)")
            return
        digest = doc["sha256"]
        if digest not in cache:
            cache[digest] = read_json(config.data_dir / "extractions" / f"{digest}.json")
        text = cache[digest]["pages"][page-1]["text"]
        excerpt = source.get("excerpt", "")
        if source.get("evidence_type") == "visual_transcription":
            image_path = (config.root / source.get("review_image", "")).resolve()
            review_dir = (config.data_dir / "review").resolve()
            if not image_path.is_relative_to(review_dir) or not image_path.is_file():
                errors.append(f"{label}: falta imagen de revisión del proyecto")
            elif sha256(image_path) != source.get("review_image_sha256"):
                errors.append(f"{label}: imagen de revisión modificada")
            elif not image_path.with_suffix(".json").exists():
                errors.append(f"{label}: falta vínculo de render con PDF original")
            else:
                render = read_json(image_path.with_suffix(".json"))
                if (render.get("document"), render.get("page"), render.get("source_sha256"), render.get("image_sha256")) != (doc["name"], page, digest, source.get("review_image_sha256")):
                    errors.append(f"{label}: render pertenece a otro documento o página")
            region = source.get("region_bbox", [])
            if len(region) != 4 or not (0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1):
                errors.append(f"{label}: región visual inválida")
            if not source.get("transcription"):
                errors.append(f"{label}: falta transcripción de evidencia visual")
        elif len(normalize(excerpt)) < 8 or normalize(excerpt).casefold() not in normalize(text).casefold():
            errors.append(f"{label}: extracto no encontrado en la página citada")

    for key in ("quantities", "materials", "requirements", "amendments", "risks"):
        for row in data[key]:
            if not row.get("sources"):
                errors.append(f"{row['id']}: falta referencia documental")
            for source in row.get("sources", []):
                check_source(source, row["id"])

    quantities = {r["id"]: r for r in data["quantities"]}
    for row in quantities.values():
        qty = row.get("quantity")
        if qty is None:
            if row.get("quantity_status") != "PENDING_MEASUREMENT":
                errors.append(f"{row['id']}: cantidad vacía sin estado pendiente")
        else:
            if type(qty) not in (int, float) or not math.isfinite(qty) or qty < 0:
                errors.append(f"{row['id']}: cantidad inválida")
            if row.get("quantity_status") not in ("DOCUMENT_QUANTITY", "CALCULATED_FROM_DOCUMENT"):
                errors.append(f"{row['id']}: estado de cantidad no admitido")
            if row.get("quantity_status") == "DOCUMENT_QUANTITY":
                import re
                evidence = " ".join(s.get("transcription", s.get("excerpt", "")) for s in row.get("sources", []))
                tokens = re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w.])", evidence)
                if not any(float(token.replace(",", "")) == qty for token in tokens):
                    errors.append(f"{row['id']}: cantidad no aparece en el extracto/transcripción")
            if row.get("quantity_status") == "CALCULATED_FROM_DOCUMENT":
                try:
                    if abs(calculated_quantity(row["calculation"]) - qty) > 0.0001:
                        errors.append(f"{row['id']}: fórmula y cantidad no coinciden")
                except (KeyError, ValueError, TypeError, ArithmeticError):
                    errors.append(f"{row['id']}: cálculo inválido")
            if not row.get("basis"):
                errors.append(f"{row['id']}: falta base de medición")
    for row in data["materials"]:
        if row.get("quantity_id") is not None and row["quantity_id"] not in quantities:
            errors.append(f"{row['id']}: vínculo de cantidad inválido")
        elif row.get("quantity_id") is not None and row.get("unit") != quantities[row["quantity_id"]].get("unit"):
            errors.append(f"{row['id']}: unidad incompatible con la cantidad vinculada")
    for key in ("tax_rate", "allowance"):
        if data.get(key) is not None:
            if type(data[key]) not in (int, float) or not math.isfinite(data[key]) or data[key] < 0:
                errors.append(f"{key}: valor inválido")
            if not data.get(key + "_source"):
                errors.append(f"{key}: valor sin respaldo")
            else:
                check_source(data[key + "_source"], key)
    if data.get("tax_treatment_source"):
        check_source(data["tax_treatment_source"], "tax_treatment")
    return errors


def require_valid_analysis(config: ProjectConfig) -> dict:
    data = load_analysis(config)
    errors = validate_analysis(config, data)
    if errors:
        raise ValueError("Análisis inválido: " + "; ".join(errors))
    return data
