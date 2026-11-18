"""Core domain state machine and tamper-evident audit ledger for ALKAN Bid Engine."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
from typing import Any

CANONICAL_STATES: tuple[str, ...] = (
    "Draft",
    "Processing",
    "Review Required",
    "Approved",
    "Rejected",
    "Exported",
    "Error",
)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "Draft": {"Draft", "Processing", "Review Required", "Error"},
    "Processing": {"Processing", "Review Required", "Error", "Rejected"},
    "Review Required": {"Review Required", "Approved", "Rejected", "Processing", "Draft", "Error"},
    "Approved": {"Approved", "Exported", "Review Required", "Rejected"},
    "Rejected": {"Rejected", "Draft", "Processing", "Review Required"},
    "Exported": {"Exported", "Approved", "Review Required"},
    "Error": {"Error", "Draft", "Processing", "Review Required"},
}

LEGACY_STATUS_MAP: dict[str, str] = {
    "draft": "Draft",
    "borrador": "Draft",
    "queued": "Processing",
    "running": "Processing",
    "processing": "Processing",
    "en_proceso": "Processing",
    "pendiente": "Review Required",
    "lista": "Review Required",
    "review required": "Review Required",
    "review_required": "Review Required",
    "needs_review": "Review Required",
    "autorizada": "Approved",
    "approved": "Approved",
    "aprobado": "Approved",
    "rejected": "Rejected",
    "rechazado": "Rejected",
    "exported": "Exported",
    "exportado": "Exported",
    "detenida": "Error",
    "bloqueada": "Error",
    "error": "Error",
    "failed": "Error",
}


class InvalidStateTransitionError(ValueError):
    """Raised when an invalid bid workflow transition is attempted."""


def normalize_state(value: str | None) -> str:
    """Map legacy or canonical state labels onto CANONICAL_STATES."""
    raw = (value or "Draft").strip()
    if raw in CANONICAL_STATES:
        return raw
    mapped = LEGACY_STATUS_MAP.get(raw.lower())
    if mapped:
        return mapped
    raise ValueError(f"Unknown workflow state: {value!r}")


def assert_transition(current_state: str, target_state: str) -> str:
    """Validate transition between canonical or legacy states and return target."""
    src = normalize_state(current_state)
    dst = normalize_state(target_state)
    if dst not in ALLOWED_TRANSITIONS[src]:
        raise InvalidStateTransitionError(f"Invalid transition from {src!r} to {dst!r}")
    return dst


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AuditEvent:
    seq: int
    timestamp: str
    org_id: str
    project_id: str
    actor: str
    role: str
    action: str
    state_from: str
    state_to: str
    resource_type: str
    resource_id: str
    detail: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    entry_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AuditLedger:
    """Append-only SHA-256 hash-chained audit trail per organization or root."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read_lines(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for idx, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entries.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corrupted audit ledger JSON on line {idx}: {exc}") from exc
        return entries

    def record(
        self,
        *,
        org_id: str,
        project_id: str,
        actor: str,
        role: str,
        action: str,
        state_from: str = "",
        state_to: str = "",
        resource_type: str = "bid",
        resource_id: str = "",
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        if not org_id.strip():
            raise ValueError("org_id is required for audit logging")
        if not actor.strip():
            raise ValueError("actor is required for audit logging")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            existing = self._read_lines()
            prev_hash = existing[-1]["entry_hash"] if existing else "0" * 64
            seq = (existing[-1]["seq"] + 1) if existing else 1
            body = {
                "seq": seq,
                "timestamp": _utc_now(),
                "org_id": org_id.strip(),
                "project_id": project_id.strip(),
                "actor": actor.strip(),
                "role": (role or "operator").strip(),
                "action": action.strip(),
                "state_from": state_from,
                "state_to": state_to,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail": detail or {},
                "prev_hash": prev_hash,
            }
            entry_hash = _stable_hash(body)
            event = AuditEvent(entry_hash=entry_hash, **body)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
            return event

    def list_events(self, *, org_id: str | None = None, project_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._read_lines()
        if org_id is not None:
            rows = [r for r in rows if r.get("org_id") == org_id]
        if project_id is not None:
            rows = [r for r in rows if r.get("project_id") == project_id]
        return list(reversed(rows[-limit:]))

    def verify_chain(self) -> dict[str, Any]:
        with self._lock:
            rows = self._read_lines()
        expected_prev = "0" * 64
        for idx, row in enumerate(rows, start=1):
            if row.get("seq") != idx:
                return {"valid": False, "count": len(rows), "error": f"Sequence mismatch at line {idx}"}
            if row.get("prev_hash") != expected_prev:
                return {"valid": False, "count": len(rows), "error": f"Broken prev_hash at seq {idx}"}
            body = {k: v for k, v in row.items() if k != "entry_hash"}
            recomputed = _stable_hash(body)
            if row.get("entry_hash") != recomputed:
                return {"valid": False, "count": len(rows), "error": f"Tampered entry_hash at seq {idx}"}
            expected_prev = recomputed
        return {"valid": True, "count": len(rows), "head_hash": expected_prev}
