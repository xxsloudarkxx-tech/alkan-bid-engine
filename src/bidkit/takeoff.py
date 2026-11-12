from __future__ import annotations

from .audit import audit
from .config import ProjectConfig
from .data_store import write_json
from .project_schema import input_fingerprint, require_valid_analysis


def document_candidates(document):
    """Conservative explicit quantities only. Never infer drawing scale or approval."""
    import re
    from decimal import Decimal
    candidates, mentions = [], []
    units = r"(?:linear\s+feet|square\s+feet|cubic\s+yards|pies\s+lineales|pies\s+cuadrados|yardas\s+c[uú]bicas|feet|foot|ft|pies|LF|EA|SF|CY|HR|H|IN|SY|CF|M)\b"
    expression = re.compile(r"(\d+(?:\.\d+)?(?:\s*\+\s*\d+(?:\.\d+)?)+)\s*(" + units + r")", re.I)
    single = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(" + units + r")", re.I)
    for page in document["pages"]:
        for text in page["text"].splitlines():
            reference = {"document_id": document["document_id"], "page": page["page"], "excerpt": text.strip(),
                         "document_version": document["version"], "captured_at": document["uploaded_at"]}
            lower = text.lower()
            for category, words in {"demolition": ("demolition", "demolición", "demoler"),
                                    "gates": ("gate", "portón", "portones"),
                                    "gravel": ("gravel", "grava"),
                                    "transport": ("transport", "delivery", "transporte"),
                                    "disposal": ("disposal", "waste", "residuos"),
                                    "specification": ("specification", "especificación", "design change", "cambio de diseño")}.items():
                if any(word in lower for word in words):
                    mentions.append({"category": category, "evidence": reference})
            def scope_for(unit):
                if any(w in lower for w in ("demolition", "demolición", "remove existing", "demoler")): return "demolition_length"
                if any(w in lower for w in ("hog wire", "hog-wire")): return "fence_hog_wire_length"
                if any(w in lower for w in ("cedar", "cedro")): return "fence_cedar_length"
                if any(w in lower for w in ("gravel", "grava")): return "gravel_" + ("area" if unit == "SF" else "volume")
                if any(w in lower for w in ("fence", "cerca")): return "fence_length"
                if any(w in lower for w in ("gate", "portón", "portones")): return "gate_double" if any(w in lower for w in ("double", "doble")) else "gate_single"
                return ""
            def canonical(unit):
                v=unit.lower()
                if v in ("feet", "foot", "ft", "pies", "lf", "linear feet", "pies lineales"): return "LF"
                if v in ("square feet", "pies cuadrados"): return "SF"
                if v in ("cubic yards", "yardas cúbicas"): return "CY"
                return unit.upper()
            def enrich(row):
                unit=canonical(row["unit"]); scope=scope_for(unit)
                category="other" if scope.startswith("demolition") else "material"
                aggregate=any(w in lower for w in ("combined", "combinada", "combinado", "total new fence"))
                return {**row, "unit":unit, "scope_key": "fence_combined_check" if aggregate else scope,
                        "category":category, "active":not aggregate, "data_type":"quantity", "assumptions":[],
                        "document_date":document.get("document_date"), "document_version":document["version"]}
            for match in expression.finditer(text):
                operands = re.findall(r"\d+(?:\.\d+)?", match[1])
                candidates.append(enrich({"description": text.strip(), "quantity": str(sum(Decimal(n) for n in operands)),
                                   "unit": match[2],
                                   "quantity_status": "CALCULATED_FROM_MEASUREMENTS", "calculation": {"operation": "sum", "operands": operands},
                                   "evidence": reference}))
            cleaned = expression.sub("", text)
            for match in single.finditer(cleaned):
                candidates.append(enrich({"description": text.strip(), "quantity": match[1],
                                   "unit": match[2],
                                   "quantity_status": "AUTO_EXTRACTED", "evidence": reference,
                                   }))
    return candidates, mentions


def document_facts(document):
    """Commercial amounts remain commercial observations, never execution costs."""
    import re
    from datetime import datetime
    from .estimator_v1 import _decimal
    facts=[]
    for page in document["pages"]:
        for text in page["text"].splitlines():
            for match in re.finditer(r"\b(subtotal|tax|impuesto|total)\s*:?\s*(?:\$\s*(?P<dollar>[0-9][0-9,]*(?:\.\d{1,2})?)|(?P<usd>[0-9][0-9,]*(?:\.\d{1,2})?)\s*USD\b)",text,re.I):
                value=str(_decimal((match['dollar'] or match['usd']).replace(",",""),"commercial amount"))
                facts.append({"data_type":"commercial_"+match[1].lower(),"value":value,"unit":"USD" if match['usd'] else "DOLLAR_CURRENCY_PENDING",
                    "review_status":"PENDING_HUMAN_REVIEW","document_id":document["document_id"],"page":page["page"],
                    "excerpt":text.strip(),"sha256":document["sha256"],"document_version":document["version"],"captured_at":document["uploaded_at"]})
            for fmt,pattern in (("%Y-%m-%d",r"\b\d{4}-\d{2}-\d{2}\b"),("%B %d, %Y",r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b")):
                for token in re.findall(pattern,text):
                    try: value=datetime.strptime(token,fmt).date().isoformat()
                    except ValueError: continue
                    facts.append({"data_type":"document_date","value":value,"unit":None,"document_id":document["document_id"],
                                  "page":page["page"],"excerpt":text.strip(),"sha256":document["sha256"],"document_version":document["version"],
                                  "captured_at":document["uploaded_at"],"review_status":"PENDING_HUMAN_REVIEW"})
    return facts


def takeoff(config: ProjectConfig) -> dict:
    audit(config)
    analysis = require_valid_analysis(config)
    quantities = {r["id"]: r for r in analysis["quantities"]}
    materials = []
    for material in analysis["materials"]:
        row = dict(material)
        quantity = quantities.get(row.get("quantity_id"), {})
        row.update(quantity=quantity.get("quantity"), quantity_status=quantity.get("quantity_status", "PENDING_MEASUREMENT"))
        materials.append(row)
    payload = {"project_id": config.id, "input_fingerprint": input_fingerprint(config, analysis), "scope_status": analysis["scope_status"], "records": analysis["quantities"], "materials": materials}
    write_json(config.data_dir / "takeoff" / "takeoff.json", payload)
    return payload
