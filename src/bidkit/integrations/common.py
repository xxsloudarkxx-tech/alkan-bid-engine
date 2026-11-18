"""Shared idempotency, retry backoff, outbox queue, and HTTP transport helpers for integrations."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class IntegrationError(RuntimeError):
    """Raised when an external service call or contract fails."""


def retry_with_backoff(
    fn: Callable[[], Any],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.05,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[Any, int]:
    """Execute fn retrying transient failures up to max_attempts; returns (result, attempts)."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(), attempt
        except (HTTPError, URLError, TimeoutError, IntegrationError) as exc:
            last_exc = exc
            if isinstance(exc, HTTPError) and 400 <= exc.code < 500 and exc.code != 429:
                raise
            if attempt < max_attempts:
                sleep_fn(base_delay_s * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


class IdempotencyLedger:
    """Thread-safe persistent idempotency key store scoped by org_id."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def get(self, org_id: str, key: str) -> dict[str, Any] | None:
        compound = f"{org_id}:{key}"
        with self._lock:
            return self._load().get(compound)

    def record(self, org_id: str, key: str, result: dict[str, Any]) -> None:
        compound = f"{org_id}:{key}"
        with self._lock:
            data = self._load()
            data[compound] = {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
            self._save(data)


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
) -> tuple[int, dict[str, Any]]:
    """Send JSON POST request using stdlib urllib with explicit header merge."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Accept": "application/json", **(headers or {})}
    req = Request(url, data=raw, headers=req_headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8") or "{}"
        return int(resp.status), json.loads(body)
