"""Estimator agent: document index, tools, guards and the full loop with a scripted (fake) API."""
import json
from pathlib import Path

import pytest
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from bidkit.estimator_agent.agent import EstimatorAgent, _prune_images, write_report
from bidkit.estimator_agent.anthropic_client import AnthropicClient, APIError
from bidkit.estimator_agent.docindex import DocIndex
from bidkit.estimator_agent.tools import TOOLS, ToolBox

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "profiles" / "ss_custom_iron_works.json").read_text(encoding="utf-8"))
PROFILE["date"] = "2026-11-09"


@pytest.fixture
def bidset(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    c = canvas.Canvas(str(d / "PLANS.pdf"), pagesize=(36 * inch, 24 * inch), invariant=1)
    c.setFont("Helvetica", 14)
    c.drawString(2 * inch, 20 * inch, "FURNISHING SCHEDULE  BR BIKE RACK  SEE SPEC  4")
    c.drawString(2 * inch, 19 * inch, "PERIMETER FENCE 4'-0\" CHAIN LINK BLACK VINYL")
    c.line(1 * inch, 23 * inch, 3 * inch, 23 * inch)        # 2.000" long, 1" from top-left
    c.drawString(30 * inch, 1 * inch, "L1.00")
    c.showPage()
    c.drawString(2 * inch, 20 * inch, "DETAILS  PERIMETER FENCE  3/L6.3")
    c.drawString(30 * inch, 1 * inch, "L6.3")
    c.save()
    a = canvas.Canvas(str(d / "Addendum_3.pdf"), invariant=1)
    a.drawString(72, 700, "ADDENDUM NO. 3  All dates extended as follows:")
    a.drawString(72, 680, "Submission Deadline: 11/10/2026 1:00PM")
    a.save()
    return d


def test_index_search_text_and_sheet(bidset, tmp_path):
    idx = DocIndex.build(bidset, tmp_path / "cache")
    names = {d["doc"]: d for d in idx.listing()}
    assert names["Addendum_3.pdf"]["kind"] == "addendum"
    assert names["PLANS.pdf"]["page_size_pt"] == [2592, 1728]
    hits = idx.search(r"extended")
    assert hits and hits[0]["doc"] == "Addendum_3.pdf"
    assert idx.page_text("PLANS", 1)["sheet"] == "L1.00"


def test_index_is_cached_by_hash(bidset, tmp_path):
    DocIndex.build(bidset, tmp_path / "cache")
    idx2 = DocIndex.build(bidset, tmp_path / "cache")
    assert len(idx2.docs) == 2


def test_zip_input(bidset, tmp_path):
    import zipfile
    z = tmp_path / "set.zip"
    with zipfile.ZipFile(z, "w") as f:
        for p in bidset.iterdir():
            f.write(p, f"/{p.name}")              # absolute-style names like the real county ZIPs
        f.writestr("../evil.pdf", b"x")           # path traversal is ignored
    idx = DocIndex.build(z, tmp_path / "zcache")
    assert set(idx.docs) == {"PLANS.pdf", "Addendum_3.pdf"}


def test_measure_true_scale(bidset, tmp_path):
    idx = DocIndex.build(bidset, tmp_path / "cache")
    view, b64 = idx.render("PLANS", 1)
    s = view.px_per_pt
    pts = [[72 * s, 72 * s], [216 * s, 72 * s]]               # the 2" line, in view pixels
    assert idx.measure(view.view_id, pts, feet_per_inch=10)["feet"] == pytest.approx(20, abs=0.05)
    assert idx.measure(view.view_id, pts, scale_in_per_ft=0.25)["feet"] == pytest.approx(8, abs=0.05)
    cal = idx.calibrate(view.view_id, pts[0], pts[1], 20, [[0, 0], [pts[1][0] - pts[0][0], 0]])
    assert cal["feet"] == pytest.approx(20, abs=0.01)


def test_crop_render_dimensions(bidset, tmp_path):
    idx = DocIndex.build(bidset, tmp_path / "cache")
    view, _ = idx.render("PLANS", 1, crop=[0, 0, 0.25, 0.25])
    assert view.left == 0 and view.top == 0 and max(view.width_px, view.height_px) <= 1568
    with pytest.raises(ValueError):
        idx.render("PLANS", 1, crop=[0.5, 0, 0.25, 1])


def _draft():
    return {"project": {"key": "TEST", "short": "Test Park", "title": "Test Park — Metal", "owner": "Pierce County Parks",
                        "site": "Tacoma, WA", "county": "Pierce", "documents": ["PLANS.pdf", "Addendum_3.pdf"],
                        "bid_date": "November 10, 2026, 1:00 PM"},
            "labor_rates": {"FE": {"label": "Fence erector", "kind": "prevailing_wage", "trade": "fence_erector",
                                   "rate": "57.66", "source": "L&I Pierce (test)", "burden_pct": "0"}},
            "materials": [{"section": "A. Furnishings", "item": "Bike rack", "spec": "Surface mount", "qty": "4", "unit": "EA",
                           "unit_price": "850.00", "price_basis": "BUDGET", "price_source": "price book", "qty_source": "L1.00"}],
            "labor": [{"task": "Install 4 bike racks", "rate": "FE", "hours": "6"}],
            "other": [{"item": "Mobilization", "category": "Mobilization", "qty": "1", "unit": "EA", "rate": "150.00"}],
            "scope": [{"title": "Bike racks", "text": "Furnish and install 4 bike racks."}],
            "exclusions": ["Alternates."],
            "markups": {"contingency_pct": "0", "overhead_pct": "0", "profit_pct": "90", "rounding": "1"}}


def test_profile_controls_markups_burden_and_release(bidset, tmp_path):
    tb = ToolBox(DocIndex.build(bidset, tmp_path / "c"), PROFILE, tmp_path / "out", base_dir=ROOT / "profiles")
    out, err = tb.call("save_package", _draft())
    assert not err, out
    pkg = json.loads(tb.package_path.read_text(encoding="utf-8"))
    assert pkg["markups"] == PROFILE["markups"]                 # model-supplied markups ignored
    assert pkg["labor_rates"]["FE"]["burden_pct"] == PROFILE["burden_pct"]
    assert pkg["labor_rates"]["SHOP"] == PROFILE["labor_rates"]["SHOP"]
    assert pkg["release"]["authorized"] is False
    out, err = tb.call("build_package", {})
    assert not err and json.loads(out)["qa"] == "PASS"


def test_tool_errors_are_returned_not_raised(bidset, tmp_path):
    tb = ToolBox(DocIndex.build(bidset, tmp_path / "c"), PROFILE, tmp_path / "out")
    assert tb.call("read_page_text", {"doc": "PLANS", "page": 99})[1] is True
    assert tb.call("build_package", {})[1] is True
    assert tb.call("nope", {})[1] is True
    bad = _draft(); bad["labor_rates"]["FE"]["source"] = ""
    assert tb.call("save_package", bad)[1] is True              # PW without L&I source is blocked


def test_knowledge_base_lookups(bidset, tmp_path):
    tb = ToolBox(DocIndex.build(bidset, tmp_path / "c"), PROFILE, tmp_path / "out")
    assert json.loads(tb.call("lookup_wage", {"county": "King", "trade": "iron"})[0])["rows"][0]["rate"] == "94.82"
    assert json.loads(tb.call("lookup_price", {"keywords": "chain link fabric black"})[0])["rows"]
    assert json.loads(tb.call("lookup_productivity", {"keywords": "handrail"})[0])["rows"]


def test_prune_keeps_last_images():
    def res(i):
        return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": str(i),
                                             "content": [{"type": "text", "text": "m"}, {"type": "image", "source": {}}]}]}
    msgs = [res(i) for i in range(5)]
    _prune_images(msgs, 2)
    kinds = [m["content"][0]["content"][1]["type"] for m in msgs]
    assert kinds == ["text", "text", "text", "image", "image"]


