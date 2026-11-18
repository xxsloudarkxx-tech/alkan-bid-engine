"""Multi-tenant RBAC, authentication, anti-self-approval, rate limiting, and secret sanitization."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any

ROLES: tuple[str, ...] = ("admin", "estimator", "reviewer", "operator", "client")

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "estimate:read",
        "estimate:create",
        "estimate:edit",
        "estimate:submit_review",
        "estimate:review",
        "estimate:approve",
        "estimate:reject",
        "estimate:export",
        "takeoff:edit",
        "pricebook:read",
        "pricebook:import",
        "pricebook:verify",
        "labor:read",
        "labor:verify",
        "rfq:prepare",
        "rfq:authorize_send",
        "rfi:prepare",
        "qb:dry_run",
        "qb:sync",
        "integration:read",
        "integration:write",
        "backup:manage",
        "admin:users",
        "admin:settings",
        "audit:read",
    },
    "estimator": {
        "estimate:read",
        "estimate:create",
        "estimate:edit",
        "estimate:submit_review",
        "takeoff:edit",
        "pricebook:read",
        "pricebook:import",
        "labor:read",
        "rfq:prepare",
        "rfi:prepare",
        "qb:dry_run",
        "integration:read",
        "audit:read",
    },
    "reviewer": {
        "estimate:read",
        "estimate:review",
        "estimate:approve",
        "estimate:reject",
        "pricebook:read",
        "pricebook:verify",
        "labor:read",
        "labor:verify",
        "integration:read",
        "audit:read",
    },
    "operator": {
        "estimate:read",
        "estimate:export",
        "pricebook:read",
        "labor:read",
        "rfq:prepare",
        "rfq:authorize_send",
        "qb:dry_run",
        "qb:sync",
        "integration:read",
        "integration:write",
        "backup:manage",
        "audit:read",
    },
    "client": {
        "estimate:read_approved",
    },
}

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|authorization|refresh_token|access_token|private_key)",
    re.IGNORECASE,
)
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class SecurityError(PermissionError):
    """Base security failure."""


class AuthenticationError(SecurityError):
    """Missing or invalid credentials."""


class AuthorizationError(SecurityError):
    """Caller lacks required role permission."""


class TenantIsolationError(SecurityError):
    """Cross-organization or cross-client data access denied."""


class SelfApprovalError(SecurityError):
    """Estimator attempted to approve or sign off on their own work."""


class RateLimitError(RuntimeError):
    """Too many requests within configured time window."""


@dataclass(frozen=True)
class SecurityContext:
    actor: str
    role: str
    org_id: str
    client_id: str | None = None
    allowed_orgs: tuple[str, ...] = field(default_factory=tuple)
    auth_method: str = "session"

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def has_org(self, target_org_id: str) -> bool:
        if not target_org_id:
            return False
        return target_org_id == self.org_id or target_org_id in self.allowed_orgs


def assert_independent_approver(
    prepared_by: str,
    approver: str,
    approver_role: str | None = None,
) -> None:
    """Strictly forbid an estimator/preparer from approving their own estimate or review."""
    prep = (prepared_by or "").strip()
    app = (approver or "").strip()
    if not prep:
        raise SelfApprovalError("prepared_by identity is required before authorization.")
    if not app:
        raise SelfApprovalError("approver identity is required for authorization.")
    if prep.lower() == app.lower():
        raise SelfApprovalError(
            f"Self-approval blocked: actor '{app}' prepared the estimate and cannot approve it."
        )
    if approver_role is not None and approver_role not in ("reviewer", "admin"):
        raise AuthorizationError(
            f"Role '{approver_role}' is not permitted to approve estimates; requires reviewer or admin."
        )


def require_permission(
    ctx: SecurityContext,
    permission: str,
    *,
    org_id: str | None = None,
    client_id: str | None = None,
) -> None:
    """Enforce RBAC permission + organization and optional client tenant isolation."""
    if ctx.role not in ROLE_PERMISSIONS:
        raise AuthorizationError(f"Unknown role: {ctx.role!r}")
    if permission not in ROLE_PERMISSIONS[ctx.role]:
        raise AuthorizationError(f"Role '{ctx.role}' lacks permission '{permission}'")
    if org_id is not None and not ctx.has_org(org_id):
        raise TenantIsolationError(
            f"Tenant isolation violation: actor '{ctx.actor}' (org '{ctx.org_id}') cannot access org '{org_id}'."
        )
    if ctx.client_id and client_id and ctx.client_id != client_id:
        raise TenantIsolationError(
            f"Client isolation violation: context '{ctx.client_id}' cannot access client '{client_id}'."
        )


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash password with PBKDF2-HMAC-SHA256 (200,000 iterations)."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify PBKDF2-HMAC-SHA256 password hash using constant-time comparison."""
    try:
        scheme, iter_s, salt_hex, hash_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    """Compute hex HMAC-SHA256 signature over '<timestamp>.<body>'."""
    msg = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify_hmac_signature(
    secret: str,
    timestamp: str,
    body: bytes,
    provided_signature: str,
    *,
    max_skew_seconds: int = 300,
    now_ts: float | None = None,
) -> bool:
    """Validate HMAC-SHA256 webhook/service signature and replay timestamp window."""
    if not secret or not timestamp or not provided_signature:
        return False
    try:
        ts_val = float(timestamp)
    except ValueError:
        return False
    current = time.time() if now_ts is None else now_ts
    if abs(current - ts_val) > max_skew_seconds:
        return False
    expected = sign_payload(secret, timestamp, body)
    sig_clean = provided_signature.removeprefix("sha256=").strip()
    return hmac.compare_digest(expected, sig_clean)


