"""ALKAN method learned on the metal-fabrication bids: target price, benchmarks and method checks."""
from bidkit.estimator_agent.agent import METHOD, target_price_lines, write_report
from bidkit.estimator_agent.sanity import method_checks, sanity_checks
from bidkit.estimator_agent.tools import TOOLS

BASE = {"materials": [], "labor": [], "other": [], "scope": [], "exclusions": [], "assumptions": []}


def test_method_carries_metal_lessons():
    for words in ("SUPPLIER QUOTES FIRST", "per GC direction", "fire watch", "elevator", "ENGINEER'S ESTIMATE",
                  "TARGET PRICE", "never mention prior bids"):
        assert words in METHOD


def test_tools_accept_benchmark_and_target_price():
    by = {t["name"]: t for t in TOOLS}
    assert "benchmark" in by["record_note"]["input_schema"]["properties"]["kind"]["enum"]
    assert "target_price" in by["finish"]["input_schema"]["properties"]


def test_target_price_never_below_cost_silently():
    lines = "\n".join(target_price_lines({"price": "120000.00", "direct": "100000.00"}, "$95,000"))
    assert "-25,000.00" in lines and "debajo del costo directo" in lines
    thin = "\n".join(target_price_lines({"price": "120000.00", "direct": "100000.00"}, "105000"))
    assert "menor a 8%" in thin
    ok = "\n".join(target_price_lines({"price": "120000.00", "direct": "100000.00"}, "125000"))
    assert "ALERTA" not in ok and "Ojo" not in ok and "NO se ajustaron" in ok


def test_internal_words_do_not_reach_the_proposal():
    pkg = {**BASE, "scope": [{"title": "Guardrail", "text": "Same as prior bid SEA10 at $139,268"}],
           "exclusions": ["Engineer's estimate is $65,000"]}
    leaks = [f for f in method_checks(pkg) if f["code"] == "internal_leak"]
    assert len(leaks) == 2


def test_quote_lines_need_quote_number():
    pkg = {**BASE, "materials": [
        {"id": "M001", "item": "W8x31", "price_basis": "QUOTE", "price_source": "Farwest Steel"},
        {"id": "M002", "item": "HSS 4x4", "price_basis": "QUOTE", "price_source": "Farwest Steel quote #3851690 10/14/2026"}]}
    bad = [f["text"] for f in method_checks(pkg) if f["code"] == "quote_no_ref"]
    assert len(bad) == 1 and bad[0].startswith("M001")


def test_special_conditions_must_be_priced_or_excluded():
    notes = [{"kind": "risk", "text": "Pieces limited by elevator 12 ft / 3,000 lb; hot work requires fire watch", "source": "GC email"}]
    codes = [f["text"] for f in method_checks(BASE, notes) if f["code"] == "special_unpriced"]
    assert len(codes) == 2
    priced = {**BASE, "labor": [{"task": "Fire watch during field welding", "rate": "IW", "hours": "16"}],
              "other": [{"item": "Field splices for elevator delivery", "category": "Other"}]}
    assert not [f for f in method_checks(priced, notes) if f["code"] == "special_unpriced"]


def test_sanity_still_works_without_notes():
    assert isinstance(sanity_checks(BASE, {"materials": "0", "labor": "0"}, []), list)


def test_report_shows_benchmark_and_target(tmp_path):
    result = {"report": {"decision": "GO", "summary": "ok", "must_verify": [], "target_price": "100000"},
              "notes": [{"kind": "benchmark", "text": "Engineer's estimate $65,000-$70,000 whole project", "source": "Ad p1"}],
              "build": {"computation": {"totals": {"price": "110000.00", "direct": "90000.00"}},
                        "qa": {"status": "PASS"}, "proposal_release": {"label": "DRAFT"}},
              "usage": {"calls": 1, "input_tokens": 1, "output_tokens": 1}, "images": 0}
    rep = write_report(tmp_path, "T", result).read_text(encoding="utf-8")
    assert "Referencias de precio" in rep and "Precio objetivo" in rep and "-10,000.00" in rep
