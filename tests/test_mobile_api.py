"""End-to-end verification of the ALKAN Bid Engine Mobile API gateway."""
from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib import error as urlerror
from urllib import request as urlrequest

from PIL import Image
from pypdf import PdfReader

ROOT_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_REPO / "src"))

from bidkit.mobile_api import BinaryResponse, MobileBidEngineAPI  # noqa: E402


def _make_sample_pdf(text: str = "SHEET A1.01 SAMPLE PLAN") -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def _make_sample_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color=(15, 61, 62)).save(buf, format="PNG")
    return buf.getvalue()


class MobileBidEngineAPITest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="alkan_mobile_test_"))
        for folder in ("profiles", "examples", "data"):
            src = ROOT_REPO / folder
            if src.exists():
                shutil.copytree(src, self.tmp / folder)
        # Keep source tree knowledge files resolvable via symlink/copy
        shutil.copytree(
            ROOT_REPO / "src" / "bidkit" / "estimator_agent" / "knowledge",
            self.tmp / "src" / "bidkit" / "estimator_agent" / "knowledge",
        )
        self.api = MobileBidEngineAPI(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_health_and_auth_separation(self) -> None:
        status, health = self.api.handle_safe("GET", "/api/mobile/health")
        self.assertEqual(status, 200)
        spec_ids = {s["id"] for s in health["specialties"]}
        self.assertEqual(spec_ids, {"metal", "techado", "tablaroca", "pintura", "molduras", "cubiertas"})
        self.assertIn("King", health["counties"])

        # Protected route rejects missing token
        status_unauth, _ = self.api.handle_safe("GET", "/api/mobile/runs")
        self.assertEqual(status_unauth, 401)

        # Bootstrap creates estimator & reviewer and logs in estimator
        st_boot, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        self.assertEqual(st_boot, 200)
        self.assertEqual(est["role"], "estimator")
        self.assertTrue(est["seeded"])

        # Reviewer login works independently
        st_rev, rev = self.api.handle_safe(
            "POST",
            "/api/v4/auth/login",
            body={"username": "reviewer", "password": "Reviewer!2026"},
        )
        self.assertEqual(st_rev, 200)
        self.assertEqual(rev["role"], "reviewer")

    def test_resumable_chunked_upload_and_photo_to_pdf(self) -> None:
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        hdrs = self._auth_headers(est["token"])
        upload_id = "0123456789abcdef0123456789abcdef"

        pdf_bytes = _make_sample_pdf("PLANO DE PRUEBA KING COUNTY")
        half = len(pdf_bytes) // 2

        st0, r0 = self.api.handle_safe(
            "POST",
            "/api/mobile/upload/chunk",
            body={
                "upload_id": upload_id,
                "name": "planos_obra.pdf",
                "index": 0,
                "content": base64.b64encode(pdf_bytes[:half]).decode("ascii"),
                "is_last": False,
            },
            headers=hdrs,
        )
        self.assertEqual(st0, 200)
        self.assertEqual(r0["next_index"], 1)

        # Check resumable upload status mid-stream
        st_status, ustatus = self.api.handle_safe(
            "GET",
            "/api/mobile/upload/status",
            query={"upload_id": [upload_id]},
            headers=hdrs,
        )
        self.assertEqual(st_status, 200)
        self.assertEqual(ustatus["files"][0]["next_index"], 1)

        # Re-sending chunk 0 is idempotent (no duplicate bytes)
        st_dup, rdup = self.api.handle_safe(
            "POST",
            "/api/mobile/upload/chunk",
            body={
                "upload_id": upload_id,
                "name": "planos_obra.pdf",
                "index": 0,
                "content": base64.b64encode(pdf_bytes[:half]).decode("ascii"),
                "is_last": False,
            },
            headers=hdrs,
        )
        self.assertEqual(st_dup, 200)
        self.assertTrue(rdup["already_received"])

        st1, r1 = self.api.handle_safe(
            "POST",
            "/api/mobile/upload/chunk",
            body={
                "upload_id": upload_id,
                "name": "planos_obra.pdf",
                "index": 1,
                "content": base64.b64encode(pdf_bytes[half:]).decode("ascii"),
                "is_last": True,
            },
            headers=hdrs,
        )
        self.assertEqual(st1, 200)
        self.assertEqual(r1["bytes"], len(pdf_bytes))

        # Camera photo upload automatically converts PNG -> PDF
        png_bytes = _make_sample_png()
        st_img, rimg = self.api.handle_safe(
            "POST",
            "/api/mobile/upload/chunk",
            body={
                "upload_id": upload_id,
                "name": "croquis_campo.png",
                "index": 0,
                "content": base64.b64encode(png_bytes).decode("ascii"),
                "is_last": True,
            },
            headers=hdrs,
        )
        self.assertEqual(st_img, 200)
        self.assertTrue(rimg["converted_to_pdf"])
        self.assertTrue(rimg["name"].endswith(".pdf"))

    def test_quick_package_3_pdfs_human_lock_and_voice_note(self) -> None:
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        _, rev = self.api.handle_safe(
            "POST",
            "/api/v4/auth/login",
            body={"username": "reviewer", "password": "Reviewer!2026"},
        )
        est_hdrs = self._auth_headers(est["token"])
        rev_hdrs = self._auth_headers(rev["token"])

        # Build metal package as estimator
        st_qp, summary = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/quick-package",
            body={
                "key": "MOBWSJ",
                "project_title": "West Seattle Park Metal",
                "profile": "ss_custom_iron_works",
                "specialty": "metal",
                "county": "King",
                "voice_notes": "Solo base bid y validar postes en campo.",
            },
            headers=est_hdrs,
        )
        self.assertEqual(st_qp, 200, summary)
        run_id = summary["run"]["id"]
        self.assertEqual(summary["run"]["badge_status"], "draft_ready")
        self.assertEqual(summary["run"]["qa"], "PASS")
        self.assertFalse(summary["human_lock"]["is_approved"])
        self.assertFalse(summary["human_lock"]["client_share_unlocked"])
        self.assertEqual(len(summary["documents"]), 3)
        self.assertTrue(all(d["exists"] for d in summary["documents"]))
        self.assertTrue(all(not d["share_to_client_allowed"] for d in summary["documents"]))

        # Verify 03_ESTIMATE_PROPOSAL.pdf carries DRAFT banner before approval
        st_pdf, pdf_resp = self.api.handle_safe(
            "GET",
            "/api/app/run/file",
            query={"id": [run_id], "name": ["MOBWSJ_03_ESTIMATE_PROPOSAL.pdf"]},
            headers=est_hdrs,
        )
        self.assertEqual(st_pdf, 200)
        self.assertIsInstance(pdf_resp, BinaryResponse)
        draft_text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_resp.data)).pages)
        self.assertIn("DRAFT", draft_text.upper())

        # Record adjustment voice note on Screen 4
        st_vn, vn_res = self.api.handle_safe(
            "POST",
            f"/api/mobile/runs/{run_id}/voice-note",
            body={"transcript": "Revisar precio del tubo ASTM A53 antes de enviar", "kind": "adjustment_request"},
            headers=est_hdrs,
        )
        self.assertEqual(st_vn, 200)
        self.assertEqual(vn_res["total_notes"], 2)

        # Estimator cannot approve their own estimate (role + strict separation)
        st_self, self_err = self.api.handle_safe(
            "POST",
            "/api/v4/bids/approve",
            body={"run_id": run_id, "note": "Auto-aprobación"},
            headers=est_hdrs,
        )
        self.assertEqual(st_self, 403, self_err)

        # Independent reviewer approves -> unlocks ONLY 03_ESTIMATE_PROPOSAL.pdf
        st_app, _ = self.api.handle_safe(
            "POST",
            "/api/v4/bids/approve",
            body={"run_id": run_id, "note": "Aprobado en campo"},
            headers=rev_hdrs,
        )
        self.assertEqual(st_app, 200)

        st_after, sum_after = self.api.handle_safe(
            "GET",
            f"/api/mobile/runs/{run_id}/summary",
            headers=rev_hdrs,
        )
        self.assertEqual(st_after, 200)
        self.assertTrue(sum_after["human_lock"]["is_approved"])
        self.assertTrue(sum_after["human_lock"]["client_share_unlocked"])
        docs_by_type = {d["doc_type"]: d for d in sum_after["documents"]}
        self.assertFalse(docs_by_type["cost_analysis"]["share_to_client_allowed"])
        self.assertFalse(docs_by_type["material_list"]["share_to_client_allowed"])
        self.assertTrue(docs_by_type["proposal"]["share_to_client_allowed"])
        self.assertFalse(docs_by_type["proposal"]["is_draft"])

        # Verify rebuilt 03_ESTIMATE_PROPOSAL.pdf no longer has DRAFT stamp
        st_pdf2, pdf_resp2 = self.api.handle_safe(
            "GET",
            "/api/app/run/file",
            query={"id": [run_id], "name": ["MOBWSJ_03_ESTIMATE_PROPOSAL.pdf"]},
            headers=rev_hdrs,
        )
        self.assertEqual(st_pdf2, 200)
        final_text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_resp2.data)).pages)
        self.assertNotIn("DRAFT — PENDING AUTHORIZATION", final_text)

    def test_roofing_starter_reject_profile_and_quote_import(self) -> None:
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        _, rev = self.api.handle_safe(
            "POST",
            "/api/v4/auth/login",
            body={"username": "reviewer", "password": "Reviewer!2026"},
        )
        est_hdrs = self._auth_headers(est["token"])
        rev_hdrs = self._auth_headers(rev["token"])

        # Generate roofing package (no static template, uses knowledge base)
        st_rf, sum_rf = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/quick-package",
            body={
                "key": "ROOFWA",
                "project_title": "PJ Techado Bodega",
                "profile": "pj_roofing",
                "specialty": "techado",
                "county": "Pierce",
            },
            headers=est_hdrs,
        )
        self.assertEqual(st_rf, 200, sum_rf)
        self.assertEqual(sum_rf["run"]["qa"], "PASS")
        run_id = sum_rf["run"]["id"]

        # Reject / mark NO-GO as reviewer
        st_rej, _ = self.api.handle_safe(
            "POST",
            "/api/v4/bids/reject",
            body={"run_id": run_id, "reason": "Falta licencia actualizada"},
            headers=rev_hdrs,
        )
        self.assertEqual(st_rej, 200)
        _, sum_rej = self.api.handle_safe("GET", f"/api/mobile/runs/{run_id}/summary", headers=rev_hdrs)
        self.assertEqual(sum_rej["run"]["badge_status"], "no_go")
        self.assertFalse(sum_rej["human_lock"]["client_share_unlocked"])

        # Save profile + logo and stream logo back
        _, prof_res = self.api.handle_safe("GET", "/api/app/profile", query={"name": ["pj_roofing"]}, headers=est_hdrs)
        prof = prof_res["profile"]
        prof["contractor"].update({
            "address": "1200 Pacific Ave, Tacoma, WA",
            "license": "WA Lic. PJROORL881K2",
            "phone": "(253) 555-0199",
            "contact": "Palemon",
        })
        st_save, _ = self.api.handle_safe(
            "POST",
            "/api/app/profile/save",
            body={
                "name": "pj_roofing",
                "profile": prof,
                "logo": {"content": base64.b64encode(_make_sample_png()).decode("ascii")},
            },
            headers=est_hdrs,
        )
        self.assertEqual(st_save, 200)
        st_logo, logo_resp = self.api.handle_safe("GET", "/api/mobile/profiles/pj_roofing/logo", headers=est_hdrs)
        self.assertEqual(st_logo, 200)
        self.assertIsInstance(logo_resp, BinaryResponse)

        # Import supplier CSV quote (BUDGET -> QUOTE)
        csv_data = b"material,unit,unit_price,specification_std\nTPO Membrane 60mil,SF,2.85,Carlisle\n"
        st_imp, imp_res = self.api.handle_safe(
            "POST",
            "/api/mobile/pricebook/import-file",
            body={
                "file_name": "abc_supply_quote.csv",
                "content_b64": base64.b64encode(csv_data).decode("ascii"),
                "supplier": "ABC Supply",
                "city": "Tacoma",
            },
            headers=est_hdrs,
        )
        self.assertEqual(st_imp, 200)
        self.assertEqual(imp_res["imported_count"], 1)

    def test_live_http_server_roundtrip(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from urllib.parse import parse_qs, quote, urlsplit
        from bidkit.mobile_api import _cors_headers

        gateway = self.api

        class TestHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, st: int, pl):
                data = pl.data if isinstance(pl, BinaryResponse) else json.dumps(pl).encode("utf-8")
                ctype = pl.media_type if isinstance(pl, BinaryResponse) else "application/json; charset=utf-8"
                self.send_response(st)
                for k, v in _cors_headers().items():
                    self.send_header(k, v)
                if isinstance(pl, BinaryResponse) and pl.filename:
                    self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(pl.filename))
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                u = urlsplit(self.path)
                st, pl = gateway.handle_safe("GET", u.path, parse_qs(u.query), {}, dict(self.headers))
                self._send(st, pl)

            def do_POST(self):
                u = urlsplit(self.path)
                n = int(self.headers.get("Content-Length") or "0")
                body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                st, pl = gateway.handle_safe("POST", u.path, parse_qs(u.query), body, dict(self.headers))
                self._send(st, pl)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        port = srv.server_port
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            with urlrequest.urlopen(f"http://127.0.0.1:{port}/api/mobile/health") as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["status"], "ok")

            req = urlrequest.Request(
                f"http://127.0.0.1:{port}/api/mobile/runs",
                method="GET",
            )
            with self.assertRaises(urlerror.HTTPError) as ctx:
                urlrequest.urlopen(req)
            self.assertEqual(ctx.exception.code, 401)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_preview_draft_multi_specialty_and_quantity_overrides(self) -> None:
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        hdrs = self._auth_headers(est["token"])

        st_prev, preview = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/preview-draft",
            body={
                "key": "MADISON",
                "project_title": "Madison ES Mixed",
                "profile": "diaz_finish_carpenter",
                "specialties": ["tablaroca", "pintura"],
                "county": "Snohomish",
                "voice_notes": "26 aulas muros tablaroca y pintura dos manos",
            },
            headers=hdrs,
        )
        self.assertEqual(st_prev, 200, preview)
        self.assertGreater(len(preview["materials"]), 1)
        self.assertGreater(len(preview["labor"]), 1)
        self.assertEqual(preview["specialties"], ["tablaroca", "pintura"])
        first_mat = preview["materials"][0]

        # Build baseline vs edited quantity override and confirm price reflects edit + QA passes
        st_base, base_sum = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/quick-package",
            body={
                "key": "MADBASE",
                "project_title": "Madison Base",
                "profile": "diaz_finish_carpenter",
                "specialties": ["tablaroca", "pintura"],
                "county": "Snohomish",
            },
            headers=hdrs,
        )
        self.assertEqual(st_base, 200, base_sum)
        self.assertEqual(base_sum["run"]["qa"], "PASS")

        new_qty = str(int(float(first_mat["qty"])) + 500)
        st_edit, edit_sum = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/quick-package",
            body={
                "key": "MADEDIT",
                "project_title": "Madison Edited",
                "profile": "diaz_finish_carpenter",
                "specialties": ["tablaroca", "pintura"],
                "county": "Snohomish",
                "materials_overrides": [{"id": first_mat["id"], "qty": new_qty}],
                "markups": {"contingency_pct": "5", "overhead_pct": "10", "profit_pct": "12"},
                "validity_days": 45,
            },
            headers=hdrs,
        )
        self.assertEqual(st_edit, 200, edit_sum)
        self.assertEqual(edit_sum["run"]["qa"], "PASS")
        self.assertNotEqual(base_sum["financials"]["sell_price"], edit_sum["financials"]["sell_price"])

        # Verify PDF renders with ALKAN Assistant header text cleanly
        st_pdf, pdf_resp = self.api.handle_safe(
            "GET",
            "/api/app/run/file",
            query={"id": [edit_sum["run"]["id"]], "name": ["MADEDIT_03_ESTIMATE_PROPOSAL.pdf"]},
            headers=hdrs,
        )
        self.assertEqual(st_pdf, 200)
        txt = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf_resp.data)).pages)
        self.assertIn("ALKAN Assistant", txt)

    def test_phase3_production_auth_hardening(self) -> None:
        prod_root = Path(tempfile.mkdtemp(prefix="alkan_prod_test_"))
        try:
            for folder in ("profiles", "examples", "data"):
                src = ROOT_REPO / folder
                if src.exists():
                    shutil.copytree(src, prod_root / folder)
            shutil.copytree(
                ROOT_REPO / "src" / "bidkit" / "estimator_agent" / "knowledge",
                prod_root / "src" / "bidkit" / "estimator_agent" / "knowledge",
            )

            # 1. With ALKAN_ALLOW_BOOTSTRAP=false and empty user store, default credentials are rejected
            with mock.patch.dict(
                os.environ,
                {
                    "ALKAN_ALLOW_BOOTSTRAP": "false",
                    "BIDKIT_DELIVERY_DIR": str(prod_root / "data" / "ENTREGAS" / "AGENTE"),
                },
                clear=False,
            ):
                os.environ.pop("ALKAN_INITIAL_USERS_JSON", None)
                no_boot_api = MobileBidEngineAPI(prod_root)
                st_fail, _ = no_boot_api.handle_safe(
                    "POST",
                    "/api/mobile/auth/bootstrap",
                    body={"username": "estimator", "password": "Estimator!2026"},
                )
                self.assertEqual(st_fail, 401)
                self.assertEqual(
                    no_boot_api.app.runs.base.resolve(),
                    (prod_root / "data" / "ENTREGAS" / "AGENTE").resolve(),
                )

            # 2. Seeding via ALKAN_INITIAL_USERS_JSON sets must_change_password=True
            seed_users = [
                {"username": "alkan_admin", "password": "TempAdmin#2026!", "role": "admin", "must_change_password": True},
                {"username": "obra_est", "password": "TempEst#2026!", "role": "estimator", "must_change_password": True},
                {"username": "obra_rev", "password": "TempRev#2026!", "role": "reviewer", "must_change_password": True},
            ]
            prod_root2 = Path(tempfile.mkdtemp(prefix="alkan_prod_seed_"))
            try:
                for folder in ("profiles", "examples", "data"):
                    src = ROOT_REPO / folder
                    if src.exists():
                        shutil.copytree(src, prod_root2 / folder)
                shutil.copytree(
                    ROOT_REPO / "src" / "bidkit" / "estimator_agent" / "knowledge",
                    prod_root2 / "src" / "bidkit" / "estimator_agent" / "knowledge",
                )
                with mock.patch.dict(
                    os.environ,
                    {
                        "ALKAN_ALLOW_BOOTSTRAP": "false",
                        "ALKAN_INITIAL_USERS_JSON": json.dumps(seed_users),
                    },
                    clear=False,
                ):
                    prod_api = MobileBidEngineAPI(prod_root2)

                st_l1, est_login = prod_api.handle_safe(
                    "POST",
                    "/api/v4/auth/login",
                    body={"username": "obra_est", "password": "TempEst#2026!"},
                )
                self.assertEqual(st_l1, 200)
                self.assertTrue(est_login["must_change_password"])

                # 3. Password change rotates credentials, clears must_change_password, and issues valid token
                st_cp, rotated = prod_api.handle_safe(
                    "POST",
                    "/api/mobile/auth/change-password",
                    body={
                        "username": "obra_est",
                        "current_password": "TempEst#2026!",
                        "new_password": "MiNuevaClave!2026",
                    },
                )
                self.assertEqual(st_cp, 200, rotated)
                self.assertFalse(rotated["must_change_password"])

                # Old session token is revoked after rotation
                st_revoked, _ = prod_api.handle_safe(
                    "GET",
                    "/api/mobile/runs",
                    headers=self._auth_headers(est_login["token"]),
                )
                self.assertEqual(st_revoked, 401)

                # New token works
                st_ok, _ = prod_api.handle_safe(
                    "GET",
                    "/api/mobile/runs",
                    headers=self._auth_headers(rotated["token"]),
                )
                self.assertEqual(st_ok, 200)

                # 4. Admin creates new contractor user & lists users (estimator denied)
                st_adm, adm_login = prod_api.handle_safe(
                    "POST",
                    "/api/v4/auth/login",
                    body={"username": "alkan_admin", "password": "TempAdmin#2026!"},
                )
                self.assertEqual(st_adm, 200)
                adm_hdrs = self._auth_headers(adm_login["token"])

                st_denied, _ = prod_api.handle_safe(
                    "GET",
                    "/api/mobile/auth/users",
                    headers=self._auth_headers(rotated["token"]),
                )
                self.assertEqual(st_denied, 403)

                st_new, created = prod_api.handle_safe(
                    "POST",
                    "/api/mobile/auth/users",
                    body={
                        "username": "carlos_obra",
                        "password": "CarlosTemp#2026!",
                        "user_role": "estimator",
                        "must_change_password": True,
                    },
                    headers=adm_hdrs,
                )
                self.assertEqual(st_new, 200, created)
                self.assertEqual(created["username"], "carlos_obra")
                self.assertTrue(created["must_change_password"])

                st_list, users_res = prod_api.handle_safe(
                    "GET",
                    "/api/mobile/auth/users",
                    headers=adm_hdrs,
                )
                self.assertEqual(st_list, 200)
                usernames = {u["username"] for u in users_res["users"]}
                self.assertIn("carlos_obra", usernames)
                self.assertIn("alkan_admin", usernames)
            finally:
                shutil.rmtree(prod_root2, ignore_errors=True)
        finally:
            shutil.rmtree(prod_root, ignore_errors=True)

    def test_vnaipro_anthropic_base_url(self) -> None:
        from bidkit.estimator_agent.anthropic_client import AnthropicClient

        client = AnthropicClient(api_key="sk-test-vnaipro", base_url="https://apikey.vnaipro.app/v1")
        self.assertEqual(client.url, "https://apikey.vnaipro.app/v1/messages")
        self.assertEqual(client.models_url, "https://apikey.vnaipro.app/v1/models")
        hdrs = client._headers()
        self.assertEqual(hdrs["x-api-key"], "sk-test-vnaipro")
        self.assertEqual(hdrs["authorization"], "Bearer sk-test-vnaipro")
        self.assertIn("user-agent", hdrs)

    def test_quick_register_profile_and_added_lines(self) -> None:
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        hdrs = self._auth_headers(est["token"])

        st_reg, reg_res = self.api.handle_safe(
            "POST",
            "/api/mobile/profiles/register",
            body={
                "contractor_name": "Cascade Steel Builders LLC",
                "contact": "Roberto",
                "phone": "(206) 555-0144",
                "address": "Seattle, WA",
                "specialty": "metal",
            },
            headers=hdrs,
        )
        self.assertEqual(st_reg, 200, reg_res)
        slug = reg_res["profile"]["name"]
        self.assertIn("cascade_steel", slug)
        self.assertTrue(any(p["name"] == slug for p in reg_res["profiles"]))

        st_qp, summary = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/quick-package",
            body={
                "key": "CASC99",
                "project_title": "Cascade Entry Gate",
                "profile": slug,
                "specialty": "metal",
                "county": "King",
                "client_name": "Absher Construction",
                "materials_overrides": [
                    {"id": "M101", "item": "Custom Steel Bollard", "qty": "4", "unit": "EA", "unit_price": "150.00"},
                ],
                "labor_overrides": [
                    {"id": "L101", "task": "Field bollard anchor install", "rate": "SHOP", "hours": "6"},
                ],
            },
            headers=hdrs,
        )
        self.assertEqual(st_qp, 200, summary)
        self.assertEqual(summary["run"]["qa"], "PASS")
        self.assertTrue(all(d["exists"] for d in summary["documents"]))

    def test_calibration_and_voice_signals(self) -> None:
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        hdrs = self._auth_headers(est["token"])

        st_h, health = self.api.handle_safe("GET", "/api/mobile/health")
        self.assertEqual(st_h, 200)
        self.assertEqual(health["verified_wage_counties"], ["King", "Snohomish"])

        st_p, profs = self.api.handle_safe("GET", "/api/mobile/profiles", headers=hdrs)
        self.assertEqual(st_p, 200, profs)
        by_name = {p["name"]: p for p in profs["profiles"]}
        self.assertIn("calibration_pct", by_name["ss_custom_iron_works"])
        self.assertGreater(
            by_name["ss_custom_iron_works"]["calibration_pct"],
            by_name["generico_sin_marca"]["calibration_pct"],
        )

        st_c, cal = self.api.handle_safe(
            "GET",
            "/api/mobile/calibration",
            query={"profile": ["ss_custom_iron_works"]},
            headers=hdrs,
        )
        self.assertEqual(st_c, 200, cal)
        self.assertEqual(len(cal["modules"]), 5)
        self.assertGreaterEqual(cal["percent"], 80)

        # Unverified county emits honest warning & voice signals detect county + trade
        st_prev, preview = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/preview-draft",
            body={
                "key": "PIERCE1",
                "project_title": "Pierce Gate",
                "profile": "ss_custom_iron_works",
                "specialty": "metal",
                "county": "Pierce",
                "voice_notes": "Trabajo en Snohomish County con barandal de acero y pintura exterior",
            },
            headers=hdrs,
        )
        self.assertEqual(st_prev, 200, preview)
        self.assertFalse(preview["county_wage_verified"])
        self.assertIn("King y Snohomish", preview["county_wage_warning"])
        self.assertEqual(preview["detected"]["county"], "Snohomish")
        self.assertIn("metal", preview["detected"]["specialties"])
        self.assertIn("pintura", preview["detected"]["specialties"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