def sanitize_spreadsheet_cell(value: Any) -> Any:
    """Neutralize CSV/Excel formula injection on untrusted text strings."""
    if isinstance(value, str) and value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def sanitize_filename(name: str, fallback: str = "file") -> str:
    """Strip path traversal and invalid filename characters."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name or fallback).name).strip("._")
    return cleaned or fallback


def redact_secrets(obj: Any) -> Any:
    """Return a copy of obj with sensitive credential fields masked."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SECRET_KEY_RE.search(str(k)) and isinstance(v, str) and v:
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    return obj


class SlidingWindowRateLimiter:
    """In-memory thread-safe per-key sliding window rate limiter."""

    def __init__(self, max_requests: int = 120, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, now_ts: float | None = None) -> None:
        now = time.monotonic() if now_ts is None else now_ts
        cutoff = now - self.window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.max_requests:
                raise RateLimitError(f"Rate limit exceeded for {key} ({self.max_requests}/{self.window_seconds}s)")
            q.append(now)


class AuthStore:
    """Persistent multi-tenant user & service API-key registry."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"organizations": {"default": {"name": "Default ALKAN Org"}}, "users": {}, "api_keys": {}, "sessions": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def create_organization(self, org_id: str, name: str) -> dict[str, Any]:
        oid = sanitize_filename(org_id.lower())
        with self._lock:
            data = self._load()
            data["organizations"][oid] = {"org_id": oid, "name": name.strip() or oid, "created_at": datetime.now(timezone.utc).isoformat()}
            self._save(data)
            return data["organizations"][oid]

    def create_user(
        self,
        username: str,
        password: str,
        *,
        role: str,
        org_id: str = "default",
        allowed_orgs: list[str] | None = None,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        if role not in ROLES:
            raise ValueError(f"Invalid role {role!r}; expected one of {ROLES}")
        uname = username.strip().lower()
        if not uname or not re.match(r"^[a-z0-9._@-]{3,64}$", uname):
            raise ValueError(f"Invalid username: {username!r}")
        with self._lock:
            data = self._load()
            if org_id not in data["organizations"]:
                self.create_organization(org_id, org_id)
                data = self._load()
            data["users"][uname] = {
                "username": uname,
                "role": role,
                "org_id": org_id,
                "allowed_orgs": sorted(set(allowed_orgs or [org_id])),
                "client_id": client_id,
                "password_hash": hash_password(password),
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save(data)
            return {"username": uname, "role": role, "org_id": org_id}

    def authenticate_password(self, username: str, password: str) -> tuple[str, SecurityContext]:
        uname = (username or "").strip().lower()
        with self._lock:
            data = self._load()
            user = data["users"].get(uname)
            if not user or not user.get("active", True) or not verify_password(password, user["password_hash"]):
                raise AuthenticationError("Invalid username or password.")
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            data["sessions"][digest] = {
                "username": uname,
                "expires_at": time.time() + 28800,
            }
            self._save(data)
            ctx = SecurityContext(
                actor=uname,
                role=user["role"],
                org_id=user["org_id"],
                client_id=user.get("client_id"),
                allowed_orgs=tuple(user.get("allowed_orgs") or (user["org_id"],)),
                auth_method="session",
            )
            return token, ctx

    def authenticate_session(self, token: str) -> SecurityContext | None:
        if not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            data = self._load()
            sess = data["sessions"].get(digest)
            if not sess or sess.get("expires_at", 0) < time.time():
                return None
            user = data["users"].get(sess["username"])
            if not user or not user.get("active", True):
                return None
            return SecurityContext(
                actor=user["username"],
                role=user["role"],
                org_id=user["org_id"],
                client_id=user.get("client_id"),
                allowed_orgs=tuple(user.get("allowed_orgs") or (user["org_id"],)),
                auth_method="session",
            )

    def create_service_key(self, service_name: str, *, org_id: str = "default", role: str = "operator") -> str:
        if role not in ROLES:
            raise ValueError(f"Invalid role {role!r}")
        raw_key = f"alkan_sk_{secrets.token_urlsafe(24)}"
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        with self._lock:
            data = self._load()
            data["api_keys"][digest] = {
                "service": service_name.strip(),
                "org_id": org_id,
                "role": role,
                "active": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save(data)
        return raw_key

    def authenticate_service_key(self, raw_key: str) -> SecurityContext | None:
        if not raw_key:
            return None
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        with self._lock:
            data = self._load()
            rec = data["api_keys"].get(digest)
            if not rec or not rec.get("active", True):
                return None
            return SecurityContext(
                actor=f"service:{rec['service']}",
                role=rec["role"],
                org_id=rec["org_id"],
                allowed_orgs=(rec["org_id"],),
                auth_method="api_key",
            )
