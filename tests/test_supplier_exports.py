"""V3.1 supplier export center: real dossier state, safe read-only artifacts."""
from copy import deepcopy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from uuid import uuid4
import csv
import io
import json
import unittest

from pypdf import PdfReader

import test_intelligence_v2 as v2
from bidkit.intelligence_ui import make_handler
from bidkit.supplier_exports import comparison_data, directory_data, export_supplier_center, project_data


class SupplierExportTests(unittest.TestCase):
    setUp=v2.IntelligenceTests.setUp
    tearDown=v2.IntelligenceTests.tearDown
    act=v2.IntelligenceTests.act
    upload=v2.IntelligenceTests.upload
    ready=v2.IntelligenceTests.ready
    evidence=v2.IntelligenceTests.evidence

    def make_two_suppliers(self):
        self.ready()
        self.act("supplier",{"name":"Segundo proveedor, S.A.\nSucursal","location":"Seattle, WA"})
        second=self.row["state"]["suppliers"][-1]["supplier_id"]
        line=self.row["state"]["lines"][0]
        self.act("quote",{"line_id":line["line_id"],"supplier_id":second,"kind":"FORMAL_QUOTE","description":"Panel, special\nline",
            "specification":"S1","unit":"EA","unit_price":"101","pack_size":"1","delivery":"10","tax_total":"0","discount_percent":"0","currency":"USD",
            "quoted_on":v2.TODAY,"valid_until":v2.EXPIRY,"confirmed":True,"availability_confirmed":True,"technical_match":True,"evidence_reference":self.evidence()})
        return line["line_id"]

    def test_directory_has_only_registered_records_and_missing_fields_are_explicit(self):
        self.make_two_suppliers();before=deepcopy(self.service.store.load(self.pid));meta,rows=directory_data(self.service,self.pid,"es")
        self.assertEqual(len(rows),2);self.assertEqual(meta["coverage"]["company_specialty_city_fields_available"],False)
        self.assertTrue(all(r["verification_status"]=="No verificado" for r in rows))
        self.assertTrue(all(r["company"]=="No registrado" and r["contact_email"]=="No registrado" for r in rows))
        self.assertEqual(self.service.store.load(self.pid),before)

    def test_project_export_filters_one_dossier_and_reports_unquoted_lines(self):
        line_id=self.make_two_suppliers()
        self.act("line", {"description":"Unquoted synthetic line","trade":"Construction","category":"equipment",
            "quantity":"1","unit":"EA","quantity_status":"PENDING_VERIFICATION","specification":"S1",
            "scope_key":"","evidence_reference":self.evidence()})
        meta,rows=project_data(self.service,self.pid,"en")
        self.assertTrue(rows);self.assertTrue(all(r["project_id"]==self.pid for r in rows));self.assertTrue(any(r["line_id"]!=line_id for r in rows))
        self.assertTrue(any(r["supplier_status"]=="NO_SUPPLIER_REGISTERED" for r in rows))
        other=self.service.create({"name":"Other isolated dossier","work_type":"commercial","contractual_relationship":"direct_homeowner"},"Reviewer")
        other_meta,other_rows=project_data(self.service,other["project_id"],"en")
        self.assertNotEqual(meta["project_id"],other_meta["project_id"]);self.assertNotEqual({r["project_id"] for r in rows},{other["project_id"]})
        self.assertTrue(all(r["supplier_name"]=="No registrado" for r in other_rows))

    def test_comparison_preserves_quote_versions_currency_and_does_not_mix_totals(self):
        line_id=self.make_two_suppliers();line=self.row["state"]["lines"][0];first=deepcopy(self.row["state"]["quotes"][0])
        self.act("quote",{**first,"supersedes":first["quote_id"],"unit_price":"105"})
        meta,rows=comparison_data(self.service,self.pid,"en")
        line_rows=[r for r in rows if r["line_id"]==line_id]
        self.assertGreaterEqual(len(line_rows),2);self.assertIn("SUPERSEDED",{r["version_status"] for r in line_rows});self.assertTrue(meta["coverage"]["currency_totals_not_mixed"])
        self.assertTrue(all(r["currency"]=="USD" for r in rows));self.assertTrue(all(r["effective_total"]!="No registrado" or r["total_status"]!="ELIGIBLE_USD_TOTAL" for r in rows))
        self.assertTrue(any(r["evidence_document"]!="No registrado" for r in rows))

    def test_csv_is_excel_safe_and_pdf_contains_provenance(self):
        self.make_two_suppliers();self.row=self.act("line",{**self.row["state"]["lines"][0],"description":"=HYPERLINK(\"https://invalid\")\nPanel, special"})
        before=deepcopy(self.service.store.load(self.pid));result=export_supplier_center(self.service,self.pid,self.row["revision"],"comparison","es","both")
        self.assertEqual(len(result["artifacts"]),2)
        csv_art=next(a for a in result["artifacts"] if a["format"]=="csv");raw=self.service.store.child(self.pid,"exports",csv_art["name"]).read_bytes();self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        text=raw.decode("utf-8-sig");parsed=list(csv.DictReader(io.StringIO(text)));self.assertTrue(any(v.startswith("'") for row in parsed for v in row.values() if v))
        pdf_art=next(a for a in result["artifacts"] if a["format"]=="pdf");pdftext="\n".join(p.extract_text() for p in PdfReader(self.service.store.child(self.pid,"exports",pdf_art["name"])).pages)
        self.assertIn("Comparativo interno",pdftext);self.assertIn("Segundo proveedor",pdftext);self.assertIn("evidencia",pdftext.lower());self.assertNotIn("target_margin",pdftext.lower())
        self.assertEqual(self.service.store.load(self.pid),before)

    def test_repeating_export_is_idempotent_and_legacy_project_has_no_directory(self):
        self.make_two_suppliers();before=deepcopy(self.service.store.load(self.pid));first=export_supplier_center(self.service,self.pid,self.row["revision"],"directory","en","both");after=deepcopy(self.service.store.load(self.pid));second=export_supplier_center(self.service,self.pid,self.row["revision"],"directory","en","both")
        self.assertEqual(before,after);self.assertEqual(first,second)
        legacy=Path(__file__).resolve().parents[1]
        with self.assertRaises(FileNotFoundError):directory_data(__import__('bidkit.intelligence',fromlist=['Intelligence']).Intelligence(legacy),"gonyea-playfield","en")

    def test_http_download_content_and_access_validation(self):
        self.make_two_suppliers()
        with TemporaryDirectory() as tmp:
            service_root=Path(tmp);from bidkit.intelligence import Intelligence;service=Intelligence(service_root);row=service.create({"name":"HTTP export dossier","work_type":"residential","contractual_relationship":"direct_homeowner"},"Reviewer")
            server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(service_root));thread=Thread(target=server.serve_forever,daemon=True);thread.start();token=""
            def request(method,path,data=None,valid=True):
                c=HTTPConnection("127.0.0.1",server.server_port,timeout=10);c.request(method,path,json.dumps(data) if data else None,{"Content-Type":"application/json","X-ALKAN-Token":token if valid else "wrong"});r=c.getresponse();raw=r.read();ctype=r.getheader("Content-Type","");c.close();return r.status,raw,ctype
            try:
                token=json.loads(request("GET","/api/session")[1])["token"]
                req={"actor":"Reviewer","project_id":row["project_id"],"revision":row["revision"],"kind":"directory","language":"en","formats":"both"}
                status,raw,_=request("POST","/api/supplier-export",req,False);self.assertEqual(status,403)
                status,raw,_=request("POST","/api/supplier-export",req);self.assertEqual(status,200);body=json.loads(raw);self.assertEqual(body["row_count"],1)
                for artifact in body["artifacts"]:
                    status,data,ctype=request("GET",artifact["url"]);self.assertEqual(status,200);self.assertEqual(ctype,"text/csv; charset=utf-8" if artifact["format"]=="csv" else "application/pdf");self.assertEqual(data[:3],b"\xef\xbb\xbf" if artifact["format"]=="csv" else b"%PD")
                self.assertEqual(request("GET",f"/api/supplier-export-file?project_id={row['project_id']}&name=..%2F..%2Fsecret.csv")[0],400)
            finally:server.shutdown();server.server_close();thread.join()


if __name__=="__main__":unittest.main()
