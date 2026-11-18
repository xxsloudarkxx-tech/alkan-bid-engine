"""QuickBooks Online v3 adapter for Estimates, Customer mapping, SyncToken control, and human-gated sync."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..domain import AuditLedger, normalize_state
from ..package_method import Package, compute as compute_legacy
from ..security import SecurityContext, assert_independent_approver, require_permission, sanitize_filename

QBO_HOSTS = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}


class QuickBooksSyncError(RuntimeError):
    """Raised on missing credentials, unapproved estimates, duplicate or SyncToken conflicts."""


def _default_qbo_request(
    method: str,
    url: str,
    *,
    access_token: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=15) as resp:
        txt = resp.read().decode("utf-8") or "{}"
        return int(resp.status), json.loads(txt)


def build_qbo_estimate_payload(
    pkg: Package,
    *,
    customer_id: str,
    version: int = 1,
    item_ref_id: str = "1",
) -> dict[str, Any]:
    """Map an ALKAN Package into an Intuit QuickBooks Online Estimate JSON payload."""
    comp = compute_legacy(pkg)
    doc_number = f"ALK-{pkg.estimate_id}"[:21]  # QBO DocNumber max length is 21 chars

    lines: list[dict[str, Any]] = []
    line_num = 1

    def add_line(desc: str, amount: Decimal, qty: Decimal = Decimal("1"), unit_price: Decimal | None = None) -> None:
        nonlocal line_num
        up = amount if unit_price is None else unit_price
        lines.append({
            "LineNum": line_num,
            "Description": desc[:4000],
            "Amount": float(amount.quantize(Decimal("0.01"))),
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {
                "ItemRef": {"value": item_ref_id, "name": "Construction Services"},
                "Qty": float(qty),
                "UnitPrice": float(up.quantize(Decimal("0.01"))),
            },
        })
        line_num += 1

    for m in pkg.materials:
        add_line(f"{m.id}: {m.item} ({m.spec}) [{m.price_basis}]", m.extended, m.qty, m.unit_price)
    for l in pkg.labor:
        rate = pkg.rates[l.rate_key].loaded
        ext = (l.hours * rate).quantize(Decimal("0.01"))
        add_line(f"Labor {l.id}: {l.task}", ext, l.hours, rate)
    for o in pkg.other:
        add_line(f"{o.category}: {o.item}", o.extended, o.qty, o.rate)

    if comp["contingency"] > 0:
        add_line(f"Contingency ({pkg.contingency_pct}%)", comp["contingency"])
    if comp["overhead"] > 0:
        add_line(f"Overhead ({pkg.overhead_pct}%)", comp["overhead"])
    if comp["profit"] > 0:
        add_line(f"Profit ({pkg.profit_pct}%)", comp["profit"])

    provenance_hash = hashlib.sha256(
        f"{pkg.estimate_id}:v{version}:{comp['price']}".encode("utf-8")
    ).hexdigest()[:16]

    return {
        "DocNumber": doc_number,
        "TxnDate": pkg.date,
        "CustomerRef": {"value": str(customer_id)},
        "TxnStatus": "Pending",
        "PrivateNote": f"ALKAN Bid Engine {pkg.estimate_id} v{version} | BidTotal={comp['price']} | Hash={provenance_hash}",
        "Line": lines,
        "TotalAmt": float(comp["total"]),
    }


class QuickBooksAdapter:
    """QuickBooks Online Estimate sync adapter with human authorization, duplicate check & SyncToken lock."""

    def __init__(
        self,
        root: Path,
        *,
        environment: str | None = None,
        realm_id: str | None = None,
        access_token: str | None = None,
        transport: Callable[..., tuple[int, dict[str, Any]]] | None = None,
    ):
        self.root = Path(root).resolve()
        self.environment = (environment or os.environ.get("QUICKBOOKS_ENV", "sandbox")).lower()
        if self.environment not in QBO_HOSTS:
            raise ValueError(f"Invalid QuickBooks environment: {self.environment!r}")
        self.realm_id = realm_id if realm_id is not None else os.environ.get("QUICKBOOKS_REALM_ID", "")
        self.access_token = access_token if access_token is not None else os.environ.get("QUICKBOOKS_ACCESS_TOKEN", "")
        self._transport = transport or _default_qbo_request
        self._ledger_path = self.root / "data" / "integrations" / "quickbooks_sync_ledger.json"
        self._lock = threading.RLock()

    def status(self) -> dict[str, Any]:
        missing: list[str] = []
        if not self.realm_id:
            missing.append("QUICKBOOKS_REALM_ID")
        if not self.access_token:
            missing.append("QUICKBOOKS_ACCESS_TOKEN")
        return {
            "service": "quickbooks-online",
            "environment": self.environment,
            "host": QBO_HOSTS[self.environment],
            "credentials_ready": not missing,
            "missing_credentials": missing,
            "realm_id_configured": bool(self.realm_id),
        }

    def _base_url(self) -> str:
        if not self.realm_id or not self.access_token:
            raise QuickBooksSyncError(
                "QuickBooks credentials not configured (set QUICKBOOKS_REALM_ID and QUICKBOOKS_ACCESS_TOKEN or connect via ALKAN Studio OAuth)."
            )
        return f"{QBO_HOSTS[self.environment]}/v3/company/{self.realm_id}"

    def _load_ledger(self) -> dict[str, Any]:
        if not self._ledger_path.exists():
            return {}
        return json.loads(self._ledger_path.read_text(encoding="utf-8"))

    def _save_ledger(self, data: dict[str, Any]) -> None:
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._ledger_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self._ledger_path)

    def lookup_customer(self, display_name: str) -> dict[str, Any] | None:
        safe_name = display_name.replace("'", "\\'")
        query = urlencode({"query": f"select * from Customer where DisplayName = '{safe_name}' maxresults 1"})
        url = f"{self._base_url()}/query?{query}"
        status, body = self._transport("GET", url, access_token=self.access_token)
        if status >= 400:
            raise QuickBooksSyncError(f"QuickBooks Customer query failed ({status}): {body}")
        customers = (body.get("QueryResponse") or {}).get("Customer") or []
        return customers[0] if customers else None

    def sync_estimate(
        self,
        pkg: Package,
        *,
        org_id: str,
        customer_id: str,
        bid_state: str,
        prepared_by: str,
        authorized_by: str,
        version: int = 1,
        dry_run: bool = True,
        confirm_financial_sync: bool = False,
        expected_sync_token: str | None = None,
        ctx: SecurityContext | None = None,
    ) -> dict[str, Any]:
        """Dry-run or live sync an Approved Estimate to QuickBooks Online with duplicate & SyncToken guards."""
        if ctx:
            perm = "qb:dry_run" if dry_run else "qb:sync"
            require_permission(ctx, perm, org_id=org_id)

        canonical = normalize_state(bid_state)
        payload = build_qbo_estimate_payload(pkg, customer_id=customer_id, version=version)
        ledger_key = f"{org_id}:{pkg.estimate_id}"

        if dry_run:
            return {
                "mode": "dry_run",
                "org_id": org_id,
                "estimate_id": pkg.estimate_id,
                "version": version,
                "bid_state": canonical,
                "ready_for_live_sync": canonical in ("Approved", "Exported"),
                "qbo_payload": payload,
            }

        # Live financial action checks
        if canonical not in ("Approved", "Exported"):
            raise QuickBooksSyncError(f"Cannot sync estimate in state {canonical!r}; must be Approved or Exported.")
        if not confirm_financial_sync:
            raise QuickBooksSyncError("Human confirmation gate blocked live QuickBooks sync (confirm_financial_sync=True required).")
        assert_independent_approver(prepared_by, authorized_by, ctx.role if ctx else None)

        base = self._base_url()
        with self._lock:
            ledger = self._load_ledger()
            existing_rec = ledger.get(ledger_key)

            # Query QBO to detect duplicates or fetch current SyncToken before write
            q = urlencode({"query": f"select Id, DocNumber, SyncToken from Estimate where DocNumber = '{payload['DocNumber']}' maxresults 1"})
            _, q_body = self._transport("GET", f"{base}/query?{q}", access_token=self.access_token)
            remote_matches = (q_body.get("QueryResponse") or {}).get("Estimate") or []

            if existing_rec and existing_rec.get("version") == version and remote_matches:
                return {
                    "mode": "idempotent_skip",
                    "qbo_id": remote_matches[0]["Id"],
                    "sync_token": remote_matches[0]["SyncToken"],
                    "doc_number": payload["DocNumber"],
                }

            action = "create"
            if remote_matches:
                remote = remote_matches[0]
                if expected_sync_token is not None and str(remote["SyncToken"]) != str(expected_sync_token):
                    raise QuickBooksSyncError(
                        f"SyncToken mismatch: expected {expected_sync_token}, QBO reports {remote['SyncToken']}."
                    )
                payload["Id"] = remote["Id"]
                payload["SyncToken"] = remote["SyncToken"]
                payload["sparse"] = True
                action = "update"

            status, resp = self._transport("POST", f"{base}/estimate?minorversion=65", access_token=self.access_token, body=payload)
            if status >= 400:
                raise QuickBooksSyncError(f"QuickBooks Estimate {action} failed ({status}): {resp}")

            est = resp.get("Estimate") or resp
            result = {
                "mode": action,
                "environment": self.environment,
                "qbo_id": str(est.get("Id") or ""),
                "sync_token": str(est.get("SyncToken") or "0"),
                "doc_number": payload["DocNumber"],
                "version": version,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "authorized_by": authorized_by,
            }
            ledger[ledger_key] = result
            self._save_ledger(ledger)

        AuditLedger(self.root / "data" / "orgs" / sanitize_filename(org_id) / "audit_ledger.jsonl").record(
            org_id=org_id,
            project_id=str(pkg.project.get("key") or pkg.estimate_id),
            actor=authorized_by,
            role=ctx.role if ctx else "operator",
            action=f"QUICKBOOKS_ESTIMATE_{action.upper()}",
            state_from=canonical,
            state_to="Exported",
            resource_type="qbo_estimate",
            resource_id=result["qbo_id"] or payload["DocNumber"],
            detail={"doc_number": payload["DocNumber"], "version": version},
        )
        return result
