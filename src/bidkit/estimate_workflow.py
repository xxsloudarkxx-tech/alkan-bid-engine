"""Persistent coordination of existing V2.1 engines, using the same dossier revisions."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from uuid import UUID, uuid4, uuid5

from .data_store import fingerprint
from .intelligence import Intelligence, basis, difference
from .intelligence_reports import export_document
from .intelligence_store import RevisionConflict, utcnow

STEPS = ("documents", "analysis", "quantities", "costs", "approval")
EXPORT_KINDS = ("internal", "supplier", "proposal", "contract")
# Documents created automatically when an event is saved. Same gates as manual export; nothing is sent.
AUTO_EXPORTS = {"approve": (("internal", False), ("proposal", True)), "contract_acceptance": (("contract", True),)}
AUTO_LANGUAGE = "es"
AUTO_NAMESPACE = UUID("3c0f6a52-9d1e-4b8a-a0f1-5e2d7c9b4a10")
LABELS = ("Proyecto y documentos", "Análisis y evidencia", "Partidas y cantidades", "Proveedores y costos", "Aprobación y documentos")
DOMAIN_ACTIONS = {"analyze", "review_document", "line", "supplier", "quote", "quote_batch", "select_quote", "settings",
                  "resolve", "requirement", "change_order", "review_change_order", "approve", "issue", "contract_acceptance",
                  "actual_cost", "catalog_import", "catalog_review"}


class EstimateWorkflow:
    def __init__(self, root, service=None):
        self.service = service or Intelligence(root)
        self.store = self.service.store

    @staticmethod
    def _request(actor, action, payload, request_id):
        if not str(actor or "").strip(): raise ValueError("Indique el responsable de esta revisión")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise ValueError("Identificador de operación inválido; recargue e intente de nuevo")
        return fingerprint({"actor":actor,"action":action,"payload":payload})

    @staticmethod
    def _receipt(row, request_id, digest):
        old=row["state"].get("workflow",{}).get("operations",{}).get(request_id)
        if old and old["digest"]!=digest: raise ValueError("Esta operación ya se usó con información diferente")
        return old

    @staticmethod
    def _documents(state):
        return sorted(d["sha256"] for d in state["documents"])

    def create(self, project, actor, request_id):
        digest=self._request(actor,"create",project,request_id)
        pid=str(uuid5(UUID("7701a8e1-0218-4966-b4e6-d937a9e59138"),request_id))
        try: row=self.store.load(pid)
        except FileNotFoundError:
            try:row=self.service.create({**project,"workflow_creation_digest":digest},actor,project_id=pid)
            except RevisionConflict:
                row=self.store.load(pid)
        if row["state"]["project"].get("workflow_creation_digest")!=digest:
            raise ValueError("La solicitud de alta ya corresponde a otro proyecto")
        return self.get(pid)

    def get(self, pid):
        row=self.store.load(pid);self.service.check_originals(pid,row["state"])
        return self.present(row)

    def present(self, row):
        row=deepcopy(row);state=row["state"];state["result"]=self.service.evaluate(state)
        result=state["result"];meta=state.get("workflow",{});docs=self._documents(state)
        analyzed=bool(docs) and meta.get("analyzed_documents")==docs
        active=[l for l in state["lines"] if l.get("active",True)]
        blockers=result["release_blockers"]
        quantities=bool(active) and not any("QUANTITY" in b or "CONTRADICTIONS" in b for b in blockers) and all(l.get("specification") for l in active)
        prices=bool(active) and all(any(q["quote_id"]==l.get("selected_quote_id") and q["eligible"] for q in result["comparisons"].get(l["line_id"],[])) for l in active)
        approved=bool(state.get("current_approval")) and not blockers
        completed=[bool(docs),analyzed and all(d.get("reviewed_by") for d in state["documents"]),quantities,
                   prices and state["financial"].get("confirmed") is True and result["totals"]["estimated_all_in_cost"] is not None,approved]
        selected=meta.get("current_step")
        if selected not in STEPS:selected=STEPS[next((i for i,done in enumerate(completed) if not done),4)]
        labels={"internal":"Análisis interno de costos","proposal":"Propuesta comercial","contract":"Registro de aceptación de contrato"}
        generated=[{"kind":a["kind"],"label":labels[a["kind"]]+("" if a["final"] else " · borrador"),"url":f"/api/export-file?project_id={row['project_id']}&name={a['name']}"}
                   for a in meta.get("exports",[]) if a["kind"] in labels and a["basis"]==basis(state)]
        row["workflow_view"]={"generated_documents":generated,"current_step":selected,"steps":[{"id":step,"label":label,"complete":done} for step,label,done in zip(STEPS,LABELS,completed)],
                              "progress":20*sum(completed),"analyzed":analyzed,"ready_for_approval":not blockers,
                              "approved":approved,"release_blockers":blockers,"saved_revision":row["revision"],
                              "exports":meta.get("exports",[]),"auto_export_errors":meta.get("auto_export_errors",[]),"manual_review_documents":[d["document_id"] for d in state["documents"] if d.get("processing_state")=="PENDING_VISUAL_REVIEW" or any(p.get("needs_ocr_or_visual_review") for p in d["pages"])]}
        return row

    def _save(self, previous, state, actor, action, request_id, digest):
        meta=state.setdefault("workflow",{})
        meta.setdefault("operations",{})[request_id]={"digest":digest,"basis":basis(state),"action":action,"recorded_by":actor,"recorded_at":utcnow(),"revision":previous["revision"]+1}
        state["result"]=self.service.evaluate(state)
        state["result"]["changes_since_previous"]=difference(previous["state"],state)
        row=self.store.append(previous["project_id"],state,previous["revision"],actor,"WORKFLOW:"+action)
        return self.present(row)

    def execute(self, pid, revision, actor, action, payload, request_id):
        if action not in DOMAIN_ACTIONS|{"transition","calculate"}:raise ValueError("Operación de flujo desconocida")
        if not isinstance(payload,dict):raise ValueError("Información de operación inválida")
        digest=self._request(actor,action,payload,request_id)
        with self.store.locked(pid):
            previous=self.store.load(pid);self.service.check_originals(pid,previous["state"])
            if self._receipt(previous,request_id,digest):return self.present(previous)
            if previous["revision"]!=revision:raise RevisionConflict("El expediente cambió. Recargue para revisar la nueva versión antes de guardar.")
            state=deepcopy(previous["state"]);meta=state.setdefault("workflow",{})
            before=basis(state)
            if action=="transition":
                step=payload.get("step")
                if step not in STEPS:raise ValueError("Etapa inválida")
                if step!="documents" and not state["documents"]:raise ValueError("Primero cargue los documentos del proyecto")
                if step in ("quantities","costs") and not self.present(previous)["workflow_view"]["analyzed"]:
                    raise ValueError("Analice los documentos nuevos antes de revisar cantidades y costos")
                meta["current_step"]=step
            elif action=="calculate":
                meta["calculated_basis"]=before;meta["current_step"]="costs"
            else:
                already_approved=action=="approve" and payload.get("human_confirmation") is True and state.get("current_approval") and not self.service.evaluate(state)["release_blockers"]
                if not already_approved:
                    if action=="actual_cost":payload={**payload,"estimate_revision":revision,"estimated_cost_baseline":previous["state"]["result"]["totals"]["estimated_all_in_cost"]}
                    self.service.apply(state,pid,actor,action,payload)
                if action=="analyze":meta.update(analyzed_documents=self._documents(state),current_step="analysis")
                if action=="approve":meta["current_step"]="approval"
            # Navigation, repeated analysis and report receipts never change the estimate basis.
            if action not in ("approve","issue") and basis(state)!=before:state["current_approval"]=None
            saved=self._save(previous,state,actor,action,request_id,digest)
        return self._auto_export(pid,actor,action,request_id) if action in AUTO_EXPORTS else saved

    def _auto_export(self,pid,actor,action,request_id):
        """Creates the event's PDFs through the gated export path. A failed PDF never undoes the saved action."""
        for index,(kind,final) in enumerate(AUTO_EXPORTS[action]):
            state=self.store.load(pid)["state"]
            if kind=="proposal" and (not state.get("current_approval") or self.service.evaluate(state)["release_blockers"]):continue
            if kind=="contract" and not state.get("contracts"):continue
            key=basis(state)
            if any(a["basis"]==key and a["kind"]==kind and a["language"]==AUTO_LANGUAGE and a["final"]==final for a in state.get("workflow",{}).get("exports",[])):continue
            try:
                self.export(pid,self.store.load(pid)["revision"],actor,[kind],AUTO_LANGUAGE,final,str(uuid5(AUTO_NAMESPACE,f"{request_id}:{action}:{kind}:{index}")))
            except (ValueError,RevisionConflict) as error:
                self._record_auto_error(pid,actor,action,kind,str(error))
        return self.present(self.store.load(pid))

    def _record_auto_error(self,pid,actor,action,kind,message):
        try:
            with self.store.locked(pid):
                previous=self.store.load(pid);state=deepcopy(previous["state"])
                state.setdefault("workflow",{}).setdefault("auto_export_errors",[]).append({"action":action,"kind":kind,"message":message,"recorded_at":utcnow()})
                self._save(previous,state,actor,"auto_export_error",str(uuid4()),fingerprint({"action":action,"kind":kind,"message":message}))
        except RevisionConflict:
            pass  # The main action is already saved; the error stays visible in the next load of the file.

    def upload(self, pid, revision, actor, files, request_id):
        payload=[{"name":name,"sha256":sha256(raw).hexdigest()} for name,raw in files]
        digest=self._request(actor,"upload",payload,request_id)
        old=self.store.load(pid);self.service.check_originals(pid,old["state"])
        if self._receipt(old,request_id,digest):return self.present(old)
        # Content-addressed ingestion recovers safely if the process stopped before its receipt.
        seen={d["sha256"] for d in old["state"]["documents"]}
        if old["revision"]!=revision and not all(f["sha256"] in seen for f in payload):
            raise RevisionConflict("El expediente cambió; recargue antes de subir archivos nuevos")
        row=self.service.upload(pid,old["revision"],actor,files)
        with self.store.locked(pid):
            latest=self.store.load(pid)
            if latest["revision"]!=row["revision"]:raise RevisionConflict("La carga se conservó. Recargue para continuar con la revisión actual.")
            state=deepcopy(latest["state"]);state.setdefault("workflow",{})["current_step"]="documents"
            return self._save(latest,state,actor,"upload",request_id,digest)

    def export(self,pid,revision,actor,kinds,language,final,request_id):
        if not isinstance(kinds,list) or not kinds or len(set(kinds))!=len(kinds) or any(k not in EXPORT_KINDS for k in kinds):raise ValueError("Seleccione documentos válidos")
        if language not in ("en","es") or type(final) is not bool:raise ValueError("Idioma o estado de entrega inválido")
        payload={"kinds":kinds,"language":language,"final":final};digest=self._request(actor,"export",payload,request_id)
        with self.store.locked(pid):
            previous=self.store.load(pid);self.service.check_originals(pid,previous["state"])
            receipt=self._receipt(previous,request_id,digest)
            if receipt and receipt.get("basis")!=basis(previous["state"]):raise RevisionConflict("El expediente cambió desde esa exportación. Revise la versión actual y genere otra solicitud.")
            if not receipt and previous["revision"]!=revision:raise RevisionConflict("Recargue antes de generar documentos")
            state=deepcopy(previous["state"]);result=self.service.evaluate(state)
            needs_approval="proposal" in kinds or (final and any(k!="contract" for k in kinds))
            if needs_approval and (not state.get("current_approval") or result["release_blockers"]):
                raise ValueError("La entrega final requiere información completa y aprobación humana vigente")
            key=basis(state);meta=state.setdefault("workflow",{});exports=meta.setdefault("exports",[])
            artifacts=[]
            for kind in kinds:
                artifact_final = final and kind != "supplier"
                artifact=next((r for r in exports if r["basis"]==key and r["kind"]==kind and r["language"]==language and r["final"]==artifact_final),None)
                if artifact:
                    path=self.store.child(pid,"exports",artifact["name"])
                    if not path.exists() or sha256(path.read_bytes()).hexdigest()!=artifact["sha256"]:raise ValueError("Documento histórico ausente o alterado; requiere conciliación")
                else:
                    path=export_document(self.service,pid,kind,language)
                    artifact={"basis":key,"kind":kind,"language":language,"final":artifact_final,"name":path.name,"sha256":sha256(path.read_bytes()).hexdigest(),
                              "source_revision":previous["revision"],"recorded_by":actor,"recorded_at":utcnow(),"approval_id":(state.get("current_approval") or {}).get("approval_id")}
                    exports.append(artifact)
                artifacts.append({**artifact,"url":f"/api/export-file?project_id={pid}&name={artifact['name']}"})
            meta["current_step"]="approval"
            row=self.present(previous) if receipt else self._save(previous,state,actor,"export",request_id,digest)
            return {"row":row,"artifacts":artifacts}

    def attach_catalog(self,pid,revision,actor,payload,request_id):
        if not isinstance(payload,dict):raise ValueError("Referencia de catálogo inválida")
        digest=self._request(actor,"catalog_use",payload,request_id)
        old=self.store.load(pid);self.service.check_originals(pid,old["state"])
        if self._receipt(old,request_id,digest):return self.present(old)
        if old["revision"]!=revision:raise RevisionConflict("Recargue antes de vincular un precio del catálogo")
        reference={"project_id":payload["source_project_id"],"record_id":payload["record_id"]}
        existing=any(q.get("catalog_reference")==reference and q["line_id"]==payload["line_id"] for q in old["state"]["quotes"])
        row=old if existing else self.service.attach_catalog(pid,revision,actor,payload)
        with self.store.locked(pid):
            latest=self.store.load(pid)
            if latest["revision"]!=row["revision"]:raise RevisionConflict("La referencia se conservó. Recargue antes de continuar.")
            state=deepcopy(latest["state"]);state.setdefault("workflow",{})["current_step"]="costs"
            return self._save(latest,state,actor,"catalog_use",request_id,digest)
