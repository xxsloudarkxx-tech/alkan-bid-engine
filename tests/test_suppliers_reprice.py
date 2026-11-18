"""Supplier logistics: directory, price/supplier changes and price lists on the example estimates."""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from bidkit.package_method import compute, package_from_dict, validate
from bidkit.reprice import main as reprice_main, run
from bidkit.suppliers import (SupplierError, apply_changes, auto_assign, load_directory, load_price_lists, offers,
                              purchasing, reprice, resolve_supplier, suggest_supplier)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = sorted((ROOT / "examples" / "packages").glob("*.json"))
DIR = load_directory()


def _pkg(name="hc3_ss"):
    return json.loads((ROOT / "examples" / "packages" / f"{name}.json").read_text(encoding="utf-8"))


def _price(p):
    return compute(package_from_dict(p))["price"]


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_every_example_computes_and_accepts_supplier_assignment(path):
    p = json.loads(path.read_text(encoding="utf-8"))
    before = _price(p)
    res = reprice(p, assign=True, directory=DIR)
    assert res["summary"]["sell_price_after"] == f"{before:.2f}"     # assigning a supplier never moves the price
    assert _price(p) == before                                       # original untouched
    known = {s["id"] for s in DIR}
    assert all(m.get("supplier", "") in known | {""} for m in res["package"]["materials"])


def test_directory_ids_unique_and_resolution():
    assert len({s["id"] for s in DIR}) == len(DIR) >= 10
    assert resolve_supplier("Farwest Steel", DIR)["id"] == "farwest_steel"
    assert resolve_supplier("FARWEST_STEEL", DIR)["id"] == "farwest_steel"
    with pytest.raises(SupplierError, match="farwest_steel"):
        resolve_supplier("Farwest", DIR)                             # ambiguous short name → suggestion, not a guess
    with pytest.raises(SupplierError):
        resolve_supplier("Acme Nonexistent", DIR)


def test_suggestion_uses_first_keyword_in_item_and_whole_words():
    assert suggest_supplier({"item": "Galvanizing misc. metals (angles, clips, bent plate)"}, DIR) == "galvanizador"
    assert suggest_supplier({"item": "Base plates 1\" x 14\""}, DIR) == "farwest_steel"
    assert suggest_supplier({"item": "Metal grommets, painted to blend", "spec": "Rakks primer"}, DIR) is None
    assert suggest_supplier({"item": "Fabric 4'-0\" x 50' roll, 2\" mesh"}, DIR) is None


def test_price_change_becomes_quote_and_moves_total():
    p = _pkg()
    res = reprice(p, changes=[{"id": "M003", "unit": "LF", "supplier": "farwest_steel", "unit_price": "26.40",
                               "price_basis": "QUOTE", "quote_ref": "Q-1", "quote_date": "2026-11-16"}], directory=DIR)
    m = next(x for x in res["package"]["materials"] if x["id"] == "M003")
    assert (m["unit_price"], m["price_basis"], m["supplier"], m["quote_ref"]) == ("26.40", "QUOTE", "farwest_steel", "Q-1")
    assert m["price_source"] == "Farwest Steel quote #Q-1 2026-11-16"
    assert res["summary"]["materials_delta"] == "-384.00"            # 240 LF × (26.40 − 28.00)
    assert Decimal(res["summary"]["sell_price_after"]) < Decimal(res["summary"]["sell_price_before"])
    assert res["package"]["revision_log"][-1]["lines_changed"] == 1
    assert next(x for x in p["materials"] if x["id"] == "M003")["unit_price"] == "28.00"


def test_supplier_swap_drops_old_quote():
    p = _pkg()
    apply_changes(p, [{"id": "M003", "supplier": "farwest_steel", "unit_price": "26.40", "price_basis": "QUOTE", "quote_ref": "Q-1"}], DIR)
    log = apply_changes(p, [{"current_supplier": "farwest_steel", "supplier": "pacific_metals"}], DIR)
    m = next(x for x in p["materials"] if x["id"] == "M003")
    assert m["supplier"] == "pacific_metals" and m["price_basis"] == "BUDGET" and "quote_ref" not in m
    assert m["unit_price"] == "26.40" and "anterior" in log[0]["note"]


def test_percent_change_by_section():
    p = _pkg()
    res = reprice(p, changes=[{"section": "Mechanical Roof Screen", "pct_change": "10"}], directory=DIR)
    assert res["summary"]["lines_changed"] == 7
    assert res["summary"]["materials_delta"] == "2049.00"            # 10% of the $20,490 section


