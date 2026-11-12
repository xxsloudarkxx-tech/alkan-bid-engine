"""V3 end-to-end service coordination; real parsers, store and PDF generators."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import unittest
import base64
import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from tempfile import TemporaryDirectory
from threading import Thread

from pypdf import PdfReader
from bidkit.estimate_workflow import EstimateWorkflow
from bidkit.intelligence_store import RevisionConflict
from bidkit.intelligence_ui import make_handler
import test_intelligence_v2 as v2


class WorkflowTests(unittest.TestCase):
    setUp=v2.IntelligenceTests.setUp
    tearDown=v2.IntelligenceTests.tearDown
    act=v2.IntelligenceTests.act
    ready=v2.IntelligenceTests.ready
    upload=v2.IntelligenceTests.upload
    evidence=v2.IntelligenceTests.evidence

    def wf(self):return EstimateWorkflow(self.root,self.service)

    def run_action(self,action,payload=None,key=None):
        self.row=self.wf().execute(self.pid,self.row["revision"],"Reviewer",action,payload or {},key or str(uuid4()))
        return self.row

    def test_create_multiple_uploads_analysis_and_retry_after_restart(self):
        flow=self.wf();project={"name":"Anonymous V3","work_type":"residential","contractual_relationship":"general_contractor"}
        key=str(uuid4());row=flow.create(project,"Reviewer",key)
        self.assertEqual(flow.create(project,"Reviewer",key)["project_id"],row["project_id"])
        with self.assertRaises(ValueError):flow.create({**project,"name":"Other"},"Reviewer",key)
        self.pid=row["project_id"];uploadkey=str(uuid4())
        files=[("scope.pdf",v2.pdf_bytes("Scope of work: 10 EA panels. Specification S1.")),("labor.txt",b"8 HR installation. Specification L1.")]
        self.row=flow.upload(self.pid,row["revision"],"Reviewer",files,uploadkey)
        same=EstimateWorkflow(self.root).upload(self.pid,row["revision"],"Reviewer",files,uploadkey)
        self.assertEqual(same["revision"],self.row["revision"]);self.assertEqual(len(same["state"]["documents"]),2)
        self.run_action("analyze");first=self.row
        self.run_action("analyze");self.assertEqual(len(self.row["state"]["lines"]),2)
        self.assertTrue(self.row["workflow_view"]["analyzed"])
        self.run_action("transition",{"step":"quantities"})
        reopened=EstimateWorkflow(self.root).get(self.pid)
        self.assertEqual(reopened["workflow_view"]["current_step"],"quantities")
        self.assertEqual(first["state"]["lines"],reopened["state"]["lines"])

    def test_financial_review_approval_bundle_and_navigation_idempotence(self):
        self.ready();self.run_action("analyze")
        # ready() creates manual lines; analyze also detects candidates. Exclude only with explicit review.
        for line in deepcopy(self.row["state"]["lines"]):
            if line.get("candidate_id"):self.run_action("line",{**line,"active":False})
        for issue in self.row["state"]["result"]["issues"]:
            self.run_action("resolve",{"issue_id":issue["issue_id"],"disposition":"included","reason":"Synthetic reviewed specification and delivery included","evidence_reference":self.evidence()})
        self.run_action("settings",{"review":{"scope_confirmed":True}})
        self.run_action("calculate")
        self.assertEqual(self.row["state"]["result"]["totals"]["proposed_price_before_contract_specific_taxes"],"1959.38")
        key=str(uuid4());oldrev=self.row["revision"];self.run_action("approve",{"human_confirmation":True},key)
        approval=self.row["state"]["current_approval"]
        repeated=self.wf().execute(self.pid,oldrev,"Reviewer","approve",{"human_confirmation":True},key)
        self.assertEqual(repeated["revision"],self.row["revision"])
        self.run_action("approve",{"human_confirmation":True})
        self.assertEqual(len(self.row["state"]["approvals"]),1)
        self.run_action("transition",{"step":"documents"});self.run_action("analyze");self.run_action("calculate")
        self.assertEqual(self.row["state"]["current_approval"],approval)
        exportkey=str(uuid4());revision=self.row["revision"]
        result=self.wf().export(self.pid,revision,"Reviewer",["internal","supplier","proposal"],"en",True,exportkey)
        retry=EstimateWorkflow(self.root).export(self.pid,revision,"Reviewer",["internal","supplier","proposal"],"en",True,exportkey)
        self.assertEqual(result,retry)
        self.assertEqual(len({a["basis"] for a in result["artifacts"]}),1)
        for artifact in result["artifacts"]:
            text="".join(p.extract_text() for p in PdfReader(self.service.store.child(self.pid,"exports",artifact["name"])).pages)
            if artifact["kind"]!="internal":
                for secret in ("target_margin","Synthetic supplier","overhead_percent"):self.assertNotIn(secret,text)

    def test_insufficient_evidence_drafts_and_final_blocks(self):
        self.row=self.wf().upload(self.pid,self.row["revision"],"Reviewer",[("scan.pdf",v2.pdf_bytes(""))],str(uuid4()))
        self.run_action("analyze")
        self.assertEqual(len(self.row["workflow_view"]["manual_review_documents"]),1)
        with self.assertRaises(ValueError):self.run_action("approve",{"human_confirmation":True})
        with self.assertRaises(ValueError):self.wf().export(self.pid,self.row["revision"],"Reviewer",["internal"],"en",True,str(uuid4()))
        result=self.wf().export(self.pid,self.row["revision"],"Reviewer",["internal","supplier"],"en",False,str(uuid4()))
        for artifact in result["artifacts"]:
            text="".join(p.extract_text() for p in PdfReader(self.service.store.child(self.pid,"exports",artifact["name"])).pages)
            self.assertIn("DRAFT",text)

    def test_quantity_corrections_quotes_and_prior_versions_survive(self):
        self.ready();self.run_action("analyze")
        line=deepcopy(self.row["state"]["lines"][-1]);self.run_action("line",{**line,"quantity":"9","quantity_status":"MANUALLY_CORRECTED"})
        self.run_action("analyze");self.assertEqual(self.row["state"]["lines"][-1]["quantity"],"9")
        q=deepcopy(self.row["state"]["quotes"][0]);old=deepcopy(q)
        self.run_action("quote",{**q,"supersedes":q["quote_id"],"unit_price":"105"})
        self.assertEqual(self.row["state"]["quotes"][0],old)
        self.assertEqual(self.row["state"]["result"]["price_update_impacts"][-1]["line_cost_delta"],"50.00")

    def test_request_collision_conflict_and_transition_preconditions(self):
        with self.assertRaises(ValueError):self.run_action("transition",{"step":"analysis"})
        key=str(uuid4());self.run_action("transition",{"step":"documents"},key)
        with self.assertRaises(ValueError):self.run_action("transition",{"step":"approval"},key)
        with self.assertRaises(RevisionConflict):self.wf().execute(self.pid,1,"Reviewer","calculate",{},str(uuid4()))
        self.upload();self.run_action("analyze");self.run_action("transition",{"step":"costs"})
        self.upload("new.txt","Scope changed: 11 EA panels.")
        with self.assertRaises(ValueError):self.run_action("transition",{"step":"quantities"})

    def test_quote_selection_preserves_scope_reconciliation_but_quantity_change_invalidates(self):
        self.ready();self.run_action("analyze")
        for issue in self.row["state"]["result"]["issues"]:
            self.run_action("resolve",{"issue_id":issue["issue_id"],"disposition":"included","reason":"Synthetic scope confirmed","evidence_reference":self.evidence()})
        q=deepcopy(self.row["state"]["quotes"][0]);self.run_action("quote",{**q,"supersedes":q["quote_id"],"unit_price":"105"})
        new=self.row["state"]["quotes"][-1];self.run_action("select_quote",{"line_id":new["line_id"],"quote_id":new["quote_id"]})
        self.assertTrue(all(i["resolved"] for i in self.row["state"]["result"]["issues"]))
        line=self.row["state"]["lines"][0];self.run_action("line",{**line,"quantity":"11"})
        self.assertTrue(any(not i["resolved"] for i in self.row["state"]["result"]["issues"]))

    def test_catalog_reference_retries_do_not_duplicate_and_current_basis_exports_only(self):
        self.ready();source=self.service.catalog()[0]
        payload={**source,"line_id":self.row["state"]["lines"][0]["line_id"]};key=str(uuid4());revision=self.row["revision"]
        self.row=self.wf().attach_catalog(self.pid,revision,"Reviewer",payload,key)
        count=len(self.row["state"]["quotes"])
        retry=self.wf().attach_catalog(self.pid,revision,"Reviewer",payload,key)
        self.assertEqual(retry["revision"],self.row["revision"])
        self.row=self.wf().attach_catalog(self.pid,self.row["revision"],"Reviewer",payload,str(uuid4()))
        self.assertEqual(len(self.row["state"]["quotes"]),count)
        exportkey=str(uuid4());exported=self.wf().export(self.pid,self.row["revision"],"Reviewer",["supplier"],"es",False,exportkey)
        self.row=exported["row"];self.run_action("settings",{"project":{"address":"Changed synthetic location"}})
        with self.assertRaises(RevisionConflict):self.wf().export(self.pid,self.row["revision"],"Reviewer",["supplier"],"es",False,exportkey)

    def test_synthetic_document_to_final_without_manual_engine_shortcuts(self):
        self.row=self.wf().upload(self.pid,self.row["revision"],"Reviewer",[("scope.txt",b"10 EA panels\n8 HR installation\nS1 synthetic dimensions and costs: material 100 each plus 25 freight; labor 50 per hour, zero freight.")],str(uuid4()))
        self.run_action("analyze");doc=self.row["state"]["documents"][0]
        self.run_action("review_document",{"document_id":doc["document_id"],"notes":"Synthetic source and arithmetic reviewed"})
        self.run_action("supplier",{"name":"Anonymous supplier","location":"Synthetic branch"})
        for i,line in enumerate(deepcopy(self.row["state"]["lines"])):
            self.run_action("line",{**line,"category":"material" if i==0 else "labor","specification":"S1","quantity_status":"CONFIRMED_WITH_EVIDENCE"})
            self.run_action("quote",{"line_id":line["line_id"],"supplier_id":self.row["state"]["suppliers"][0]["supplier_id"],"kind":"FORMAL_QUOTE",
                "description":"Synthetic quote","specification":"S1","unit":line["unit"],"unit_price":"100" if i==0 else "50","pack_size":"1","delivery":"25" if i==0 else "0",
                "tax_total":"0","discount_percent":"0","currency":"USD","quoted_on":v2.TODAY,"valid_until":v2.EXPIRY,"confirmed":True,"availability_confirmed":True,"technical_match":True,"evidence_reference":self.evidence()})
            self.run_action("select_quote",{"line_id":line["line_id"],"quote_id":self.row["state"]["quotes"][-1]["quote_id"]})
        self.run_action("settings",{"financial":{"overhead_percent":"10","contingency_percent":"0","target_margin_percent":"20","confirmed":True},
             "review":{"scope_confirmed":True,"tax_reviewed":True,"tax_basis":"Explicit zero synthetic tax, QA only","company_confirmed":True,"terms":"Synthetic terms","assumptions":"Synthetic scope","exclusions":"Unlisted work","valid_until":v2.EXPIRY}})
        self.run_action("calculate");self.assertEqual(self.row["state"]["result"]["totals"]["proposed_price_before_contract_specific_taxes"],"1959.38")
        with self.assertRaises(ValueError):self.run_action("approve",{"human_confirmation":False})
        self.run_action("approve",{"human_confirmation":True})
        result=self.wf().export(self.pid,self.row["revision"],"Reviewer",["internal","supplier","proposal"],"es",True,str(uuid4()))
        self.assertEqual(len(result["artifacts"]),3);self.assertTrue(result["row"]["workflow_view"]["approved"])


class WorkflowHTTPTests(unittest.TestCase):
    def test_persistent_http_operations_and_session_protection(self):
        with TemporaryDirectory() as tmp:
            server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(Path(tmp)))
            thread=Thread(target=server.serve_forever,daemon=True);thread.start();token=""
            def request(method,path,data=None,valid=True):
                c=HTTPConnection("127.0.0.1",server.server_port,timeout=10)
                c.request(method,path,json.dumps(data) if data else None,{"Content-Type":"application/json","X-ALKAN-Token":token if valid else "invalid"})
                r=c.getresponse();raw=r.read();c.close();return r.status,json.loads(raw) if r.getheader("Content-Type","").startswith("application/json") else raw
            try:
                token=request("GET","/api/session")[1]["token"]
                self.assertEqual(request("GET","/contractor_workflow.js")[0],200)
                key=str(uuid4());create={"actor":"Reviewer","request_id":key,"project":{"name":"Anonymous HTTP V3","work_type":"residential","contractual_relationship":"direct_homeowner"}}
                self.assertEqual(request("POST","/api/workflow/create",create,False)[0],403)
                status,row=request("POST","/api/workflow/create",create);self.assertEqual(status,200)
                self.assertEqual(request("POST","/api/workflow/create",create)[1]["project_id"],row["project_id"])
                pid=row["project_id"];upload={"actor":"Reviewer","project_id":pid,"revision":row["revision"],"request_id":str(uuid4()),"files":[{"name":"scope.pdf","content":base64.b64encode(v2.pdf_bytes("Scope of work: fence 426 feet")).decode()}]}
                status,row=request("POST","/api/workflow/upload",upload);self.assertEqual(status,200)
                self.assertEqual(request("POST","/api/workflow/upload",upload)[1]["revision"],row["revision"])
                status,row=request("POST","/api/workflow/action",{"actor":"Reviewer","project_id":pid,"revision":row["revision"],"request_id":str(uuid4()),"action":"analyze"});self.assertEqual(status,200)
                self.assertEqual(row["state"]["lines"][0]["quantity"],"426")
                self.assertEqual(request("GET","/api/workflow?project_id="+pid)[1]["workflow_view"]["current_step"],"analysis")
                status,exported=request("POST","/api/workflow/export",{"actor":"Reviewer","project_id":pid,"revision":row["revision"],"request_id":str(uuid4()),"kinds":["supplier"],"language":"en","final":False});self.assertEqual(status,200)
                self.assertTrue(request("GET",exported["artifacts"][0]["url"])[1].startswith(b"%PDF-"))
                self.assertEqual(request("POST","/api/workflow/export",{"actor":"Reviewer","project_id":pid,"revision":exported["row"]["revision"],"request_id":str(uuid4()),"kinds":["proposal"],"final":True})[0],400)
            finally:server.shutdown();server.server_close();thread.join()


if __name__=="__main__":unittest.main()
