#!/usr/bin/env python3
"""ALKAN - independently branded internal bid-review packets, no prices or submission.

Requires existing original project dossiers. Never imports commercial costs
from the other bidder. Keeps originals and prior review exports untouched.
"""
from __future__ import annotations
import csv
import json
from datetime import date
from pathlib import Path
import shutil
import sys
import zipfile
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether
import prepare_independent_bid_review as prior

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"ENTREGAS"/"CONTROL_COMPETENCIA_2026-11-06_BRANDED"
BRAND=ROOT/"data"/"brand_assets_2026-11-06"
BIDDERS={
  "S_S_CUSTOM_IRON_WORKS_LLC": {
    "legal_name":"S & S CUSTOM IRON WORKS LLC",
    "ubi":"604724501","license":"SSCUSSC781J9",
    "address":"18526 N High Rock Rd, Monroe, WA 98272",
    "contact":"Shahram Faezi, Partner/Member",
    "phone":"(425) 443-1691","email":"info@ss-ironworks.com",
    "website":"https://www.ss-ironworks.com/",
    "logo":"S_S_CUSTOM_IRON_WORKS_LLC_logo.png",
    "source":"https://www.ss-ironworks.com/",
    "logo_url":"https://static.wixstatic.com/media/7bdc26_0e3313964257401689f6afadda9fbc93~mv2.png",
    "registration_check":"WA L&I registration verified 2026-11-06 per local S&S profile. Recheck before release.",
  },
  "THE_FABRICATOR_LLC": {
    "legal_name":"THE FABRICATOR LLC",
    "ubi":"604345518","license":"FABRIFL811JN",
    "address":"837 NW 49th St, Seattle, WA 98107",
    "contact":"Tirso Alcantar, CEO",
    "phone":"(206) 293-4543","email":"tirsoalca@thefabwelding.com",
    "website":"https://thefabwelding.com/",
    "logo":"THE_FABRICATOR_LLC_logo.png",
    "source":"https://thefabwelding.com/contact",
    "logo_url":"https://img1.wsimg.com/isteam/ip/8301a26b-fbc8-4c35-97cb-b2d8f9d230eb/Logo%20Fabricator3-01.png",
    "registration_check":"L&I URL supplied, not accessed live. Crosschecked through The Fabricator website and licensing listings. Reconfirm before bid release.",
  }
}
PROJECTS=prior.PROJECTS

def p(text,style):
    return Paragraph(escape(str(text)),style)

