"""V2.1: real parsers and persistence, anonymous documents and supplier numbers."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
import json
import unittest
from unittest.mock import patch

from openpyxl import Workbook
from reportlab.pdfgen import canvas

import test_intelligence_v2 as v2
from bidkit.intelligence_documents import parse_document
from bidkit.intelligence_reports import export_document
from bidkit.price_catalog import FIELDS
from bidkit.data_store import fingerprint


def cedar_pdf():
    """Equivalent anonymous seven-page proposal; segment lengths are synthetic."""
    pages=["Anonymous commercial proposal. March 7, 2026\nDemolition: 415 LF", "Hog wire fence: 62 LF",
           "Cedar fence sections: 66 + 48 + 126 + 112 + 112 LF", "Double gate: 1 EA\nSingle gates: 2 EA",
           "Gravel area: 936 SF\nGravel volume: 9 CY", "Combined new fence: 526 LF",
           "Subtotal: $31,718\nTax: $3,010\nTotal: $34,728"]
    stream=BytesIO(); pdf=canvas.Canvas(stream,invariant=1)
    for text in pages:
        for i,line in enumerate(text.splitlines()):pdf.drawString(40,750-20*i,line)
        pdf.showPage()
    pdf.save();return stream.getvalue()


def csv_bytes(price="100"):
    return ("product_name,supplier,location,unit,unit_price,pack_size,specification,currency,delivery,tax_total,discount_percent,quoted_on,valid_until,kind\n"
            f"Synthetic panels,Synthetic supplier,Branch,EA,{price},100,S1,USD,25,0,0,{v2.TODAY},{v2.EXPIRY},FORMAL_QUOTE\n").encode()


class TestV21(unittest.TestCase):
    setUp=v2.IntelligenceTests.setUp
    tearDown=v2.IntelligenceTests.tearDown
    act=v2.IntelligenceTests.act
    upload=v2.IntelligenceTests.upload
    evidence=v2.IntelligenceTests.evidence
    ready=v2.IntelligenceTests.ready

    def test_seven_page_cedar_scopes_and_commercial_amounts(self):
        self.row=self.service.upload(self.pid,self.row["revision"],"Reviewer",[("anonymous_proposal.pdf",cedar_pdf())])
        self.act("analyze");state=self.row["state"]
        quantities={r["scope_key"]:r["quantity"] for r in state["lines"]}
        self.assertEqual(quantities["demolition_length"],"415")
        self.assertEqual(quantities["fence_cedar_length"],"464")
        self.assertEqual(quantities["fence_hog_wire_length"],"62")
        self.assertEqual(quantities["gravel_volume"],"9")
        self.assertEqual(quantities["gravel_area"],"936")
        self.assertFalse(next(r for r in state["lines"] if r["scope_key"]=="fence_combined_check")["active"])
        self.assertFalse(any(i["kind"]=="QUANTITY_CONTRADICTION" for i in state["result"]["issues"]))
        self.assertEqual([f["value"] for f in state["document_facts"] if f["data_type"].startswith("commercial_")],["31718","3010","34728"])
        self.assertTrue(all(r["quantity_status"]!="CONFIRMED_WITH_EVIDENCE" for r in state["lines"]))
        self.assertTrue(all(r["document_date"]=="2026-03-07" for r in state["lines"]))
        self.assertIsNone(state["result"]["totals"]["estimated_all_in_cost"])

    def test_csv_xlsx_imports_with_row_evidence_and_no_automatic_confirmation(self):
        for name,raw in (("prices.csv",csv_bytes()),("prices.xlsx",self.xlsx())):
            self.row=self.service.upload(self.pid,self.row["revision"],"Reviewer",[(name,raw)])
            doc=self.row["state"]["documents"][-1]
            self.act("catalog_import",{"document_id":doc["document_id"]})
            entry=self.row["state"]["catalog_entries"][-1]
            self.assertEqual(entry["evidence_reference"]["row"],2)
            self.assertFalse(entry["confirmed"])
        self.assertEqual(len(self.service.catalog("Synthetic")),2)
        self.act("catalog_import",{"document_id":doc["document_id"]})
        self.assertEqual(len(self.row["state"]["catalog_entries"]),2)

    def xlsx(self,formula=False):
        book=Workbook();sheet=book.active
        sheet.append(["product_name","supplier","unit","unit_price"])
        sheet.append(["Synthetic bolt","Supplier","EA","=1+2" if formula else "3.50"])
        stream=BytesIO();book.save(stream);book.close();return stream.getvalue()

    def test_reject_spreadsheet_formulas_and_bad_price(self):
        with self.assertRaises(ValueError):parse_document("bad.xlsx",self.xlsx(True))
        self.row=self.service.upload(self.pid,self.row["revision"],"Reviewer",[("bad.csv",csv_bytes("NaN"))])
        with self.assertRaises(ValueError):self.act("catalog_import",{"document_id":self.row["state"]["documents"][-1]["document_id"]})

    def test_duplicate_scope_and_incompatible_units(self):
        self.ready();line=deepcopy(self.row["state"]["lines"][0]);line["scope_key"]="panels";self.act("line",line)
        second={**line,"line_id":None};self.act("line",second)
        self.assertTrue(any(i["kind"]=="POSSIBLE_DUPLICATE_QUANTITY" for i in self.row["state"]["result"]["issues"]))
        second=self.row["state"]["lines"][-1];self.act("line",{**second,"unit":"SF"})
        self.assertTrue(any(i["kind"]=="INCOMPATIBLE_SCOPE_UNITS" for i in self.row["state"]["result"]["issues"]))

    def test_phone_without_document_is_provisional(self):
        self.ready();q=deepcopy(self.row["state"]["quotes"][0]);q.update(kind="PHONE_QUOTE",evidence_reference=None)
        self.act("quote",q);new=self.row["state"]["quotes"][-1]
        self.assertFalse(new["confirmed"]);self.assertEqual(new["evidence_status"],"UNDOCUMENTED_PHONE_RECORD")
        with self.assertRaises(ValueError):self.act("select_quote",{"line_id":q["line_id"],"quote_id":new["quote_id"]})

    def test_sensitivity_excludes_delivery_and_tax_and_financial_regression(self):
        self.ready();result=self.row["state"]["result"]
        self.assertEqual(result["price_stress"]["material_plus_5%"]["additional_material_cost"],"50.00")
        self.assertEqual(result["totals"]["proposed_price_before_contract_specific_taxes"],"1959.38")

    def test_shared_quote_allocates_delivery_once(self):
        self.ready();line=deepcopy(self.row["state"]["lines"][0]);line["line_id"]=None;self.act("line",line)
        ids=[r["line_id"] for r in self.row["state"]["lines"] if r["category"]=="material"]
        q=deepcopy(self.row["state"]["quotes"][0]);q["delivery"]="30"
        self.act("quote_batch",{"line_ids":ids,"quote":q,"allocations":{i:{"delivery":"15","tax_total":"0"} for i in ids}})
        group=self.row["state"]["quotes"][-2:]
        self.assertEqual(sum(Decimal(q["delivery"]) for q in group),Decimal(30))
        self.assertEqual(group[0]["quote_group_id"],group[1]["quote_group_id"])
        with self.assertRaises(ValueError):self.act("quote_batch",{"line_ids":ids,"quote":q,"allocations":{i:{"delivery":"30","tax_total":"0"} for i in ids}})

    def test_catalog_reuse_requires_target_review_and_preserves_source(self):
        self.ready();source=self.row
        entry=self.service.catalog("Synthetic rate")[0]
        target=self.service.create({"name":"Other synthetic job","work_type":"residential","contractual_relationship":"direct_homeowner"},"Reviewer")
        doc=source["state"]["documents"][0]
        original=(self.service.store.directory(self.pid)/"originals"/doc["stored_name"]).read_bytes()
        target=self.service.upload(target["project_id"],target["revision"],"Reviewer",[(doc["original_name"],original)])
        line=deepcopy(source["state"]["lines"][0]);line["line_id"]=None
        target=self.service.transact(target["project_id"],target["revision"],"Reviewer","line",line)
        result=self.service.attach_catalog(target["project_id"],target["revision"],"Reviewer",{**entry,"line_id":target["state"]["lines"][0]["line_id"]})
        self.assertFalse(result["state"]["quotes"][0]["confirmed"])
        self.assertEqual(self.service.store.load(self.pid),source)

    def test_package_minimum_and_freight_comparison(self):
        self.ready();q=deepcopy(self.row["state"]["quotes"][0])
        q.update(unit_price="500",pack_size="6",whole_packs=True,delivery="0",minimum_quantity="0")
        self.act("quote",q);r=self.row["state"]["result"]["comparisons"][q["line_id"]][-1]
        self.assertEqual(r["packs"],"2");self.assertEqual(r["effective_total"],"1000.00")
        self.assertEqual(r["difference_vs_selected"],"-25.00")
        q["minimum_quantity"]="20";self.act("quote",q)
        self.assertIn("MINIMUM_QUANTITY_NOT_MET",self.row["state"]["result"]["comparisons"][q["line_id"]][-1]["issues"])

    def test_compatible_conversion_and_formula_disagreement(self):
        self.ready();line=deepcopy(self.row["state"]["lines"][0]);line.update(quantity="10",unit="FT",scope_key="same_length")
        self.act("line",line);self.act("line",{**line,"line_id":None,"quantity":"120","unit":"IN"})
        kinds={i["kind"] for i in self.row["state"]["result"]["issues"]}
        self.assertIn("POSSIBLE_DUPLICATE_QUANTITY",kinds);self.assertNotIn("QUANTITY_CONTRADICTION",kinds)
        last=self.row["state"]["lines"][-1]
        self.act("line",{**last,"calculation":{"operation":"product","operands":["10","10"]}})
        self.assertIn("QUANTITY_FORMULA_MISMATCH:"+last["line_id"],self.row["state"]["result"]["release_blockers"])

    def test_actual_cost_evidence_correction_and_fixed_baseline(self):
        self.ready();doc=self.upload("paid_expense.txt","Anonymous paid expense record SYNTHETIC-001: 1700 USD. Corrected amount 1680 USD; additional material purchased.");baseline=self.row["revision"]
        cost={"category":"material","amount":"1700","incurred_on":v2.TODAY,"invoice_reference":"SYNTHETIC-001",
              "provider":"Synthetic supplier","cause":"unconfirmed","evidence_reference":{"document_id":doc["document_id"],"page":1,"excerpt":doc["pages"][0]["text"]},"evidence_type":"expense_record","human_confirmation":True}
        self.act("actual_cost",cost);prior=self.row["state"]["actual_costs"][0]
        actual=self.row["state"]["result"]["actual_vs_estimated"]
        self.assertEqual(actual["estimated_cost"],"1567.50");self.assertEqual(actual["variance"],"132.50")
        self.assertEqual(actual["baseline_revision"],baseline);self.assertFalse(actual["automatic_blame"])
        with self.assertRaises(ValueError):self.act("actual_cost",cost)
        with self.assertRaises(ValueError):self.act("actual_cost",{**cost,"evidence_reference":None})
        with self.assertRaises(ValueError):self.act("actual_cost",{**cost,"cause":"waste","invoice_reference":"new"})
        self.act("actual_cost",{**cost,"supersedes":prior["actual_id"],"amount":"1680","cause":"additional_material","cause_notes":"Synthetic documented extra purchase"})
        self.assertEqual(len(self.row["state"]["actual_costs"]),2)
        self.assertEqual(self.row["state"]["result"]["actual_vs_estimated"]["actual_documented_cost"],"1680.00")
        self.act("settings",{"financial":{"overhead_percent":"20"}})
        self.assertEqual(self.row["state"]["result"]["actual_vs_estimated"]["estimated_cost"],"1567.50")
        self.assertEqual(self.service.actual_analysis("Construction","residential","Synthetic")[0]["cause"],"additional_material")
        self.assertEqual(self.service.actual_analysis(work_type="industrial"),[])

    def test_quote_three_days_later_preserves_approved_files(self):
        self.ready();old=deepcopy(self.row["state"]["quotes"][0]);old.update(supersedes=old["quote_id"],quoted_on=(date.today()-timedelta(days=3)).isoformat())
        self.act("quote",old);old=deepcopy(self.row["state"]["quotes"][-1]);self.act("select_quote",{"line_id":old["line_id"],"quote_id":old["quote_id"]})
        self.act("approve",{"human_confirmation":True});approved=self.row
        file=export_document(self.service,self.pid,"proposal");raw=file.read_bytes()
        q=deepcopy(old);q.update(supersedes=q["quote_id"],unit_price="105",quoted_on=v2.TODAY)
        self.act("quote",q)
        self.assertEqual((date.fromisoformat(q["quoted_on"])-date.fromisoformat(old["quoted_on"])).days,3)
        self.assertEqual(file.read_bytes(),raw);self.assertEqual(self.row["state"]["approvals"][0]["approved_price"],"1959.38")
        self.assertIsNone(self.row["state"]["current_approval"])
        self.assertEqual(self.row["state"]["result"]["price_update_impacts"][-1]["line_cost_delta"],"50.00")
        with self.assertRaises(ValueError):export_document(self.service,self.pid,"proposal")

    def test_atomic_failure_leaves_readable_history(self):
        self.ready();before=self.service.store.load(self.pid)
        with patch("bidkit.intelligence_store.os.link",side_effect=OSError("Synthetic disk failure")):
            with self.assertRaises(OSError):self.act("settings",{"project":{"next_action":"Never committed"}})
        self.assertEqual(self.service.store.load(self.pid),before)
        self.assertFalse(list(self.service.store.child(self.pid,"revisions").glob("*.staged")))
        self.assertFalse((self.service.store.directory(self.pid)/".write-lock").exists())
        with self.assertRaises(ValueError):self.service.store.child(self.pid,"originals","../../../../outside")

    def test_missing_tax_and_expired_quote_block_approval(self):
        self.ready();self.act("settings",{"review":{"tax_reviewed":False,"tax_basis":""}})
        self.assertIn("CONTRACT_JURISDICTION_TAX_REVIEW_PENDING",self.row["state"]["result"]["release_blockers"])
        q=deepcopy(self.row["state"]["quotes"][0]);q.update(quoted_on="2020-01-01",valid_until="2020-01-02")
        self.act("quote",q)
        self.assertIn("QUOTE_EXPIRED_OR_FUTURE",self.row["state"]["result"]["comparisons"][q["line_id"]][-1]["issues"])

    def test_minimal_catalog_can_be_reused_as_incomplete_quote(self):
        self.ready();self.row=self.service.upload(self.pid,self.row["revision"],"Reviewer",[("minimal.xlsx",self.xlsx())])
        self.act("catalog_import",{"document_id":self.row["state"]["documents"][-1]["document_id"]})
        record=next(r for r in self.service.catalog() if r["source_type"]=="catalog_entries")
        self.row=self.service.attach_catalog(self.pid,self.row["revision"],"Reviewer",{**record,"line_id":self.row["state"]["lines"][0]["line_id"]})
        q=self.row["state"]["quotes"][-1]
        self.assertIsNone(q["location"]);self.assertIsNone(q["quoted_on"])
        self.assertFalse(self.row["state"]["result"]["comparisons"][q["line_id"]][-1]["eligible"])

    def test_export_tamper_is_rejected_and_not_overwritten(self):
        self.ready();self.act("approve",{"human_confirmation":True})
        file=export_document(self.service,self.pid,"proposal");file.write_bytes(b"Synthetic corruption")
        with self.assertRaises(ValueError):export_document(self.service,self.pid,"proposal")
        self.assertEqual(file.read_bytes(),b"Synthetic corruption")

    def test_reopen_service_recovers_catalog_costs_and_revisions(self):
        self.ready();self.row=self.service.upload(self.pid,self.row["revision"],"Reviewer",[("prices.csv",csv_bytes())])
        self.act("catalog_import",{"document_id":self.row["state"]["documents"][-1]["document_id"]})
        reopened=v2.Intelligence(self.root)
        self.assertEqual(reopened.store.load(self.pid),self.row)
        self.assertEqual(reopened.catalog(),self.service.catalog())
        self.assertEqual(reopened.evaluate(self.row["state"]),self.service.evaluate(self.row["state"]))

    def test_v2_candidate_identity_does_not_duplicate_reviewed_quantities(self):
        self.upload(text="Fence demolition 10 feet");self.act("analyze")
        line=deepcopy(self.row["state"]["lines"][0]);ev=line["evidence_reference"]
        legacy={"description":"Fence demolition 10 feet","quantity":"10","unit":"LF","quantity_status":"AUTO_EXTRACTED",
                "scope_key":"fence_length","evidence":{k:ev[k] for k in ("document_id","page","excerpt")}}
        self.act("line",{**line,"candidate_id":fingerprint(legacy)[:20],"quantity":"11","quantity_status":"MANUALLY_CORRECTED"})
        self.act("analyze")
        self.assertEqual(len(self.row["state"]["lines"]),1)
        self.assertEqual(self.row["state"]["lines"][0]["quantity"],"11")
        self.assertEqual(len(self.row["state"]["mentions"]),1)

    def test_length_total_is_not_interpreted_as_money(self):
        self.upload(text="Fence total: 526 LF\nTotal: 526 LF\nCommercial total: 34728 USD")
        self.act("analyze")
        facts=[f for f in self.row["state"]["document_facts"] if f["data_type"].startswith("commercial_")]
        self.assertEqual([(f["value"],f["unit"]) for f in facts],[("34728","USD")])

    def test_damaged_pdf_and_image_fail_as_validation_errors(self):
        for name,raw in (("damaged.pdf",b"%PDF-1.4\ntruncated"),("damaged.png",b"not an image")):
            with self.subTest(name=name),self.assertRaises(ValueError):parse_document(name,raw)


if __name__=="__main__":unittest.main()
