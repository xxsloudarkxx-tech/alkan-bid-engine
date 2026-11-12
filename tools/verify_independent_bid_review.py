#!/usr/bin/env python3
"""QA for independent internal bid-review packs; re-renders Tirzo PDFs without competitor refs."""
import csv
import json
from pathlib import Path
from pypdf import PdfReader
import prepare_independent_bid_review as x

def main():
    folder = x.OUTPUT
    results = []
    for slug in x.PROJECTS:
        project = x.read_json(x.ROOT/"projects"/slug/"project.json")
        scope = x.metal_scope(x.read_json(x.ROOT/"projects"/slug/"analysis.json"))
        tirzo_path = folder/"TIRZO_IDENTIDAD_PENDIENTE"/slug/"01_SCOPE_READINESS_INTERNAL_DRAFT.pdf"
        x.make_pdf(tirzo_path,x.BIDDERS["TIRZO_IDENTIDAD_PENDIENTE"],project,scope,True)
        for bidder in x.BIDDERS:
            d = folder/bidder/slug
            pdf = d/"01_SCOPE_READINESS_INTERNAL_DRAFT.pdf"
            data = d/"02_BIDDER_OWN_PRICING_INPUT_BLANK.csv"
            status = json.loads((d/"03_REVIEW_STATUS.json").read_text(encoding="utf-8"))
            assert pdf.exists() and data.exists()
            reader=PdfReader(str(pdf))
            content="\n".join((p.extract_text() or "") for p in reader.pages)
            assert len(reader.pages)>0 and "NOT FOR SUBMISSION" in content
            assert "INTERNAL_BLOCKED" in content
            assert status["bid_authorized"] is False and status["pricing_ready"] is False
            assert status["metal_lines"] == scope["count_identified"]
            if bidder=="TIRZO_IDENTIDAD_PENDIENTE":
                assert "S & S" not in content and "S&S" not in content
                assert "THE FABRICATOR" not in content.upper()
                assert "LEGAL BIDDER IDENTITY UNCONFIRMED" in content
            else:
                assert "S & S CUSTOM IRON WORKS" in content
                assert "TIRZO" not in content.upper()
            with data.open(encoding="utf-8-sig",newline="") as f:
                rows=list(csv.DictReader(f))
            assert len(rows)==scope["count_identified"]
            assert all(not r["bidder_unit_price_usd"] for r in rows)
            assert all(not r["labor_hours"] for r in rows)
            assert all(not r["bidder_supplier"] for r in rows)
            results.append({"bidder":bidder,"project":slug,"pdf_pages":len(reader.pages),
                            "metal_rows":len(rows),"no_prices_entered":True,
                            "no_cross_bidding_identity":True})
    out=folder/"QA_VALIDATION.json"
    out.write_text(json.dumps({"status":"PASSED","documents":results},indent=2),encoding="utf-8")
    print("QA PASSED:",len(results),"PDFs,",sum(r["metal_rows"] for r in results),"scope-row templates")
    for r in results:print(r)
if __name__=="__main__":
    main()
