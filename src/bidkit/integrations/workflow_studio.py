"""ALKAN Workflow Studio integration client, event outbox, and inbound command validator."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid

from ..security import (
    AuthenticationError,
    SecurityContext,
    redact_secrets,
    require_permission,
    sign_payload,
    verify_hmac_signature,
)
from .common import IdempotencyLedger, post_json, retry_with_backoff

STUDIO_EVENTS: tuple[str, ...] = (
    "bid.created",
    "bid.documents_parsed",
    "bid.takeoff_completed",
    "bid.pricing_completed",
    "bid.review_flagged",
    "bid.review_approved",
    "bid.rfq_prepared",
    "bid.rfi_prepared",
    "bid.proposal_generated",
    "bid.exported",
)


class WorkflowStudioClient:
    """Bid Engine <-> ALKAN Workflow Studio contract client matching /api/automation/event."""

    def __init__(
        self,
        root: Path,
        *,
        base_url: str | None = None,
        shared_secret: str | None = None,
        transport: Callable[..., tuple[int, dict[str, Any]]] | None = None,
    ):
        self.root = Path(root).resolve()
        self.base_url = (base_url if base_url is not None else os.environ.get("ALKAN_STUDIO_URL", "")).rstrip("/")
        self.shared_secret = shared_secret if shared_secret is not None else os.environ.get("ALKAN_STUDIO_HMAC_SECRET", "")
        self._transport = transport or post_json
        self._outbox_path = self.root / "data" / "integrations" / "studio_outbox.json"
        self._idemp = IdempotencyLedger(self.root / "data" / "integrations" / "studio_idempotency.json")
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        with self._lock:
            outbox = self._load_outbox()
        return {
            "service": "alkan-workflow-studio",
            "configured": bool(self.base_url),
            "endpoint": f"{self.base_url}/api/automation/event" if self.base_url else None,
            "hmac_enabled": bool(self.shared_secret),
            "outbox_counts": {
                "pending": sum(1 for e in outbox if e["delivery_status"] == "pending"),
                "delivered": sum(1 for e in outbox if e["delivery_status"] == "delivered"),
                "failed": sum(1 for e in outbox if e["delivery_status"] == "failed"),
            },
            "supported_events": list(STUDIO_EVENTS),
        }

    def _load_outbox(self) -> list[dict[str, Any]]:
        if not self._outbox_path.exists():
            return []
        return json.loads(self._outbox_path.read_text(encoding="utf-8"))

    def _save_outbox(self, rows: list[dict[str, Any]]) -> None:
        self._outbox_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._outbox_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self._outbox_path)

    def emit_event(
        self,
        *,
        event_type: str,
        org_id: str,
        project_id: str,
        estimate_id: str,
        actor: str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
        version: int = 1,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Validate, deduplicate, and send (or queue if unconfigured) a bid.* event to Studio."""
        if event_type not in STUDIO_EVENTS:
            raise ValueError(f"Unsupported Studio event type: {event_type!r}")
        if not org_id.strip() or not project_id.strip():
            raise ValueError("org_id and project_id are required on Studio events.")
        if ctx:
            require_permission(ctx, "integration:write", org_id=org_id)

        ikey = idempotency_key or f"{org_id}:{project_id}:{estimate_id}:{event_type}:v{version}"
        cached = self._idemp.get(org_id, ikey)
        if cached:
            return {**cached["result"], "idempotent_replay": True}

        envelope = {
            "type": event_type,
            "source": "alkan-bid-engine",
            "entityType": "bid",
            "entityId": estimate_id,
            "payload": redact_secrets(payload),
            "metadata": {
                "org_id": org_id,
                "project_id": project_id,
                "version": version,
                "actor": actor,
                "idempotency_key": ikey,
                "emitted_at": datetime.now(timezone.utc).isoformat(),
                "trace_id": str(uuid.uuid4()),
            },
        }

        if not self.base_url:
            entry = {
                "idempotency_key": ikey,
                "delivery_status": "pending",
                "attempts": 0,
                "reason": "ALKAN_STUDIO_URL not configured; queued in local outbox.",
                "envelope": envelope,
            }
            with self._lock:
                rows = self._load_outbox()
                rows.append(entry)
                self._save_outbox(rows)
            self._idemp.record(org_id, ikey, entry)
            return entry

        endpoint = f"{self.base_url}/api/automation/event"
        ts = str(int(time.time()))
        raw_bytes = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        headers = {"X-Idempotency-Key": ikey, "X-Org-Id": org_id, "X-ALKAN-Timestamp": ts}
        if self.shared_secret:
            headers["X-ALKAN-Signature"] = f"sha256={sign_payload(self.shared_secret, ts, raw_bytes)}"

        try:
            (http_status, resp_body), attempts = retry_with_backoff(
                lambda: self._transport(endpoint, envelope, headers=headers),
                max_attempts=3,
            )
            entry = {
                "idempotency_key": ikey,
                "delivery_status": "delivered" if 200 <= http_status < 300 else "failed",
                "http_status": http_status,
                "attempts": attempts,
                "response": resp_body,
                "envelope": envelope,
            }
        except Exception as exc:
            entry = {
                "idempotency_key": ikey,
                "delivery_status": "failed",
                "attempts": 3,
                "reason": str(exc),
                "envelope": envelope,
            }
        with self._lock:
            rows = self._load_outbox()
            rows.append(entry)
            self._save_outbox(rows)
        if entry["delivery_status"] == "delivered":
            self._idemp.record(org_id, ikey, entry)
        return entry

    def verify_inbound_command(
        self,
        *,
        body: bytes,
        timestamp: str,
        signature: str,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Validate HMAC or authenticated service context for inbound Workflow Studio commands."""
        if self.shared_secret:
            if not verify_hmac_signature(self.shared_secret, timestamp, body, signature):
                raise AuthenticationError("Invalid ALKAN Workflow Studio HMAC signature.")
        elif ctx is None:
            raise AuthenticationError("Service authentication or ALKAN_STUDIO_HMAC_SECRET required.")
        payload = json.loads(body.decode("utf-8"))
        org_id = str(payload.get("org_id") or "")
        project_id = str(payload.get("project_id") or "")
        if not org_id or not project_id:
            raise ValueError("Inbound command requires org_id and project_id.")
        if ctx:
            require_permission(ctx, "integration:write", org_id=org_id)
        return payload

    def list_outbox(self, *, org_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._load_outbox()
        if org_id is not None:
            rows = [r for r in rows if r["envelope"]["metadata"].get("org_id") == org_id]
        return list(reversed(rows[-100:]))
