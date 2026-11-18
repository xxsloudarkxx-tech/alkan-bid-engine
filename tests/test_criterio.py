"""Criterio de Don Miguel: reglas del vigilante y tope de ajuste porcentual."""
import copy
import json
from pathlib import Path

import pytest

from bidkit.criterio import familia, load_criterio, main as criterio_main, report_md, review
from bidkit.reprice import run
from bidkit.suppliers import SupplierError, load_directory, reprice

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples" / "packages").glob("*.json"))
DIR = load_directory()
TODAY = "2026-11-16"


def _pkg(name="hc3_ss"):
    return json.loads((ROOT / "examples" / "packages" / f"{name}.json").read_text(encoding="utf-8"))


def _rules(res, level):
    return [f["rule"] for f in res["findings"] if f["level"] == level]


def _quoted(p, when=TODAY):
    for m in p["materials"]:
        m.update(price_basis="QUOTE", supplier="farwest_steel", quote_ref="Q-1", quote_date=when)
    return p


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_reviews_without_touching_it(path):
    p = json.loads(path.read_text(encoding="utf-8"))
    before = copy.deepcopy(p)
    res = review(p, today=TODAY)
    assert p == before and res["verdict"] in ("LISTO", "REVISAR", "DETENER")
    assert "Veredicto" in report_md(res)


def test_authorized_estimate_on_generic_prices_is_stopped():
    res = review(_pkg(), today=TODAY)                       # hc3_ss: authorized, 100% BUDGET
    assert res["verdict"] == "DETENER" and "cotizacion" in _rules(res, "ALTO")
    e = res["exposure"]
    assert e["unquoted_pct"] == "100.0" and float(e["price_low"]) < float(res["price"]) < float(e["price_high"])


def test_draft_on_generic_prices_is_only_a_warning():
    p = _pkg()
    p["release"]["authorized"] = False
    res = review(p, today=TODAY)
    assert res["verdict"] == "REVISAR" and "cotizacion" in _rules(res, "AVISO")


def test_quoted_and_hours_confirmed_is_ready():
    p = _quoted(_pkg())
    p["release"]["hours_confirmed"] = {"by": "Shervin Faezi", "date": TODAY}
    res = review(p, today=TODAY)
    assert res["verdict"] == "LISTO" and res["counts"]["ALTO"] == 0 and res["counts"]["AVISO"] == 0


def test_unconfirmed_hours_stop_an_authorized_estimate():
    res = review(_quoted(_pkg()), today=TODAY)
    assert _rules(res, "ALTO") == ["horas"]


@pytest.mark.parametrize("when,level", [("2026-11-10", None), ("2026-10-28", "AVISO"), ("2026-10-01", "ALTO")])
def test_quote_age(when, level):
    res = review(_quoted(_pkg(), when), today=TODAY)
    found = [f["level"] for f in res["findings"] if f["rule"] == "vigencia"]
    assert found == ([level] if level else [])


def test_markup_below_target_and_no_profit():
    p = _pkg()
    p["markups"]["profit_pct"] = "5"
    assert "markup" in _rules(review(p, today=TODAY), "AVISO")
    p["markups"]["profit_pct"] = "0"
    assert "markup" in _rules(review(p, today=TODAY), "ALTO")


def test_prevailing_wage_rate_from_another_county():
    p = _pkg()
    p["labor_rates"]["IW"]["source"] = "L&I journey-level Ironworker, Pierce Co."
    assert "condado" in _rules(review(p, today=TODAY), "ALTO")


def test_pending_numbers_are_reported_not_invented():
    res = review(_pkg("gonyea"), today=TODAY)                # Pierce: factor still null
    assert {"relacion", "condado"} <= set(_rules(res, "PENDIENTE"))
    crit = load_criterio()
    crit["condados"]["factor"]["Pierce"] = 0.95
    crit["markup"]["objetivo_por_relacion"]["sub_to_gc"] = 20
    assert review(_pkg("gonyea"), crit, today=TODAY)["counts"]["PENDIENTE"] == 0


def test_owner_direct_with_resale_tax_and_missing_mobilization():
    p = _pkg()
    p["relationship"] = "direct_homeowner"
    p["other"] = [o for o in p["other"] if o["category"] != "Mobilization"]
    rules = _rules(review(p, today=TODAY), "AVISO")
    assert "relacion" in rules and "distancia" in rules


def test_short_labor_share_and_too_many_rounds():
    p = _pkg()
    for l in p["labor"]:
        l["hours"] = "4"
    p["revision_log"] = [{}, {}, {}]
    assert _rules(review(p, today=TODAY), "AVISO").count("horas") == 2


def test_material_family_and_base_suppliers():
    crit = load_criterio()
    assert familia({"item": "60 mil TPO membrane"}, crit) == "techado"
    assert familia({"item": "HSS 4x4x1/4 steel tube"}, crit) == "metal"
    assert familia({"item": "2x6 lumber, PT"}, crit) == "madera"
    assert crit["proveedores_base"]["techado"] == ["abc_supply", "conway"]
    assert {s["id"] for s in DIR} >= {x for v in crit["proveedores_base"].values() for x in v}


def test_percent_change_cap_and_override():
    with pytest.raises(SupplierError, match="tope"):
        reprice(_pkg(), changes=[{"id": "M003", "pct_change": "900"}], directory=DIR)
    with pytest.raises(SupplierError, match="tope"):
        reprice(_pkg(), changes=[{"id": "M003", "pct_change": "-60"}], directory=DIR)
    assert reprice(_pkg(), changes=[{"id": "M003", "pct_change": "50"}], directory=DIR)["log"]
    res = reprice(_pkg(), changes=[{"id": "M003", "pct_change": "900"}], directory=DIR, force_pct=True)
    assert next(m for m in res["package"]["materials"] if m["id"] == "M003")["unit_price"] == "280.00"


def test_reprice_writes_the_criterio_report(tmp_path):
    out = run(ROOT / "examples" / "packages" / "hc3_ss.json", tmp_path,
              changes=str(ROOT / "examples" / "cambios" / "hc3_ss_cambios.csv"), today=TODAY)
    assert out["criterio"]["verdict"] == "DETENER" and out["criterio"]["altos"]
    assert (tmp_path / "hc3_ss_criterio.md").exists() and (tmp_path / "hc3_ss_criterio.json").exists()


def test_cli_exit_code(tmp_path, capsys):
    assert criterio_main([str(ROOT / "examples" / "packages" / "hc3_ss.json"), "--out", str(tmp_path), "--today", TODAY]) == 1
    assert criterio_main([str(ROOT / "examples" / "packages" / "wsj.json"), "--today", TODAY]) == 0
    assert "Veredicto" in capsys.readouterr().out
