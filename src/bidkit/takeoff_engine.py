"""Enterprise drawing classification, scale calibration, measurement, and structured Material Takeoff."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
from typing import Any

import pypdfium2 as pdfium

from .plan_measurement import calibrar_escala, medir_plano
from .units import convertir_unidades

EVIDENCE_TAGS: tuple[str, ...] = (
    "medido",
    "declarado",
    "estimado_con_supuestos",
    "no_determinado",
)

REVIEW_STATUSES: tuple[str, ...] = ("pending", "verified", "flagged", "overridden")

DISCIPLINE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Structural", re.compile(r"\b(structural|framing|foundation|footing|rebar|w\d+x\d+|hss\s*\d+|plate|anchor\s+bolt)\b|^(S|ST)\d", re.I | re.M)),
    ("Civil", re.compile(r"\b(civil|grading|storm|sewer|utility|paving|curb|sidewalk|asphalt|trench)\b|^(C|CE)\d", re.I | re.M)),
    ("MEP", re.compile(r"\b(mechanical|electrical|plumbing|hvac|duct|conduit|panelboard|piping|sprinkler)\b|^(M|E|P|FP)\d", re.I | re.M)),
    ("Landscape", re.compile(r"\b(landscape|irrigation|planting|fencing|chain[- ]?link|bollard|park|site furnishings?)\b|^L\d", re.I | re.M)),
    ("Architectural", re.compile(r"\b(architectural|elevation|floor plan|roof plan|partition|ceiling|handrail|guardrail|door schedule)\b|^A\d", re.I | re.M)),
)

_SCALE_RE = re.compile(
    r"(?i)(?:scale\s*[:=]?\s*)?("
    r"\d+(?:/\d+)?\s*[\"']\s*=\s*\d+(?:'-\d+\"?|\"|')?"
    r"|1\s*:\s*\d+(?:\.\d+)?"
    r"|NTS|NOT\s+TO\s+SCALE"
    r")"
)
_SPEC_RE = re.compile(r"\b(?:ASTM\s+[A-Z]\d+[A-Z0-9-]*|AISC\s+\w+|AWWA\s+\w+|Section\s+\d{2}\s+\d{2}\s+\d{2})\b", re.I)
_SHEET_RE = re.compile(r"\b([ASCMELFP]-?\d+(?:\.\d+)*)\b")
_REV_RE = re.compile(r"(?i)\b(?:REV(?:ISION)?\s*[:#-]?\s*([A-Z0-9.-]+)|ADDENDUM\s*(?:NO\.?\s*)?(\d+))\b")
_DIM_RE = re.compile(r"\b(\d+(?:\s*-\s*\d+(?:/\d+)?\"|\.\d+)?\s*(?:'|\"|ft|in|mm|cm|m|LF|SF|CF|CY))\b", re.I)


def _d(val: Any) -> Decimal:
    return Decimal(str(val))


def _round_qty(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class SheetProfile:
    document: str
    page: int
    sheet_id: str
    discipline: str
    is_scanned: bool
    char_count: int
    scales_detected: list[str]
    revisions_detected: list[str]
    spec_refs: list[str]
    dimensions_sample: list[str]
    unit_system: str
    alerts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_sheet_text(text: str, *, document: str, page: int) -> SheetProfile:
    """Classify discipline, scales, unit system, revision markers, and OCR need for a PDF page."""
    clean = text or ""
    char_count = len(re.sub(r"\s+", " ", clean).strip())
    is_scanned = char_count < 40

    discipline = "Unknown"
    for label, pattern in DISCIPLINE_PATTERNS:
        if pattern.search(clean):
            discipline = label
            break

    sheet_m = _SHEET_RE.search(clean)
    sheet_id = sheet_m.group(1) if sheet_m else f"P{page}"
    scales = list(dict.fromkeys(m.group(1).strip() for m in _SCALE_RE.finditer(clean)))[:8]
    revs = list(dict.fromkeys((m.group(1) or m.group(2) or "").strip() for m in _REV_RE.finditer(clean) if (m.group(1) or m.group(2))))[:6]
    specs = list(dict.fromkeys(m.group(0).strip() for m in _SPEC_RE.finditer(clean)))[:12]
    dims = list(dict.fromkeys(m.group(1).strip() for m in _DIM_RE.finditer(clean)))[:15]

    has_imp = bool(re.search(r"(\d'\s*-|\bft\b|\bin\b|\bLF\b|\bSF\b|\bCF\b|\bCY\b|\")", clean, re.I))
    has_met = bool(re.search(r"\b(\d+(?:\.\d+)?\s*(?:mm|cm|m)\b|1\s*:\s*(?:50|100|200|500))\b", clean, re.I))
    if has_imp and has_met:
        unit_system = "mixed"
    elif has_met:
        unit_system = "metric"
    elif has_imp:
        unit_system = "imperial"
    else:
        unit_system = "undetermined"

    alerts: list[str] = []
    if is_scanned:
        alerts.append("LOW_TEXT_DENSITY: scanned/raster sheet requires visual verification or OCR.")
    if not scales:
        alerts.append("MISSING_SCALE: no explicit drawing scale detected on sheet.")
    elif any("NTS" in s.upper() or "NOT TO SCALE" in s.upper() for s in scales):
        alerts.append("NTS_WARNING: sheet contains Not-To-Scale note; do not scale graphically.")
    if unit_system == "mixed":
        alerts.append("MIXED_UNITS: both imperial and metric notations appear on this sheet.")

    return SheetProfile(
        document=document,
        page=page,
        sheet_id=sheet_id,
        discipline=discipline,
        is_scanned=is_scanned,
        char_count=char_count,
        scales_detected=scales,
        revisions_detected=revs,
        spec_refs=specs,
        dimensions_sample=dims,
        unit_system=unit_system,
        alerts=alerts,
    )


def inspect_pdf_drawings(pdf_path: Path, *, max_pages: int = 80) -> dict[str, Any]:
    """Inspect a PDF drawing/specification file without inventing missing measurements."""
    pdf_path = Path(pdf_path)
    doc = pdfium.PdfDocument(str(pdf_path))
    sheets: list[dict[str, Any]] = []
    try:
        total_pages = len(doc)
        for idx in range(min(total_pages, max_pages)):
            page = doc[idx]
            tp = page.get_textpage()
            text = tp.get_text_bounded() or ""
            tp.close()
            page.close()
            sheets.append(classify_sheet_text(text, document=pdf_path.name, page=idx + 1).to_dict())
    finally:
        doc.close()
    scanned_pages = [s["page"] for s in sheets if s["is_scanned"]]
    return {
        "document": pdf_path.name,
        "total_pages": total_pages,
        "inspected_pages": len(sheets),
        "scanned_pages": scanned_pages,
        "sheets": sheets,
    }


def calibrate_drawing_scale(
    pdf_path: str | Path,
    page: int,
    ref_points: list[list[float]],
    real_distance: float | str | Decimal,
    real_unit: str,
    source: str,
    *,
    dpi: int = 150,
    uncertainty_pct: float | None = None,
) -> dict[str, Any]:
    """Calibrate scale cleanly over a PDF page and record confidence + unit system."""
    cal = calibrar_escala(
        ruta=str(pdf_path),
        pagina=page,
        puntos_referencia=ref_points,
        distancia_real=real_distance,
        unidad_real=real_unit,
        fuente=source,
        dpi=dpi,
        incertidumbre_pct=uncertainty_pct,
    )
    unc = Decimal(str(cal.get("incertidumbre_pct") or 5))
    confidence = max(Decimal("0.10"), min(Decimal("0.99"), Decimal("1") - (unc / Decimal("100"))))
    return {
        **cal,
        "calibration_id": f"CAL-P{page}-{cal['fuente'][:18].replace(' ', '_')}",
        "confidence": float(confidence.quantize(Decimal("0.01"))),
        "ambiguous": unc > Decimal("10"),
    }


def compute_measurement(
    calibration: dict[str, Any],
    points: list[list[float]],
    kind: str,
    source: str,
    *,
    output_unit: str = "",
    depth_value: float | str | Decimal | None = None,
    depth_unit: str = "ft",
) -> dict[str, Any]:
    """Compute length, area, count, or volume from calibrated drawing geometry with Decimal accuracy."""
    kind_norm = (kind or "").strip().lower()
    if kind_norm == "volumen":
        kind_norm = "volume"
    elif kind_norm == "longitud":
        kind_norm = "length"
    elif kind_norm in ("area", "área"):
        kind_norm = "area"
    elif kind_norm in ("conteo", "count"):
        kind_norm = "count"

    if kind_norm == "volume":
        area_res = medir_plano(calibration, points, "area", source)
        if depth_value is None:
            raise ValueError("depth_value is required for volume measurements.")
        depth_m = _d(convertir_unidades(str(depth_value), depth_unit, "m"))
        area_m2 = _d(area_res["valor"])
        vol_m3 = area_m2 * depth_m
        target_u = output_unit or "CY"
        # m3 to CF or CY via linear meters cubed
        factor = _d(convertir_unidades("1", target_u if target_u in ("m3", "CF", "CY") else "CY", "m3")) if target_u in ("CF", "CY", "m3") else None
        if target_u.lower() in ("m3", "cbm"):
            final_val = vol_m3
        elif target_u.upper() == "CF":
            final_val = vol_m3 * (_d(convertir_unidades("1", "m", "ft")) ** 3)
        elif target_u.upper() == "CY":
            final_val = vol_m3 * (_d(convertir_unidades("1", "m", "yd")) ** 3)
        else:
            raise ValueError(f"Unsupported volume unit {target_u!r}; expected m3, CF, or CY.")
        return {
            "kind": "volume",
            "valor": str(_round_qty(final_val)),
            "unidad": target_u,
            "area_m2": area_res["valor"],
            "depth_m": str(_round_qty(depth_m)),
            "confianza": area_res.get("confianza"),
            "fuente": source,
            "trazabilidad": area_res.get("trazabilidad", {}),
        }

    pt_kind = {"length": "longitud", "area": "area", "count": "conteo"}.get(kind_norm)
    if not pt_kind:
        raise ValueError(f"Unsupported measurement kind: {kind!r}")
    raw = medir_plano(calibration, points, pt_kind, source)
    if not output_unit or kind_norm == "count":
        return raw
    base_u = raw["unidad"]
    if kind_norm == "length":
        conv = _d(convertir_unidades(raw["valor"], base_u, output_unit))
    else:
        # Area conversion: scale linear ratio squared safely
        lin = _d(convertir_unidades("1", "m", output_unit.replace("S", "").replace("2", "") if output_unit.upper() in ("SF", "SY") else output_unit))
        if output_unit.upper() == "SF":
            lin = _d(convertir_unidades("1", "m", "ft"))
        elif output_unit.upper() == "SY":
            lin = _d(convertir_unidades("1", "m", "yd"))
        elif output_unit.lower() in ("m2", "sqm"):
            lin = Decimal("1")
        else:
            raise ValueError(f"Unsupported area output unit: {output_unit!r}")
        conv = _d(raw["valor"]) * (lin * lin)
    return {**raw, "valor": str(_round_qty(conv)), "unidad": output_unit}


@dataclass
class MaterialTakeoffItem:
    code: str
    description: str
    material: str
    specification: str
    dimensions: str
    unit: str
    calculated_qty: Decimal | None
    waste_factor_pct: Decimal
    final_qty: Decimal | None
    source_sheet: str
    document_ref: str
    confidence: float
    evidence_status: str = "medido"
    review_status: str = "pending"
    calibration_id: str = ""
    original_measurement: dict[str, Any] = field(default_factory=dict)
    override_history: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.evidence_status not in EVIDENCE_TAGS:
            raise ValueError(f"Invalid evidence_status: {self.evidence_status!r}")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"Invalid review_status: {self.review_status!r}")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        self.waste_factor_pct = _d(self.waste_factor_pct)
        if self.waste_factor_pct < 0 or self.waste_factor_pct > Decimal("100"):
            raise ValueError("waste_factor_pct must be between 0 and 100")
        if self.calculated_qty is not None:
            self.calculated_qty = _d(self.calculated_qty)
            if self.calculated_qty < 0:
                raise ValueError("calculated_qty cannot be negative")
            expected_final = _round_qty(self.calculated_qty * (Decimal("1") + self.waste_factor_pct / Decimal("100")))
            if self.final_qty is None:
                self.final_qty = expected_final
            else:
                self.final_qty = _d(self.final_qty)
        elif self.evidence_status != "no_determinado":
            raise ValueError("Missing calculated_qty is only valid when evidence_status='no_determinado'.")
        if not self.original_measurement:
            self.original_measurement = {
                "calculated_qty": str(self.calculated_qty) if self.calculated_qty is not None else None,
                "waste_factor_pct": str(self.waste_factor_pct),
                "final_qty": str(self.final_qty) if self.final_qty is not None else None,
                "unit": self.unit,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        if self.evidence_status == "no_determinado" or self.calculated_qty is None:
            if "MISSING_QUANTITY_RFI_REQUIRED" not in self.alerts:
                self.alerts.append("MISSING_QUANTITY_RFI_REQUIRED")

    def apply_manual_override(
        self,
        *,
        new_calculated_qty: Decimal | str | float,
        actor: str,
        reason: str,
        new_waste_factor_pct: Decimal | str | float | None = None,
    ) -> None:
        """Apply human correction while preserving original_measurement immutably."""
        if not actor.strip() or not reason.strip():
            raise ValueError("actor and reason are required for manual takeoff overrides.")
        qty_d = _d(new_calculated_qty)
        if qty_d < 0:
            raise ValueError("Override quantity cannot be negative.")
        waste_d = _d(new_waste_factor_pct) if new_waste_factor_pct is not None else self.waste_factor_pct
        new_final = _round_qty(qty_d * (Decimal("1") + waste_d / Decimal("100")))
        self.override_history.append({
            "at": datetime.now(timezone.utc).isoformat(),
            "actor": actor.strip(),
            "reason": reason.strip(),
            "prev_calculated_qty": str(self.calculated_qty) if self.calculated_qty is not None else None,
            "new_calculated_qty": str(qty_d),
            "prev_final_qty": str(self.final_qty) if self.final_qty is not None else None,
            "new_final_qty": str(new_final),
        })
        self.calculated_qty = qty_d
        self.waste_factor_pct = waste_d
        self.final_qty = new_final
        self.review_status = "overridden"
        if self.evidence_status == "no_determinado":
            self.evidence_status = "declarado"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["calculated_qty"] = str(self.calculated_qty) if self.calculated_qty is not None else None
        d["waste_factor_pct"] = str(self.waste_factor_pct)
        d["final_qty"] = str(self.final_qty) if self.final_qty is not None else None
        return d


def detect_takeoff_gaps(items: list[MaterialTakeoffItem]) -> list[dict[str, Any]]:
    """Return blocking/warning gaps for missing quantities, low confidence, or missing references."""
    findings: list[dict[str, Any]] = []
    for item in items:
        if item.calculated_qty is None or item.evidence_status == "no_determinado":
            findings.append({
                "code": item.code,
                "severity": "HIGH",
                "type": "missing_measurement",
                "message": f"{item.code} ({item.description}): quantity unresolved; generate RFI before firm pricing.",
                "source_sheet": item.source_sheet,
            })
        if item.confidence < 0.65:
            findings.append({
                "code": item.code,
                "severity": "MEDIUM",
                "type": "low_confidence",
                "message": f"{item.code}: confidence {item.confidence:.2f} below 0.65 threshold.",
                "source_sheet": item.source_sheet,
            })
        if not item.source_sheet.strip() or not item.document_ref.strip():
            findings.append({
                "code": item.code,
                "severity": "HIGH",
                "type": "missing_traceability",
                "message": f"{item.code}: missing source_sheet or document_ref citation.",
                "source_sheet": item.source_sheet,
            })
    return findings