def mk_pdf(path, bid, meta, project, scope):
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="IdentitySmall",parent=styles["BodyText"],
                              fontName="Helvetica",fontSize=8.2,leading=11,spaceAfter=1))
    styles.add(ParagraphStyle(name="ScopeSmall",parent=styles["BodyText"],
                              fontName="Helvetica",fontSize=7.1,leading=9.5))
    styles.add(ParagraphStyle(name="ScopeHead",parent=styles["BodyText"],
                              fontName="Helvetica-Bold",fontSize=7.4,leading=9.7))
    styles.add(ParagraphStyle(name="DraftCaution",parent=styles["BodyText"],
                              fontName="Helvetica-Bold",fontSize=11,leading=14,
                              textColor=colors.HexColor("#A12C2C"),spaceBefore=5,spaceAfter=7))
    styles.add(ParagraphStyle(name="CompanyName",parent=styles["Heading2"],
                              fontName="Helvetica-Bold",fontSize=13,leading=16,textColor=colors.HexColor("#263445")))
    logo_path=BRAND/meta["logo"]
    assert logo_path.exists(),f"Missing real company logo: {logo_path}"
    with PILImage.open(logo_path) as im:
        im.verify()
    with PILImage.open(logo_path) as im:
        w,h=im.size
    w2=125.0;h2=w2*h/w
    if h2>100: h2=100.0;w2=h2*w/h
    logo=Image(str(logo_path),width=w2,height=h2)
    ident=[
        p(meta["legal_name"],styles["CompanyName"]),
        p(f'WA UBI {meta["ubi"]}   |   Contractor Reg. {meta["license"]}',styles["IdentitySmall"]),
        p(meta["address"],styles["IdentitySmall"]),
        p(f'Contact: {meta["contact"]}',styles["IdentitySmall"]),
        p(f'Phone: {meta["phone"]}   |   {meta["email"]}',styles["IdentitySmall"]),
        p(meta["website"],styles["IdentitySmall"]),
    ]
    brandtable=Table([[logo,ident]],colWidths=[130,410],hAlign="LEFT")
    brandtable.setStyle(TableStyle([
       ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
       ("LEFTPADDING",(0,0),(-1,-1),0),
       ("RIGHTPADDING",(0,0),(0,0),8),
       ("LINEBELOW",(0,0),(-1,-1),1.2,colors.HexColor("#253B53")),
       ("BOTTOMPADDING",(0,0),(-1,-1),10)
    ]))
    story=[brandtable,Spacer(1,12),
           p("DRAFT - INTERNAL BID REVIEW - NOT FOR SUBMISSION",styles["DraftCaution"]),
           p("Metal Fabrications Only | Project Scope & Pricing Readiness",styles["Heading2"]),
           p("Project: "+project["name"],styles["BodyText"]),
           p("Procurement: "+str(project.get("procurement_no") or "NOT CONFIRMED"),styles["BodyText"]),
           p("Owner from project dossier: "+str(project.get("owner") or "NOT CONFIRMED"),styles["BodyText"]),
           p("Document date: "+date.today().isoformat(),styles["BodyText"]),
           Spacer(1,9),
           p("Company license and insurance: recheck official WA L&I records before any bid release.",styles["ScopeSmall"]),
           p("Scope below is an automated metal-screened selection from the shared project dossier. "
             "Scope lines, packages, measurements, installation assumptions and addenda require manual review.",
             styles["ScopeSmall"]),
           Spacer(1,10),
           p("1. Preliminary metal scope - quantity review",styles["Heading2"])]
    headers=["ID","Project item","Qty","Review needed"]
    rows=[[p(v,styles["ScopeHead"]) for v in headers]]
    for it in scope["metal_items"]:
        ref=str(it.get("id") or "")
        descr=str(it.get("item") or "")
        quantity=(str(it["quantity"]) if it["measured"] else "TBD")+" "+str(it.get("unit") or "")
        need="CHECK TRADE LIMITS"
        if not it["measured"]: need="MEASURE / SPLIT"
        if ref.startswith("P-Q-"): need="SPLIT MIXED LS SCOPE"
        if ("alt" in descr.lower() or "alt" in str(it.get("pricing_scope") or "").lower()):
            need+="; ALT - SEPARATE"
        rows.append([p(ref,styles["ScopeSmall"]),p(descr,styles["ScopeSmall"]),
                     p(quantity,styles["ScopeSmall"]),p(need,styles["ScopeSmall"])])
    tab=Table(rows,colWidths=[65,267,61,147],repeatRows=1,hAlign="LEFT")
    tab.setStyle(TableStyle([
       ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#E2EDF7")),
       ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#F7FAFC")]),
       ("GRID",(0,0),(-1,-1),0.3,colors.HexColor("#C8D0D8")),
       ("VALIGN",(0,0),(-1,-1),"TOP"),
       ("TOPPADDING",(0,0),(-1,-1),4),
       ("BOTTOMPADDING",(0,0),(-1,-1),4),
    ]))
    story.extend([tab,Spacer(1,9),
        p(f"Metal-screened lines: {scope['count_identified']} | with documentary quantity: {scope['count_measured']} | requiring measurement: {scope['count_pending_measurement']}",
          styles["BodyText"]),
        p("2. Required inputs before creating the commercial estimate",styles["Heading2"])])
    for n,need in enumerate(prior.REQUIRED,1):
        story.append(p(f"[  ] {n}. {need}",styles["ScopeSmall"]))
    story.extend([
      Spacer(1,7),p("3. Bidder-specific confidentiality and approvals",styles["Heading2"]),
      p("Use this contractor's own quotes, costs, production rates, labor rates and margin decisions only. "
        "Do not move confidential numbers or intended bid amounts between competing bidders.",styles["ScopeSmall"]),
      Spacer(1,8),p("STATUS: INTERNAL_BLOCKED / NO APPROVED BID AMOUNT",styles["DraftCaution"]),
    ])
    doc=SimpleDocTemplate(str(path),pagesize=letter,leftMargin=36,rightMargin=36,
                          topMargin=32,bottomMargin=35,title=f"{meta['legal_name']} - {project['name']} - INTERNAL REVIEW",
                          author="ALKAN Systems - Internal review only")
    doc.build(story)

