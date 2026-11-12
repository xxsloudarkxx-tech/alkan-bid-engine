"""Bid-document index for the estimator agent.

Ingests a project folder or ZIP (plans, specs, addenda, bid forms), caches the
text of every page, guesses sheet numbers, and renders pages / crops to PNG for
vision.  Uses pypdfium2 only (no poppler), so it runs the same on Windows.

Original files are never modified: ZIPs are extracted to a cache folder and
every document is fingerprinted (SHA-256).
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

SHEET_RE = re.compile(r"\b([A-Z]{1,3}\d{0,2}[.-]\d{1,3}(?:\.\d)?)\b")
ADDENDUM_RE = re.compile(r"(?<![a-z])add(?:endum)?[\s_#.\-]*\d", re.I)
MAX_IMAGE_PX = 1568          # long-edge limit that keeps vision detail without waste


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class View:
    """A rendered image of (part of) a page; needed to convert pixels to feet."""
    view_id: str
    doc: str
    page: int
    left: float      # crop box in PDF points (origin top-left, y down)
    top: float
    px_per_pt: float
    width_px: int
    height_px: int


@dataclass
class DocIndex:
    root: Path
    cache: Path
    docs: dict = field(default_factory=dict)       # name -> {path, pages, sha256, kind, size_pt}
    views: dict = field(default_factory=dict)

    # ───────────────────────────────────────────────── build
    @classmethod
    def build(cls, source: str | Path, cache_dir: str | Path) -> "DocIndex":
        source, cache = Path(source).resolve(), Path(cache_dir).resolve()
        cache.mkdir(parents=True, exist_ok=True)
        root = source
        if source.is_file() and source.suffix.lower() == ".zip":
            root = cache / "extracted"
            if not root.exists():
                root.mkdir(parents=True)
                with zipfile.ZipFile(source) as z:
                    for info in z.infolist():
                        name = Path(info.filename.replace("\\", "/").lstrip("/"))
                        if info.is_dir() or ".." in name.parts or name.suffix.lower() != ".pdf":
                            continue
                        target = root / name.name
                        with z.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
        idx = cls(root=root, cache=cache)
        manifest = cache / "index.json"
        old = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        for pdf in sorted(root.rglob("*.pdf")):
            name = pdf.relative_to(root).as_posix()
            sha = _sha(pdf)
            if old.get(name, {}).get("sha256") == sha and (cache / "text" / f"{sha}.json").exists():
                idx.docs[name] = old[name]
                idx.docs[name]["path"] = str(pdf)
                continue
            idx.docs[name] = idx._extract(pdf, name, sha)
        manifest.write_text(json.dumps(idx.docs, indent=1), encoding="utf-8")
        return idx

    def _extract(self, pdf: Path, name: str, sha: str) -> dict:
        doc = pdfium.PdfDocument(str(pdf))
        pages, sheets = [], []
        w, h = doc[0].get_size() if len(doc) else (0, 0)
        for i in range(len(doc)):
            page = doc[i]
            try:
                text = page.get_textpage().get_text_range()
            except Exception:  # noqa: BLE001 - scanned or broken page
                text = ""
            pages.append(text)
            sheets.append(_guess_sheet(text))
        doc.close()
        (self.cache / "text").mkdir(exist_ok=True)
        (self.cache / "text" / f"{sha}.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
        kind = "addendum" if ADDENDUM_RE.search(name) else ("plans" if w > 1000 else "document")
        return {"path": str(pdf), "pages": len(pages), "sha256": sha, "kind": kind,
                "size_pt": [round(w), round(h)], "sheets": sheets,
                "no_text_pages": sum(1 for p in pages if len(p.strip()) < 30)}

    # ───────────────────────────────────────────────── queries
    def _pages(self, name: str) -> list[str]:
        d = self.docs[name]
        return json.loads((self.cache / "text" / f"{d['sha256']}.json").read_text(encoding="utf-8"))["pages"]

    def resolve(self, doc: str) -> str:
        if doc in self.docs:
            return doc
        hits = [n for n in self.docs if doc.lower() in n.lower()]
        if len(hits) == 1:
            return hits[0]
        raise ValueError(f"Documento '{doc}' no encontrado o ambiguo; opciones: {list(self.docs)[:20]}")

    def listing(self) -> list[dict]:
        return [{"doc": n, "kind": d["kind"], "pages": d["pages"], "page_size_pt": d["size_pt"],
                 "pages_without_text": d["no_text_pages"],
                 "sheets_sample": [s for s in d["sheets"] if s][:12]} for n, d in self.docs.items()]

    def search(self, pattern: str, doc: str | None = None, max_hits: int = 40, context: int = 120) -> list[dict]:
        try:
            rx = re.compile(pattern, re.I)
        except re.error as exc:
            raise ValueError(f"Regex inválida: {exc}") from None
        out = []
        names = [self.resolve(doc)] if doc else list(self.docs)
        for name in names:
            sheets = self.docs[name]["sheets"]
            for i, text in enumerate(self._pages(name), 1):
                for m in rx.finditer(text):
                    a, b = max(0, m.start() - context), min(len(text), m.end() + context)
                    out.append({"doc": name, "page": i, "sheet": sheets[i - 1],
                                "snippet": re.sub(r"\s+", " ", text[a:b])})
                    if len(out) >= max_hits:
                        return out
                    break  # one hit per page keeps results broad
        return out

    def page_text(self, doc: str, page: int, max_chars: int = 12000) -> dict:
        name = self.resolve(doc)
        pages = self._pages(name)
        if not 1 <= page <= len(pages):
            raise ValueError(f"Página fuera de rango (1–{len(pages)})")
        t = re.sub(r"[ \t]+", " ", pages[page - 1])
        return {"doc": name, "page": page, "sheet": self.docs[name]["sheets"][page - 1],
                "truncated": len(t) > max_chars, "text": t[:max_chars]}

    def render(self, doc: str, page: int, crop: list[float] | None = None, max_px: int = MAX_IMAGE_PX) -> tuple[View, str]:
        """Render a page or a crop (fractions [x0,y0,x1,y1] of the page) to base64 PNG."""
        name = self.resolve(doc)
        pdf = pdfium.PdfDocument(self.docs[name]["path"])
        if not 1 <= page <= len(pdf):
            raise ValueError(f"Página fuera de rango (1–{len(pdf)})")
        pg = pdf[page - 1]
        W, H = pg.get_size()
        x0, y0, x1, y1 = crop or [0, 0, 1, 1]
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("crop debe ser [x0,y0,x1,y1] en fracciones 0–1 con x0<x1, y0<y1")
        cw, ch = (x1 - x0) * W, (y1 - y0) * H
        scale = min(max_px / max(cw, ch), 6.0)        # px per PDF point
        img = pg.render(scale=scale, crop=(x0 * W, (1 - y1) * H, (1 - x1) * W, y0 * H)).to_pil()
        pdf.close()
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG", optimize=True)
        vid = f"v{len(self.views) + 1}"
        view = View(vid, name, page, x0 * W, y0 * H, scale, img.width, img.height)
        self.views[vid] = view
        return view, base64.b64encode(buf.getvalue()).decode()

    def measure(self, view_id: str, points: list[list[float]], scale_in_per_ft: float | None = None,
                feet_per_inch: float | None = None) -> dict:
        """Length of a polyline drawn on a rendered view, converted with the drawing scale.

        Scale as on the sheet: 1/8"=1'-0" -> scale_in_per_ft=0.125; 1"=20' -> feet_per_inch=20.
        Assumes the PDF is plotted at true sheet size (72 points per inch).
        """
        v = self.views.get(view_id)
        if not v:
            raise ValueError("view_id desconocido; use view_page primero")
        if len(points) < 2:
            raise ValueError("Se requieren al menos 2 puntos")
        if feet_per_inch is None:
            if not scale_in_per_ft:
                raise ValueError("Indique scale_in_per_ft (p.ej. 0.25 para 1/4\"=1') o feet_per_inch (p.ej. 20 para 1\"=20')")
            feet_per_inch = 1 / scale_in_per_ft
        px = sum(((points[i + 1][0] - points[i][0]) ** 2 + (points[i + 1][1] - points[i][1]) ** 2) ** 0.5
                 for i in range(len(points) - 1))
        inches = px / v.px_per_pt / 72
        return {"view_id": view_id, "pixels": round(px, 1), "paper_inches": round(inches, 3),
                "feet": round(inches * feet_per_inch, 2), "feet_per_inch": feet_per_inch,
                "note": "Verifique contra una cota conocida o la barra de escala; si el PDF no está a tamaño real, use calibrate."}

    def calibrate(self, view_id: str, p1: list[float], p2: list[float], known_feet: float, points: list[list[float]]) -> dict:
        """Measure using a known dimension on the same view (scale bar or dimension string)."""
        v = self.views.get(view_id)
        if not v:
            raise ValueError("view_id desconocido")
        ref = ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5
        if ref <= 0 or known_feet <= 0:
            raise ValueError("Referencia inválida")
        px = sum(((points[i + 1][0] - points[i][0]) ** 2 + (points[i + 1][1] - points[i][1]) ** 2) ** 0.5
                 for i in range(len(points) - 1))
        return {"view_id": view_id, "feet": round(px / ref * known_feet, 2), "ref_pixels": round(ref, 1),
                "ft_per_pixel": round(known_feet / ref, 5)}


def _guess_sheet(text: str) -> str:
    """Most likely sheet number: the title-block id usually appears near the end of the page text."""
    tail = text[-1500:]
    c = Counter(m.group(1) for m in SHEET_RE.finditer(tail))
    cands = [s for s, _ in c.most_common() if not re.match(r"^\d", s)]
    return cands[-1] if cands else ""
