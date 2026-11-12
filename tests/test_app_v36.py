"""v3.6: admin settings, API client features, sanity checks, review loop, runs and delivery over HTTP."""
import base64
import io
import json
import time
import urllib.request
import uuid
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError

import pytest

from bidkit.app_api import AppAPI
from bidkit.app_settings import AppSettings
from bidkit.estimator_agent import anthropic_client as ac
from bidkit.estimator_agent.agent import Cancelled, EstimatorAgent, write_report
from bidkit.estimator_agent.docindex import DocIndex
from bidkit.estimator_agent.sanity import sanity_checks
from bidkit.estimator_agent.tools import ToolBox
from bidkit.intelligence_ui import make_handler
from test_estimator_agent import PROFILE, ROOT, FakeClient, _draft, bidset  # noqa: F401

REQ = ("record_note", {"kind": "requirement", "text": "Mandatory pre-bid Nov 2 (ya pasó)", "source": "Invitation p1"})
REVIEW_OK = [("submit_review", {"verdict": "PASS", "summary": "Sin bloqueadores.", "findings": []})]
REVIEW_FIX = [("submit_review", {"verdict": "FIX", "summary": "Falta concreto.", "findings": [
    {"severity": "blocker", "where": "M001", "issue": "Bike racks sin anclas", "fix": "Agregar anclas"}]})]


# ───────────────────────────── settings
def test_settings_roundtrip_and_secrets_stay_out_of_the_engine_folder(tmp_path):
    s = AppSettings(tmp_path / "root", secrets_dir=tmp_path / "user")
    assert s.load()["engine"]["model"] == "claude-fable-5-2"
    s.save({"engine": {"max_turns": 80, "effort": "medium"}, "delivery": {"report_pdf": False}})
    assert s.load()["engine"]["max_turns"] == 80 and s.load()["delivery"]["report_pdf"] is False
    for bad in ({"engine": {"max_turns": 5}}, {"engine": {"effort": "turbo"}}, {"engine": {"nope": 1}}, {"x": {}}):
        with pytest.raises(ValueError):
            s.save(bad)
    s.set_secret("anthropic", "sk-ant-test-1234567890", remember=True)
    assert s.secret_view("anthropic") == {"configured": True, "source": "sesión", "hint": "…7890"}
    assert "sk-ant" not in (tmp_path / "root" / "data" / "settings.json").read_text(encoding="utf-8")
    again = AppSettings(tmp_path / "root", secrets_dir=tmp_path / "user")
    assert again.secret("anthropic")[0] == "sk-ant-test-1234567890"
    again.clear_secret("anthropic")
    assert not AppSettings(tmp_path / "root", secrets_dir=tmp_path / "user")._saved


# ───────────────────────────── client
def test_request_body_uses_adaptive_thinking_and_cache_for_fable():
    c = ac.AnthropicClient(api_key="k", effort="high")
    body = c._body("SYS", [{"role": "user", "content": "hi"}], [{"name": "t"}])
    assert body["model"] == "claude-fable-5-2"
    assert body["thinking"] == {"type": "adaptive"} and body["output_config"] == {"effort": "high"}
    assert body["system"][0]["cache_control"] and body["messages"][-1]["content"][-1]["cache_control"]
    old = ac.AnthropicClient(api_key="k", model="claude-sonnet-4-5", effort="high", thinking_budget=4000)
    assert old._body("S", [{"role": "user", "content": "x"}], [])["thinking"] == {"type": "enabled", "budget_tokens": 4000}


def test_cache_mark_does_not_mutate_the_conversation():
    msgs = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "1", "content": "x"}]}]
    marked = ac._with_cache_mark(msgs)
    assert "cache_control" in marked[-1]["content"][-1] and "cache_control" not in msgs[-1]["content"][-1]


