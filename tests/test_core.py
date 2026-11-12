import unittest
from pathlib import Path

from bidkit.records import AMENDMENTS, TAKEOFF


class RecordsTests(unittest.TestCase):
    def test_final_bid_addendum_is_04(self) -> None:
        active = [item["addendum"] for item in AMENDMENTS if item["precedence"] == "active_final_for_bid_time"]
        self.assertEqual(active, ["04"])

    def test_pending_takeoff_lines_are_not_invented(self) -> None:
        for item in TAKEOFF:
            if item["quantity_status"] == "PENDIENTE DE MEDICIÓN":
                self.assertIsNone(item["quantity"])


class AuditTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1] / "data/audit/document_inventory.json").exists(), "Inventario histórico no incluido en ZIP de código")
    def test_source_manifest_exists_after_audit(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "data" / "audit" / "document_inventory.json").exists())

