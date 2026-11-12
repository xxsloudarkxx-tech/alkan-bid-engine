"""Bounded local parsers. Customer document text is inert, untrusted data."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from PIL import Image

from .audit import normalize
from .intelligence_store import utcnow

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PAGES = 500
MAX_TEXT = 4_000_000
PARSER_VERSION = "local-pypdf-text-image-table-v2.1"
SUPPORTED = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".csv", ".xlsx"}


def parse_document(name: str, raw: bytes):
    if (not name or name != Path(name).name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or len(name) > 180 or name.endswith((" ", "."))):
        raise ValueError("Nombre de archivo inválido")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("Formato sin parser: use PDF, TXT UTF-8, PNG, JPEG, CSV o XLSX")
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise ValueError("Archivo vacío o mayor de 25 MB")
    pages, table_rows, status = [], [], "EXTRACTED_REVIEW_REQUIRED"
    if suffix in (".csv", ".xlsx"):
        from .price_catalog import table_pages
        pages, table_rows = table_pages(name, raw)
    elif suffix == ".pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Contenido no corresponde a PDF")
        try:reader = PdfReader(BytesIO(raw))
        except (PdfReadError,OSError) as exc:raise ValueError("PDF inválido o incompleto") from exc
        if reader.is_encrypted:
            raise ValueError("PDF cifrado: proporcionar copia autorizada sin contraseña")
        if len(reader.pages) > MAX_PAGES:
            raise ValueError("PDF excede límite de 500 páginas")
        for index, page in enumerate(reader.pages, 1):
            try:
                text, error = page.extract_text() or "", None
            except Exception as exc:
                text, error = "", type(exc).__name__
            pages.append({"page": index, "text": text, "error": error,
                          "needs_ocr_or_visual_review": len(normalize(text)) < 20})
        if not pages or any(p["needs_ocr_or_visual_review"] or p["error"] for p in pages):
            status = "ADDITIONAL_PROCESSING_REQUIRED"
    elif suffix == ".txt":
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError("TXT contiene datos binarios")
        pages = [{"page": 1, "text": text, "error": None, "needs_ocr_or_visual_review": False}]
    else:
        try:
            with Image.open(BytesIO(raw)) as im:
                if im.format not in ("PNG", "JPEG") or (suffix == ".png") != (im.format == "PNG"):
                    raise ValueError("Imagen no coincide con extensión")
                im.verify()
        except (OSError,Image.DecompressionBombError) as exc:raise ValueError("Imagen inválida o excede límite de píxeles") from exc
        status = "VISUAL_REVIEW_REQUIRED_NO_OCR"
        pages = [{"page": 1, "text": "", "error": None, "needs_ocr_or_visual_review": True}]
    if sum(len(p["text"]) for p in pages) > MAX_TEXT:
        raise ValueError("Extracción excede límite de texto")
    combined = normalize(" ".join(p["text"] for p in pages)).lower()
    matches = []
    for kind, needles in {
        "supplier_quote": ("quotation", "cotización", "quote number"),
        "invoice": ("invoice number", "factura"),
        "scope_of_work": ("scope of work", "alcance del trabajo"),
        "invitation_to_bid": ("invitation to bid", "request for proposal"),
        "specifications": ("technical specifications", "especificaciones técnicas"),
        "structural_plans": ("structural plan", "plano estructural"),
        "architectural_plans": ("architectural plan", "plano arquitectónico"),
        "material_list": ("bill of materials", "lista de materiales"),
    }.items():
        found = next((n for n in needles if n in combined), None)
        if found:
            matches.append({"kind": kind, "matched_text": found})
    digest = sha256(raw).hexdigest()
    return {"document_id": digest, "sha256": digest, "original_name": name,
            "bytes": len(raw), "uploaded_at": utcnow(), "version": 1,
            "parser": PARSER_VERSION, "status": status,
            "kind": matches[0]["kind"] if len(matches) == 1 else "unclassified",
            "classification_evidence": matches, "pages": pages, "table_rows": table_rows,
            "processing_state": "PENDING_VISUAL_REVIEW" if status in ("ADDITIONAL_PROCESSING_REQUIRED", "VISUAL_REVIEW_REQUIRED_NO_OCR") else "PENDING_HUMAN_REVIEW",
            "reviewed_by": None}


def validate_evidence(state, evidence):
    if not isinstance(evidence, dict):
        raise ValueError("Se requiere evidencia con documento, página y extracto")
    doc = next((d for d in state["documents"] if d["document_id"] == evidence.get("document_id")), None)
    page = evidence.get("page")
    if not doc or type(page) is not int or not 1 <= page <= len(doc["pages"]):
        raise ValueError("Documento o página de evidencia no existe")
    excerpt = normalize(evidence.get("excerpt", ""))
    visual = evidence.get("mode") == "visual" and doc.get("reviewed_by")
    if len(excerpt) < 5 or (not visual and excerpt.casefold() not in normalize(doc["pages"][page-1]["text"]).casefold()):
        raise ValueError("Extracto no encontrado en página; revisión visual requiere responsable")
    return {**evidence, "sha256": doc["sha256"], "source_document": doc["original_name"],
            "document_version": doc["version"], "captured_at": doc["uploaded_at"]}
