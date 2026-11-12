"""Quality checks for independently branded internal bid reviews."""
import csv, json, hashlib, zipfile, sys
from pathlib import Path
from pypdf import PdfReader
from PIL import Image
import pypdfium2 as pdfium
import prepare_branded_bid_review as branded

ROOT=branded.ROOT
BASE=branded.OUT
results=[]
for bidder,meta in branded.BIDDERS.items():
    z=BASE/(bidder+"_BRANDED_INTERNAL_REVIEW_ONLY.zip")
    assert z.exists()
    with zipfile.ZipFile(z) as archive:
        names=archive.namelist()
        assert any("official_site_logo.png" in n for n in names)
        assert all(n.startswith(bidder+"/") for n in names)
    for slug in branded.PROJECTS:
        path=BASE/bidder/slug/"01_BRANDED_SCOPE_REVIEW_INTERNAL.pdf"
        reader=PdfReader(path)
        content="\n".join((p.extract_text() or "") for p in reader.pages)
        assert 1<=len(reader.pages)<=4
        assert meta["legal_name"] in content
        assert meta["ubi"] in content
        assert meta["license"] in content
        assert meta["phone"] in content
        assert meta["email"] in content
        assert "NOT FOR SUBMISSION" in content
        assert "INTERNAL_BLOCKED" in content
        assert len(reader.pages[0].images)>=1, "Logo missing in pdf image XObjects"
        if bidder=="THE_FABRICATOR_LLC":
            assert "SSCUSSC781J9" not in content
            assert "SHAHRAM" not in content.upper()
            assert "S & S CUSTOM IRON WORKS" not in content.upper()
        else:
            assert "FABRIFL811JN" not in content
            assert "TIRSO" not in content.upper()
            assert "THE FABRICATOR LLC" not in content.upper()
        with (BASE/bidder/slug/"02_OWN_COST_INPUT_BLANK.csv").open(encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
        assert all(not x["bidder_unit_price_usd"] for x in rows)
        assert all(not x["bidder_supplier"] for x in rows)
        assert all(not x["labor_hours"] for x in rows)
        status=json.loads((BASE/bidder/slug/"03_REVIEW_STATUS.json").read_text(encoding="utf-8"))
        assert len(rows)==status["metal_items"]
        assert status["bid_authorized"] is False and status["pricing_ready"] is False
        results.append({"bidder":bidder,"project":slug,"pages":len(reader.pages),"images_first_page":len(reader.pages[0].images),"rows":len(rows),"result":"PASS"})
    # render first page of one PDF at 0.6x to verify visual composition
    f=BASE/bidder/"orangegate-park-phase-1"/"01_BRANDED_SCOPE_REVIEW_INTERNAL.pdf"
    doc=pdfium.PdfDocument(str(f))
    image=doc[0].render(scale=0.7).to_pil().convert("RGB")
    thumb=BASE/(bidder+"_VISUAL_QA_PAGE1.png")
    image.save(thumb,optimize=True)
    print("VISUAL_QA",thumb.name,image.size,thumb.stat().st_size)
res=BASE/"QA_BRANDED_VALIDATION.json"
res.write_text(json.dumps({"pass":len(results)==6,"results":results},indent=2),encoding="utf-8")
for row in results:print(row)
print("ALL_PASS",len(results))