def main():
    if OUT.exists():raise RuntimeError(f"Refusing to overwrite: {OUT}")
    for key,meta in BIDDERS.items():
        bidder_dir=OUT/key
        bidder_dir.mkdir(parents=True,exist_ok=False)
        asset_dir=bidder_dir/"assets"
        asset_dir.mkdir()
        shutil.copy2(BRAND/meta["logo"],asset_dir/"official_site_logo.png")
        (bidder_dir/"IDENTITY_PROVENANCE.json").write_text(json.dumps({
          "legal_name":meta["legal_name"],"ubi":meta["ubi"],"license":meta["license"],
          "contact":meta["contact"],"phone":meta["phone"],"email":meta["email"],
          "address":meta["address"],"website":meta["website"],
          "logo_url":meta["logo_url"],"company_source":meta["source"],
          "registration_check":meta["registration_check"],
          "bid_authorized":False,"branding_review_required":True,
        },indent=2),encoding="utf-8")
        for slug in PROJECTS:
            project=prior.read_json(ROOT/"projects"/slug/"project.json")
            scope=prior.metal_scope(prior.read_json(ROOT/"projects"/slug/"analysis.json"))
            dest=bidder_dir/slug
            dest.mkdir()
            mk_pdf(dest/"01_BRANDED_SCOPE_REVIEW_INTERNAL.pdf",key,meta,project,scope)
            prior.make_csv(dest/"02_OWN_COST_INPUT_BLANK.csv",scope)
            (dest/"03_REVIEW_STATUS.json").write_text(json.dumps({
               "bidder_legal_name":meta["legal_name"],
               "ubi":meta["ubi"],"contractor_registration":meta["license"],
               "project":project["name"],"metal_items":scope["count_identified"],
               "measured":scope["count_measured"],"unmeasured":scope["count_pending_measurement"],
               "brand_logo_embedded":True,"bid_authorized":False,"pricing_ready":False,
               "status":"INTERNAL_BLOCKED","document_type":"INTERNAL_DRAFT",
               "registration_must_be_rechecked":True,
            },indent=2),encoding="utf-8")
        dst=OUT/(key+"_BRANDED_INTERNAL_REVIEW_ONLY.zip")
        with zipfile.ZipFile(dst,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
            for file in sorted(bidder_dir.rglob("*")):
                if file.is_file():z.write(file,file.relative_to(OUT))
    (OUT/"README_LEEME.txt").write_text(
      "ALKAN 2026-11-06 BRANDED INTERNAL BID REVIEW\n"
      "S&S and The Fabricator LLC have separate branded PDFs, cost-input templates and ZIPs.\n"
      "Logos were downloaded from each company's official website; identity and source links are in IDENTITY_PROVENANCE.json.\n"
      "The Fabricator UBI 604345518 / license FABRIFL811JN: supplied by user and corroborated by public listings; official L&I live lookup could not be fetched, so reconfirm status.\n"
      "No prices are populated, no amount is authorized, nothing has been emailed or submitted.\n"
      "Do not cross-share pricing or bid intentions between these competing contractors.\n"
      "Older original dossiers and previous review drafts remain untouched.\n",
      encoding="utf-8")
    for file in sorted(OUT.rglob("*")):
        if file.is_file():print(file.relative_to(ROOT),file.stat().st_size)
if __name__=="__main__":
    main()
