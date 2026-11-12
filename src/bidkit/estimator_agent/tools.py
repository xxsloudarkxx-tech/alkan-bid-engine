"""Tools exposed to the estimator agent and their dispatcher.

The model can read, view, measure, look up and propose.  It can NOT change the
contractor's markups, burden, tax mode, commission or release/authorization:
those come from the contractor profile and are merged in by ``save_package``.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from ..package_method import PACKAGE_SCHEMA, compute, package_from_dict, result_json
from .docindex import DocIndex
from .sanity import sanity_checks

KB_DIR = Path(__file__).with_name("knowledge")


KB_TABLES = ("wages", "price_book", "productivity")


def _load_kb(name: str, override_dir: Path | None = None):
    """Knowledge table; an edited copy in ``override_dir`` (data/knowledge) wins over the built-in one."""
    if override_dir and (Path(override_dir) / name).exists():
        return json.loads((Path(override_dir) / name).read_text(encoding="utf-8"))
    return json.loads((KB_DIR / name).read_text(encoding="utf-8"))


# Stage shown in the app while the agent works, by tool.
STAGES = {"list_documents": "Inventario de documentos", "search_documents": "Fechas, requisitos y alcance",
          "read_page_text": "Lectura de specs, addenda y bid form", "view_page": "Takeoff en planos",
          "measure_on_view": "Takeoff en planos", "lookup_price": "Precios", "web_search": "Precios y tarifas (web)",
          "lookup_wage": "Mano de obra", "lookup_productivity": "Mano de obra", "record_note": "Notas para el reporte",
          "save_package": "Paquete: cálculo", "build_package": "Paquete: PDFs y verificación cruzada",
          "finish": "Reporte final"}


def merge_profile(draft: dict, profile: dict, base_dir: Path | None = None) -> dict:
    """alkan-package/1 from an estimate draft + the contractor profile.

    Everything commercial comes from the profile and overrides the draft:
    contractor identity, shop/office rates, burden, markups, tax, commission and
    release.  Used by the agent (save_package) and to re-brand an existing
    package for another contractor.
    """
    p = profile
    rates = deepcopy(draft["labor_rates"])
    for key, r in p.get("labor_rates", {}).items():   # profile rates (SHOP, ADMIN) are authoritative
        rates[key] = r
    for r in rates.values():
        if r.get("kind") == "prevailing_wage":
            r["burden_pct"] = p["burden_pct"]
    pkg = {"schema": PACKAGE_SCHEMA, "estimate_id": draft.get("estimate_id") or f"{p['estimate_prefix']}-{draft['project']['key']}-01",
           "date": p["date"], "relationship": p.get("relationship", "sub_to_gc"), "tier": p.get("tier", "competitive"),
           "contractor": dict(p["contractor"]), "project": draft["project"], "labor_rates": rates,
           "markups": p["markups"], "tax": p.get("tax", {"mode": "excluded_resale"}),
           "materials": deepcopy(draft["materials"]), "labor": draft["labor"], "other": draft["other"],
           "scope": draft["scope"], "exclusions": draft["exclusions"], "assumptions": draft.get("assumptions", []),
           "alkan_commission": p.get("alkan_commission"),
           "release": {"authorized": False, "allow_budget_prices": True,
                       "note": "Borrador generado por el agente; precios no cotizados pendientes de RFQ (decisión del contratista)."},
           "validity_days": p.get("validity_days", 30)}
    for i, m in enumerate(pkg["materials"], 1):
        m.setdefault("id", f"M{i:03d}")
    logo = pkg["contractor"].get("logo")
    if logo and base_dir and not Path(logo).is_absolute():
        pkg["contractor"]["logo"] = str((Path(base_dir) / logo).resolve())
    return pkg


TOOLS = [
    {"name": "list_documents", "description": "List every bid document (plans, specs, addenda, bid forms) with page counts, kind and sample sheet numbers. Call this first.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "search_documents", "description": "Regex search (case-insensitive) across page text. Returns doc, page, guessed sheet and a snippet; one hit per page. Use for scope words (fence|rail|bollard|grating|steel|HSS), schedules, spec sections (05 50 00), bid dates, alternates and addenda changes.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "doc": {"type": "string", "description": "Optional document name or unique fragment"}, "max_hits": {"type": "integer", "default": 40}}, "required": ["pattern"]}},
    {"name": "read_page_text", "description": "Full extracted text of one page (schedules, keynotes, spec sections, bid forms, addenda).",
     "input_schema": {"type": "object", "properties": {"doc": {"type": "string"}, "page": {"type": "integer"}}, "required": ["doc", "page"]}},
    {"name": "view_page", "description": "Render a page (or a zoomed crop, fractions [x0,y0,x1,y1] from top-left) as an image so you can read drawings. Returns view_id and pixel size; use the view_id with measure_on_view. Zoom into details instead of reading whole sheets at low resolution.",
     "input_schema": {"type": "object", "properties": {"doc": {"type": "string"}, "page": {"type": "integer"}, "crop": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4}}, "required": ["doc", "page"]}},
    {"name": "measure_on_view", "description": "Length of a polyline drawn in the pixel coordinates of a view. Give the sheet scale (scale_in_per_ft: 0.125 for 1/8\"=1'-0\"; or feet_per_inch: 20 for 1\"=20'). Alternatively give ref_p1, ref_p2 and ref_feet from a scale bar or dimension on the same view (preferred when available).",
     "input_schema": {"type": "object", "properties": {"view_id": {"type": "string"}, "points": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}, "scale_in_per_ft": {"type": "number"}, "feet_per_inch": {"type": "number"}, "ref_p1": {"type": "array", "items": {"type": "number"}}, "ref_p2": {"type": "array", "items": {"type": "number"}}, "ref_feet": {"type": "number"}}, "required": ["view_id", "points"]}},
    {"name": "lookup_wage", "description": "Washington prevailing-wage table kept by Alkan (journey-level total = wage + fringe, with source and effective date). Returns rows for a county/trade.",
     "input_schema": {"type": "object", "properties": {"county": {"type": "string"}, "trade": {"type": "string"}}, "required": ["county"]}},
    {"name": "lookup_price", "description": "Search Alkan's price book (past estimates and supplier quotes) by keywords. Returns unit price, unit, basis (QUOTE/CATALOG/BUDGET), source and date. Prefer QUOTE rows; otherwise use web_search and mark the line BUDGET.",
     "input_schema": {"type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"]}},
    {"name": "lookup_productivity", "description": "Alkan labor productivity norms (hours per unit by task) used in past estimates.",
     "input_schema": {"type": "object", "properties": {"keywords": {"type": "string"}}}},
    {"name": "record_note", "description": "Record a fact for the final report: a key date (bid due, questions, substitutions — check every addendum for extensions), a requirement to be able to bid (mandatory pre-bid meeting or site visit, bid bond, registration, forms, licenses), a risk, an assumption, an open question, a scope note or a contact (owner, prime/GC).",
     "input_schema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["date", "requirement", "risk", "assumption", "question", "scope", "contact"]}, "text": {"type": "string"}, "source": {"type": "string"}}, "required": ["kind", "text", "source"]}},
    {"name": "save_package", "description": "Save the estimate as an alkan-package/1 draft. Provide project, labor_rate_keys, materials, labor, other, scope, exclusions, assumptions. Contractor data, markups, burden, tax, commission and release are filled from the contractor profile and cannot be set here. Numbers must be strings. Returns totals and validation (blockers/warnings).",
     "input_schema": {"type": "object", "properties": {
         "project": {"type": "object", "description": "key, short, title, owner, owner_contact, project_no, site, county, prime_contractor, bid_date, wage_basis, scope_label, documents[]"},
         "labor_rates": {"type": "object", "description": "Map KEY -> {label, kind:'prevailing_wage'|'loaded', trade, rate, source}. Use lookup_wage for prevailing wage; use profile keys SHOP/ADMIN as given."},
         "materials": {"type": "array", "items": {"type": "object"}, "description": "{section, item, spec, qty, unit, unit_price, price_basis, price_source, qty_source}"},
         "labor": {"type": "array", "items": {"type": "object"}, "description": "{task, rate (key), hours}"},
         "other": {"type": "array", "items": {"type": "object"}, "description": "{item, category: Equipment|Mobilization|Fees|Other|Subcontract, qty, unit, rate}"},
         "scope": {"type": "array", "items": {"type": "object"}, "description": "{title, text}"},
         "exclusions": {"type": "array", "items": {"type": "string"}},
         "assumptions": {"type": "array", "items": {"type": "string"}}},
         "required": ["project", "labor_rates", "materials", "labor", "other", "scope", "exclusions"]}},
    {"name": "build_package", "description": "Render the 3 PDFs (01 cost analysis, 02 material list, 03 proposal) from the saved package and run the cross-document QA. Fix and re-save if QA fails.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "finish", "description": "End the run with the final report for the estimator (Spanish): summary, sell price, key dates, top risks and what a human must verify before sending. decision: GO (package built and QA PASS), GO_WITH_CONDITIONS (package built, but something must happen before bidding — say what), or NO_GO (a mandatory requirement can no longer be met, e.g. a mandatory pre-bid meeting already held; no package needed, but record_note kind=requirement with the source first).",
     "input_schema": {"type": "object", "properties": {"decision": {"type": "string", "enum": ["GO", "GO_WITH_CONDITIONS", "NO_GO"]}, "summary": {"type": "string"}, "must_verify": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "must_verify"]}},
]


def web_search_tool(max_uses: int = 15, tool_type: str = "web_search_20250305") -> dict:
    return {"type": tool_type or "web_search_20250305", "name": "web_search", "max_uses": max_uses}


class ToolBox:
    def __init__(self, index: DocIndex, profile: dict, out_dir: Path, base_dir: Path | None = None,
                 knowledge_dir: Path | None = None, price_deviation_pct: int = 35):
        self.index, self.profile, self.out_dir = index, profile, Path(out_dir)
        self.base_dir = base_dir
        self.notes: list[dict] = []
        self.package_path: Path | None = None
        self.last_build: dict | None = None
        self.last_sanity: list[dict] = []
        self.key: str | None = None            # run key; when set, the package and its files always use it
        self.price_deviation_pct = price_deviation_pct
        self.images = 0
        self.wages = _load_kb("wages.json", knowledge_dir)
        self.prices = _load_kb("price_book.json", knowledge_dir)
        self.productivity = _load_kb("productivity.json", knowledge_dir)
        extra = profile.get("price_book")
        if extra and Path(extra).exists():
            self.prices += json.loads(Path(extra).read_text(encoding="utf-8"))

    def tool_defs(self) -> list[dict]:
        return TOOLS

    # Each tool returns (content, is_error).  Content is a str or a list of content blocks.
    def call(self, name: str, args: dict):
        try:
            fn = getattr(self, f"t_{name}")
        except AttributeError:
            return f"Herramienta desconocida: {name}", True
        try:
            return fn(**args), False
        except (ValueError, KeyError, TypeError) as exc:
            return f"ERROR: {exc}", True

    def t_list_documents(self):
        return json.dumps(self.index.listing(), ensure_ascii=False)

    def t_search_documents(self, pattern, doc=None, max_hits=40):
        hits = self.index.search(pattern, doc, min(int(max_hits), 80))
        return json.dumps({"hits": hits, "count": len(hits)}, ensure_ascii=False)

    def t_read_page_text(self, doc, page):
        return json.dumps(self.index.page_text(doc, int(page)), ensure_ascii=False)

    def t_view_page(self, doc, page, crop=None):
        view, b64 = self.index.render(doc, int(page), crop)
        self.images += 1
        meta = {"view_id": view.view_id, "doc": view.doc, "page": view.page, "width_px": view.width_px,
                "height_px": view.height_px, "crop": crop or [0, 0, 1, 1]}
        return [{"type": "text", "text": json.dumps(meta)},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]

    def t_measure_on_view(self, view_id, points, scale_in_per_ft=None, feet_per_inch=None, ref_p1=None, ref_p2=None, ref_feet=None):
        if ref_p1 and ref_p2 and ref_feet:
            return json.dumps(self.index.calibrate(view_id, ref_p1, ref_p2, float(ref_feet), points))
        return json.dumps(self.index.measure(view_id, points, scale_in_per_ft, feet_per_inch))

    def t_lookup_wage(self, county, trade=""):
        rows = [w for w in self.wages if w["county"].lower() == county.lower()
                and (not trade or trade.lower() in (w["trade"] + " " + w["classification"]).lower())]
        return json.dumps({"rows": rows, "note": "Si no hay fila o la fecha es vieja, búsquelo en L&I con web_search y cite la fuente."}, ensure_ascii=False)

    def t_lookup_price(self, keywords):
        words = [w for w in re.split(r"\W+", keywords.lower()) if len(w) > 1]
        scored = []
        for p in self.prices:
            hay = (p["item"] + " " + p.get("spec", "")).lower()
            s = sum(1 for w in words if w in hay)
            if s:
                scored.append((s, p))
        scored.sort(key=lambda x: (-x[0], {"QUOTE": 0, "CATALOG": 1, "BUDGET": 2}.get(x[1].get("price_basis"), 3)))
        return json.dumps({"rows": [p for _, p in scored[:12]]}, ensure_ascii=False)

    def t_lookup_productivity(self, keywords=""):
        words = [w for w in re.split(r"\W+", keywords.lower()) if len(w) > 2]
        rows = [r for r in self.productivity if not words or any(w in r["task"].lower() for w in words)]
        return json.dumps({"rows": rows[:40]}, ensure_ascii=False)

    def t_record_note(self, kind, text, source):
        self.notes.append({"kind": kind, "text": text, "source": source})
        return "ok"

    def _merge(self, draft: dict) -> dict:
        return merge_profile(draft, self.profile, self.base_dir)

    def t_save_package(self, **draft):
        if self.key:
            draft["project"] = {**draft["project"], "key": self.key}
        pkg = self._merge(draft)
        r = compute(package_from_dict(pkg))          # raises ValueError with blockers
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.package_path = self.out_dir / f"{pkg['project']['key'].lower()}.json"
        self.package_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
        res = result_json(package_from_dict(pkg), r)
        return json.dumps({"saved": str(self.package_path), "status": res["status"], "totals": res["totals"],
                           "sections": res["sections"], "hours_by_trade": res["hours_by_trade"],
                           "validation": res["validation"]}, ensure_ascii=False)

    def t_build_package(self):
        if not self.package_path:
            raise ValueError("primero save_package")
        from ..package_build import build
        m = build(self.package_path, self.out_dir)
        self.last_build = m
        fails = [c for c in m["qa"]["checks"] if c["result"] != "PASS"]
        pkg = json.loads(self.package_path.read_text(encoding="utf-8"))
        self.last_sanity = sanity_checks(pkg, m["computation"]["totals"], self.prices, self.price_deviation_pct)
        return json.dumps({"qa": m["qa"]["status"], "failures": fails, "files": {k: v["path"] for k, v in m["files"].items()},
                           "proposal": m["proposal_release"], "sanity": self.last_sanity,
                           "sanity_note": "Corrija lo que sea un error real y vuelva a guardar y construir; lo que sea correcto, "
                                          "déjelo y explíquelo en must_verify."}, ensure_ascii=False)

    def t_finish(self, summary, must_verify, decision="GO"):
        return "FINISHED"
