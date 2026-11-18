"""Tests for the Alkan estimation methodology module — using real job patterns."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from bidkit.alkan_method import (
    BASE_MARKUP,
    PROJECT_STATES,
    EstimateConfig,
    ScopeItem,
    LaborRate,
    AlkanCommission,
    ProjectEstimate,
    QuoteLineItem,
    SupplierQuote,
    apply_contractor_adjustment,
    apply_supplier_quote,
    calculate_estimate,
    calculate_preestimate,
    estimate_mobilization,
    estimate_consumables,
    finalize_project_estimate,
    generate_project_pdfs,
     WA_JURISDICTION_TAXES,
    WASTE_DEFAULTS,
    TRADES,
)


class TaxRegistryTests(unittest.TestCase):
    def test_known_jurisdictions_are_in_range(self):
        for name, rate in WA_JURISDICTION_TAXES.items():
            self.assertGreater(rate, Decimal("6"), f"{name} below WA state base")
            self.assertLess(rate, Decimal("15"), f"{name} unreasonably high")

    def test_jurisdiction_lookup_case_insensitive(self):
        config = EstimateConfig(estimate_id="T1", project_name="Test", contractor_name="C",
                                jurisdiction="Seattle", tax_confirmed=False)
        self.assertEqual(config.effective_tax_rate(), Decimal("10.35"))


class WasteDefaultsTests(unittest.TestCase):
    def test_all_defaults_positive(self):
        for material, pct in WASTE_DEFAULTS.items():
            self.assertGreater(pct, 0, material)
            self.assertLessEqual(pct, Decimal("20"), material)


class MetalFabEstimateTests(unittest.TestCase):
    """Simulates an S&S-style metal fabrication bid as subcontractor to GC."""

    def setUp(self):
        self.config = EstimateConfig(
            estimate_id="SS-2026-1107",
            project_name="Orangegate Park Phase 1",
            contractor_name="S & S CUSTOM IRON WORKS LLC",
            contractor_license="SSCUSCI791QE",
            client_name="A-1 Landscaping and Construction, Inc.",
            project_address="Pierce County",
            jurisdiction="pierce_county_unincorp",
            county="Pierce",
            relationship="sub_to_gc",
            tier="competitive",
            pricing_method="markup",
            markup_pct=Decimal("15"),
            prevailing_wage=True,
            tax_confirmed=True,
            tax_rate=Decimal("0"),  # sub to GC, tax excluded from sub bid
            estimator="Miguel Alcantara",
            date="2026-11-07",
        )
        self.items = [
            ScopeItem(id="MAT-001", description="Chain link fabric 9ga galv", trade="chain_link_fabric",
                      category="material", quantity=Decimal("426"), unit="LF",
                      quantity_status="CONFIRMED", quantity_source="Sheet L1.15",
                      unit_cost=Decimal("4.85"), cost_source="A1 Metal Supplier catalog"),
            ScopeItem(id="MAT-002", description="Steel posts 2-3/8 SS40", trade="steel_structural",
                      category="material", quantity=Decimal("48"), unit="EA",
                      quantity_status="CONFIRMED", quantity_source="Sheet L1.15 @ 10' OC",
                      unit_cost=Decimal("32.50"), cost_source="A1 Metal Supplier catalog"),
            ScopeItem(id="LAB-001", description="Field installation ironworker", trade="ironworker",
                      category="labor", quantity=Decimal("1"), unit="LS",
                      quantity_status="CONFIRMED", quantity_source="Crew estimate",
                      field_hours=Decimal("120"),
                      labor_rate=LaborRate(trade="ironworker", base_rate=Decimal("75.00"),
                                           fringe=Decimal("19.82"), county="Pierce",
                                           prevailing_wage=True, source="L&I WAC 296-127")),
            ScopeItem(id="EQ-001", description="Bobcat + post driver rental", trade="fence_erector",
                      category="equipment", quantity=Decimal("5"), unit="DAY",
                      quantity_status="CONFIRMED", quantity_source="Schedule estimate",
                      unit_cost=Decimal("285"), cost_source="Sunbelt Rentals quote"),
        ]

    def test_metal_fab_calculates_with_markup_method(self):
        result = calculate_estimate(self.config, self.items)
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertEqual(result["pricing_method"], "markup")
        self.assertIsNotNone(result["totals"]["selling_price_before_tax"])
        # Markup: (direct + mob) × 1.15
        direct = Decimal(result["totals"]["direct_cost"])
        selling = Decimal(result["totals"]["selling_price_before_tax"])
        self.assertEqual(selling, (direct * Decimal("1.15")).quantize(Decimal("0.01")))

    def test_prevailing_wage_blocker_without_county(self):
        self.config.county = ""
        result = calculate_estimate(self.config, self.items)
        self.assertIn("Prevailing wage requires county", result["blockers"])


class RoofingEstimateTests(unittest.TestCase):
    """Simulates a generic roofing contractor residential estimate."""

    def test_roofing_margin_method_with_tax(self):
        config = EstimateConfig(
            estimate_id="ROOF-2026-0701",
            project_name="27012 115th Pl SE Exterior Remodel",
            contractor_name="TO_BE_FILLED LLC",
            contractor_license="XXXXXX000XX",
            client_name="Property Owner",
            jurisdiction="kent",
            relationship="direct_homeowner",
            tier="competitive",
            pricing_method="margin",
            target_margin_pct=Decimal("20"),
            overhead_pct=Decimal("10"),
            contingency_pct=Decimal("5"),
            tax_confirmed=True,
            tax_rate=Decimal("10.20"),
            estimator="Andrés",
            date="2026-07-01",
        )
        items = [
            ScopeItem(id="MAT-R01", description="CertainTeed Landmark shingles", trade="roofing_shingles",
                      category="material", quantity=Decimal("25"), unit="SQ",
                      quantity_status="CONFIRMED", quantity_source="Roof measurement",
                      unit_cost=Decimal("125"), cost_source="ABC Supply quote"),
            ScopeItem(id="MAT-R02", description="Ice & water shield", trade="underlayment",
                      category="material", quantity=Decimal("2500"), unit="SF",
                      quantity_status="CONFIRMED", quantity_source="Full deck coverage",
                      unit_cost=Decimal("0.85"), cost_source="ABC Supply quote"),
            ScopeItem(id="LAB-R01", description="Roofing crew installation", trade="roofer",
                      category="labor", quantity=Decimal("1"), unit="LS",
                      quantity_status="CONFIRMED", quantity_source="Crew plan",
                      field_hours=Decimal("40"),
                      labor_rate=LaborRate(trade="roofer", base_rate=Decimal("38"))),
        ]
        result = calculate_estimate(config, items)
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertIsNotNone(result["totals"]["total_with_tax"])
        # Verify tax is applied.
        selling = Decimal(result["totals"]["selling_price_before_tax"])
        total = Decimal(result["totals"]["total_with_tax"])
        expected_tax = (selling * Decimal("10.20") / 100).quantize(Decimal("0.01"))
        self.assertEqual(total, selling + expected_tax)

    def test_waste_defaults_applied_to_shingles(self):
        item = ScopeItem(id="T", description="test", trade="roofing_shingles",
                         category="material", quantity=Decimal("100"), unit="SF",
                         quantity_status="CONFIRMED", unit_cost=Decimal("1"))
        self.assertEqual(item.waste_factor, Decimal("12"))
        self.assertEqual(item.adjusted_quantity, Decimal("112.00"))


class CommissionTests(unittest.TestCase):
    """Tests the Alkan commission structure (3% + 3%)."""

    def test_find_only_commission(self):
        c = AlkanCommission(gross_sale=Decimal("150000"))
        self.assertEqual(c.find_estimate_fee, Decimal("4500.00"))
        self.assertEqual(c.coordination_fee, Decimal("0"))
        self.assertEqual(c.total_fee, Decimal("4500.00"))
        sched = c.schedule()
        self.assertEqual(sched["at_contract_signing"], "2250.00")
        self.assertEqual(sched["on_first_payment"], "2250.00")

    def test_full_commission_with_coordination(self):
        c = AlkanCommission(gross_sale=Decimal("150000"), coordination_included=True)
        self.assertEqual(c.total_fee, Decimal("9000.00"))

    def test_schedule_rounds_correctly(self):
        c = AlkanCommission(gross_sale=Decimal("33333"))
        sched = c.schedule()
        half = Decimal(sched["at_contract_signing"])
        other = Decimal(sched["on_first_payment"])
        self.assertEqual(half + other, c.total_fee)


class MobilizationTests(unittest.TestCase):
    def test_basic_mobilization(self):
        result = estimate_mobilization(
            distance_miles=Decimal("45"),
            crew_size=3,
            trips=2,
        )
        self.assertGreater(Decimal(result["total_mobilization"]), 0)
        self.assertEqual(result["trips"], 2)


class ConsumablesTests(unittest.TestCase):
    def test_welding_consumables(self):
        result = estimate_consumables(welding_hours=Decimal("80"), paint_gallons=Decimal("5"))
        self.assertGreater(Decimal(result["welding_consumables"]), 0)
        self.assertGreater(Decimal(result["paint_cost"]), 0)
        total = Decimal(result["total_consumables"])
        self.assertEqual(total, Decimal(result["welding_consumables"]) + Decimal(result["paint_cost"]))


class BlockerTests(unittest.TestCase):
    def test_missing_quantity_blocks(self):
        config = EstimateConfig(estimate_id="T1", project_name="Test", contractor_name="C",
                                jurisdiction="seattle", tax_confirmed=True, tax_rate=Decimal("10.35"))
        items = [ScopeItem(id="X", description="test", trade="general", category="material",
                           unit="EA", quantity_status="PENDING")]
        result = calculate_estimate(config, items)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("Quantity" in b for b in result["blockers"]))

    def test_unknown_jurisdiction_without_explicit_tax_blocks(self):
        config = EstimateConfig(estimate_id="T2", project_name="Test", contractor_name="C",
                                jurisdiction="timbuktu", tax_confirmed=False)
        result = calculate_estimate(config, [])
        self.assertTrue(any("tax" in b.lower() or "Tax" in b for b in result["blockers"]))


class ThreeStageWorkflowTests(unittest.TestCase):
    """Tests the 3-stage ProjectEstimate workflow: preestimado -> ajustado -> final."""

    def setUp(self):
        self.scope_items = [
            ScopeItem(
                id="MAT-101",
                description="HSS 4x4x1/4 Steel Tube",
                trade="steel_structural",
                category="material",
                quantity=Decimal("20"),
                unit="EA",
                quantity_status="CONFIRMED",
                quantity_source="Sheet S1.01",
                reference_price=Decimal("120.00"),
            ),
            ScopeItem(
                id="MAT-102",
                description="Galvanized Anchor Bolts 3/4 in",
                trade="metal_fabrication",
                category="material",
                quantity=Decimal("80"),
                unit="EA",
                quantity_status="CONFIRMED",
                quantity_source="Detail 4/S2.01",
                reference_price=Decimal("8.50"),
            ),
        ]
        self.farwest_quote = SupplierQuote(
            supplier_name="Farwest",
            quote_number="FW-2026-991",
            quote_date=date(2026, 11, 10),
            line_items=[
                QuoteLineItem(
                    description="HSS 4x4x1/4 Steel Tube",
                    quantity=Decimal("20"),
                    unit="EA",
                    unit_price=Decimal("110.00"),
                    total=Decimal("2200.00"),
                    matches_scope_item_id="MAT-101",
                )
            ],
            file_path="quotes/farwest_fw2026_991.pdf",
            is_verified=True,
        )

    def test_preestimate_applies_quotes_reference_prices_and_base_markup(self):
        project = calculate_preestimate(
            project_id="EST-3STAGE-001",
            name="Commercial Canopy Steel",
            scope_items=self.scope_items,
            preliminary_hours=Decimal("40"),
            supplier_quotes=[self.farwest_quote],
            county="King",
            is_prevailing_wage=True,
            distance_miles=25.0,
            client_type="gc",
        )
        self.assertEqual(project.status, "preestimado")
        self.assertEqual(project.preliminary_hours_status, "pending_confirmation")
        self.assertEqual(BASE_MARKUP, Decimal("0.20"))
        self.assertEqual(project.supplier_quotes_used, ["FW-2026-991"])
        # MAT-101 matched Farwest quote; MAT-102 used reference price and is in needs_quote_items
        mat_101 = next(x for x in project.materials if x.id == "MAT-101")
        mat_102 = next(x for x in project.materials if x.id == "MAT-102")
        self.assertEqual(mat_101.pricing_source, "supplier_quote")
        self.assertEqual(mat_101.final_unit_price, Decimal("110.00"))
        self.assertEqual(mat_102.pricing_source, "reference")
        self.assertEqual(mat_102.final_unit_price, Decimal("8.50"))
        self.assertIn("MAT-102", project.needs_quote_items)
        self.assertNotIn("MAT-101", project.needs_quote_items)

        # Price is always visible on screen without generating PDFs
        self.assertGreater(project.base_price, Decimal("0"))
        self.assertEqual(project.visible_price, project.base_price)
        screen = project.screen_summary()
        self.assertFalse(screen["pdf_generation_enabled"])
        self.assertEqual(screen["visible_price"], str(project.base_price))

    def test_contractor_adjustment_and_quote_replacement_and_final_pdfs(self):
        project = calculate_preestimate(
            project_id="EST-3STAGE-002",
            name="Stair & Railing Package",
            scope_items=self.scope_items,
            preliminary_hours=Decimal("40"),
            supplier_quotes=[self.farwest_quote],
            county="Pierce",
            is_prevailing_wage=False,
            distance_miles=10.0,
            client_type="gc",
        )
        with TemporaryDirectory() as tmp:
            # 1. PDF generation MUST fail in 'preestimado'
            with self.assertRaises(ValueError):
                generate_project_pdfs(project, tmp)

            # 2. Contractor confirms real hours and desired markup -> status becomes 'ajustado'
            apply_contractor_adjustment(
                project,
                confirmed_hours=Decimal("52"),
                contractor_markup=Decimal("0.25"),
            )
            self.assertEqual(project.status, "ajustado")
            self.assertEqual(project.preliminary_hours_status, "confirmed")
            self.assertEqual(project.confirmed_hours, Decimal("52"))
            self.assertIsNotNone(project.final_price)
            self.assertEqual(project.visible_price, project.final_price)

            # PDF generation MUST still fail in 'ajustado'
            with self.assertRaises(ValueError):
                generate_project_pdfs(project, tmp)

            # 3. Upload real supplier quote for MAT-102 in 'ajustado' -> replaces reference price & auto-updates total
            price_before_quote = project.final_price
            conway_quote = SupplierQuote(
                supplier_name="Conway",
                quote_number="CW-880",
                quote_date=date(2026, 11, 12),
                line_items=[
                    QuoteLineItem(
                        description="Galvanized Anchor Bolts 3/4 in",
                        quantity=Decimal("80"),
                        unit="EA",
                        unit_price=Decimal("6.00"),
                        total=Decimal("480.00"),
                        matches_scope_item_id="MAT-102",
                    )
                ],
                file_path="quotes/conway_880.pdf",
                is_verified=True,
            )
            apply_supplier_quote(project, conway_quote)
            mat_102 = next(x for x in project.materials if x.id == "MAT-102")
            self.assertEqual(mat_102.pricing_source, "supplier_quote")
            self.assertEqual(mat_102.final_unit_price, Decimal("6.00"))
            self.assertNotIn("MAT-102", project.needs_quote_items)
            self.assertLess(project.final_price, price_before_quote)

            # 4. Transition to 'final' -> now the 3 PDFs are generated
            finalize_project_estimate(project)
            self.assertEqual(project.status, "final")
            self.assertTrue(project.screen_summary()["pdf_generation_enabled"])

            pdfs = generate_project_pdfs(project, Path(tmp))
            self.assertEqual(set(pdfs.keys()), {"cost_analysis", "material_list", "proposal"})
            for pdf_path in pdfs.values():
                self.assertTrue(Path(pdf_path).exists())
                self.assertGreater(Path(pdf_path).stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
