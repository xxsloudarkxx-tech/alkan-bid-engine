"""Unified /api/v4/* router exposing Stage B/C/D enterprise capabilities cleanly."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from .agent_jobs import RunManager
from .backup import create_backup, verify_backup
from .cost_engine import analyze_package_costs
from .deliverables_v4 import generate_all_deliverables
from .domain import CANONICAL_STATES, AuditLedger
from .integrations import QuickBooksAdapter, SuperbotBridge, WorkflowStudioClient
from .labor_engine import load_structured_wages, parse_legacy_productivity
from .package_method import load_package
from .pricebook import PriceRecord, PricebookStore
from .review_engine import resolve_discrepancy, run_independent_review
from .rfi_rfq import RFIRFQWorkspace
from .security import (
    AuthStore,
    RateLimitError,
    SecurityContext,
    SlidingWindowRateLimiter,
    require_permission,
    sanitize_filename,
)
from .takeoff_engine import detect_takeoff_gaps, inspect_pdf_drawings


class V4API:
    """Enterprise API controller delegating to domain, security, cost, review, RFQ, and integration modules."""

    def __init__(self, root: Path, runs: RunManager):
        self.root = Path(root).resolve()
        self.runs = runs
        self.auth = AuthStore(self.root / "data" / "security" / "auth.json")
        self.pricebook = PricebookStore(self.root)
        self.studio = WorkflowStudioClient(self.root)
        self.superbot = SuperbotBridge(self.root)
        self.quickbooks = QuickBooksAdapter(self.root)
        self.limiter = SlidingWindowRateLimiter(max_requests=240, window_seconds=60)

    def _org_ledger(self, org_id: str) -> AuditLedger:
        return AuditLedger(self.root / "data" / "orgs" / sanitize_filename(org_id or "default") / "audit_ledger.jsonl")

    def _rfi_ws(self, org_id: str, project_id: str) -> RFIRFQWorkspace:
        return RFIRFQWorkspace(
            self.root / "data" / "orgs" / sanitize_filename(org_id or "default") / "rfq" / f"{sanitize_filename(project_id)}.json"
        )

    def _resolve_context(
        self,
        *,
        headers: dict[str, str],
        actor: str,
        org_id: str = "default",
        role_hint: str = "estimator",
    ) -> SecurityContext:
        auth_hdr = (headers.get("Authorization") or "").strip()
        if auth_hdr.startswith("Bearer "):
            tok = auth_hdr[7:].strip()
            ctx = self.auth.authenticate_service_key(tok) or self.auth.authenticate_session(tok)
            if ctx is None:
                raise PermissionError("Invalid Bearer token or API key.")
            return ctx
        api_key = (headers.get("X-ALKAN-API-Key") or "").strip()
        if api_key:
            ctx = self.auth.authenticate_service_key(api_key)
            if ctx is None:
                raise PermissionError("Invalid X-ALKAN-API-Key.")
            return ctx
        # Local single-desktop loopback context
        role = role_hint if role_hint in ("admin", "estimator", "reviewer", "operator", "client") else "estimator"
        return SecurityContext(actor=actor or "local", role=role, org_id=org_id or "default", allowed_orgs=(org_id or "default",))

    def _package_for_run(self, run_id: str):
        run_dir = self.runs.run_dir(run_id)
        state = self.runs._read(run_dir)
        pkg_path = self.runs._package(run_dir, state)
        return state, pkg_path, load_package(pkg_path)

    def get(self, path: str, q: dict[str, list[str]], headers: dict[str, str] | None = None) -> dict[str, Any] | None:
        one = lambda k, default="": (q.get(k) or [default])[0]
        org_id = one("org_id", "default")
        self.limiter.check(f"get:{org_id}")

        if path == "/api/v4/dashboard":
            runs = self.runs.list()
            counts = {st: sum(1 for r in runs if r.get("canonical_state") == st) for st in CANONICAL_STATES}
            return {
                "canonical_states": list(CANONICAL_STATES),
                "counts": counts,
                "total_runs": len(runs),
                "runs": runs,
                "integrations": {
                    "workflow_studio": self.studio.status(),
                    "quickbooks": self.quickbooks.status(),
                    "superbot_jobs": len(self.superbot.list_jobs(org_id=org_id)),
                },
            }

        if path == "/api/v4/pricebook":
            kpb = self.root / "src" / "bidkit" / "estimator_agent" / "knowledge" / "price_book.json"
            if not self.pricebook.list_records(org_id) and kpb.exists():
                self.pricebook.import_legacy_price_book(org_id, kpb)
            return {
                "org_id": org_id,
                "records": self.pricebook.list_records(
                    org_id,
                    price_type=one("price_type") or None,
                    query=one("query"),
                    city=one("city"),
                    state=one("state"),
                ),
            }

        if path == "/api/v4/pricebook/compare":
            return {
                "query": one("query"),
                "comparisons": self.pricebook.compare_suppliers(
                    org_id,
                    one("query"),
                    quantity=one("qty", "1") or "1",
                ),
            }

        if path == "/api/v4/labor":
            kw = self.root / "src" / "bidkit" / "estimator_agent" / "knowledge" / "wages.json"
            kp = self.root / "src" / "bidkit" / "estimator_agent" / "knowledge" / "productivity.json"
            wages = [
                {
                    "key": w.key,
                    "trade": w.trade,
                    "classification": w.classification,
                    "county": w.county,
                    "state": w.state,
                    "effective_date": w.effective_date,
                    "source": w.source,
                    "verified": w.verified,
                    **w.breakdown(),
                }
                for w in (load_structured_wages(kw) if kw.exists() else [])
            ]
            norms = [
                {
                    "norm_id": n.norm_id,
                    "task": n.task,
                    "trade": n.trade,
                    "unit": n.unit,
                    "hours_per_unit": str(n.hours_per_unit),
                    "hours_per_post_or_element": str(n.hours_per_post_or_element),
                    "source": n.source,
                    "confidence": n.confidence,
                }
                for n in (parse_legacy_productivity(kp) if kp.exists() else [])
            ]
            return {"wages": wages, "productivity": norms}

        if path == "/api/v4/rfi-rfq":
            pid = one("project_id", "default")
            return self._rfi_ws(org_id, pid).snapshot()

        if path == "/api/v4/integrations/status":
            return {
                "workflow_studio": self.studio.status(),
                "studio_outbox": self.studio.list_outbox(org_id=org_id),
                "quickbooks": self.quickbooks.status(),
                "superbot_jobs": self.superbot.list_jobs(org_id=org_id),
            }

        if path == "/api/v4/audit-trail":
            ledger = self._org_ledger(org_id)
            return {
                "org_id": org_id,
                "chain_verification": ledger.verify_chain(),
                "events": ledger.list_events(org_id=org_id, project_id=one("project_id") or None),
            }

        return None

    def post(
        self,
        path: str,
        req: dict[str, Any],
        actor: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        hdrs = headers or {}
        org_id = str(req.get("org_id") or "default")
        self.limiter.check(f"post:{org_id}:{actor}")
        ctx = self._resolve_context(
            headers=hdrs,
            actor=actor,
            org_id=org_id,
            role_hint=str(req.get("role") or "estimator"),
        )

        if path == "/api/v4/auth/users":
            require_permission(ctx, "admin:users", org_id=org_id)
            return self.auth.create_user(
                req["username"],
                req["password"],
                role=req["user_role"],
                org_id=org_id,
                client_id=req.get("client_id"),
            )

        if path == "/api/v4/auth/login":
            token, user_ctx = self.auth.authenticate_password(req["username"], req["password"])
            return {"token": token, "actor": user_ctx.actor, "role": user_ctx.role, "org_id": user_ctx.org_id}

        if path == "/api/v4/pricebook/save":
            rec = PriceRecord.from_dict({**req["record"], "org_id": org_id})
            saved = self.pricebook.upsert(rec, ctx=ctx)
            return saved.to_dict()

        if path == "/api/v4/pricebook/verify":
            rec = self.pricebook.verify_record(
                org_id=org_id,
                record_id=req["record_id"],
                verifier=ctx.actor,
                target_price_type=req.get("target_price_type", "VERIFIED"),
                ctx=ctx,
            )
            return rec.to_dict()

        if path == "/api/v4/pricebook/import":
            raw = base64.b64decode(req["content_b64"], validate=True)
            return self.pricebook.import_quote_file(
                org_id=org_id,
                file_name=req["file_name"],
                raw_bytes=raw,
                supplier=req["supplier"],
                city=req.get("city", ""),
                state=req.get("state", ""),
                quoted_date=req.get("quoted_date", ""),
                valid_until=req.get("valid_until", ""),
                ctx=ctx,
            )

        if path == "/api/v4/cost-analysis":
            require_permission(ctx, "estimate:read", org_id=org_id)
            if req.get("package_path"):
                pkg = load_package(Path(req["package_path"]))
            else:
                _, _, pkg = self._package_for_run(req["run_id"])
            return analyze_package_costs(
                pkg,
                profit_mode=req.get("profit_mode", "markup"),
                sales_tax_pct=Decimal(str(req.get("sales_tax_pct", "0"))),
            )

        if path == "/api/v4/review/run":
            require_permission(ctx, "estimate:review", org_id=org_id)
            state, _, pkg = self._package_for_run(req["run_id"])
            pb = self.pricebook.list_records(org_id)
            report = run_independent_review(
                pkg,
                prepared_by=req.get("prepared_by") or state.get("actor") or "estimator",
                reviewer_id=ctx.actor,
                pricebook_records=pb,
            )
            self._org_ledger(org_id).record(
                org_id=org_id,
                project_id=state["key"],
                actor=ctx.actor,
                role=ctx.role,
                action="INDEPENDENT_REVIEW_RUN",
                state_from=state.get("canonical_state", ""),
                state_to="Review Required",
                resource_id=req["run_id"],
                detail={"discrepancies": report["total_discrepancies"], "critical": report["critical_count"]},
            )
            return report

        if path == "/api/v4/bids/approve":
            require_permission(ctx, "estimate:approve", org_id=org_id)
            return self.runs.authorize(req["run_id"], ctx.actor, req.get("note", ""), strict_separation=True)

        if path == "/api/v4/bids/reject":
            require_permission(ctx, "estimate:reject", org_id=org_id)
            return self.runs.reject(req["run_id"], ctx.actor, req.get("reason", ""))

        if path == "/api/v4/deliverables/generate":
            require_permission(ctx, "estimate:export", org_id=org_id)
            if req.get("run_id"):
                return self.runs.export_v4(req["run_id"], ctx.actor)
            pkg = load_package(Path(req["package_path"]))
            return generate_all_deliverables(
                pkg,
                Path(req["out_dir"]),
                version=int(req.get("version", 1)),
                status=req.get("status", "Review Required"),
                reviewer=ctx.actor,
            )

        if path == "/api/v4/rfi-rfq/generate":
            require_permission(ctx, "rfq:prepare", org_id=org_id)
            _, _, pkg = self._package_for_run(req["run_id"])
            ws = self._rfi_ws(org_id, pkg.project.get("key") or pkg.estimate_id)
            rfqs = [r.to_dict() for r in ws.build_rfqs_from_package(pkg, only_unquoted=bool(req.get("only_unquoted", False)))]
            return {"rfqs": rfqs, "snapshot": ws.snapshot()}

        if path == "/api/v4/rfi-rfq/authorize-send":
            ws = self._rfi_ws(org_id, req["project_id"])
            return ws.authorize_dispatch(
                kind=req["kind"],
                item_id=req["item_id"],
                actor=ctx.actor,
                channel=req.get("channel", "email"),
                recipient=req["recipient"],
                ctx=ctx,
                explicit_human_approval=bool(req.get("explicit_human_approval", False)),
            )

        if path == "/api/v4/integrations/studio/emit":
            return self.studio.emit_event(
                event_type=req["event_type"],
                org_id=org_id,
                project_id=req["project_id"],
                estimate_id=req["estimate_id"],
                actor=ctx.actor,
                payload=req.get("payload") or {},
                idempotency_key=req.get("idempotency_key"),
                version=int(req.get("version", 1)),
                ctx=ctx,
            )

        if path == "/api/v4/integrations/superbot/intake":
            return self.superbot.intake_opportunity({**req, "org_id": org_id}, ctx=ctx)

        if path == "/api/v4/integrations/quickbooks/sync":
            state, _, pkg = self._package_for_run(req["run_id"])
            return self.quickbooks.sync_estimate(
                pkg,
                org_id=org_id,
                customer_id=req["customer_id"],
                bid_state=state.get("canonical_state", "Review Required"),
                prepared_by=state.get("actor", ""),
                authorized_by=ctx.actor,
                version=int(state.get("version") or 1),
                dry_run=bool(req.get("dry_run", True)),
                confirm_financial_sync=bool(req.get("confirm_financial_sync", False)),
                ctx=ctx,
            )

        if path == "/api/v4/backup/create":
            require_permission(ctx, "backup:manage", org_id=org_id)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out_zip = self.root / "data" / "backups" / f"alkan_backup_{org_id}_{stamp}.zip"
            info = create_backup(self.root, out_zip, org_id=req.get("org_filter"))
            return {**info, "verification": verify_backup(out_zip)}

        if path == "/api/v4/drawings/inspect":
            require_permission(ctx, "takeoff:edit", org_id=org_id)
            return inspect_pdf_drawings(Path(req["pdf_path"]))

        return None
