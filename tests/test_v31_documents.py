"""V3.1 exports: three document types from the same persisted dossier.

Validates that the internal cost analysis keeps its seven sections and totals,
the commercial proposal never reveals internal costs/margins, the materials
CSV contains only real dossier records, and that exporting never mutates the
dossier or its revision history.
"""
from copy import deepcopy
from io import BytesIO, StringIO
import csv
import unittest

from pypdf import PdfReader

import test_intelligence_v2 as v2
from bidkit.intelligence_reports import export_document, render_document
from bidkit.supplier_exports import export_supplier_center

INTERNAL_SECTIONS = (
    "Alcance completo del trabajo",
    "Cuantificación y mediciones",
    "Materiales, especificaciones",
    "Mano de obra, horas, tarifas",
    "Oficina, permisos, equipos",
    "Desglose final",
    "Riesgos, observaciones y verificaciones",
)
INTERNAL_FORBIDDEN_NONE = None  # internal is allowed to show costs
PROPOSAL_FORBIDDEN = ("CONFIDENCIAL", "Costo directo", "Indirectos", "target_margin", "normalized_unit_price",
                      "estimated_all_in_cost", "Utilidad estimada", "unit_price", "Materiales", "overhead_percent")


class V31DocumentExportTests(unittest.TestCase):
    setUp = v2.IntelligenceTests.setUp
    tearDown = v2.IntelligenceTests.tearDown
    act = v2.IntelligenceTests.act
    upload = v2.IntelligenceTests.upload
    ready = v2.IntelligenceTests.ready
    evidence = v2.IntelligenceTests.evidence

    def extract(self, kind, language="es"):
        row = self.service.store.load(self.pid)
        row["state"]["result"] = self.service.evaluate(row["state"])
        raw = render_document(row, kind, language)
        return raw, "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(raw)).pages), PdfReader(BytesIO(raw)).pages

    def test_internal_has_seven_sections_totals_match_and_confidential(self):
        self.ready(); self.act("approve", {"human_confirmation": True})
        t = self.row["state"]["result"]["totals"]
        raw, txt, pages = self.extract("internal")
        self.assertTrue(pages)
        self.assertIn("CONFIDENCIAL — USO INTERNO", txt)
        for sec in INTERNAL_SECTIONS:
            self.assertIn(sec, txt)
        # Totals in the internal document must match the persisted dossier exactly.
        self.assertIn("USD {:,.2f}".format(float(t["estimated_all_in_cost"])), txt)
        self.assertIn("USD {:,.2f}".format(float(t["proposed_price_before_contract_specific_taxes"])), txt)
        self.assertIn("USD {:,.2f}".format(float(t["estimated_gross_profit"])), txt)

    def test_proposal_has_identification_scope_price_auth_and_no_leak(self):
        self.ready(); self.act("approve", {"human_confirmation": True})
        raw, txt, pages = self.extract("proposal")
        self.assertTrue(pages)
        self.assertIn("Autorización", txt)
        self.assertIn("Firma / Fecha", txt)
        self.assertIn("Total propuesto", txt)
        self.assertIn("Vigencia", txt)
        self.assertIn("Exclusiones", txt)
        self.assertIn("Condiciones comerciales", txt)
        for bad in PROPOSAL_FORBIDDEN:
            self.assertNotIn(bad, txt)

    def test_all_exports_share_same_dossier_and_do_not_mutate(self):
        self.ready(); self.act("approve", {"human_confirmation": True})
        before = deepcopy(self.service.store.load(self.pid))
        rev_before = before["revision"]
        export_document(self.service, self.pid, "internal", "es")
        export_document(self.service, self.pid, "proposal", "es")
        after = deepcopy(self.service.store.load(self.pid))
        self.assertEqual(before, after)
        self.assertEqual(after["revision"], rev_before)

    def test_materials_csv_contains_only_real_records(self):
        self.ready()
        result = export_supplier_center(self.service, self.pid, self.row["revision"], "project", "es", "csv")
        self.assertEqual(len(result["artifacts"]), 1)
        path = self.service.store.child(self.pid, "exports", result["artifacts"][0]["name"])
        text = path.read_text(encoding="utf-8-sig")
        rows = list(csv.DictReader(StringIO(text)))
        self.assertTrue(rows)
        # every row belongs to this dossier and every non-empty supplier is a registered record
        self.assertTrue(all(r["project_id"] == self.pid for r in rows))
        registered = {s["supplier_id"] for s in self.row["state"]["suppliers"]}
        for r in rows:
            if r["supplier_id"]:
                self.assertIn(r["supplier_id"], registered)
        # does not mutate
        self.assertEqual(self.service.store.load(self.pid)["revision"], self.row["revision"])

    def test_pdf_is_byte_identical_on_repeat(self):
        self.ready()
        a = export_document(self.service, self.pid, "internal", "en")
        b = export_document(self.service, self.pid, "internal", "en")
        self.assertEqual(a, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())


if __name__ == "__main__":
    unittest.main()