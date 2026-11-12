"""ALKAN 3-document package: method, release gates, rendering and cross-document QA."""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from bidkit.package_build import build, main as package_main
from bidkit.package_method import compute, load_package, package_from_dict, proposal_release, round_to

EX = Path(__file__).resolve().parents[1] / "examples" / "packages"

# Sell prices delivered to S&S on 2026-11-08 (reference results of the method).
EXPECTED = {"wsj.json": "22000.00", "meridian.json": "32150.00", "orangegate.json": "257550.00", "gonyea.json": "196000.00"}


def _data(name="wsj.json"):
    return json.loads((EX / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name,price", EXPECTED.items())
def test_reference_projects_reproduce_delivered_price(name, price):
    r = compute(load_package(EX / name))
    assert str(r["price"]) == price
    assert r["status"] == "BUDGETARY"  # all reference lines are budget-priced


def test_sequential_markups_and_rounding():
    d = _data()
    d["materials"] = [{"section": "A", "item": "Pipe", "qty": "10", "unit": "EA", "unit_price": "100.00",
                       "price_basis": "QUOTE", "qty_source": "S1"}]
    d["labor"] = [{"task": "Weld", "rate": "SHOP", "hours": "10"}]
    d["other"] = []
    r = compute(package_from_dict(d))
    assert r["direct"] == Decimal("1650.00")                # 1000 + 10 × 65
    assert r["contingency"] == Decimal("82.50")              # 5% of direct
    assert r["overhead"] == Decimal("173.25")                # 10% of (direct + cont)
    assert r["profit"] == Decimal("190.58")                  # 10% of (direct + cont + OH)
    assert r["total"] == Decimal("2096.33")
    assert r["price"] == Decimal("2100.00")
    assert r["status"] == "READY_FOR_REVIEW"


def test_prevailing_wage_loaded_rate():
    pkg = load_package(EX / "wsj.json")
    assert pkg.rates["IW"].loaded == Decimal("109.04")
    assert pkg.rates["FE"].loaded == Decimal("66.31")


def test_round_to():
    assert round_to(Decimal("22011.97"), Decimal("50")) == Decimal("22000")
    assert round_to(Decimal("22025.00"), Decimal("50")) == Decimal("22050")


def test_prevailing_wage_without_source_blocks():
    d = _data()
    d["labor_rates"]["IW"]["source"] = ""
    with pytest.raises(ValueError, match="fuente L&I"):
        compute(package_from_dict(d))


def test_float_values_rejected():
    d = _data()
    d["materials"][0]["unit_price"] = 438.0
    with pytest.raises(ValueError, match="float"):
        package_from_dict(d)


def test_unknown_rate_blocks():
    d = _data()
    d["labor"][0]["rate"] = "WELDER_X"
    with pytest.raises(ValueError, match="no definida"):
        compute(package_from_dict(d))


def test_budget_prices_block_proposal_without_human_exception():
    d = _data()
    d["release"] = {"authorized": False, "allow_budget_prices": False}
    pkg = package_from_dict(d)
    rel = proposal_release(pkg, compute(pkg))
    assert rel["produce"] is False


def test_budget_exception_requires_note():
    d = _data()
    d["release"] = {"allow_budget_prices": True}
    pkg = package_from_dict(d)
    assert proposal_release(pkg, compute(pkg))["produce"] is False


def test_engine_never_self_authorizes():
    pkg = load_package(EX / "wsj.json")
    rel = proposal_release(pkg, compute(pkg))
    assert rel["produce"] is True and rel["label"].startswith("DRAFT")
    d = _data()
    d["release"]["authorized"] = True
    pkg2 = package_from_dict(d)
    r2 = compute(pkg2)
    assert proposal_release(pkg2, r2)["label"] == "LUMP-SUM PROPOSAL"
    assert r2["status"] == "AUTHORIZED"


def test_alkan_commission_is_informational():
    r = compute(load_package(EX / "wsj.json"))
    assert r["commission"]["total"] == Decimal("660.00")      # 3% of 22,000
    assert r["price"] == Decimal("22000.00")                   # not added to price


@pytest.mark.parametrize("name", EXPECTED)
def test_build_renders_three_documents_and_qa_passes(tmp_path, name):
    m = build(EX / name, tmp_path)
    assert m["qa"]["status"] == "PASS", [c for c in m["qa"]["checks"] if c["result"] != "PASS"]
    assert set(m["files"]) == {"cost_analysis", "material_list", "proposal"}
    for f in m["files"].values():
        assert Path(f["path"]).stat().st_size > 5000
    key = json.loads((EX / name).read_text(encoding="utf-8"))["project"]["key"]
    assert (tmp_path / f"{key}_package_manifest.json").exists()


def test_cli_multiple_inputs(tmp_path, capsys):
    rc = package_main([str(EX / "*.json"), "--out", str(tmp_path)])
    assert rc == 0
    assert {p.name for p in tmp_path.iterdir()} == {"WSJ", "MERIDIAN", "ORANGEGATE", "GONYEA"}


def test_qa_detects_tampered_document(tmp_path):
    from bidkit.package_build import qa
    from bidkit.package_render import render_all
    pkg = load_package(EX / "wsj.json")
    r = compute(pkg)
    files = render_all(pkg, r, tmp_path)["files"]
    bad = copy.deepcopy(r)
    bad["price"] = Decimal("23000.00")
    assert qa(pkg, bad, files)["status"] == "FAIL"
