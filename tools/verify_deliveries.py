"""Read-only checks of the four final bundles, original hashes and live cost formulas."""
from pathlib import Path
import sys

from openpyxl import load_workbook
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from bidkit.audit import sha256
from bidkit.config import ProjectConfig
from bidkit.data_store import read_json, write_json
from finalize_deliveries import NAMES, FOLDERS
from qa_excel_formulas import Evaluator


def main():
    assert {p.name for p in (ROOT/"ENTREGAS").iterdir() if p.is_dir()} == set(NAMES)
    results=[]
    for name in NAMES:
        c=ProjectConfig(ROOT,name);base=ROOT/"ENTREGAS"/name
        assert {p.name for p in base.iterdir() if p.is_dir()} == set(FOLDERS)
        manifest_path=base/FOLDERS[5]/"MANIFIESTO_ENTREGA.json"
        manifest=read_json(manifest_path)
        actual={p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file() and p != manifest_path}
        assert actual == set(manifest["files"])
        for filename,digest in manifest["files"].items(): assert sha256(base/filename) == digest,filename
        originals=read_json(base/FOLDERS[5]/"Integridad_Originales.json")["originals"]
        for asset in originals:
            assert sha256(c.source_root/asset["file"]) == asset["sha256"] == sha256(base/FOLDERS[6]/asset["file"])
        assert len(originals) == len(c.source_assets)
        pricing=read_json(base/FOLDERS[1]/"Entradas_Precios.json")
        registry=read_json(base/FOLDERS[1]/"Fuentes_y_Cotizaciones.json")
        cost=read_json(base/FOLDERS[5]/"Calculos_Costos.json")
        prep=read_json(base/FOLDERS[5]/"Preparacion_Licitacion.json")
        assert all(r["project_id"] == c.id for r in (pricing,registry,cost,prep))
        assert pricing["mode"] == "REAL" and all(q["kind"] == "REAL" for q in registry["quotes"])
        assert not prep["authorization"]["signed"] and not prep["authorization"]["submitted"]
        assert prep["historical_test"] == (name == NAMES[3])
        for path in base.rglob("*.xlsx"):
            book=load_workbook(path);assert book.sheetnames
            if path.name != "Presupuesto_Principal.xlsx": continue
            assert book.properties.category == "REAL_PRELIMINARY_COSTS" and book["Settings"]["B2"].value == c.id
            e=Evaluator(book);formulas=0
            for sheet in book:
                for row in sheet:
                    for cell in row:
                        if cell.data_type == "f": e.cell(sheet.title,cell.coordinate);formulas+=1
            for row,s in enumerate(cost["summaries"],2):
                for col,key in (("F","known_direct_partial"),("G","known_direct_low"),("H","known_direct_high")):
                    expected=s[key] if s[key] is not None else ""
                    got=e.cell("Scopes",f"{col}{row}")
                    assert got == expected if expected == "" else abs(got-expected)<.011,(name,key,got,expected)
            assert e.cell("Summary","B7") == ""  # These supplied records remain incomplete.
        pages=0
        for path in (base/FOLDERS[1]/"Resumen_Profesional.pdf",base/FOLDERS[5]/"Respaldo_Tecnico.pdf"):
            pdf=PdfReader(path);assert len(pdf.pages)>0;pages+=len(pdf.pages)
        results.append({"project":name,"status":"PASS","hashed_files":len(actual),"originals":len(originals),"real_workbook_formulas_evaluated":formulas,"generated_pdf_pages_read":pages,"native_excel_recalculated":False})
        print(f"{name}: final integrity, isolation, XLSX and PDF PASS",flush=True)
    write_json(ROOT/"data/qa/phase-d/delivery_verification.json",{"status":"PASS","projects":results,"original_source_files_unchanged":True})


if __name__ == "__main__": main()