@pytest.mark.parametrize("change,msg", [
    ({"id": "M999", "unit_price": "1", "price_basis": "BUDGET"}, "ningún renglón"),
    ({"id": "M003", "supplier": "nobody_inc"}, "desconocido"),
    ({"id": "M003", "unit": "EA", "unit_price": "26", "price_basis": "BUDGET"}, "unidad"),
    ({"id": "M003", "unit_price": "26"}, "price_basis"),
    ({"id": "M003", "unit_price": "26", "price_basis": "QUOTE", "supplier": "farwest_steel"}, "quote_ref"),
    ({"id": "M003", "unit_price": "26", "price_basis": "QUOTE", "quote_ref": "Q"}, "proveedor"),
    ({"section": "Roof Screen", "unit_price": "5", "price_basis": "BUDGET"}, "un solo renglón"),
    ({"id": "M003", "unit_price": "26", "pct_change": "5", "price_basis": "BUDGET"}, "no los dos"),
    ({"supplier": "farwest_steel"}, "filtro"),
    ({"id": "M003", "note": "x"}, "qué cambiar"),
    ({"id": "M003", "unit_price": "-4", "price_basis": "BUDGET"}, "fuera de rango"),
])
def test_bad_changes_are_refused_and_nothing_changes(change, msg):
    p = _pkg()
    original = copy.deepcopy(p)
    with pytest.raises(SupplierError, match=msg):
        reprice(p, changes=[{"id": "M001", "pct_change": "5"}, change], directory=DIR)
    assert p == original


def test_price_lists_best_offer_expired_and_units(tmp_path):
    rows = load_price_lists([ROOT / "examples" / "cambios" / "lista_precios_demo.csv"], DIR, today="2026-11-16")
    p = _pkg()
    tube = next(m for m in p["materials"] if m["id"] == "M003")
    assert [o["supplier"] for o in offers(tube, rows)] == ["pacific_metals", "farwest_steel", "cascade_steel"]  # quotes first
    res = reprice(p, price_rows=rows, best=True, directory=DIR)
    new = {m["id"]: m for m in res["package"]["materials"]}
    assert (new["M003"]["supplier"], new["M003"]["unit_price"], new["M003"]["price_basis"]) == ("pacific_metals", "25.10", "QUOTE")
    assert new["M004"]["supplier"] == "roofscreen_mfg"               # CityScapes list expired → not used
    assert any("vencido" in s for s in res["skipped"])
    only = reprice(p, price_rows=rows, supplier="farwest_steel", directory=DIR)
    assert only["summary"]["lines_changed"] == 1
    with pytest.raises(SupplierError):
        reprice(p, price_rows=rows, supplier="farwest_steel", best=True, directory=DIR)
    bad = tmp_path / "l.csv"
    bad.write_text("supplier,match,unit,unit_price,price_basis\nfarwest_steel,tubing,LF,10,QUOTE\n", encoding="utf-8")
    with pytest.raises(SupplierError, match="quote_ref"):
        load_price_lists([bad], DIR)


def test_validation_flags_duplicates_unknown_supplier_and_auto():
    p = _pkg()
    p["other"][1]["id"] = p["other"][0]["id"]
    assert any("id repetido" in b for b in validate(package_from_dict(p))["blockers"])
    p = _pkg()
    p["materials"][0]["supplier"] = "ghost"
    auto_assign(p, DIR)
    w = " | ".join(validate(package_from_dict(p))["warnings"])
    assert "ghost" in w and "sugerido automáticamente" in w


def test_purchasing_totals_match_materials():
    p = reprice(_pkg("gonyea"), assign=True, directory=DIR)["package"]
    groups = purchasing(p, DIR)
    assert sum(Decimal(g["total"]) for g in groups) == compute(package_from_dict(p))["materials"]
    assert groups[-1]["supplier"] == ""                              # unassigned last


def test_cli_builds_documents_and_never_overwrites_input(tmp_path):
    src = ROOT / "examples" / "packages" / "hc3_ss.json"
    raw = src.read_bytes()
    out = run(src, tmp_path, changes=str(ROOT / "examples" / "cambios" / "hc3_ss_cambios.csv"), build=True, today="2026-11-16")
    assert out["qa"] == "PASS" and out["sell_price_before"] == "67150.00" and out["sell_price_after"] == "66500.00"
    assert src.read_bytes() == raw
    csv_text = (tmp_path / "HC3_04_COMPRAS_POR_PROVEEDOR.csv").read_text(encoding="utf-8-sig")
    assert "Farwest Steel" in csv_text and "SUBTOTAL" in csv_text
    from pypdf import PdfReader
    text = "\n".join(pg.extract_text() for pg in PdfReader(str(tmp_path / "HC3_01_COST_ANALYSIS.pdf")).pages)
    assert "Purchasing by supplier" in text and "Farwest Steel" in text
    material_list = "\n".join(pg.extract_text() for pg in PdfReader(str(tmp_path / "HC3_02_MATERIAL_LIST.pdf")).pages)
    proposal = "\n".join(pg.extract_text() for pg in PdfReader(str(tmp_path / "HC3_03_ESTIMATE_PROPOSAL.pdf")).pages)
    assert "Farwest" not in material_list + proposal                 # supplier names stay internal
    bad = tmp_path / "bad.csv"
    bad.write_text("id,precio\nM001,5\n", encoding="utf-8")
    assert reprice_main([str(src), "--changes", str(bad), "--out", str(tmp_path / "x")]) == 1
    assert not (tmp_path / "x").exists()


def test_same_project_key_gets_separate_folders(tmp_path):
    from bidkit.package_build import main
    assert main([str(ROOT / "examples" / "packages" / "hc3_*.json"), "--out", str(tmp_path)]) == 0
    assert sorted(d.name for d in tmp_path.iterdir()) == ["HC3_hc3_diaz", "HC3_hc3_jcgranite", "HC3_hc3_ss"]
