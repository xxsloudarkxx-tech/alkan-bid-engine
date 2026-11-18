"""Stage E Security, Multi-Tenant Isolation, Integration Contracts & Live HTTP E2E tests."""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request

import pytest

from bidkit.app_api import AppAPI
from bidkit.app_settings import AppSettings
from bidkit.integrations import QuickBooksAdapter, STUDIO_EVENTS, SuperbotBridge, WorkflowStudioClient
from bidkit.integrations.quickbooks_sync import QuickBooksSyncError
from bidkit.intelligence_ui import make_handler
from bidkit.package_method import load_package
from bidkit.pricebook import PriceRecord, PricebookStore
from bidkit.security import (
    AuthStore,
    AuthorizationError,
    RateLimitError,
    SelfApprovalError,
    SlidingWindowRateLimiter,
    TenantIsolationError,
    assert_independent_approver,
    redact_secrets,
    require_permission,
    sign_payload,
    verify_hmac_signature,
)

ROOT = Path(__file__).resolve().parent.parent


def test_rbac_auth_rate_limit_hmac_and_secret_redaction(tmp_path):
    auth = AuthStore(tmp_path / "auth.json")
    auth.create_organization("orgA", "Org Alpha")
    auth.create_organization("orgB", "Org Beta")
    auth.create_user("est_a", "StrongPass123!", role="estimator", org_id="orgA")
    auth.create_user("rev_a", "StrongPass123!", role="reviewer", org_id="orgA")

    tok_est, ctx_est = auth.authenticate_password("est_a", "StrongPass123!")
    _, ctx_rev = auth.authenticate_password("rev_a", "StrongPass123!")
    assert auth.authenticate_session(tok_est).actor == "est_a"

    with pytest.raises(AuthorizationError):
        require_permission(ctx_est, "estimate:approve", org_id="orgA")
    with pytest.raises(TenantIsolationError):
        require_permission(ctx_rev, "estimate:approve", org_id="orgB")

    with pytest.raises(SelfApprovalError):
        assert_independent_approver("est_a", "est_a", "admin")

    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
    limiter.check("u1", now_ts=100.0)
    limiter.check("u1", now_ts=101.0)
    with pytest.raises(RateLimitError):
        limiter.check("u1", now_ts=102.0)

    body = b'{"event":"bid.created"}'
    ts = str(int(time.time()))
    sig = sign_payload("topsecret", ts, body)
    assert verify_hmac_signature("topsecret", ts, body, f"sha256={sig}") is True
    assert verify_hmac_signature("wrongsecret", ts, body, f"sha256={sig}") is False

    redacted = redact_secrets({"api_key": "sk-ant-1234", "nested": {"access_token": "tok"}, "name": "safe"})
    assert redacted["api_key"] == "***REDACTED***" and redacted["nested"]["access_token"] == "***REDACTED***"
    assert redacted["name"] == "safe"


