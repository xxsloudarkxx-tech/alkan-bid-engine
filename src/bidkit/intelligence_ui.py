"""Loopback UI; forms and tables share the dossier service, no separate drafts."""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit, parse_qs, quote
import webbrowser

from .intelligence import Intelligence, difference
from .intelligence_store import RevisionConflict
from .intelligence_reports import export_document
from .price_catalog import FIELDS
from .data_store import fingerprint
from .estimate_workflow import EstimateWorkflow
from .supplier_exports import artifact as supplier_artifact, export_supplier_center
from . import material_import
from .estimation_ui import measurement_upload, measurement_tool, agent_status, run_agent
from .app_api import AppAPI, Download

MAX_BODY = 38 * 1024 * 1024


def make_handler(root, app=None):
    app = app or AppAPI(root)
    service = Intelligence(root); workflow = EstimateWorkflow(root,service); token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def send(self, status, data, kind="application/json; charset=utf-8", download=None):
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8") if not isinstance(data, bytes) else data
            self.send_response(status)
            if download: self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(download))
            for key, value in {"Content-Type": kind, "Content-Length": str(len(raw)), "Cache-Control": "no-store",
                               "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                               "Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"}.items():
                self.send_header(key, value)
            self.end_headers(); self.wfile.write(raw)

        def trusted(self):
            authority = f"127.0.0.1:{self.server.server_port}"
            return self.headers.get("Host") == authority and self.headers.get("Origin", "http://" + authority) == "http://" + authority

        def do_GET(self):
            if not self.trusted(): return self.send(403, {"error": "Origen local inválido"})
            url = urlsplit(self.path); query = parse_qs(url.query)
            pid = query.get("project_id", [""])[0]
            try:
                # "/" is the unified app; the dossier panel keeps its old deep links ("/?mode=…&project_id=…").
                if url.path == "/" and not url.query: return self.send(200, Path(__file__).with_name("app.html").read_bytes(), "text/html; charset=utf-8")
                if url.path in ("/", "/expedientes"): return self.send(200, Path(__file__).with_name("intelligence_ui.html").read_bytes(), "text/html; charset=utf-8")
                if url.path in ("/app.js", "/nav.js"): return self.send(200, Path(__file__).with_name(url.path[1:]).read_bytes(), "text/javascript; charset=utf-8")
                if url.path.startswith("/api/app/"):
                    result = app.get(url.path, query)
                    if isinstance(result, Download):
                        return self.send(200, result.path.read_bytes(), result.kind, download=result.path.name if query.get("download") else None)
                    if result is not None: return self.send(200, result)
                if url.path == "/nuevo": return self.send(200, Path(__file__).with_name("quick_start.html").read_bytes(), "text/html; charset=utf-8")
                if url.path == "/intelligence_ui.js": return self.send(200, Path(__file__).with_name("intelligence_ui.js").read_bytes(), "text/javascript; charset=utf-8")
                if url.path == "/contractor_workflow.js": return self.send(200, Path(__file__).with_name("contractor_workflow.js").read_bytes(), "text/javascript; charset=utf-8")
                if url.path == "/herramientas": return self.send(200, Path(__file__).with_name("estimation_tools.html").read_bytes(), "text/html; charset=utf-8")
                if url.path == "/estimation_tools.js": return self.send(200, Path(__file__).with_name("estimation_tools.js").read_bytes(), "text/javascript; charset=utf-8")
                if url.path == "/api/agent/status": return self.send(200, agent_status())
                if url.path == "/api/session": return self.send(200, {"token": token})
                if url.path == "/api/projects": return self.send(200, service.list_projects())
                if url.path == "/api/catalog": return self.send(200, service.catalog(query.get("q", [""])[0],query.get("trade", [""])[0]))
                if url.path == "/api/actual-analysis": return self.send(200, service.actual_analysis(query.get("trade",[""])[0],query.get("work_type",[""])[0],query.get("provider",[""])[0]))
                if url.path == "/api/catalog-template": return self.send(200, (",".join(FIELDS)+"\n").encode(), "text/csv; charset=utf-8")
                if url.path == "/api/supplier-export-file":
                    path=supplier_artifact(service,pid,query.get("name",[""])[0])
                    kind="text/csv; charset=utf-8" if path.suffix.lower()==".csv" else "application/pdf"
                    return self.send(200,path.read_bytes(),kind)
                if url.path == "/api/material-preview":
                    file, rows = material_import.load_material_rows(root, query.get("file",[""])[0])
                    return self.send(200, material_import.preview(service, pid, file, rows))
                if url.path == "/api/workflow":return self.send(200,workflow.get(pid))
                if url.path == "/api/project":
                    row = service.store.load(pid); service.check_originals(pid, row["state"])
                    row["state"]["result"] = service.evaluate(row["state"])
                    return self.send(200, row)
                if url.path == "/api/history":
                    history = service.store.history(pid); previous = {}
                    rows = []
                    for r in history:
                        rows.append({k: r[k] for k in ("revision", "created_at", "actor", "action", "sha256")})
                        rows[-1]["difference"] = difference(previous, r["state"]); previous = r["state"]
                    return self.send(200, rows)
                if url.path == "/api/export-file":
                    name = query.get("name", [""])[0]
                    if not name or Path(name).name != name or not name.endswith(".pdf"): raise ValueError("Archivo inválido")
                    path = service.store.child(pid,"exports",name)
                    raw=path.read_bytes()
                    if path.stem.rsplit("-",1)[-1]!=fingerprint(list(raw))[:12]: raise ValueError("Exportación histórica modificada")
                    return self.send(200, raw, "application/pdf")
                if url.path == "/api/original":
                    row = service.store.load(pid); service.check_originals(pid, row["state"])
                    doc = next(d for d in row["state"]["documents"] if d["document_id"] == query.get("document_id", [""])[0])
                    path = service.store.child(pid,"originals",doc["stored_name"])
                    kind = {".pdf":"application/pdf", ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg", ".txt":"text/plain; charset=utf-8"}.get(path.suffix.lower(),"application/octet-stream")
                    return self.send(200, path.read_bytes(), kind)
                return self.send(404, {"error": "Ruta no encontrada"})
            except (ValueError, FileNotFoundError, StopIteration) as exc:
                return self.send(400, {"error": str(exc) or "Registro no encontrado"})

        def do_POST(self):
            if not self.trusted() or self.headers.get("X-ALKAN-Token") != token: return self.send(403, {"error": "Sesión local inválida"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY: raise ValueError("Solicitud excede límite de 38 MB; cargue por lotes")
                if self.headers.get_content_type() != "application/json": raise ValueError("Content-Type inválido")
                req = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Número no finito")))
                if not isinstance(req,dict):raise ValueError("La solicitud debe ser un objeto JSON")
                actor = str(req.get("actor", "")).strip()
                if not actor: raise ValueError("Indique responsable")
                path = urlsplit(self.path).path; pid = req.get("project_id")
                if path.startswith("/api/app/"):
                    result = app.post(path, req, actor)
                    return self.send(200, result) if result is not None else self.send(404, {"error": "Ruta no encontrada"})
                if path == "/api/measurement/upload": result=measurement_upload(root,req["content"])
                elif path == "/api/measurement/tool": result=measurement_tool(root,req["name"],req["arguments"])
                elif path == "/api/agent/run": result=run_agent(root,req)
                elif path == "/api/workflow/create":result=workflow.create(req["project"],actor,req["request_id"])
                elif path == "/api/workflow/upload":result=workflow.upload(pid,req["revision"],actor,[(f["name"],base64.b64decode(f["content"],validate=True)) for f in req["files"]],req["request_id"])
                elif path == "/api/workflow/action":result=workflow.execute(pid,req["revision"],actor,req["action"],req.get("payload",{}),req["request_id"])
                elif path == "/api/workflow/catalog-use":result=workflow.attach_catalog(pid,req["revision"],actor,req["payload"],req["request_id"])
                elif path == "/api/workflow/export":result=workflow.export(pid,req["revision"],actor,req["kinds"],req.get("language","en"),req.get("final",False),req["request_id"])
                elif path == "/api/supplier-export":
                    result=export_supplier_center(service,pid,req["revision"],req["kind"],req.get("language","en"),req.get("formats","both"))
                elif path == "/api/material-apply":
                    file, rows = material_import.load_material_rows(root, req["file"])
                    result=material_import.apply(service,pid,req["revision"],actor,file,rows,
                                                 confirm=req.get("confirm",False),request_id=req.get("request_id"))
                elif path == "/api/create": result = service.create(req["project"], actor)
                elif path == "/api/adopt": result = service.adopt(pid, req["project"], actor)
                elif path == "/api/upload":
                    result = service.upload(pid, req["revision"], actor, [(f["name"], base64.b64decode(f["content"], validate=True)) for f in req["files"]])
                elif path == "/api/import-legacy": result = service.import_legacy(pid, req["revision"], actor)
                elif path == "/api/catalog-use": result = service.attach_catalog(pid, req["revision"], actor, req["payload"])
                elif path == "/api/action": result = service.transact(pid, req["revision"], actor, req["action"], req.get("payload", {}))
                elif path == "/api/export":
                    if service.store.load(pid)["revision"] != req["revision"]: raise RevisionConflict("Recargue antes de exportar")
                    artifact = export_document(service, pid, req["kind"], req.get("language", "en"))
                    result = {"url": f"/api/export-file?project_id={pid}&name={artifact.name}"}
                else: return self.send(404, {"error": "Ruta no encontrada"})
                return self.send(200, result)
            except RevisionConflict as exc: return self.send(409, {"error": str(exc)})
            except (ValueError, KeyError, TypeError, StopIteration, FileNotFoundError) as exc:
                return self.send(400, {"error": str(exc) or "Registro no encontrado"})

    return Handler


def serve(root, port=8765, *, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"ALKAN Bid Engine: {url}", flush=True)
    if open_browser: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
