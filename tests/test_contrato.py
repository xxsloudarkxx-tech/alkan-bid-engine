"""Contrato con alcance preconfigurado por cliente (bidkit.contrato)."""
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from bidkit import contrato

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pdir(tmp_path):
    d = tmp_path / "profiles"
    shutil.copytree(ROOT / "profiles", d)
    return d


def _draft():
    return json.loads((ROOT / "examples" / "packages" / "hc3_diaz.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["diaz", "DÍAZ", "Luis Diaz", "diaz_finish_carpenter", "Díaz Finish Carpenter"])
def test_resolve_by_alias_without_accents(pdir, name):
    assert contrato.resolve(name, pdir)[0] == "diaz_finish_carpenter"


def test_resolve_unknown_lists_options(pdir):
    with pytest.raises(ValueError, match="no encontrado"):
        contrato.resolve("zzz roofing de marte", pdir)


def test_county_prevailing_wage_beats_profile_rate(pdir):
    draft = _draft()
    draft["labor_rates"]["FC"] = {"label": "Carpenter", "kind": "prevailing_wage", "trade": "carpenter",
                                  "rate": "87.71", "source": "Snohomish Co. eff. 11/2/2026"}
    pkg, _ = contrato.preparar(draft, "diaz", pdir)
    assert pkg["labor_rates"]["FC"]["rate"] == "87.71"      # profile carries King 83.21
    assert pkg["labor_rates"]["FC"]["burden_pct"] == "15"


def test_unused_profile_rates_are_dropped_and_base_exclusions_added(pdir):
    draft = _draft()
    pkg, rep = contrato.preparar(draft, "diaz", pdir)
    assert set(pkg["labor_rates"]) == {l["rate"] for l in pkg["labor"]}
    assert any("countertop subcontractor" in e for e in pkg["exclusions"])
    assert len(pkg["exclusions"]) == len({contrato._norm(e) for e in pkg["exclusions"]})
    assert pkg["estimate_id"].startswith("DIAZ-EST-2026-")
    assert rep["faltan_datos"] == ["license"]


def test_scope_conflict_flags_countertops_for_diaz(pdir):
    draft = _draft()
    draft["materials"].append({"id": "M999", "section": "B. Countertops", "item": "HPDL countertops with backsplash",
                               "spec": "", "qty": "10", "unit": "LF", "unit_price": "95", "price_basis": "BUDGET"})
    _, rep = contrato.preparar(draft, "diaz", pdir)
    assert [c["id"] for c in rep["fuera_de_alcance"]] == ["M999"]


def test_hacer_builds_three_documents(pdir, tmp_path):
    src = tmp_path / "hc3.json"
    src.write_text(json.dumps(_draft()), encoding="utf-8")
    rep = contrato.hacer(src, "luis", tmp_path / "out", pdir)
    assert rep["qa"] == "PASS" and len(rep["archivos"]) == 3
    assert all(Path(f).exists() for f in rep["archivos"])


def test_strict_mode_blocks_out_of_scope(pdir, tmp_path):
    draft = _draft()
    draft["materials"].append({"id": "M999", "section": "x", "item": "Solid surface countertops", "spec": "",
                               "qty": "1", "unit": "LF", "unit_price": "1", "price_basis": "BUDGET"})
    src = tmp_path / "d.json"
    src.write_text(json.dumps(draft), encoding="utf-8")
    with pytest.raises(ValueError, match="no hace"):
        contrato.hacer(src, "diaz", tmp_path / "out", pdir, estricto=True)


def test_logo_pack_import_from_zip(pdir, tmp_path):
    def png(color, size=(400, 200)):
        img = Image.new("RGB", size, "white")
        img.paste(Image.new("RGB", (200, 100), color), (100, 50))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    pack = tmp_path / "logos.zip"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("Logos/Diaz Logo.png", png("navy"))
        zf.writestr("Logos/JC-Granite.jpg", png("gray"))
        zf.writestr("Logos/PJ_Roofing.png", png("red"))
        zf.writestr("Logos/random photo.png", png("green"))
    res = contrato.importar_logos(pack, pdir)
    assert {r["cliente"] for r in res["importados"]} == {"diaz_finish_carpenter", "jc_granite_design", "pj_roofing"}
    assert res["sin_cliente"] == ["random photo.png"]
    logo = contrato.find_logo("diaz_finish_carpenter", contrato.list_profiles(pdir)["diaz_finish_carpenter"], pdir)
    assert logo.name == "diaz_finish_carpenter.png"
    assert Image.open(logo).size == (200, 100)     # white border trimmed
    prof = json.loads((pdir / "diaz_finish_carpenter.json").read_text(encoding="utf-8"))
    assert prof["contractor"]["logo"] == "assets/diaz_finish_carpenter.png"


def test_incomplete_profiles_report_missing_data(pdir):
    _, rep = contrato.preparar(_draft(), "palemon", pdir)
    assert rep["incompleto"] and {"license", "phone"} <= set(rep["faltan_datos"])