def test_client_drops_a_rejected_optional_feature_and_retries(monkeypatch):
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=0):
        body = json.loads(req.data)
        seen.append(body)
        if "output_config" in body:
            raise HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(json.dumps({"error": {"message": "output_config.effort: unknown value"}}).encode()))
        return Resp(json.dumps({"content": [{"type": "text", "text": "OK"}], "usage": {"input_tokens": 3, "output_tokens": 1}}).encode())

    monkeypatch.setattr(ac, "urlopen", fake_urlopen)
    c = ac.AnthropicClient(api_key="k", effort="max")
    out = c.create("S", [{"role": "user", "content": "x"}], [])
    assert out["content"][0]["text"] == "OK" and len(seen) == 2 and "thinking" not in seen[1]
    assert c.warnings and c.usage["calls"] == 1
    assert ac.equivalent_tokens({"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}) == 25


# ───────────────────────────── sanity
def test_sanity_flags_what_a_chief_estimator_would_ask():
    pkg = {"labor_rates": {"FE": {"kind": "prevailing_wage"}}, "tax": {"mode": "excluded_resale"}, "project": {},
           "materials": [{"id": "M001", "item": "Chain link fabric black vinyl 4 ft", "spec": "", "section": "A", "qty": "100", "unit": "LF",
                          "unit_price": "90.00", "price_basis": "BUDGET", "price_source": ""},
                         {"id": "M002", "item": "Chain link fabric black vinyl 4 ft", "spec": "", "section": "A", "qty": "1", "unit": "LF",
                          "unit_price": "0", "price_basis": "QUOTE"}],
           "labor": [{"rate": "FE", "hours": "1"}], "other": [], "exclusions": ["Bonds."]}
    book = [{"item": "Chain-link fabric 4 ft black vinyl coated", "unit": "LF", "unit_price": "6.00", "price_basis": "QUOTE", "source": "x"}]
    codes = {f["code"] for f in sanity_checks(pkg, {"materials": "9000.00", "labor": "60.00"}, book, 35)}
    assert {"price_deviation", "duplicate", "zero_price", "no_price_source", "budget_share", "labor_low",
            "no_li_fees", "no_mobilization", "alternates", "no_bid_date"} <= codes


# ───────────────────────────── agent guards
def _agent(bidset, tmp_path, script, **kw):
    out = tmp_path / "out"
    tb = ToolBox(DocIndex.build(bidset, tmp_path / "c"), PROFILE, out, base_dir=ROOT / "profiles")
    fake = FakeClient(script)
    return EstimatorAgent(fake, tb, PROFILE, out / "log.jsonl", max_turns=30, web_search=False, **kw), fake, out


def test_no_go_stops_before_estimating_but_needs_the_requirement_on_record(bidset, tmp_path):
    agent, fake, out = _agent(bidset, tmp_path, [
        [("finish", {"decision": "NO_GO", "summary": "Pre-bid obligatorio ya pasó.", "must_verify": []})],
        [REQ],
        [("finish", {"decision": "NO_GO", "summary": "Pre-bid obligatorio ya pasó.", "must_verify": ["Confirmar con el owner"]})]])
    result = agent.run("TEST")
    assert result["report"]["decision"] == "NO_GO" and result["build"] is None and fake.calls == 3
    rep = write_report(out, "TEST", result).read_text(encoding="utf-8")
    assert "NO-GO" in rep and "Requisitos para poder ofertar" in rep
    assert "NO_GO" in agent.system and "Standing instructions" not in agent.system


def test_finish_is_refused_without_a_verified_package(bidset, tmp_path):
    agent, fake, _ = _agent(bidset, tmp_path, [
        [("finish", {"summary": "listo", "must_verify": []})],
        [("save_package", _draft())], [("build_package", {})],
        [("finish", {"decision": "GO", "summary": "listo", "must_verify": []})]])
    result = agent.run("TEST")
    assert result["completed"] and result["build"]["qa"]["status"] == "PASS" and result["sanity"]
    assert "Aún no hay paquete" in json.dumps(fake.seen[1], ensure_ascii=False)


def test_independent_review_sends_blockers_back_once(bidset, tmp_path):
    script = [[("save_package", _draft())], [("build_package", {})],
              [("finish", {"summary": "v1", "must_verify": []})], REVIEW_FIX,
              [("save_package", _draft())], [("build_package", {})],
              [("finish", {"summary": "v2", "must_verify": []})]]
    agent, fake, out = _agent(bidset, tmp_path, script, review_rounds=1)
    agent.reviewer = fake
    result = agent.run("TEST")
    assert result["report"]["summary"] == "v2" and result["reviews"][0]["verdict"] == "FIX" and fake.calls == len(script)
    assert "Bike racks sin anclas" in write_report(out, "TEST", result).read_text(encoding="utf-8")
    review_call = fake.seen[3]
    assert review_call[0]["content"].startswith("PACKAGE") and len(review_call) == 1      # fresh context


def test_run_key_wins_over_the_key_the_model_writes(bidset, tmp_path):
    agent, _, out = _agent(bidset, tmp_path, [[("save_package", _draft())], [("build_package", {})],
                                             [("finish", {"summary": "x", "must_verify": []})]])
    agent.run("OTRA")
    assert (out / "otra.json").exists() and (out / "OTRA_01_COST_ANALYSIS.pdf").exists()


def test_cancel_stops_between_turns(bidset, tmp_path):
    agent, fake, _ = _agent(bidset, tmp_path, [[("list_documents", {})]] * 3, should_stop=lambda: fake.calls >= 1)
    with pytest.raises(Cancelled):
        agent.run("TEST")
    assert fake.calls == 1


# ───────────────────────────── app over HTTP
class App:
    def __init__(self, root, script):
        self.fakes = []

        def factory(model, effort, cache):
            self.fakes.append(FakeClient(script))
            return self.fakes[-1]

        self.api = AppAPI(root, AppSettings(root, secrets_dir=root / "_user"), factory)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, self.api))
        Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.token = self.get("/api/session")["token"]

    def raw(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read(), r.headers

    def get(self, path):
        return json.loads(self.raw(path)[0])

    def post(self, path, data, expect=200):
        req = urllib.request.Request(self.base + path, json.dumps({"actor": "Andrés", **data}).encode(),
                                     {"Content-Type": "application/json", "X-ALKAN-Token": self.token})
        try:
            with urllib.request.urlopen(req) as r:
                assert r.status == expect
                return json.loads(r.read())
        except HTTPError as exc:
            assert exc.code == expect, exc.read()
            return json.loads(exc.read())

    def wait(self, run_id):
        for _ in range(200):
            run = self.get(f"/api/app/run?id={run_id}")
            if run["finished_at"]:
                return run
            time.sleep(0.05)
        raise AssertionError("la corrida no terminó")


@pytest.fixture
def app(tmp_path, bidset):
    root = tmp_path / "root"
    (root / "profiles" / "assets").mkdir(parents=True)
    for name in ("ss_custom_iron_works.json", "generico_sin_marca.json"):
        (root / "profiles" / name).write_bytes((ROOT / "profiles" / name).read_bytes())
    (root / "profiles" / "assets" / "ss_logo.png").write_bytes((ROOT / "profiles" / "assets" / "ss_logo.png").read_bytes())
    script = [[("list_documents", {})],
              [("record_note", {"kind": "date", "text": "Bid due Nov 10 1:00 PM PT", "source": "Addendum_3.pdf p1"})],
              [("save_package", _draft())], [("build_package", {})],
              [("finish", {"decision": "GO", "summary": "Paquete listo.", "must_verify": ["Tarifa Pierce"]})], REVIEW_OK]
    a = App(root, script)
    a.bidset = bidset
    yield a
    a.server.shutdown()


def test_pages_and_status(app):
    home, _ = app.raw("/")
    assert b"ALKAN" in home and b"app.js" in home
    assert b"Estimate Intelligence" in app.raw("/expedientes")[0]
    assert b"Estimate Intelligence" in app.raw("/?mode=advanced")[0]           # old deep links keep working
    st = app.get("/api/app/status")
    assert st["ready"] is False and st["checks"][0]["id"] == "key" and st["model"] == "claude-fable-5-2"
    app.post("/api/app/key", {"key": "sk-ant-abcdefghijkl", "remember": False})
    st = app.get("/api/app/status")
    assert st["ready"] and "sk-ant" not in json.dumps(st)
    assert app.post("/api/app/settings", {"settings": {"engine": {"effort": "nope"}}}, expect=400)["error"]
    assert app.post("/api/app/settings", {"settings": {"engine": {"max_turns": 60}}})["settings"]["engine"]["max_turns"] == 60


def test_upload_run_deliver_authorize_and_rebrand(app):
    upload = str(uuid.uuid4())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(app.bidset / "PLANS.pdf", "Plans/PLANS.pdf")
    blob = buf.getvalue()
    half = len(blob) // 2
    for i, part in enumerate((blob[:half], blob[half:])):                         # chunked, like large plan sets
        app.post("/api/app/upload", {"upload_id": upload, "name": "Set.zip", "index": i, "content": base64.b64encode(part).decode()})
    app.post("/api/app/upload", {"upload_id": upload, "name": "Addendum_3.pdf", "index": 0,
                                 "content": base64.b64encode((app.bidset / "Addendum_3.pdf").read_bytes()).decode()})
    assert app.post("/api/app/upload", {"upload_id": upload, "name": "x.exe", "index": 0, "content": "QQ=="}, expect=400)["error"]
    spec = {"key": "test", "profile": "generico_sin_marca", "upload_id": upload, "notes": "base bid"}
    assert "oficio" in app.post("/api/app/run/start", {"spec": spec}, expect=400)["error"]     # generic profile needs a trade
    spec["trade_scope"] = "Site furnishings and fences"
    run = app.post("/api/app/run/start", {"spec": spec})
    done = app.wait(run["id"])
    assert done["status"] == "lista" and done["qa"] == "PASS" and done["decision"] == "GO" and done["review"] == "PASS"
    assert done["documents"] == 2 and done["generic"] and done["proposal"].startswith("DRAFT")
    names = [f["name"] for f in done["files"]]
    assert names[:3] == ["TEST_01_COST_ANALYSIS.pdf", "TEST_02_MATERIAL_LIST.pdf", "TEST_03_ESTIMATE_PROPOSAL.pdf"]
    assert "TEST_REPORTE_AGENTE.pdf" in names and "Fechas clave" in done["report_md"] and done["events"]
    raw, headers = app.raw(f"/api/app/run/file?id={run['id']}&name={done['zip']}&download=1")
    assert "attachment" in headers["Content-Disposition"]
    inside = set(zipfile.ZipFile(io.BytesIO(raw)).namelist())
    assert {"TEST_03_ESTIMATE_PROPOSAL.pdf", "TEST_REPORTE_AGENTE.pdf", "test.json"} <= inside and "run.json" not in inside
    assert app.post("/api/app/run/file", {}, expect=404)
    with pytest.raises(HTTPError):
        app.raw(f"/api/app/run/file?id={run['id']}&name=../run.json")
    assert "Standing" not in app.fakes[0].seen[0][0]["content"]
    # Same takeoff for a real contractor: recomputed with their profile, then authorized by a person.
    branded = app.post("/api/app/run/rebrand", {"id": run["id"], "profile": "ss_custom_iron_works"})
    assert branded["source_run"] == run["id"] and branded["contractor"].startswith("S & S") and branded["qa"] == "PASS"
    pkg = json.loads((app.api.runs.run_dir(branded["id"]) / "test.json").read_text(encoding="utf-8"))
    assert pkg["contractor"]["name"].startswith("S & S") and pkg["estimate_id"].startswith("SS-EST") and not pkg["release"]["authorized"]
    final = app.post("/api/app/run/authorize", {"id": branded["id"], "note": "Aprobado por Shervin"})
    assert final["status"] == "autorizada" and final["proposal"] == "LUMP-SUM PROPOSAL" and final["authorized_by"] == "Andrés"
    runs = app.get("/api/app/runs")
    assert len(runs["runs"]) == 2 and runs["active"] is None


def test_profiles_and_knowledge_admin(app):
    profs = {p["name"]: p for p in app.get("/api/app/profiles")["profiles"]}
    assert profs["generico_sin_marca"]["generic"] and profs["ss_custom_iron_works"]["has_logo"]
    prof = app.get("/api/app/profile?name=ss_custom_iron_works")["profile"]
    prof["contractor"]["name"] = "THE FABRICATOR LLC"
    prof["markups"]["profit_pct"] = "12"
    saved = app.post("/api/app/profile/save", {"name": "The Fabricator", "profile": prof})
    assert saved["name"] == "the_fabricator" and saved["profile"]["markups"]["profit_pct"] == "12"
    prof["markups"]["profit_pct"] = 12.5
    assert "float" in app.post("/api/app/profile/save", {"name": "x", "profile": prof}, expect=400)["error"]
    wages = app.get("/api/app/knowledge?table=wages")
    assert not wages["edited"] and len(wages["rows"]) >= 5
    rows = wages["rows"] + [{"county": "Kitsap", "trade": "Ironworkers", "classification": "Journeyman", "rate": "$95.10",
                             "effective": "2026-08-31", "source": "L&I Kitsap", "verified": True}]
    out = app.post("/api/app/knowledge/save", {"table": "wages", "rows": rows})
    assert out["edited"] and out["rows"][-1]["rate"] == "95.10"
    assert app.post("/api/app/knowledge/save", {"table": "wages", "rows": [{"county": "King"}]}, expect=400)["error"]
    tb = ToolBox(DocIndex.build(app.bidset, app.api.root / "c"), PROFILE, app.api.root / "o", knowledge_dir=app.api.runs.knowledge_dir())
    assert json.loads(tb.call("lookup_wage", {"county": "Kitsap"})[0])["rows"]
    assert not app.post("/api/app/knowledge/reset", {"table": "wages"})["edited"]