def test_workflow_studio_events_retry_and_hmac_verification(tmp_path):
    received: list[dict] = []
    attempts = {"count": 0}
    secret = "studio_hmac_test_key"

    class StudioSink(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            attempts["count"] += 1
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            if attempts["count"] == 1:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b'{"error":"transient"}')
                return
            assert verify_hmac_signature(secret, self.headers["X-ALKAN-Timestamp"], raw, self.headers["X-ALKAN-Signature"])
            received.append(json.loads(raw.decode("utf-8")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    srv = HTTPServer(("127.0.0.1", 0), StudioSink)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        client = WorkflowStudioClient(tmp_path, base_url=f"http://127.0.0.1:{srv.server_port}", shared_secret=secret)
        assert len(STUDIO_EVENTS) == 10
        res = client.emit_event(
            event_type="bid.review_approved",
            org_id="orgA",
            project_id="WSJ",
            estimate_id="SS-EST-2026-WSJ-01",
            actor="reviewer_bob",
            payload={"price": "38800"},
            idempotency_key="k1",
        )
        assert res["delivery_status"] == "delivered" and res["attempts"] == 2
        assert len(received) == 1 and received[0]["type"] == "bid.review_approved"

        # Idempotent replay does NOT resend HTTP request
        replay = client.emit_event(
            event_type="bid.review_approved",
            org_id="orgA",
            project_id="WSJ",
            estimate_id="SS-EST-2026-WSJ-01",
            actor="reviewer_bob",
            payload={"price": "38800"},
            idempotency_key="k1",
        )
        assert replay.get("idempotent_replay") is True and len(received) == 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_superbot_intake_isolation_and_approval_gate(tmp_path):
    bridge = SuperbotBridge(tmp_path)
    j1 = bridge.intake_opportunity({
        "org_id": "orgA",
        "client_id": "client_alpha",
        "project_title": "Steel Stair Retrofit",
        "county": "King",
        "documents": [{"name": "scope.txt", "content_text": "20 LF stair handrail"}],
    })
    assert j1["state"] == "Draft" and j1["ready_to_send_client"] is False

    # Cross-client isolation enforced
    with pytest.raises(TenantIsolationError):
        bridge.get_job(j1["job_id"], org_id="orgA", client_id="client_beta")

    bridge.transition_and_approve(j1["job_id"], org_id="orgA", target_state="Processing", actor="est_1", role="estimator")
    bridge.transition_and_approve(j1["job_id"], org_id="orgA", target_state="Review Required", actor="est_1", role="estimator")
    with pytest.raises(SelfApprovalError):
        bridge.transition_and_approve(j1["job_id"], org_id="orgA", target_state="Approved", actor="superbot-intake", role="reviewer")
    done = bridge.transition_and_approve(j1["job_id"], org_id="orgA", target_state="Approved", actor="director_1", role="reviewer")
    assert done["ready_to_send_client"] is True and done["approved_by"] == "director_1"


def test_quickbooks_adapter_sandbox_contract_and_gates(tmp_path):
    pkg = load_package(ROOT / "examples" / "packages" / "wsj.json")

    # Missing credentials clearly reported without faking sync
    unconf = QuickBooksAdapter(tmp_path, realm_id="", access_token="")
    assert unconf.status()["credentials_ready"] is False
    with pytest.raises(QuickBooksSyncError):
        unconf.sync_estimate(
            pkg, org_id="orgA", customer_id="42", bid_state="Approved",
            prepared_by="alice", authorized_by="bob", dry_run=False, confirm_financial_sync=True,
        )

    # Mock Intuit Sandbox HTTP endpoint implementing Customer query + Estimate query/create/update
    store = {"estimates": {}}

    class MockQBO(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer test_tok"
            if "Estimate" in self.path:
                body = {"QueryResponse": {"Estimate": list(store["estimates"].values())}} if store["estimates"] else {"QueryResponse": {}}
            else:
                body = {"QueryResponse": {"Customer": [{"Id": "42", "DisplayName": "City of Seattle"}]}}
            raw = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            est_id = payload.get("Id") or "101"
            next_tok = str(int(payload.get("SyncToken", "-1")) + 1)
            est = {"Id": est_id, "DocNumber": payload["DocNumber"], "SyncToken": next_tok}
            store["estimates"][est_id] = est
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"Estimate": est}).encode("utf-8"))

    # QuickBooksAdapter uses QBO_HOSTS; test end-to-end via adapter with test transport hitting local HTTP server
    srv = HTTPServer(("127.0.0.1", 0), MockQBO)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        def local_transport(method, url, *, access_token, body=None):
            local_url = url.replace("https://sandbox-quickbooks.api.intuit.com", f"http://127.0.0.1:{srv.server_port}")
            data = json.dumps(body).encode("utf-8") if body is not None else None
            headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(local_url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=5) as resp:
                return int(resp.status), json.loads(resp.read().decode("utf-8"))

        qb = QuickBooksAdapter(tmp_path, environment="sandbox", realm_id="999999", access_token="test_tok", transport=local_transport)
        cust = qb.lookup_customer("City of Seattle")
        assert cust["Id"] == "42"

        # Blocked unless Approved + confirm_financial_sync=True
        with pytest.raises(QuickBooksSyncError):
            qb.sync_estimate(pkg, org_id="orgA", customer_id="42", bid_state="Draft", prepared_by="alice", authorized_by="bob", dry_run=False, confirm_financial_sync=True)

        created = qb.sync_estimate(pkg, org_id="orgA", customer_id="42", bid_state="Approved", prepared_by="alice", authorized_by="bob", version=1, dry_run=False, confirm_financial_sync=True)
        assert created["mode"] == "create" and created["qbo_id"] == "101"

        # Same version returns idempotent_skip
        dup = qb.sync_estimate(pkg, org_id="orgA", customer_id="42", bid_state="Approved", prepared_by="alice", authorized_by="bob", version=1, dry_run=False, confirm_financial_sync=True)
        assert dup["mode"] == "idempotent_skip"

        # Version 2 with wrong SyncToken rejected
        with pytest.raises(QuickBooksSyncError):
            qb.sync_estimate(pkg, org_id="orgA", customer_id="42", bid_state="Approved", prepared_by="alice", authorized_by="bob", version=2, dry_run=False, confirm_financial_sync=True, expected_sync_token="99")

        updated = qb.sync_estimate(pkg, org_id="orgA", customer_id="42", bid_state="Approved", prepared_by="alice", authorized_by="bob", version=2, dry_run=False, confirm_financial_sync=True, expected_sync_token="0")
        assert updated["mode"] == "update" and updated["sync_token"] == "1"
    finally:
        srv.shutdown()
        srv.server_close()


