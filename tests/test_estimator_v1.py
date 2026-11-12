import unittest
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from bidkit.estimator_v1 import calculate, new_template, import_bidengine_takeoff, make_snapshot
from bidkit.records import TAKEOFF

AS_OF = date(2026, 10, 30)


def sample():
    d = new_template(estimate_id="TEST-001", project_name="Prueba", client_type="homeowner")
    d["financial"] = {"overhead_percent": "10", "contingency_percent": "0", "target_margin_percent": "20", "confirmed": True}
    d["lines"] = [
        {"id":"MAT", "description":"Panel", "category":"material", "unit":"EA", "quantity":"10", "quantity_status":"verified", "quantity_evidence":"takeoff/approved-001.pdf", "selected_option_id":"SUP-A", "options":[
            {"id":"SUP-A", "provider":"A", "unit_cost":"100.00", "unit":"EA", "currency":"USD", "delivery_total":"25.00", "quoted_on":"2026-10-29", "valid_until":"2026-11-15", "evidence_ref":"supplier/A.pdf"},
            {"id":"SUP-B", "provider":"B", "unit_cost":"99.00", "unit":"EA", "currency":"USD", "delivery_total":"15.00", "quoted_on":"2026-10-29", "valid_until":"2026-11-15", "evidence_ref":"supplier/B.pdf"}
        ]},
        {"id":"LAB", "description":"Instalación", "category":"labor", "unit":"HR", "quantity":"8", "quantity_status":"verified", "quantity_evidence":"takeoff/approved-001.pdf", "selected_option_id":"CREW", "options":[
            {"id":"CREW", "provider":"Cuadrilla", "unit_cost":"50.00", "unit":"HR", "currency":"USD", "delivery_total":"0", "quoted_on":"2026-10-28", "valid_until":"2026-12-01", "evidence_ref":"labor/rates-001.pdf"}
        ]}
    ]
    return d


class EstimatorV1Tests(unittest.TestCase):
    def test_calculation_and_margin(self):
        r = calculate(sample(), as_of=AS_OF)
        self.assertEqual(r["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(r["totals"]["direct_cost"], "1425.00")
        self.assertEqual(r["totals"]["overhead_cost"], "142.50")
        self.assertEqual(r["totals"]["proposed_price_before_contract_specific_taxes"], "1959.38")
        self.assertEqual(r["price_stress"]["material_plus_5%"]["additional_material_cost"], "51.25")

    def test_freight_and_vendor_alternatives(self):
        r = calculate(sample(), as_of=AS_OF)
        self.assertEqual(r["lines"][0]["eligible_cheapest_option_id"], "SUP-B")
        self.assertEqual(r["lines"][0]["potential_savings_vs_selected"], "20.00")
        self.assertEqual(r["lines"][0]["selected_option_id"], "SUP-A")  # never auto-change

    def test_no_prices_means_blocked_not_zero(self):
        d = new_template(estimate_id="NEW", project_name="Sin cotizaciones", client_type="gc_subcontract")
        r = calculate(d, as_of=AS_OF)
        self.assertEqual(r["status"], "BLOCKED_INPUTS")
        self.assertIsNone(r["totals"]["proposed_price_before_contract_specific_taxes"])

    def test_expired_quote_blocks(self):
        d = sample()
        d["lines"][0]["options"][0]["valid_until"] = "2026-10-15"
        r = calculate(d, as_of=AS_OF)
        self.assertEqual(r["status"], "BLOCKED_INPUTS")
        self.assertTrue(any("vencida" in b for b in r["blockers"]))

    def test_unverified_quantity_blocks(self):
        d = sample()
        d["lines"][1]["quantity_status"] = "pending"
        self.assertEqual(calculate(d, as_of=AS_OF)["status"], "BLOCKED_INPUTS")

    def test_unit_mismatch_blocks(self):
        d = sample()
        d["lines"][0]["options"][0]["unit"] = "SF"
        self.assertEqual(calculate(d, as_of=AS_OF)["status"], "BLOCKED_INPUTS")

    def test_no_quote_evidence_blocks(self):
        d = sample()
        d["lines"][0]["options"][0]["evidence_ref"] = ""
        self.assertEqual(calculate(d, as_of=AS_OF)["status"], "BLOCKED_INPUTS")

    def test_takeoff_import_never_auto_prices(self):
        d = new_template(estimate_id="PORT-TACOMA", project_name="Roof", client_type="public_works")
        d["project"]["bid_engine_ref"] = "072026-1044"
        import_bidengine_takeoff(d, TAKEOFF)
        self.assertEqual(len(d["takeoff_references"]), len(TAKEOFF))
        self.assertEqual(d["takeoff_references"][0]["reference_quantity"], TAKEOFF[0]["quantity"])
        self.assertEqual(d["takeoff_references"][0]["review_status"], "requires_estimator_review")
        self.assertEqual(calculate(d, as_of=AS_OF)["status"], "BLOCKED_INPUTS")

    def test_wrong_project_cannot_import_unrelated_takeoff(self):
        d = new_template(estimate_id="OTHER", project_name="Unrelated", client_type="homeowner")
        with self.assertRaises(ValueError):
            import_bidengine_takeoff(d, TAKEOFF)

    def test_margin_requires_human_confirmation(self):
        d = sample()
        d["financial"]["confirmed"] = False
        r = calculate(d, as_of=AS_OF)
        self.assertEqual(r["status"], "BLOCKED_INPUTS")
        self.assertTrue(any("confirmación humana" in x for x in r["blockers"]))

    def test_snapshot_is_immutable_and_repeatable(self):
        d = sample()
        with TemporaryDirectory() as tmp:
            p1 = make_snapshot(d, AS_OF, Path(tmp))
            p2 = make_snapshot(d, AS_OF, Path(tmp))
            self.assertEqual(p1, p2)
            self.assertEqual(len(list(Path(tmp).glob("*.json"))), 1)
            d2 = deepcopy(d)
            d2["lines"][0]["options"][0]["unit_cost"] = "105.00"
            p3 = make_snapshot(d2, AS_OF, Path(tmp))
            self.assertNotEqual(p1, p3)

    def test_reject_float_and_invalid_margin(self):
        d = sample()
        d["lines"][0]["options"][0]["unit_cost"] = 99.5
        with self.assertRaises(ValueError):
            calculate(d, as_of=AS_OF)
        d = sample()
        d["financial"]["target_margin_percent"] = "100"
        with self.assertRaises(ValueError):
            calculate(d, as_of=AS_OF)

if __name__ == "__main__":
    unittest.main()
