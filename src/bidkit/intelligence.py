"""Estimate Intelligence V2: one dossier, evidence, human review, immutable versions."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from math import prod

from .data_store import fingerprint, read_json
from .estimator_v1 import calculate, _decimal, _fmt, _date
from .intelligence_documents import parse_document, validate_evidence
from .intelligence_store import DossierStore, RevisionConflict, utcnow
from .takeoff import document_candidates, document_facts
from .costing import conversion
from .price_catalog import price_record, PRICE_TYPES

WORK_TYPES = {"residential", "commercial", "industrial", "public_works", "other"}
RELATIONSHIPS = {"direct_homeowner", "commercial_owner", "general_contractor", "subcontractor", "public_entity"}
QUANTITY_STATES = {"AUTO_EXTRACTED", "CALCULATED_FROM_MEASUREMENTS", "PENDING_VERIFICATION", "MANUALLY_CORRECTED", "CONFIRMED_WITH_EVIDENCE"}
QUOTE_KINDS = {"historical", "catalog", "formal_quote", "phone_confirmed", "invoice_actual"}
CATEGORIES = {"material", "labor", "equipment", "subcontract", "logistics", "disposal", "tax", "other"}


def basis(state):
    return fingerprint({k: v for k, v in state.items() if k not in ("result", "approvals", "current_approval", "deliveries", "workflow")})


def difference(before, after):
    changes = []
    for group, key in (("lines", "line_id"), ("quotes", "quote_id"), ("documents", "document_id")):
        old = {r[key]: r for r in before.get(group, [])}; new = {r[key]: r for r in after.get(group, [])}
        for rid in sorted(old.keys() | new.keys()):
            if old.get(rid) != new.get(rid):
                changes.append({"group": group, "id": rid, "before": old.get(rid), "after": new.get(rid)})
    for group in ("project", "financial", "review", "resolutions", "requirements", "change_orders", "catalog_entries", "actual_costs", "contracts", "workflow"):
        if before.get(group) != after.get(group):
            changes.append({"group": group, "before": before.get(group), "after": after.get(group)})
    a = before.get("result", {}).get("totals", {}); b = after.get("result", {}).get("totals", {})
    deltas = {k: _fmt(Decimal(b[k]) - Decimal(a[k])) for k in b if a.get(k) is not None and b.get(k) is not None}
    return {"changes": changes, "financial_delta": deltas}


class Intelligence:
    def __init__(self, root):
        self.store = DossierStore(Path(root))

    def list_projects(self):
        result = []
        for path in sorted((self.store.root / "projects").glob("*/project.json")):
            p = read_json(path); meta = p.get("metadata", p)
            pid = meta.get("id", meta.get("project_id", path.parent.name))
            result.append({"project_id": pid, "name": meta.get("name", meta.get("project_name", pid)),
                           "integrated": (path.parent / "intelligence/revisions").exists()})
        return result

    def catalog(self, query="", trade=""):
        """Read-only projection of canonical dossier revisions, including price history."""
        rows=[]
        for project in self.list_projects():
            if not project["integrated"]: continue
            state=self.store.load(project["project_id"])["state"]
            for source, records in (("catalog_entries",state.get("catalog_entries",[])),("quotes",state["quotes"])):
                superseded={r.get("supersedes") for r in records}
                for record in records:
                    rid=record.get("entry_id",record.get("quote_id"))
                    item={**record,"source_project_id":project["project_id"],"source_type":source,"record_id":rid,
                          "is_superseded":rid in superseded,"project_work_type":state["project"]["work_type"]}
                    haystack=" ".join(str(item.get(k) or "") for k in ("product_name","description","sku","brand","supplier","provider","specification","location")).lower()
                    if query.lower() in haystack and (not trade or trade.lower()==str(item.get("trade","")).lower()): rows.append(item)
        return rows

    def attach_catalog(self,pid,revision,actor,p):
        self.store.directory(p["source_project_id"])
        source=self.store.load(p["source_project_id"])["state"]
        group=p.get("source_type","catalog_entries")
        if group not in ("quotes","catalog_entries"): raise ValueError("Origen de catálogo inválido")
        record=next(r for r in source.get(group,[]) if r.get("entry_id",r.get("quote_id"))==p["record_id"])
        target=self.store.load(pid)
        if target["revision"]!=revision: raise RevisionConflict("Recargue antes de vincular precio")
        ev=record.get("evidence_reference")
        if not ev: raise ValueError("Precio sin documento: registre evidencia antes de reutilizarlo")
        self.check_originals(p["source_project_id"],source)
        doc=next(d for d in source["documents"] if d["document_id"]==ev["document_id"])
        if p["source_project_id"]!=pid:
            raw=(self.store.directory(p["source_project_id"])/"originals"/doc["stored_name"]).read_bytes()
            target=self.upload(pid,revision,actor,[(doc["original_name"],raw)])
        return self.transact(pid,target["revision"],actor,"catalog_quote",{**p,"record":record})

    def actual_analysis(self,trade="",work_type="",provider=""):
        """Documented actuals grouped for review; no automatic attribution or price learning."""
        rows=[]
        for project in self.list_projects():
            if not project["integrated"]:continue
            state=self.store.load(project["project_id"])["state"];p=state["project"]
            if trade and trade.casefold()!=p["trade"].casefold():continue
            if work_type and work_type!=p["work_type"]:continue
            actual=self.evaluate(state,include_impacts=False)["actual_vs_estimated"]
            for group in actual["groups"]:
                if provider.casefold() not in group["provider"].casefold():continue
                rows.append({**group,"project_id":project["project_id"],"project_name":p["name"],"trade":p["trade"],"work_type":p["work_type"],
                             "estimated_project_cost":actual["estimated_cost"],"project_documented_actual":actual["actual_documented_cost"],
                             "project_variance":actual["variance"],"coverage":actual["coverage"]})
        return rows

    def create(self, project, actor, project_id=None):
        project = deepcopy(project)
        if not str(project.get("name", "")).strip() or project.get("work_type") not in WORK_TYPES or project.get("contractual_relationship") not in RELATIONSHIPS:
            raise ValueError("Nombre, tipo de obra y relación contractual independientes son obligatorios")
        pid = project_id or str(uuid4())
        project.update(project_id=pid, received_at=project.get("received_at") or utcnow(), currency="USD")
        for key in ("address", "state", "county", "jurisdiction", "client", "contractor", "trade", "estimator", "request_date", "due_date", "next_action"):
            project.setdefault(key, "")
        state = {"schema_version": "2.0", "project": project, "documents": [], "lines": [], "suppliers": [], "quotes": [],
                 "requirements": [], "mentions": [], "resolutions": [], "change_orders": [], "contracts": [], "approvals": [], "current_approval": None, "deliveries": [],
                 "financial": {"overhead_percent": None, "contingency_percent": None, "target_margin_percent": None,
                               "confirmed": False, "pricing_method": "margin", "sensitivity_percent": "5"},
                 "review": {"scope_confirmed": False, "tax_reviewed": False, "tax_basis": "", "company_confirmed": False,
                            "terms": "", "valid_until": "", "assumptions": "", "exclusions": ""}}
        with self.store.locked(pid):
            if (self.store.directory(pid) / "revisions").exists():
                raise RevisionConflict("El proyecto ya tiene expediente V2")
            state["result"] = self.evaluate(state)
            row = self.store.append(pid, state, 0, actor, "PROJECT_CREATED")
            config = self.store.root / "projects" / pid / "project.json"
            if not config.exists():
                import json
                with config.open("x", encoding="utf-8") as fp:
                    json.dump({"id": pid, "name": project["name"], "contractor": project["contractor"], "intelligence_version": "2.0"}, fp, indent=2)
            return row

    def adopt(self, project_id, classification, actor):
        # Explicit adoption preserves existing inputs; candidates remain unverified.
        path = self.store.root / "projects" / project_id / "project.json"
        old = read_json(path); meta = old.get("metadata", old)
        return self.create({**classification, "name": meta.get("name", meta.get("project_name")),
                            "address": meta.get("location", ""), "client": meta.get("owner") or "",
                            "legacy_reference": project_id}, actor, project_id)

    def transact(self, pid, revision, actor, action, payload):
        with self.store.locked(pid):
            previous = self.store.load(pid)
            if previous["revision"] != revision:
                raise RevisionConflict("El expediente cambió; recargue")
            state = deepcopy(previous["state"])
            if action=="approve" and payload.get("human_confirmation") is True and state.get("current_approval"):
                self.check_originals(pid,state)
                if not self.evaluate(state)["release_blockers"]:return previous
            if action=="actual_cost":
                payload={**payload,"estimate_revision":revision,"estimated_cost_baseline":previous["state"]["result"]["totals"]["estimated_all_in_cost"]}
            self.apply(state, pid, actor, action, payload)
            if action not in ("approve", "issue") and basis(state)!=basis(previous["state"]):
                state["current_approval"] = None
            state["result"] = self.evaluate(state)
            state["result"]["changes_since_previous"] = difference(previous["state"], state)
            if previous["state"].get("approvals") and action not in ("approve", "issue"):
                state["result"]["alerts"].append("APPROVED_OR_ISSUED_PRICE_PRESERVED_REVIEW_NEW_REVISION")
            return self.store.append(pid, state, revision, actor, action)

    def import_legacy(self, pid, revision, actor):
        row = self.store.load(pid)
        if row["revision"] != revision: raise RevisionConflict("Recargue antes de importar")
        project = row["state"]["project"]
        if project.get("legacy_reference") != pid: raise ValueError("Solo disponible para expedientes anteriores vinculados")
        source = self.store.root / "docs" / project["name"]
        if not source.resolve().is_relative_to((self.store.root / "docs").resolve()): raise ValueError("Ruta documental inválida")
        for path in sorted(source.rglob("*.pdf")):
            if not path.resolve().is_relative_to(source.resolve()): raise ValueError("Documento enlazado fuera del proyecto")
            row = self.upload(pid, row["revision"], actor, [(path.name, path.read_bytes())])
        return self.transact(pid, row["revision"], actor, "import_legacy_lines", {})

    def upload(self, pid, revision, actor, files):
        if not 1 <= len(files) <= 20:
            raise ValueError("Seleccione entre 1 y 20 documentos")
        parsed = [(parse_document(name, raw), raw) for name, raw in files]
        with self.store.locked(pid):
            old = self.store.load(pid)
            if old["revision"] != revision:
                raise RevisionConflict("Recargue: nueva revisión disponible")
            state = deepcopy(old["state"]); seen = {d["sha256"] for d in state["documents"]}; added = []
            for doc, raw in parsed:
                if doc["sha256"] in seen:
                    continue
                folder = self.store.child(pid,"originals"); folder.mkdir(exist_ok=True)
                path = folder / (doc["sha256"] + Path(doc["original_name"]).suffix.lower())
                if not path.exists():
                    with path.open("xb") as fp: fp.write(raw)
                elif sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
                    raise ValueError("Original modificado")
                doc["stored_name"] = path.name
                doc["version"] = 1 + sum(d["original_name"] == doc["original_name"] for d in state["documents"])
                state["documents"].append(doc); seen.add(doc["sha256"]); added.append(doc["original_name"])
            if not added:
                return {**old, "duplicate_upload": True}
            state["current_approval"] = None; state["review"]["scope_confirmed"] = False
            state["result"] = self.evaluate(state)
            return self.store.append(pid, state, revision, actor, "DOCUMENTS_ADDED: " + ", ".join(added))

    def apply(self, state, pid, actor, action, p):
        if action == "import_legacy_lines":
            if state["project"].get("legacy_reference") != pid: raise ValueError("Referencia de proyecto incompatible")
            path = self.store.root / "projects" / pid / "analysis.json"
            analysis = read_json(path)
            if analysis.get("project_id") != pid: raise ValueError("Análisis de otro proyecto")
            for q in analysis.get("quantities", []):
                if any(r.get("legacy_quantity_id") == q["id"] and r.get("legacy_fingerprint") == fingerprint(q) for r in state["lines"]): continue
                evidence = None
                for ref in q.get("sources", []):
                    doc = next((d for d in state["documents"] if d["sha256"] == ref.get("sha256")), None)
                    if doc:
                        try: evidence = validate_evidence(state, {"document_id": doc["document_id"], "page": ref["page"], "excerpt": ref.get("excerpt", "")})
                        except ValueError: continue
                        break
                state["lines"].append({"line_id": str(uuid4()), "project_id": pid, "legacy_quantity_id": q["id"],
                    "description": q["item"], "trade": state["project"]["trade"], "category": "material", "legacy_fingerprint": fingerprint(q),
                    "quantity": str(q["quantity"]) if q.get("quantity") is not None else None, "unit": q["unit"],
                    "quantity_status": "PENDING_VERIFICATION", "evidence_reference": evidence, "legacy_sources": q.get("sources", []),
                    "source_document": evidence["source_document"] if evidence else "", "source_page": evidence["page"] if evidence else None,
                    "revision_id": str(uuid4()), "reviewed_by": None, "reviewed_at": None, "active": True,
                    "specification": "", "selected_quote_id": None, "scope_key": "legacy_" + q["id"]})
            state["project"]["legacy_analysis_sha256"] = sha256(path.read_bytes()).hexdigest()
        elif action == "analyze":
            for doc in state["documents"]:
                facts=document_facts(doc)
                for fact in facts:
                    if fact not in state.setdefault("document_facts",[]): state["document_facts"].append(fact)
                dates=[f["value"] for f in facts if f["data_type"]=="document_date"]
                if len(set(dates))==1: doc["document_date"]=dates[0]
                candidates, mentions = document_candidates(doc)
                for candidate in candidates:
                    cid = fingerprint(candidate)[:20]
                    # Recognize the V2 candidate identity without changing a reviewed line.
                    legacy={k:v for k,v in candidate.items() if k in ("description","quantity","unit","quantity_status","calculation")}
                    legacy["evidence"]={k:candidate["evidence"][k] for k in ("document_id","page","excerpt")}
                    legacy["scope_key"]="fence_length" if any(w in candidate["description"].lower() for w in ("fence","cerca")) else ""
                    legacy_id=fingerprint(legacy)[:20]
                    if any(r.get("candidate_id") in (cid,legacy_id) for r in state["lines"]): continue
                    evidence = validate_evidence(state, candidate.pop("evidence"))
                    state["lines"].append({**candidate, "line_id": str(uuid4()), "candidate_id": cid,
                        "project_id": pid, "trade": state["project"]["trade"], "category": candidate.get("category","material"),
                        "specification": "", "selected_quote_id": None, "evidence_reference": evidence,
                        "source_document": evidence["source_document"], "source_page": evidence["page"],
                        "revision_id": str(uuid4()), "reviewed_by": None, "reviewed_at": None, "active": candidate.get("active",True)})
                for mention in mentions:
                    def identity(item):return (item["category"],*(item["evidence"].get(k) for k in ("document_id","page","excerpt")))
                    if not any(identity(m)==identity(mention) for m in state["mentions"]): state["mentions"].append(mention)
        elif action == "review_document":
            doc = next(d for d in state["documents"] if d["document_id"] == p["document_id"])
            if not p.get("notes"): raise ValueError("Registre resultado de revisión documental")
            doc.update(reviewed_by=actor, reviewed_at=utcnow(), review_notes=p["notes"])
        elif action == "line":
            existing = next((r for r in state["lines"] if r["line_id"] == p.get("line_id")), None)
            row = {**(existing or {}), **p}
            if row.get("quantity_status") not in QUANTITY_STATES or row.get("category") not in CATEGORIES:
                raise ValueError("Estado de cantidad o categoría inválidos")
            if not row.get("description") or not row.get("unit"): raise ValueError("Descripción y unidad obligatorias")
            if row.get("quantity") is not None: _decimal(row["quantity"], "quantity")
            evidence = validate_evidence(state, row.get("evidence_reference"))
            row.update(line_id=existing["line_id"] if existing else str(uuid4()), project_id=pid,
                       source_document=evidence["source_document"], source_page=evidence["page"], evidence_reference=evidence,
                       revision_id=str(uuid4()), reviewed_by=actor, reviewed_at=utcnow(), active=row.get("active", True))
            if row.get("quantity_method") == "PRODUCTIVITY":
                output = _decimal(row.get("output_quantity"), "output_quantity")
                productivity = _decimal(row.get("productivity_per_hour"), "productivity_per_hour")
                if not productivity: raise ValueError("Productividad debe ser mayor que cero")
                row["quantity"] = str(output / productivity)
                row["calculation"] = {"operation": "productivity", "output_quantity": str(output), "productivity_per_hour": str(productivity)}
            if existing: state["lines"][state["lines"].index(existing)] = row
            else: state["lines"].append(row)
            state["review"]["scope_confirmed"] = False
        elif action == "supplier":
            if not p.get("name") or not p.get("location"): raise ValueError("Proveedor y ubicación obligatorios")
            existing=next((s for s in state["suppliers"] if s["supplier_id"]==p.get("supplier_id")),None)
            if existing: existing.update(name=p["name"],location=p["location"],reviewed_by=actor,reviewed_at=utcnow())
            else: state["suppliers"].append({"supplier_id": str(uuid4()), "name": p["name"], "location": p["location"]})
        elif action == "catalog_import":
            doc=next(d for d in state["documents"] if d["document_id"]==p["document_id"])
            if not doc.get("table_rows"): raise ValueError("Documento sin tabla de precios compatible; capture cotización PDF con evidencia y revisión")
            for item in doc["table_rows"]:
                ref={"document_id":doc["document_id"],"page":item["page"],"excerpt":item["excerpt"],"sheet":item["sheet"],"row":item["row"]}
                signature=fingerprint(ref)
                if any(r.get("import_signature")==signature for r in state.get("catalog_entries",[])): continue
                record=price_record(item["values"])
                record.update(entry_id=str(uuid4()),evidence_reference=validate_evidence(state,ref),import_signature=signature,recorded_by=actor,recorded_at=utcnow())
                state.setdefault("catalog_entries",[]).append(record)
        elif action == "catalog_review":
            old=next(r for r in state.get("catalog_entries",[]) if r["entry_id"]==p["entry_id"])
            record=price_record({**old,**p.get("values",{})})
            record.update(entry_id=str(uuid4()),supersedes=old["entry_id"],evidence_reference=validate_evidence(state,p.get("evidence_reference") or old["evidence_reference"]),
                          confirmed=p.get("confirmed") is True,technical_match=p.get("technical_match") is True,
                          availability_confirmed=p.get("availability_confirmed") is True,review_status="HUMAN_REVIEW_RECORDED",reviewed_by=actor,reviewed_at=utcnow())
            state["catalog_entries"].append(record)
        elif action == "catalog_quote":
            record=p["record"]
            supplier=next((s for s in state["suppliers"] if s["name"]==record.get("supplier",record.get("provider")) and s["location"]==record.get("location")),None)
            if not supplier:
                state["suppliers"].append({"supplier_id":str(uuid4()),"name":record.get("supplier",record.get("provider")),"location":record.get("location")})
                supplier=state["suppliers"][-1]
            self.apply(state,pid,actor,"quote",{**record,"line_id":p["line_id"],"supplier_id":supplier["supplier_id"],"supersedes":None,
                "catalog_reference":{"project_id":p["source_project_id"],"record_id":p["record_id"]},
                "description":record.get("product_name",record.get("description")),"manufacturer":record.get("manufacturer") or record.get("brand"),"confirmed":False,"technical_match":False})
        elif action == "quote_batch":
            ids=p["line_ids"]
            if len(ids)<2 or len(set(ids))!=len(ids): raise ValueError("Seleccione dos o más partidas distintas")
            allocations=p["allocations"]
            if set(allocations)!=set(ids): raise ValueError("Distribuya flete e impuestos entre todas las partidas")
            for key in ("delivery","tax_total"):
                if sum(_decimal(allocations[i].get(key),key) for i in ids)!=_decimal(p["quote"].get(key),key): raise ValueError("Distribución no coincide con total de "+key)
            group=str(uuid4())
            for lid in ids: self.apply(state,pid,actor,"quote",{**p["quote"],**allocations[lid],"line_id":lid,"quote_group_id":group})
        elif action == "quote":
            q = deepcopy(p)
            q["kind"]=PRICE_TYPES.get(q.get("kind"),q.get("kind"))
            q["price_type"]=next((key for key,value in PRICE_TYPES.items() if value==q["kind"]),None)
            line = next((r for r in state["lines"] if r["line_id"] == q.get("line_id")), None)
            supplier = next((s for s in state["suppliers"] if s["supplier_id"] == q.get("supplier_id")), None)
            if not line or not supplier or q.get("kind") not in QUOTE_KINDS: raise ValueError("Partida, proveedor o clase documental inválidos")
            for field in ("unit_price", "delivery", "tax_total", "discount_percent", "pack_size", "minimum_quantity"):
                if q.get(field)=="": q[field]=None
                if q.get(field) is not None: _decimal(q[field], field)
            if q.get("discount_percent") is not None and _decimal(q["discount_percent"], "discount") > 100:
                raise ValueError("Descuento mayor de 100%")
            if q.get("pack_size") is not None and _decimal(q["pack_size"], "pack_size") <= 0: raise ValueError("Presentación debe ser positiva")
            for key in ("quoted_on","valid_until"):
                if q.get(key): _date(q[key],key)
                else: q[key]=None
            if q["valid_until"] and q["quoted_on"] and q["valid_until"] < q["quoted_on"]: raise ValueError("Vigencia inválida")
            if q.get("evidence_reference"):
                q["evidence_reference"] = validate_evidence(state, q["evidence_reference"])
                q["evidence_status"]="DOCUMENT_LINKED_REVIEW_REQUIRED"
            elif q["kind"]=="phone_confirmed":
                q.update(evidence_reference=None,evidence_status="UNDOCUMENTED_PHONE_RECORD",confirmed=False)
            else: raise ValueError("Cotización requiere evidencia documental")
            prior = next((r for r in state["quotes"] if r["quote_id"] == q.get("supersedes")), None)
            if q.get("supersedes") and (not prior or prior["line_id"] != q["line_id"] or prior["supplier_id"] != q["supplier_id"]):
                raise ValueError("Revisión debe corresponder al mismo proveedor y partida")
            q.update(quote_id=str(uuid4()), recorded_at=utcnow(), recorded_by=actor, provider=supplier["name"], location=supplier["location"],
                     quoted_quantity=line.get("quantity"), quoted_quantity_unit=line["unit"])
            state["quotes"].append(q)  # Never updates prior quote or selection.
        elif action == "select_quote":
            line = next(r for r in state["lines"] if r["line_id"] == p["line_id"])
            q = next(q for q in state["quotes"] if q["quote_id"] == p["quote_id"])
            if q["line_id"] != line["line_id"]: raise ValueError("Cotización pertenece a otra partida")
            if self.normalized_quote(state, line, q, date.today())["issues"]:
                raise ValueError("Cotización no elegible: revise especificación, vigencia, evidencia y condiciones")
            line["selected_quote_id"] = q["quote_id"]
        elif action == "settings":
            if "financial" in p:
                f = p["financial"]
                for key in ("overhead_percent", "contingency_percent", "target_margin_percent", "sensitivity_percent"):
                    if f.get(key) is not None: _decimal(f[key], key, max_value=Decimal("99.99") if key == "target_margin_percent" else Decimal("10000"))
                if f.get("pricing_method", "margin") not in ("margin", "markup"): raise ValueError("Método inválido")
                state["financial"].update(f)
                state["financial"].update(reviewed_by=actor, reviewed_at=utcnow())
            if "review" in p: state["review"].update(p["review"])
            if "project" in p:
                changes = p["project"]
                if any(k not in state["project"] or k in ("project_id", "currency", "legacy_reference") for k in changes): raise ValueError("Campo de proyecto no editable")
                state["project"].update(changes)
                if state["project"]["work_type"] not in WORK_TYPES or state["project"]["contractual_relationship"] not in RELATIONSHIPS:
                    raise ValueError("Clasificación inválida")
        elif action == "resolve":
            if p.get("disposition") not in ("same_scope_reconciled", "different_scopes", "included", "excluded", "not_applicable") or not p.get("reason"):
                raise ValueError("Conciliación requiere disposición y motivo")
            evidence = validate_evidence(state, p.get("evidence_reference"))
            state["resolutions"].append({**p, "evidence_reference": evidence, "reviewed_by": actor,
                                         "reviewed_at": utcnow(), "input_signature": self.issue_signature(state)})
        elif action == "requirement":
            if not p.get("description"): raise ValueError("Descripción de requisito obligatoria")
            ev = validate_evidence(state, p.get("evidence_reference"))
            item = {**p, "requirement_id": p.get("requirement_id") or str(uuid4()), "evidence_reference": ev, "reviewed_by": actor, "reviewed_at": utcnow()}
            prior = next((r for r in state["requirements"] if r["requirement_id"] == item["requirement_id"]), None)
            if prior: state["requirements"][state["requirements"].index(prior)] = item
            else: state["requirements"].append(item)
        elif action == "change_order":
            if not p.get("description"): raise ValueError("Descripción obligatoria")
            ev = validate_evidence(state, p.get("evidence_reference"))
            state["change_orders"].append({**p, "change_order_id": str(uuid4()), "status": "PENDING_CONTRACTUAL_REVIEW", "evidence_reference": ev, "recorded_by": actor, "recorded_at": utcnow()})
        elif action == "review_change_order":
            change = next(c for c in state["change_orders"] if c["change_order_id"] == p["change_order_id"])
            if p.get("status") not in ("REVIEWED_INCLUDED", "REVIEWED_EXCLUDED") or not p.get("reason"):
                raise ValueError("Registre alcance incluido/excluido y justificación")
            ev = validate_evidence(state, p.get("evidence_reference"))
            change.update(status=p["status"], review_reason=p["reason"], reviewed_by=actor, reviewed_at=utcnow(), review_evidence=ev)
        elif action == "approve":
            self.check_originals(pid, state)
            result = self.evaluate(state)
            if result["release_blockers"] or p.get("human_confirmation") is not True:
                raise ValueError("Aprobación bloqueada: " + "; ".join(result["release_blockers"]))
            approval = {"approval_id": str(uuid4()), "fingerprint": basis(state), "approved_by": actor,
                        "approved_at": utcnow(), "approved_price": result["totals"]["proposed_price_before_contract_specific_taxes"],
                        "contract_price_status": "PROPOSAL_APPROVED_NOT_CONTRACT_ACCEPTANCE"}
            state["approvals"].append(approval); state["current_approval"] = approval
        elif action == "issue":
            if not state.get("current_approval") or self.evaluate(state)["release_blockers"]:
                raise ValueError("La propuesta requiere aprobación vigente")
            if not p.get("recipient") or not p.get("reference"): raise ValueError("Registre destinatario y referencia del envío manual")
            state["deliveries"].append({**p, "recorded_by": actor, "recorded_at": utcnow(), "approval_id": state["current_approval"]["approval_id"], "automatic_send": False})
        elif action == "contract_acceptance":
            if p.get("human_confirmation") is not True: raise ValueError("Aceptación contractual requiere confirmación humana")
            amount = _decimal(p.get("amount"), "contract amount")
            ev = validate_evidence(state, p.get("evidence_reference"))
            state.setdefault("contracts", []).append({"contract_id": str(uuid4()), "amount": _fmt(amount), "evidence_reference": ev,
                                                        "confirmed_by": actor, "confirmed_at": utcnow()})
        elif action == "actual_cost":
            if p.get("human_confirmation") is not True or p.get("evidence_type") not in ("purchase_invoice","paid_receipt","payroll","expense_record"):
                raise ValueError("Confirme costo ejecutado y tipo de evidencia; una cotización no prueba un costo real")
            if p.get("category") not in CATEGORIES: raise ValueError("Categoría de costo real inválida")
            causes={"supplier_price_change","quantity_error","scope_change","additional_material","waste","labor_productivity","unplanned_equipment_transport","compliance_cost","other","unconfirmed"}
            cause=p.get("cause","unconfirmed")
            if cause not in causes: raise ValueError("Causa inválida")
            amount=_decimal(p.get("amount"),"actual amount");_date(p.get("incurred_on"),"incurred_on")
            if p["incurred_on"]>date.today().isoformat(): raise ValueError("Costo real no puede tener fecha futura")
            ev=validate_evidence(state,p.get("evidence_reference"))
            if cause!="unconfirmed" and not p.get("cause_notes"): raise ValueError("Documente la causa sin atribución automática")
            if p.get("line_id") and not any(r["line_id"]==p["line_id"] for r in state["lines"]): raise ValueError("Partida de costo real inexistente")
            if p.get("currency","USD")!="USD": raise ValueError("Costo real requiere USD; no se convierten monedas")
            prior=next((r for r in state.get("actual_costs",[]) if r["actual_id"]==p.get("supersedes")),None)
            if p.get("supersedes") and (not prior or prior.get("line_id")!=p.get("line_id")): raise ValueError("Corrección de costo real incompatible")
            if prior and any(r.get("supersedes")==prior["actual_id"] for r in state.get("actual_costs",[])): raise ValueError("Corrija la versión más reciente del costo real")
            if p.get("invoice_reference") and any(r.get("invoice_reference")==p["invoice_reference"] and not p.get("supersedes") for r in state.get("actual_costs",[])):
                raise ValueError("Factura/referencia duplicada: registre corrección explícita")
            state.setdefault("actual_costs",[]).append({**p,"actual_id":str(uuid4()),"amount":_fmt(amount),"currency":"USD", "cause":cause,
                "evidence_reference":ev,"recorded_by":actor,"recorded_at":utcnow()})
        else:
            raise ValueError("Acción desconocida")

    def check_originals(self, pid, state):
        for doc in state["documents"]:
            path = self.store.child(pid,"originals",doc["stored_name"])
            if not path.exists() or sha256(path.read_bytes()).hexdigest() != doc["sha256"]:
                raise ValueError("Documento original ausente o modificado")

    @staticmethod
    def issue_signature(state):
        # A supplier selection does not change the reviewed physical scope.
        fields=("line_id","description","trade","category","quantity","unit","quantity_status","scope_key","specification",
                "active","calculation","assumptions","evidence_reference","quantity_method","output_quantity","productivity_per_hour")
        return fingerprint({"documents": [d["sha256"] for d in state["documents"]],
                            "lines":[{k:l.get(k) for k in fields} for l in state["lines"]]})

    def issues(self, state):
        issues = []
        groups = {}
        for line in state["lines"]:
            if line.get("scope_key") and line.get("quantity") is not None:
                groups.setdefault(line["scope_key"], []).append(line)
        for scope, rows in groups.items():
            unit=rows[0]["unit"]; values=[]; incompatible=False
            for row in rows:
                try: factor=conversion(row["unit"],unit)
                except ValueError: factor=None
                if factor is None: incompatible=True
                else: values.append(Decimal(row["quantity"])*factor)
            if incompatible:
                issues.append({"issue_id":"units:"+scope,"kind":"INCOMPATIBLE_SCOPE_UNITS","line_ids":[r["line_id"] for r in rows]})
            elif len(set(values)) > 1:
                issues.append({"issue_id": "quantity:" + scope + ":" + unit, "kind": "QUANTITY_CONTRADICTION",
                               "line_ids": [r["line_id"] for r in rows], "quantities": [r["quantity"] for r in rows],
                               "required_action": "Determinar si son alcances distintos y conciliar con evidencia humana"})
            elif len(rows)>1:
                issues.append({"issue_id":"duplicate:"+scope,"kind":"POSSIBLE_DUPLICATE_QUANTITY","line_ids":[r["line_id"] for r in rows]})
        for mention in state["mentions"]:
            mid = fingerprint(mention)[:16]
            issues.append({"issue_id": "mention:" + mid, "kind": "SCOPE_MENTION_REQUIRES_REVIEW", **mention})
        signature = self.issue_signature(state)
        legacy_signature=fingerprint({"documents":[d["sha256"] for d in state["documents"]],"lines":state["lines"]})
        for issue in issues:
            issue["resolved"] = any(r["issue_id"] == issue["issue_id"] and r["input_signature"] in (signature,legacy_signature) for r in state["resolutions"])
        return issues

    def normalized_quote(self, state, line, q, today):
        issues = []
        for key in ("unit_price", "delivery", "tax_total", "discount_percent", "pack_size"):
            if q.get(key) is None: issues.append("MISSING_" + key.upper())
        if q.get("technical_match") is not True or q.get("specification") != line.get("specification") or not line.get("specification"):
            issues.append("TECHNICAL_SPECIFICATION_REVIEW_PENDING")
        if q.get("availability_confirmed") is not True: issues.append("AVAILABILITY_PENDING")
        if not q.get("provider") or not q.get("location"): issues.append("SUPPLIER_LOCATION_PENDING")
        if q.get("confirmed") is not True: issues.append("PRICE_CONFIRMATION_PENDING")
        if q.get("kind") in ("historical", "catalog", "invoice_actual"):
            issues.append("DOCUMENT_CLASS_REQUIRES_CURRENT_QUOTE")
        if q.get("currency") != "USD": issues.append("CURRENCY_MISMATCH")
        if q.get("quoted_quantity") != line.get("quantity") or q.get("quoted_quantity_unit") != line["unit"]:
            issues.append("QUOTE_QUANTITY_SCOPE_CHANGED_RECONFIRM_PRICE")
        if not q.get("quoted_on") or not q.get("valid_until") or not q["quoted_on"] <= today.isoformat() <= q["valid_until"]:
            issues.append("QUOTE_EXPIRED_OR_FUTURE")
        try:
            validate_evidence(state, q.get("evidence_reference"))
        except ValueError:
            issues.append("PRICE_EVIDENCE_PENDING")
        try: factor = conversion(line["unit"], q.get("unit"))
        except ValueError: factor=None
        if factor is None: issues.append("UNIT_OR_EVIDENCE_INVALID")
        quantity = _decimal(line["quantity"], "quantity") if line.get("quantity") is not None else None
        if quantity is None: issues.append("QUANTITY_PENDING")
        total, packs, goods, normalized_unit = None, None, None, None
        computable=quantity is not None and factor is not None and q.get("currency")=="USD" and all(q.get(k) is not None for k in ("unit_price","delivery","tax_total","discount_percent","pack_size"))
        if computable:
            packs = quantity * factor / Decimal(q["pack_size"])
            if q.get("whole_packs") is True:
                packs = packs.to_integral_value(rounding=ROUND_CEILING)
            if q.get("minimum_quantity") is not None and packs*Decimal(q["pack_size"]) < Decimal(q["minimum_quantity"]):
                issues.append("MINIMUM_QUANTITY_NOT_MET")
            goods = packs * Decimal(q["unit_price"]) * (1 - Decimal(q["discount_percent"]) / 100)
            normalized_unit=Decimal(q["unit_price"])*(1-Decimal(q["discount_percent"])/100)*factor/Decimal(q["pack_size"])
            total = goods + Decimal(q["delivery"]) + Decimal(q["tax_total"])
        return {"quote_id": q["quote_id"], "provider": q["provider"], "location": q["location"], "kind": q["kind"],
                "packs": str(packs) if packs is not None else None, "effective_total": _fmt(total) if not issues else None, "goods_total":_fmt(goods) if not issues else None,
                "provisional_total":_fmt(total),"provisional_only":bool(issues),
                "normalized_unit_price":format(normalized_unit,"f") if normalized_unit is not None else None,
                "delivery":q.get("delivery"),"tax_total":q.get("tax_total"),"valid_until":q.get("valid_until"),
                "conditions":q.get("tax_conditions"),"issues": issues, "eligible": not issues}

    def evaluate(self, state, as_of=None, *, include_impacts=True):
        today = as_of or date.today(); active = [r for r in state["lines"] if r.get("active", True)]
        comparisons, engine_lines, blocking, alerts = {}, [], [], []
        material_goods=Decimal(0)
        issues = self.issues(state)
        if not state["documents"]: blocking.append("DOCUMENTS_PENDING")
        if any(not d.get("reviewed_by") for d in state["documents"]): blocking.append("DOCUMENT_REVIEW_PENDING")
        if any(not i["resolved"] for i in issues): blocking.append("CONTRADICTIONS_OR_SCOPE_MENTIONS_PENDING")
        for line in active:
            options = [q for q in state["quotes"] if q["line_id"] == line["line_id"]]
            comparisons[line["line_id"]] = [self.normalized_quote(state, line, q, today) for q in options]
            selected = next((q for q in options if q["quote_id"] == line.get("selected_quote_id")), None)
            normalized = next((q for q in comparisons[line["line_id"]] if q["quote_id"] == line.get("selected_quote_id")), None)
            for alternative in comparisons[line["line_id"]]:
                delta=Decimal(alternative["effective_total"])-Decimal(normalized["effective_total"]) if alternative["effective_total"] is not None and normalized and normalized["effective_total"] is not None else None
                alternative["difference_vs_selected"]=_fmt(delta)
                alternative["difference_percent_vs_selected"]=_fmt(100*delta/Decimal(normalized["effective_total"])) if delta is not None and Decimal(normalized["effective_total"]) else None
            if selected and any(q.get("supersedes") == selected["quote_id"] for q in options):
                blocking.append("UPDATED_QUOTE_REQUIRES_SELECTION_REVIEW:" + line["line_id"])
                alerts.append("SUPPLIER_PRICE_CHANGED:" + line["line_id"])
            confirmed = line.get("quantity_status") == "CONFIRMED_WITH_EVIDENCE" and bool(line.get("reviewed_by"))
            try: validate_evidence(state, line.get("evidence_reference"))
            except ValueError: confirmed = False
            if not confirmed: blocking.append("QUANTITY_REVIEW_PENDING:" + line["line_id"])
            calculation=line.get("calculation")
            if calculation and calculation.get("operation") in ("sum","product"):
                operands=[_decimal(n,"operand") for n in calculation.get("operands",[])]
                expected=sum(operands) if calculation["operation"]=="sum" else prod(operands)
                if not operands or line.get("quantity") is None or expected!=Decimal(line["quantity"]): blocking.append("QUANTITY_FORMULA_MISMATCH:"+line["line_id"])
            # Adapter sends the normalized line total to V1 as one LS, preserving exact money.
            option = []
            if normalized and normalized["eligible"]:
                if line["category"]=="material" and confirmed: material_goods+=Decimal(normalized["goods_total"])
                option = [{"id": selected["quote_id"], "provider": selected["provider"], "unit_cost": normalized["effective_total"],
                           "unit": "LS", "currency": "USD", "delivery_total": "0", "quoted_on": selected["quoted_on"],
                           "valid_until": selected["valid_until"], "evidence_ref": selected["evidence_reference"]["sha256"]}]
            engine_lines.append({"id": line["line_id"], "description": line["description"], "category": "logistics" if line["category"] == "disposal" else line["category"],
                                 "unit": "LS", "quantity": "1" if line.get("quantity") is not None else None,
                                 "quantity_status": "verified" if confirmed else "pending", "quantity_evidence": str(line.get("evidence_reference")),
                                 "selected_option_id": line.get("selected_quote_id"), "options": option})
        f = state["financial"]; financial = deepcopy(f)
        for key in ("overhead_percent", "contingency_percent", "target_margin_percent"):
            if f.get(key) is None:
                blocking.append("FINANCIAL_INPUT_PENDING:" + key); financial[key] = "0"; financial["confirmed"] = False
        if f.get("pricing_method") == "markup" and f.get("target_margin_percent") is not None:
            markup = Decimal(f["target_margin_percent"])
            financial["target_margin_percent"] = str(100 * markup / (100 + markup))
        result = calculate({"schema_version": "1.0", "project": {"estimate_id": state["project"]["project_id"],
                           "name": state["project"]["name"], "currency": "USD", "client_type": "homeowner"},
                           "financial": financial, "lines": engine_lines}, as_of=today)
        if result["blockers"]: blocking.extend(result["blockers"])
        review = state["review"]
        legacy_hash = state["project"].get("legacy_analysis_sha256")
        if legacy_hash:
            legacy_path = self.store.root / "projects" / state["project"]["project_id"] / "analysis.json"
            if not legacy_path.exists() or sha256(legacy_path.read_bytes()).hexdigest() != legacy_hash:
                blocking.append("LEGACY_ANALYSIS_CHANGED_REIMPORT_AND_REVIEW")
        if not review.get("scope_confirmed"): blocking.append("SCOPE_REVIEW_PENDING")
        if not review.get("tax_reviewed") or not review.get("tax_basis"): blocking.append("CONTRACT_JURISDICTION_TAX_REVIEW_PENDING")
        if any(r.get("verified") is not True for r in state["requirements"]): blocking.append("COMPLIANCE_EVIDENCE_PENDING")
        if any(c["status"] == "PENDING_CONTRACTUAL_REVIEW" for c in state["change_orders"]): blocking.append("CHANGE_ORDER_REVIEW_PENDING")
        for field in ("address", "state", "county", "jurisdiction", "client", "contractor", "trade", "estimator"):
            if not state["project"].get(field): blocking.append("PROJECT_FIELD_PENDING:" + field)
        if not review.get("company_confirmed"): blocking.append("CONTRACTOR_IDENTITY_REVIEW_PENDING")
        for field in ("terms", "valid_until", "assumptions", "exclusions"):
            if not review.get(field): blocking.append("COMMERCIAL_FIELD_PENDING:" + field)
        try:
            if _date(review.get("valid_until"), "valid_until") < today: blocking.append("PROPOSAL_VALIDITY_EXPIRED")
        except ValueError: blocking.append("PROPOSAL_VALIDITY_PENDING")
        for q in state["quotes"]:
            if q.get("supersedes"):
                old = next(r for r in state["quotes"] if r["quote_id"] == q["supersedes"])
                alerts.append("QUOTE_VERSION:" + old["quote_id"] + "->" + q["quote_id"])
        approval = state.get("current_approval")
        if approval and approval["fingerprint"] != basis(state): blocking.append("APPROVAL_STALE")
        status = ("PROPOSAL_ISSUED" if state["deliveries"] and approval and state["deliveries"][-1]["approval_id"] == approval["approval_id"] else "APPROVED") if approval and not blocking else (
            "READY_FOR_HUMAN_REVIEW" if not blocking else "DOCUMENTS_PENDING" if not state["documents"] else
            "QUANTITIES_PENDING" if any("QUANTITY" in b or "CONTRADICTIONS" in b for b in blocking) else
            "PRICES_PENDING" if result["blockers"] else "HUMAN_REVIEW_PENDING")
        result.update(status=status, release_blockers=sorted(set(blocking)), comparisons=comparisons, issues=issues, alerts=alerts,
                      approved_contract_price=state.get("contracts", [{}])[-1].get("amount") if state.get("contracts") else None,
                      last_approved_proposal_price=state["approvals"][-1]["approved_price"] if state["approvals"] else None)
        costs=state.get("actual_costs",[]);superseded={c.get("supersedes") for c in costs}
        current_costs=[c for c in costs if c["actual_id"] not in superseded]
        actual=sum((Decimal(c["amount"]) for c in current_costs),Decimal(0))
        estimated=result["totals"]["estimated_all_in_cost"]
        baseline=costs[0].get("estimated_cost_baseline") if costs else None
        grouped={}
        for cost in current_costs:
            key=(cost["category"],cost["cause"],cost.get("provider") or "")
            grouped[key]=grouped.get(key,Decimal(0))+Decimal(cost["amount"])
        result["actual_vs_estimated"]={"estimated_cost":baseline if costs else estimated,"current_estimated_cost":estimated,"baseline_revision":costs[0].get("estimate_revision") if costs else None,"actual_documented_cost":_fmt(actual) if costs else None,
            "variance":_fmt(actual-Decimal(baseline)) if costs and baseline is not None else None,
            "coverage":"DOCUMENTED_COSTS_ONLY_COMPLETENESS_NOT_CERTIFIED","automatic_blame":False,
            "groups":[{"category":k[0],"cause":k[1],"provider":k[2],"amount":_fmt(v)} for k,v in grouped.items()]}
        review_topics=["transport","equipment","demolition","disposal","mobilization","permits","surface_protection","subcontracts","coordination","insurance","contract_requirements"]
        result["cost_review_topics"]=review_topics
        result["classification_controls"]={"work_type":state["project"]["work_type"],"contractual_relationship":state["project"]["contractual_relationship"],
            "trade":state["project"]["trade"],"review_focus":(["Review supplied bid documents, deadline and contract requirements"] if state["project"]["work_type"]=="public_works" or state["project"]["contractual_relationship"]=="public_entity" else ["Review private scope, exclusions and tax treatment"])
            + (["Review GC/subcontract scope interfaces and supplied contract conditions"] if state["project"]["contractual_relationship"] in ("general_contractor","subcontractor") else []),"automatic_margin":None,"automatic_legal_requirements":False}
        result["totals"]["material_goods_sensitivity_base"]=_fmt(material_goods)
        if result["totals"]["estimated_all_in_cost"] is not None:
            cost=Decimal(result["totals"]["estimated_all_in_cost"]); price=Decimal(result["totals"]["proposed_price_before_contract_specific_taxes"])
            result["price_stress"]={}
            for percentage in (Decimal(0),Decimal(3),Decimal(5)):
                extra=Decimal(_fmt(material_goods*percentage/100))
                result["price_stress"]["base" if percentage==0 else f"material_plus_{percentage}%"]={"simulation_only":True,"additional_material_cost":_fmt(extra),"post_increase_cost":_fmt(cost+extra),
                    "fixed_price_gross_margin_percent":_fmt(100*(price-cost-extra)/price) if price else None,"basis":"MATERIAL_GOODS_EXCLUDING_FREIGHT_AND_TAX"}
        if result["totals"]["estimated_all_in_cost"] is not None and f.get("sensitivity_percent") is not None:
            pct = _decimal(f["sensitivity_percent"], "sensitivity")
            extra = material_goods * pct / 100
            result["custom_sensitivity"] = {"simulation_only": True, "percent": str(pct), "additional_material_cost": _fmt(extra),
                                            "post_increase_cost": _fmt(Decimal(result["totals"]["estimated_all_in_cost"]) + extra)}
        if include_impacts:
            impacts = []
            for quote in state["quotes"]:
                if not quote.get("supersedes"): continue
                line = next((r for r in active if r["line_id"] == quote["line_id"]), None)
                if not line: continue
                old = next(r for r in state["quotes"] if r["quote_id"] == quote["supersedes"])
                before = self.normalized_quote(state, line, old, today)
                after = self.normalized_quote(state, line, quote, today)
                scenario = deepcopy(state)
                next(r for r in scenario["lines"] if r["line_id"] == line["line_id"])["selected_quote_id"] = quote["quote_id"]
                scenario["current_approval"] = None
                future = self.evaluate(scenario, today, include_impacts=False)
                old_total, new_total = before["effective_total"], after["effective_total"]
                price = state["approvals"][-1]["approved_price"] if state["approvals"] else None
                new_cost = future["totals"]["estimated_all_in_cost"]
                impacts.append({"line_id": line["line_id"], "old_quote_id": old["quote_id"], "new_quote_id": quote["quote_id"],
                                "old_line_cost": old_total, "new_line_cost": new_total,
                                "line_cost_delta": _fmt(Decimal(new_total) - Decimal(old_total)) if old_total and new_total else None,
                                "recalculated_totals": future["totals"], "prior_approved_price": price,
                                "gross_margin_at_prior_price_percent": _fmt(100 * (Decimal(price)-Decimal(new_cost))/Decimal(price)) if price and Decimal(price) and new_cost else None,
                                "requires_human_selection_and_approval": True})
            result["price_update_impacts"] = impacts
        return result