def test_v4_http_e2e_server_routes(tmp_path):
    root = tmp_path
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    app = AppAPI(root, AppSettings(root, secrets_dir=root / "_sec"))
    handler = make_handler(root, app=app)
    srv = HTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        tok = json.loads(urllib.request.urlopen(base + "/api/session").read().decode())["token"]
        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "#dashboard" in html and "#integrations" in html and "/v4_workspace.js" in html
        js = urllib.request.urlopen(base + "/v4_workspace.js").read().decode("utf-8")
        assert "Project Dashboard" in js

        dash = json.loads(urllib.request.urlopen(base + "/api/v4/dashboard").read().decode())
        assert len(dash["canonical_states"]) == 7

        def post(path, payload):
            req = urllib.request.Request(
                base + path,
                data=json.dumps({"actor": "reviewer1", **payload}).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-ALKAN-Token": tok},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))

        # Pricebook CSV import over HTTP v4 API
        csv_b64 = base64.b64encode(b"material,spec,unit,unit_price\nHSS 4x4x1/4,ASTM A500,LF,18.25\n").decode()
        imp = post("/api/v4/pricebook/import", {"org_id": "org1", "file_name": "q.csv", "content_b64": csv_b64, "supplier": "Cascade Steel"})
        assert imp["imported_count"] == 1

        # Tenant isolation across Pricebook API query
        pb1 = json.loads(urllib.request.urlopen(base + "/api/v4/pricebook?org_id=org1").read().decode())
        assert len(pb1["records"]) == 1

        # Cost Analysis HTTP v4 on real WSJ package
        ca = post("/api/v4/cost-analysis", {"package_path": str(ROOT / "examples" / "packages" / "wsj.json")})
        assert "13_final_bid_price" in ca["breakdown_13"]["buckets"] and len(ca["scenarios"]) == 3
    finally:
        srv.shutdown()
        srv.server_close()


def test_anthropic_client_honors_base_url_env(monkeypatch):
    from bidkit.estimator_agent.anthropic_client import AnthropicClient

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://custom-proxy.example.com/")
    c = AnthropicClient(api_key="test-key")
    assert c.url == "https://custom-proxy.example.com/v1/messages"
    assert c.models_url == "https://custom-proxy.example.com/v1/models"
