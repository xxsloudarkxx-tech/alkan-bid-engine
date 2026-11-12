from __future__ import annotations

import hashlib
import re
from pathlib import Path
from importlib.metadata import version

from pypdf import PdfReader
import pypdfium2 as pdfium

from .config import ProjectConfig
from .data_store import read_json, write_json

EXTRACTOR = "pypdfium2-" + version("pypdfium2") + "-bounded-v1"
KEYWORDS = {
    "bid_security": ["bid bond", "bid security"],
    "insurance": ["insurance"],
    "wages": ["prevailing wage"],
    "sales_tax": ["sales tax"],
    "bid_deadline": ["bid opening", "bids will be received", "bids due"],
    "addendum": ["addendum", "addenda"],
    "quantities": ["bid schedule", "schedule of prices", "plant schedule", "quantity"],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(name: str) -> str:
    lowered = name.lower()
    for kind, needles in {"addendum": ("addendum", "add "), "drawings": ("plans", "drawings"), "specifications": ("spec",), "appendices": ("append",)}.items():
        if any(n in lowered for n in needles):
            return kind
    return "other"


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extraction(config: ProjectConfig, source: Path, digest: str | None = None) -> dict:
    digest = digest or sha256(source)
    path = config.data_dir / "extractions" / f"{digest}.json"
    if path.exists():
        cached = read_json(path)
        if cached.get("extractor") == EXTRACTOR and cached.get("sha256") == digest:
            return cached
    reader = pdfium.PdfDocument(str(source))
    pages = []
    for index in range(len(reader)):
        error = None
        try:
            page = reader[index]
            textpage = page.get_textpage()
            text = textpage.get_text_bounded() or ""
            textpage.close()
            page.close()
        except Exception as exc:
            text, error = "", str(exc)
        pages.append({"page": index+1, "text": text, "error": error, "needs_visual_review": len(normalize(text)) < 40})
    reader.close()
    payload = {"sha256": digest, "extractor": EXTRACTOR, "encrypted": PdfReader(str(source)).is_encrypted, "pages": pages}
    write_json(path, payload)
    return payload


def audit(config: ProjectConfig) -> dict:
    if not config.source_files:
        raise FileNotFoundError(f"No hay PDFs en {config.source_root}")
    manifest_path = config.audit_dir / "document_inventory.json"
    if manifest_path.exists():
        failures = [r for r in validate_source_integrity(config) if r["status"] != "PASS"]
        if failures:
            raise ValueError("Cambió el expediente desde la auditoría; revise la línea base explícitamente: " + str(failures))
        old = read_json(manifest_path)
        if all(d.get("extraction_sha256") or d["pages"] is None for d in old["documents"]):
            errors = validate_extractions(config)
            if errors:
                raise ValueError("; ".join(errors))
    documents, evidence = [], {key: [] for key in KEYWORDS}
    for source in config.source_assets:
        digest = sha256(source)
        name = source.relative_to(config.source_root).as_posix()
        item = {"name": name, "path": source.relative_to(config.root).as_posix(), "bytes": source.stat().st_size, "sha256": digest, "kind": classify(name), "pages": None, "extraction_errors": [], "visual_review_pages": []}
        if source.suffix.lower() == ".pdf":
            extracted = extraction(config, source, digest)
            item.update(pages=len(extracted["pages"]), encrypted=extracted["encrypted"], extraction_sha256=sha256(config.data_dir / "extractions" / f"{digest}.json"))
            for page in extracted["pages"]:
                if page["error"]:
                    item["extraction_errors"].append({"page": page["page"], "error": page["error"]})
                if page["needs_visual_review"]:
                    item["visual_review_pages"].append(page["page"])
                compact = normalize(page["text"])
                for key, needles in KEYWORDS.items():
                    indexes = [compact.lower().find(n) for n in needles if n in compact.lower()]
                    if indexes:
                        idx = min(indexes)
                        evidence[key].append({"document": name, "page": page["page"], "sha256": digest, "excerpt": compact[max(0, idx-80):idx+450], "status": "CANDIDATE_REQUIRES_REVIEW"})
        else:
            item["kind"] = "supporting_unextracted"
        documents.append(item)
    payload = {"project": config.metadata, "documents": documents, "evidence": evidence, "policy": "Local inventory only; completeness against the owner's portal is not certified."}
    write_json(manifest_path, payload)
    return payload


def load_audit(config: ProjectConfig) -> dict:
    path = config.audit_dir / "document_inventory.json"
    return read_json(path) if path.exists() else audit(config)


def validate_source_integrity(config: ProjectConfig) -> list[dict]:
    path = config.audit_dir / "document_inventory.json"
    if not path.exists():
        return [{"document": "manifest", "status": "FAIL", "reason": "Audit baseline missing"}]
    manifest = read_json(path)
    expected = {item["path"]: item for item in manifest["documents"]}
    current = {p.relative_to(config.root).as_posix(): p for p in config.source_assets}
    results = []
    for name in sorted(set(expected) | set(current)):
        actual = sha256(current[name]) if name in current else "MISSING"
        digest = expected[name]["sha256"] if name in expected else "NOT_IN_MANIFEST"
        results.append({"document": name, "expected": digest, "actual": actual, "status": "PASS" if actual == digest else "FAIL"})
    return results


def validate_extractions(config: ProjectConfig) -> list[str]:
    errors = []
    for doc in load_audit(config)["documents"]:
        if doc["pages"] is None:
            continue
        path = config.data_dir / "extractions" / f"{doc['sha256']}.json"
        if not path.exists() or sha256(path) != doc.get("extraction_sha256"):
            errors.append(f"Extracción ausente o modificada: {doc['name']}")
    return errors


def render_page(config: ProjectConfig, document: str, page: int, scale: float = 1.5) -> Path:
    doc = next(d for d in load_audit(config)["documents"] if d["name"] == document)
    if sha256(config.root / doc["path"]) != doc["sha256"]:
        raise ValueError("No se puede renderizar una fuente modificada.")
    pdf = pdfium.PdfDocument(str(config.root / doc["path"]))
    rendered = pdf[page-1]
    bitmap = rendered.render(scale=scale)
    destination = config.data_dir / "review" / f"{Path(document).stem}-{page}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    bitmap.to_pil().save(destination)
    bitmap.close()
    rendered.close()
    pdf.close()
    write_json(destination.with_suffix(".json"), {"document": document, "page": page, "source_sha256": doc["sha256"], "image_sha256": sha256(destination), "scale": scale, "renderer": "pypdfium2-" + version("pypdfium2")})
    return destination
