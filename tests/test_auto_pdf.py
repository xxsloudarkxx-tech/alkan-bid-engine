"""Automatic PDFs on approval and contract acceptance: same gates as manual export, nothing sent."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from uuid import uuid4
import unittest

from pypdf import PdfReader

import bidkit.estimate_workflow as workflow_module
from bidkit.estimate_workflow import EstimateWorkflow
from bidkit.intelligence_reports import export_document
import test_intelligence_v2 as v2

SECRETS = ("target_margin", "Synthetic supplier", "overhead_percent")


class AutoPdfTests(unittest.TestCase):
    setUp = v2.IntelligenceTests.setUp
    tearDown = v2.IntelligenceTests.tearDown
    act = v2.IntelligenceTests.act
    ready = v2.IntelligenceTests.ready
    upload = v2.IntelligenceTests.upload
    evidence = v2.IntelligenceTests.evidence

    def wf(self):
        return EstimateWorkflow(self.root, self.service)

    def run_action(self, action, payload=None, key=None):
        self.row = self.wf().execute(self.pid, self.row["revision"], "Reviewer", action, payload or {}, key or str(uuid4()))
        return self.row

    def priced(self):
        """Reviewed, calculated estimate ready for approval (same path as the existing workflow test)."""
        self.ready(); self.run_action("analyze")
        for line in deepcopy(self.row["state"]["lines"]):
            if line.get("candidate_id"): self.run_action("line", {**line, "active": False})
        for issue in self.row["state"]["result"]["issues"]:
            self.run_action("resolve", {"issue_id": issue["issue_id"], "disposition": "included",
                "reason": "Synthetic reviewed specification and delivery included", "evidence_reference": self.evidence()})
        self.run_action("settings", {"review": {"scope_confirmed": True}})
        self.run_action("calculate")

    def artifacts(self):
        return self.row["state"]["workflow"].get("exports", [])

    def text_of(self, artifact):
        path = self.service.store.child(self.pid, "exports", artifact["name"])
        return "".join(page.extract_text() for page in PdfReader(str(path)).pages)

    def test_approval_creates_internal_and_proposal_pdfs_without_manual_export(self):
        self.priced()
        self.run_action("approve", {"human_confirmation": True})
        kinds = {(a["kind"], a["final"]) for a in self.artifacts()}
        self.assertEqual(kinds, {("internal", False), ("proposal", True)})
        for artifact in self.artifacts():
            raw = self.service.store.child(self.pid, "exports", artifact["name"]).read_bytes()
            self.assertTrue(raw.startswith(b"%PDF-"))
        proposal = next(a for a in self.artifacts() if a["kind"] == "proposal")
        text = self.text_of(proposal)
        for secret in SECRETS: self.assertNotIn(secret, text)
        self.assertIsNotNone(self.row["state"]["current_approval"])
        self.assertEqual(self.row["state"]["deliveries"], [])  # generated, never sent
        shown = {d["kind"] for d in self.row["workflow_view"]["generated_documents"]}
        self.assertEqual(shown, {"internal", "proposal"})

    def test_replay_and_non_event_actions_do_not_duplicate_pdfs(self):
        self.priced()
        key = str(uuid4())
        self.run_action("approve", {"human_confirmation": True}, key)
        count, revision = len(self.artifacts()), self.row["revision"]
        replay = self.wf().execute(self.pid, revision, "Reviewer", "approve", {"human_confirmation": True}, key)
        self.assertEqual(replay["revision"], revision)
        self.run_action("transition", {"step": "documents"})  # navigation is not an approval or contract event
        self.assertEqual(len(self.artifacts()), count)

    def test_blocked_approval_creates_no_pdf(self):
        self.priced(); self.act("settings", {"project": {"contractor": ""}})
        with self.assertRaises(ValueError):
            self.run_action("approve", {"human_confirmation": True})
        self.assertEqual(self.artifacts(), [])

    def test_contract_acceptance_creates_contract_record_pdf(self):
        self.priced(); self.run_action("approve", {"human_confirmation": True})
        self.run_action("contract_acceptance", {"amount": "1850", "human_confirmation": True, "evidence_reference": self.evidence()})
        contract = next(a for a in self.artifacts() if a["kind"] == "contract")
        text = self.text_of(contract)
        self.assertIn("1,850.00", text)
        self.assertIn("Firmas", text)
        self.assertIn("No sustituye el contrato", text)
        for secret in SECRETS: self.assertNotIn(secret, text)

    def test_contract_export_refused_without_contract_record(self):
        self.priced()
        with self.assertRaises(ValueError):
            export_document(self.service, self.pid, "contract")

    def test_pdf_failure_does_not_undo_the_approval(self):
        self.priced()
        with mock.patch.object(workflow_module, "export_document", side_effect=ValueError("Documento de prueba fallido")):
            row = self.run_action("approve", {"human_confirmation": True})
        self.assertIsNotNone(row["state"]["current_approval"])
        self.assertEqual(self.artifacts(), [])
        errors = row["workflow_view"]["auto_export_errors"]
        self.assertTrue(errors and errors[0]["action"] == "approve" and "Documento de prueba fallido" in errors[0]["message"])


if __name__ == "__main__":
    unittest.main()