def test_client_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(APIError):
        AnthropicClient()


def test_tool_schemas_are_valid():
    names = [t["name"] for t in TOOLS]
    assert len(names) == len(set(names))
    for t in TOOLS:
        assert t["input_schema"]["type"] == "object"


class FakeClient:
    """Scripted stand-in for the API: replays the method step by step."""
    def __init__(self, script):
        self.script, self.calls, self.seen = script, 0, []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    def create(self, system, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        step = self.script[self.calls]
        self.calls += 1
        self.usage["calls"] += 1
        self.usage["input_tokens"] += 1000
        blocks = [{"type": "tool_use", "id": f"t{self.calls}_{i}", "name": n, "input": a} for i, (n, a) in enumerate(step)]
        return {"content": [{"type": "text", "text": f"step {self.calls}"}] + blocks,
                "stop_reason": "tool_use" if blocks else "end_turn", "usage": {"input_tokens": 1000}}


def test_full_agent_loop_with_fake_api(bidset, tmp_path):
    idx = DocIndex.build(bidset, tmp_path / "c")
    out = tmp_path / "out"
    tb = ToolBox(idx, PROFILE, out, base_dir=ROOT / "profiles")
    script = [
        [("list_documents", {})],
        [("search_documents", {"pattern": "extended|deadline"})],
        [("record_note", {"kind": "date", "text": "Bid due Nov 10, 2026 1:00 PM PT (3:00 PM CDMX), extended by Addendum 3", "source": "Addendum_3.pdf p1"})],
        [("search_documents", {"pattern": "BIKE RACK"}), ("view_page", {"doc": "PLANS", "page": 1, "crop": [0, 0, 0.5, 0.3]})],
        [("lookup_price", {"keywords": "bike rack"}), ("lookup_wage", {"county": "Pierce", "trade": "fence"})],
        [("save_package", _draft())],
        [("build_package", {})],
        [("finish", {"summary": "Paquete listo: 4 bike racks.", "must_verify": ["Tarifa Pierce sin verificar"]})],
    ]
    fake = FakeClient(script)
    agent = EstimatorAgent(fake, tb, PROFILE, out / "log.jsonl", max_turns=20, web_search=False)
    result = agent.run("TEST")
    assert result["report"]["summary"].startswith("Paquete listo")
    assert result["build"]["qa"]["status"] == "PASS"
    assert set(result["build"]["files"]) == {"cost_analysis", "material_list", "proposal"}
    assert result["build"]["proposal_release"]["label"].startswith("DRAFT")
    assert result["images"] == 1 and fake.calls == len(script)
    # Tool results reach the model in order and roles alternate user/assistant.
    last = fake.seen[-1]
    roles = [m["role"] for m in last]
    assert roles[0] == "user" and roles[-1] == "user"
    assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    rep = write_report(out, "TEST", result).read_text(encoding="utf-8")
    assert "Fechas clave" in rep and "Nov 10, 2026" in rep and "Precio de venta" in rep
    assert len((out / "log.jsonl").read_text(encoding="utf-8").splitlines()) >= len(script) * 2


def test_budget_stop_keeps_role_alternation(bidset, tmp_path):
    tb = ToolBox(DocIndex.build(bidset, tmp_path / "c"), PROFILE, tmp_path / "out", base_dir=ROOT / "profiles")
    script = [[("list_documents", {})], [("save_package", _draft())], [("build_package", {})], [("finish", {"summary": "x", "must_verify": []})]]
    fake = FakeClient(script)
    agent = EstimatorAgent(fake, tb, PROFILE, tmp_path / "out" / "log.jsonl", web_search=False, budget_tokens=1500)
    agent.run("TEST")
    for convo in fake.seen:
        roles = [m["role"] for m in convo]
        assert all(roles[i] != roles[i + 1] for i in range(len(roles) - 1))
    assert any("Token budget reached" in json.dumps(c) for c in fake.seen)
