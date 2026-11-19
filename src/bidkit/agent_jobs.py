"""Estimate runs for the app: upload, background execution, progress, delivery.

One run = one folder under the delivery directory with ``run.json`` (state),
the agent log, the package JSON, the three PDFs, the report and the ZIP.
Only one run executes at a time so API spend stays predictable.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import zipfile
from collections import deque
from datetime import date, datetime
from pathlib import Path

from . import delivery
from .app_settings import AppSettings
from .deliverables_v4 import generate_all_deliverables
from .domain import AuditLedger, normalize_state
from .estimator_agent.agent import Cancelled, EstimatorAgent, write_report
from .estimator_agent.anthropic_client import AnthropicClient, APIError
from .estimator_agent.docindex import DocIndex
from .estimator_agent.tools import ToolBox
from .package_method import load_package
from .security import SelfApprovalError

KEY_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,23}$")
ACTIVE = ("en cola", "indexando", "estimando")
MAX_UPLOAD = 2 * 1024 ** 3


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_name(name: str) -> str:
    name = Path(str(name).replace("\\", "/")).name
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name).strip(" .")
    if not name or Path(name).suffix.lower() not in (".pdf", ".zip"):
        raise ValueError("Solo se aceptan archivos PDF o ZIP")
    return name[:140]


class RunManager:
    def __init__(self, root: Path, settings: AppSettings, client_factory=None):
        self.root, self.settings = Path(root).resolve(), settings
        self.client_factory = client_factory or self._default_client
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._events: dict[str, deque] = {}

    # ───────────────────────────── paths
    @property
    def base(self) -> Path:
        out = Path(self.settings.load()["delivery"]["output_dir"] or "ENTREGAS/AGENTE")
        return out if out.is_absolute() else self.root / out

    def profiles_dir(self) -> Path:
        return self.root / "profiles"

    def knowledge_dir(self) -> Path:
        return self.root / "data" / "knowledge"

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,23}_\d{8}_\d{6}(_[a-z0-9]+)?", run_id or ""):
            raise ValueError("Corrida inválida")
        path = self.base / run_id
        if not (path / "run.json").exists():
            raise ValueError("Corrida no encontrada")
        return path

    def load_profile(self, name: str) -> dict:
        if not re.fullmatch(r"[a-z0-9_]{1,60}", name or ""):
            raise ValueError("Seleccione un perfil de contratista")
        path = self.profiles_dir() / f"{name}.json"
        if not path.exists():
            raise ValueError(f"Perfil no encontrado: {name}")
        profile = json.loads(path.read_text(encoding="utf-8"))
        if profile.get("date") in (None, "", "AUTO"):
            profile["date"] = date.today().isoformat()
        return profile

    # ───────────────────────────── uploads (chunked: plan sets are large)
    def upload_chunk(self, upload_id: str, name: str, index: int, content: str) -> dict:
        if not re.fullmatch(r"[a-f0-9-]{16,40}", upload_id or ""):
            raise ValueError("Carga inválida")
        folder = self.root / "data" / "uploads" / upload_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / _safe_name(name)
        raw = base64.b64decode(content, validate=True)
        with self._lock:
            if int(index) == 0:
                if not (raw.startswith(b"%PDF-") or raw.startswith(b"PK")):
                    raise ValueError(f"{target.name}: no es un PDF ni un ZIP válido")
                target.write_bytes(raw)
            else:
                if not target.exists():
                    raise ValueError("Carga fuera de orden; vuelva a subir el archivo")
                with open(target, "ab") as f:
                    f.write(raw)
            total = sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
        if total > MAX_UPLOAD:
            raise ValueError("La carga supera 2 GB; use la opción de ruta local")
        return {"upload_id": upload_id, "name": target.name, "bytes": target.stat().st_size}

    @staticmethod
    def _expand_zips(folder: Path) -> None:
        """PDFs inside uploaded ZIPs become part of the same bid set."""
        for z in sorted(folder.glob("*.zip")):
            sub = folder / (z.stem + "_zip")
            if sub.exists():
                continue
            sub.mkdir()
            with zipfile.ZipFile(z) as archive:
                for info in archive.infolist():
                    inner = Path(info.filename.replace("\\", "/"))
                    if info.is_dir() or ".." in inner.parts or inner.suffix.lower() != ".pdf":
                        continue
                    target, n = sub / inner.name, 1
                    while target.exists():                      # same file name in two folders of the ZIP
                        target, n = sub / f"{inner.stem}_{n}{inner.suffix}", n + 1
                    with archive.open(info) as src, open(target, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)

    # ───────────────────────────── state
    @staticmethod
    def _canonical_for(status: str) -> str:
        mapping = {
            "en cola": "Processing",
            "indexando": "Processing",
            "estimando": "Processing",
            "lista": "Review Required",
            "incompleta": "Review Required",
            "autorizada": "Approved",
            "rechazada": "Rejected",
            "exportada": "Exported",
            "cancelada": "Error",
            "interrumpida": "Error",
            "error": "Error",
            "no-go": "Rejected",
        }
        return mapping.get((status or "").lower(), normalize_state("Draft"))

    def _write(self, run_dir: Path, state: dict) -> None:
        state["canonical_state"] = self._canonical_for(state.get("status", ""))
        state.setdefault("org_id", "default")
        with self._lock:
            tmp = json.dumps(state, indent=1, ensure_ascii=False)
            (run_dir / "run.json").write_text(tmp, encoding="utf-8")

    def _read(self, run_dir: Path) -> dict:
        with self._lock:
            state = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if state["status"] in ACTIVE and state["id"] not in self._threads:
            state["status"], state["error"] = "interrumpida", "El motor se cerró mientras esta corrida trabajaba."
        state["canonical_state"] = self._canonical_for(state.get("status", ""))
        state.setdefault("org_id", "default")
        return state

    def active(self) -> str | None:
        with self._lock:
            return next((rid for rid, t in self._threads.items() if t.is_alive()), None)

    def list(self) -> list[dict]:
        rows = []
        if self.base.exists():
            for f in self.base.glob("*/run.json"):
                try:
                    rows.append(self._read(f.parent))
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(rows, key=lambda r: r.get("started_at", ""), reverse=True)

    def get(self, run_id: str) -> dict:
        run_dir = self.run_dir(run_id)
        state = self._read(run_dir)
        state["files"] = [{"name": p.name, "bytes": p.stat().st_size} for p in delivery.deliverables(run_dir)]
        zips = sorted(run_dir.glob("*_ENTREGA.zip"))
        state["zip"] = zips[0].name if zips else None
        state["events"] = list(self._events.get(run_id) or self._tail(run_dir, state["key"]))
        report = run_dir / f"{state['key']}_REPORTE_AGENTE.md"
        state["report_md"] = report.read_text(encoding="utf-8") if report.exists() else ""
        snap_file = run_dir / "bid_snapshot.json"
        if snap_file.exists():
            try:
                state["bid_snapshot"] = json.loads(snap_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        elif not state.get("bid_snapshot"):
            from .bid_snapshot import build_bid_snapshot
            man_file = run_dir / f"{state['key']}_package_manifest.json"
            if man_file.exists():
                try:
                    man = json.loads(man_file.read_text(encoding="utf-8"))
                    if man.get("bid_snapshot"):
                        state["bid_snapshot"] = man["bid_snapshot"]
                except (OSError, ValueError):
                    pass
            if not state.get("bid_snapshot"):
                state["bid_snapshot"] = build_bid_snapshot(project_name=state["key"])
        return state

    @staticmethod
    def _compact(event: dict) -> dict | None:
        kind = event.get("event")
        if kind == "assistant":
            return {"t": event.get("t"), "turn": event.get("turn"), "stage": event.get("stage"),
                    "text": (event.get("text") or "")[:400], "tools": event.get("tools") or []}
        if kind == "tool" and event.get("error"):
            return {"t": event.get("t"), "stage": "Corrección", "text": f"{event.get('name')}: {str(event.get('result'))[:300]}", "tools": []}
        if kind in ("stage", "review_done", "budget_stop", "cancelled"):
            text = {"review_done": f"Revisión independiente: {event.get('verdict')} ({event.get('findings')} hallazgos)",
                    "budget_stop": "Se alcanzó el presupuesto de tokens: cerrando con lo que hay.",
                    "cancelled": "Cancelada."}.get(kind, "")
            return {"t": event.get("t"), "stage": event.get("stage") or "Aviso", "text": text, "tools": []}
        return None

    def _tail(self, run_dir: Path, key: str, n: int = 80) -> list[dict]:
        log = run_dir / f"{key}_agent_log.jsonl"
        if not log.exists():
            return []
        out = deque(maxlen=n)
        with open(log, encoding="utf-8") as f:
            for line in f:
                try:
                    c = self._compact(json.loads(line))
                except ValueError:
                    continue
                if c:
                    out.append(c)
        return list(out)

    # ───────────────────────────── start / cancel
    def _default_client(self, model: str, effort: str, cache: bool):
        key, _ = self.settings.secret("anthropic")
        return AnthropicClient(api_key=key or None, model=model, effort=effort, cache=cache)

    def start(self, spec: dict, actor: str) -> dict:
        key = str(spec.get("key", "")).strip().upper().replace(" ", "_")
        if not KEY_RE.match(key):
            raise ValueError("Clave del proyecto: 2 a 24 letras, números, guion o guion bajo (p. ej. GONYEA)")
        with self._lock:
            if self.active():
                raise ValueError("Ya hay una corrida en curso; espere a que termine o cancélela")
        profile_name = str(spec.get("profile", ""))
        profile = self.load_profile(profile_name)
        trade = str(spec.get("trade_scope", "")).strip()
        if trade:
            profile["scope_policy"] = [trade]
        if not profile.get("scope_policy"):
            raise ValueError("Este perfil no define el oficio; escriba el oficio y alcance a estimar")
        if spec.get("upload_id"):
            docs = self.root / "data" / "uploads" / str(spec["upload_id"])
            if not re.fullmatch(r"[a-f0-9-]{16,40}", str(spec["upload_id"])) or not docs.is_dir():
                raise ValueError("No se encontraron los archivos cargados")
            docs_label = ", ".join(sorted(p.name for p in docs.iterdir() if p.is_file()))[:300]
        else:
            docs = Path(str(spec.get("path", "")).strip().strip('"'))
            if not str(spec.get("path", "")).strip() or not docs.exists():
                raise ValueError("Cargue los documentos o indique una carpeta o ZIP que exista en esta PC")
            if docs.is_file() and docs.suffix.lower() != ".zip":
                raise ValueError("La ruta debe ser una carpeta con PDFs o un archivo ZIP")
            docs_label = str(docs)
        if not self.settings.secret("anthropic")[0] and self.client_factory == self._default_client:
            raise ValueError("Falta la clave de la API de Anthropic: cárguela en Administrador → Conexiones")
        engine = self.settings.load()["engine"]
        run_id = f"{key}_{datetime.now():%Y%m%d_%H%M%S}"
        run_dir = self.base / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        state = {"id": run_id, "key": key, "status": "en cola", "stage": "En cola", "turn": 0,
                 "max_turns": engine["max_turns"], "tokens": 0, "budget_tokens": engine["budget_tokens"],
                 "actor": actor, "profile": profile_name, "contractor": profile["contractor"]["name"],
                 "generic": bool(profile.get("generic")), "docs": docs_label, "notes": str(spec.get("notes", ""))[:2000],
                 "trade_scope": trade[:1000], "model": engine["model"], "started_at": _now(), "finished_at": None,
                 "decision": None, "price": None, "direct": None, "qa": None, "proposal": None, "error": None,
                 "authorized_by": None, "source_run": None}
        self._write(run_dir, state)
        cancel = threading.Event()
        thread = threading.Thread(target=self._work, args=(run_dir, state, profile, docs, cancel), daemon=True,
                                  name=f"run-{run_id}")
        with self._lock:
            self._threads[run_id], self._cancel[run_id] = thread, cancel
            self._events[run_id] = deque(maxlen=120)
        thread.start()
        return state

    def cancel(self, run_id: str) -> dict:
        self.run_dir(run_id)
        event = self._cancel.get(run_id)
        if not event or not self._threads[run_id].is_alive():
            raise ValueError("Esa corrida ya no está trabajando")
        event.set()
        return {"id": run_id, "status": "cancelando"}

    # ───────────────────────────── worker
    def _work(self, run_dir: Path, state: dict, profile: dict, docs: Path, cancel: threading.Event) -> None:
        cfg = self.settings.load()
        engine, deliv = cfg["engine"], cfg["delivery"]
        key = state["key"]
        events = self._events[state["id"]]
        last_write = [0.0]

        def on_event(event: dict):
            compact = self._compact(event)
            if compact:
                events.append(compact)
            if event.get("event") == "assistant":
                state["turn"] = event.get("turn", state["turn"])
                state["tokens"] = event.get("tokens", state["tokens"])
                if event.get("stage"):
                    state["stage"] = event["stage"]
            elif event.get("event") == "stage":
                state["stage"] = event["stage"]
            if time.time() - last_write[0] > 1.5:
                last_write[0] = time.time()
                self._write(run_dir, state)

        result = None
        try:
            state.update(status="indexando", stage="Leyendo e indexando documentos")
            self._write(run_dir, state)
            if docs.is_dir():
                self._expand_zips(docs)
            index = DocIndex.build(docs, run_dir / "_index")
            if not index.docs:
                raise ValueError("No se encontró ningún PDF en los documentos")
            state["documents"] = len(index.docs)
            state["pages"] = sum(d["pages"] for d in index.docs.values())
            client = self.client_factory(engine["model"], engine["effort"], engine["prompt_cache"])
            reviewer = None
            if engine["independent_review"]:
                rm = engine["review_model"].strip()
                reviewer = client if not rm or rm == engine["model"] else self.client_factory(rm, engine["effort"], engine["prompt_cache"])
            kdir = self.knowledge_dir()
            toolbox = ToolBox(index, profile, run_dir, base_dir=self.profiles_dir(),
                              knowledge_dir=kdir if kdir.exists() else None,
                              price_deviation_pct=engine["price_deviation_pct"])
            agent = EstimatorAgent(
                client, toolbox, profile, run_dir / f"{key}_agent_log.jsonl", engine["max_turns"], engine["keep_images"],
                engine["web_search"], engine["web_search_uses"], engine["budget_tokens"],
                web_tool_type=engine["web_search_tool"], preflight_stop=engine["preflight_stop"],
                reviewer=reviewer, review_rounds=engine["review_fix_rounds"], extra_system=engine["extra_instructions"],
                tz_label=deliv["local_time_label"], tz_offset=deliv["local_time_offset_from_pacific_h"],
                on_event=on_event, should_stop=cancel.is_set)
            state.update(status="estimando", stage="Inventario de documentos")
            self._write(run_dir, state)
            result = agent.run(key, state["notes"])
            self._finish(run_dir, state, result, deliv)
        except Cancelled:
            state.update(status="cancelada", stage="Cancelada por el usuario")
        except (APIError, ValueError, OSError, KeyError) as exc:
            state.update(status="error", stage="Error", error=str(exc)[:600])
        except Exception as exc:  # noqa: BLE001 - never lose the state of a paid run
            state.update(status="error", stage="Error", error=f"{type(exc).__name__}: {exc}"[:600])
        finally:
            state["finished_at"] = _now()
            self._write(run_dir, state)

    def _finish(self, run_dir: Path, state: dict, result: dict, deliv: dict) -> None:
        key = state["key"]
        report = write_report(run_dir, key, result)
        if deliv["report_pdf"]:
            delivery.report_pdf(report)
        build = result.get("build") or {}
        totals = (build.get("computation") or {}).get("totals") or {}
        decision = (result.get("report") or {}).get("decision")

        from .bid_snapshot import build_bid_snapshot
        pkg_file = run_dir / f"{key.lower()}.json"
        pkg_data = None
        if pkg_file.exists():
            try:
                pkg_data = json.loads(pkg_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        snapshot = result.get("bid_snapshot") or build_bid_snapshot(
            result.get("notes") or [],
            project_name=key,
            pkg_dict=pkg_data,
        )
        state["bid_snapshot"] = snapshot
        (run_dir / "bid_snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

        state.update(decision=decision, price=totals.get("price"), direct=totals.get("direct"),
                     qa=(build.get("qa") or {}).get("status"), proposal=(build.get("proposal_release") or {}).get("label"),
                     tokens=state["tokens"], usage=result.get("usage"), images=result.get("images"),
                     review=(result.get("reviews") or [{}])[-1].get("verdict"))
        if decision == "NO_GO":
            state.update(status="no-go", stage="NO-GO: requisito que ya no se puede cumplir")
        elif build and state["qa"] == "PASS" and result.get("completed"):
            state.update(status="lista", stage="Entrega lista para revisión")
        else:
            state.update(status="incompleta", stage="Terminó sin paquete verificado; revise el reporte")
        delivery.make_zip(run_dir, key, package_json=deliv["zip_include_package_json"], log=deliv["zip_include_log"])

    # ───────────────────────────── after the run
    def file(self, run_id: str, name: str) -> Path:
        run_dir = self.run_dir(run_id)
        if not name or Path(name).name != name or Path(name).suffix.lower() not in (".pdf", ".md", ".zip", ".json"):
            raise ValueError("Archivo inválido")
        path = run_dir / name
        if not path.is_file():
            raise ValueError("Archivo no encontrado")
        return path

    def _package(self, run_dir: Path, state: dict) -> Path:
        path = run_dir / f"{state['key'].lower()}.json"
        if not path.exists():
            raise ValueError("Esta corrida no tiene paquete")
        return path

    def authorize(self, run_id: str, actor: str, note: str = "", *, strict_separation: bool = False) -> dict:
        run_dir = self.run_dir(run_id)
        state = self._read(run_dir)
        if state["status"] != "lista":
            raise ValueError("Solo se autoriza una entrega lista y verificada")
        manifest = delivery.authorize(
            self._package(run_dir, state),
            run_dir,
            actor,
            note,
            prepared_by=state.get("actor", ""),
            org_id=state.get("org_id", "default"),
            strict_separation=strict_separation,
        )
        deliv = self.settings.load()["delivery"]
        state.update(
            proposal=manifest["proposal_release"]["label"],
            authorized_by=actor,
            authorized_at=_now(),
            version=manifest.get("version", 1),
            independent_reviewer_verified=manifest.get("independent_reviewer_verified", False),
            status="autorizada",
            stage=f"Propuesta autorizada por {actor}",
        )
        delivery.make_zip(run_dir, state["key"], package_json=deliv["zip_include_package_json"], log=deliv["zip_include_log"])
        self._write(run_dir, state)
        return self.get(run_id)

    def reject(self, run_id: str, actor: str, reason: str = "") -> dict:
        run_dir = self.run_dir(run_id)
        state = self._read(run_dir)
        actor_clean = (actor or "").strip()
        if not actor_clean:
            raise ValueError("Indique responsable de rechazo")
        prev = state.get("canonical_state", "Review Required")
        state.update(status="rechazada", rejected_by=actor_clean, rejected_at=_now(), rejection_reason=reason.strip(), stage=f"Rechazada por {actor_clean}")
        self._write(run_dir, state)
        AuditLedger(self.root / "data" / "orgs" / state.get("org_id", "default") / "audit_ledger.jsonl").record(
            org_id=state.get("org_id", "default"),
            project_id=state["key"],
            actor=actor_clean,
            role="reviewer",
            action="PROPOSAL_REJECTED",
            state_from=prev,
            state_to="Rejected",
            resource_type="run",
            resource_id=run_id,
            detail={"reason": reason.strip()},
        )
        return self.get(run_id)

    def export_v4(self, run_id: str, actor: str) -> dict:
        run_dir = self.run_dir(run_id)
        state = self._read(run_dir)
        pkg = load_package(self._package(run_dir, state))
        version = int(state.get("version") or 1)
        bundle = generate_all_deliverables(
            pkg,
            run_dir / "deliverables_v4",
            version=version,
            status=state.get("canonical_state") or "Review Required",
            reviewer=state.get("authorized_by") or "",
        )
        prev = state.get("canonical_state", "Approved")
        if prev == "Approved":
            state.update(status="exportada", stage=f"Paquete de 6 entregables exportado (v{version})")
            self._write(run_dir, state)
        AuditLedger(self.root / "data" / "orgs" / state.get("org_id", "default") / "audit_ledger.jsonl").record(
            org_id=state.get("org_id", "default"),
            project_id=state["key"],
            actor=actor,
            role="operator",
            action="DELIVERABLES_EXPORTED",
            state_from=prev,
            state_to="Exported" if prev == "Approved" else prev,
            resource_type="run",
            resource_id=run_id,
            detail={"version": version},
        )
        return bundle

    def rebrand(self, run_id: str, profile_name: str, actor: str) -> dict:
        """Apply a contractor to a package made without brand (or for someone else)."""
        src_dir = self.run_dir(run_id)
        src = self._read(src_dir)
        profile = self.load_profile(profile_name)
        new_id = f"{src['key']}_{datetime.now():%Y%m%d_%H%M%S}_{re.sub(r'[^a-z0-9]', '', profile_name)[:12]}"
        out = self.base / new_id
        _, manifest = delivery.rebrand(self._package(src_dir, src), profile, self.profiles_dir(), out)
        totals = manifest["computation"]["totals"]
        deliv = self.settings.load()["delivery"]
        note = out / f"{src['key']}_REPORTE_AGENTE.md"
        old = src_dir / note.name
        header = (f"> Paquete recalculado para **{profile['contractor']['name']}** a partir de la corrida {run_id} "
                  f"(mismo takeoff; tarifas, markups y datos del nuevo perfil).\n\n")
        note.write_text(header + (old.read_text(encoding="utf-8") if old.exists() else ""), encoding="utf-8")
        if deliv["report_pdf"]:
            delivery.report_pdf(note)
        state = {**src, "id": new_id, "actor": actor, "profile": profile_name, "contractor": profile["contractor"]["name"],
                 "generic": bool(profile.get("generic")), "started_at": _now(), "finished_at": _now(), "status": "lista",
                 "stage": "Entrega lista para revisión", "price": totals["price"], "direct": totals["direct"],
                 "qa": manifest["qa"]["status"], "proposal": manifest["proposal_release"]["label"],
                 "authorized_by": None, "source_run": run_id, "error": None}
        if state["qa"] != "PASS":
            state.update(status="incompleta", stage="La verificación cruzada falló al recalcular")
        delivery.make_zip(out, src["key"], package_json=deliv["zip_include_package_json"], log=False)
        self._write(out, state)
        return self.get(new_id)

    def purge_superseded(self, project_key: str | None = None, keep_latest: int = 1, dry_run: bool = False) -> dict:
        """Purga borradores redundantes u obsoletos para optimizar almacenamiento."""
        from .recycler import purge_superseded_runs
        return purge_superseded_runs(self.base, project_key=project_key, keep_latest_drafts=keep_latest, dry_run=dry_run)

    def purge_uploads(self, max_age_seconds: float = 3600.0, dry_run: bool = False) -> dict:
        """Purga fragmentos y archivos de carga temporales en data/uploads/."""
        from .recycler import purge_raw_uploads
        return purge_raw_uploads(self.root / "data" / "uploads", max_age_seconds=max_age_seconds, dry_run=dry_run)

    def recycle(self, project_key: str | None = None, dry_run: bool = False) -> dict:
        """Ejecuta una pasada integral de reciclaje de corridas y cargas temporales."""
        from .recycler import recycle_all
        return recycle_all(self.root, project_key=project_key, dry_run=dry_run)

