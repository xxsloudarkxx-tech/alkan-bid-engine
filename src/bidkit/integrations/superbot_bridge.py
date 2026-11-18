"""Contractor Superbot intake bridge with strict client/tenant isolation and approval gating."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any
import uuid

from ..domain import AuditLedger, assert_transition
from ..security import (
    SecurityContext,
    TenantIsolationError,
    assert_independent_approver,
    require_permission,
    sanitize_filename,
)
from .common import IdempotencyLedger


class SuperbotBridge:
    """Ingests opportunities/documents from Contractor Superbot without cross-client leakage."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._jobs_path = self.root / "data" / "integrations" / "superbot_jobs.json"
        self._idemp = IdempotencyLedger(self.root / "data" / "integrations" / "superbot_idempotency.json")
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self._jobs_path.exists():
            return {"clients": {}, "jobs": {}}
        return json.loads(self._jobs_path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self._jobs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._jobs_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._jobs_path)

    def intake_opportunity(
        self,
        payload: dict[str, Any],
        *,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Register client, project, and isolated expediente folder from Superbot message/files."""
        org_id = str(payload.get("org_id") or "default").strip()
        client_id = str(payload.get("client_id") or payload.get("client_slug") or "").strip()
        project_title = str(payload.get("project_title") or "").strip()
        if not client_id or not project_title:
            raise ValueError("Superbot intake requires client_id (or client_slug) and project_title.")
        if ctx:
            require_permission(ctx, "estimate:create", org_id=org_id, client_id=client_id)

        ikey = str(payload.get("idempotency_key") or f"sb:{org_id}:{client_id}:{project_title}")
        cached = self._idemp.get(org_id, ikey)
        if cached:
            return {**cached["result"], "idempotent_replay": True}

        safe_client = sanitize_filename(client_id)
        project_id = sanitize_filename(str(payload.get("project_id") or f"{safe_client}-{hashlib.sha1(project_title.encode()).hexdigest()[:6]}"))
        job_id = f"SB-{uuid.uuid4().hex[:10].upper()}"

        expediente_dir = self.root / "data" / "orgs" / sanitize_filename(org_id) / "clients" / safe_client / "projects" / project_id / "expediente"
        expediente_dir.mkdir(parents=True, exist_ok=True)
        archived_docs: list[dict[str, Any]] = []
        for idx, doc in enumerate(payload.get("documents") or [], start=1):
            name = sanitize_filename(str(doc.get("name") or f"doc_{idx}.bin"))
            raw_hex = doc.get("content_text", "")
            content = str(raw_hex).encode("utf-8")
            dest = expediente_dir / name
            dest.write_bytes(content)
            archived_docs.append({
                "name": name,
                "path": str(dest),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            })

        now = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": job_id,
            "org_id": org_id,
            "client_id": client_id,
            "client_name": str(payload.get("client_name") or client_id),
            "phone": str(payload.get("phone") or ""),
            "project_id": project_id,
            "project_title": project_title,
            "county": str(payload.get("county") or ""),
            "trade": str(payload.get("trade") or "Metal Fabrication"),
            "notes": str(payload.get("notes") or ""),
            "state": "Draft",
            "prepared_by": ctx.actor if ctx else "superbot-intake",
            "approved_by": None,
            "documents": archived_docs,
            "ready_to_send_client": False,
            "created_at": now,
            "updated_at": now,
        }

        with self._lock:
            data = self._load()
            data["clients"][f"{org_id}:{client_id}"] = {
                "org_id": org_id,
                "client_id": client_id,
                "client_name": job["client_name"],
                "phone": job["phone"],
                "trade": job["trade"],
            }
            data["jobs"][job_id] = job
            self._save(data)

        AuditLedger(self.root / "data" / "orgs" / sanitize_filename(org_id) / "audit_ledger.jsonl").record(
            org_id=org_id,
            project_id=project_id,
            actor=ctx.actor if ctx else "service:superbot",
            role=ctx.role if ctx else "operator",
            action="SUPERBOT_INTAKE",
            state_from="",
            state_to="Draft",
            resource_type="superbot_job",
            resource_id=job_id,
            detail={"client_id": client_id, "documents": len(archived_docs)},
        )
        self._idemp.record(org_id, ikey, job)
        return job

    def get_job(self, job_id: str, *, org_id: str, client_id: str | None = None, ctx: SecurityContext | None = None) -> dict[str, Any]:
        if ctx:
            require_permission(ctx, "estimate:read" if ctx.role != "client" else "estimate:read_approved", org_id=org_id, client_id=client_id)
        with self._lock:
            job = self._load()["jobs"].get(job_id)
        if not job:
            raise KeyError(f"Unknown Superbot job: {job_id}")
        if job["org_id"] != org_id:
            raise TenantIsolationError("Cross-organization access blocked.")
        if client_id and job["client_id"] != client_id:
            raise TenantIsolationError("Cross-client access blocked.")
        return job

    def list_jobs(self, *, org_id: str, client_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._load()["jobs"].values())
        return [
            j for j in rows
            if j["org_id"] == org_id and (client_id is None or j["client_id"] == client_id)
        ]

    def transition_and_approve(
        self,
        job_id: str,
        *,
        org_id: str,
        target_state: str,
        actor: str,
        role: str = "reviewer",
    ) -> dict[str, Any]:
        """Update Superbot job state enforcing independent approval before client notification."""
        with self._lock:
            data = self._load()
            job = data["jobs"].get(job_id)
            if not job or job["org_id"] != org_id:
                raise TenantIsolationError(f"Job {job_id} not accessible for org {org_id}")
            next_state = assert_transition(job["state"], target_state)
            if next_state in ("Approved", "Exported"):
                assert_independent_approver(job.get("prepared_by", ""), actor, role)
                job["approved_by"] = actor
                job["ready_to_send_client"] = True
            prev = job["state"]
            job["state"] = next_state
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save(data)
        AuditLedger(self.root / "data" / "orgs" / sanitize_filename(org_id) / "audit_ledger.jsonl").record(
            org_id=org_id,
            project_id=job["project_id"],
            actor=actor,
            role=role,
            action="SUPERBOT_STATE_CHANGE",
            state_from=prev,
            state_to=next_state,
            resource_type="superbot_job",
            resource_id=job_id,
        )
        return job
