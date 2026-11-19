"""Tests unitarios para bid_snapshot."""
import sys
import unittest
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parents[1]
if str(ROOT_REPO / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_REPO / "src"))

from bidkit.bid_snapshot import build_bid_snapshot, format_bid_snapshot_summary


class TestBidSnapshot(unittest.TestCase):
    def test_missing_data_marked_null_or_falta_confirmar(self):
        """Campos sin fuente = null / falta confirmar, nunca supuestos."""
        snap = build_bid_snapshot([], project_name=None)
        self.assertEqual(snap["project_name"], "falta confirmar")
        self.assertIsNone(snap["dates"]["bid_due"]["date"])
        self.assertIsNone(snap["dates"]["bid_due"]["time"])
        self.assertIsNone(snap["dates"]["bid_due"]["method"])
        self.assertFalse(snap["dates"]["pre_bid_meeting"]["mandatory"])
        self.assertFalse(snap["dates"]["pre_bid_meeting"]["passed"])
        self.assertEqual(len(snap["contacts"]), 0)
        self.assertIsNone(snap["budget_or_engineers_estimate"]["amount"])
        self.assertIsNone(snap["budget_or_engineers_estimate"]["source"])
        self.assertEqual(len(snap["bid_requirements"]), 0)
        self.assertFalse(snap["has_blockers"])

    def test_pre_bid_mandatory_passed_triggers_cannot_meet(self):
        """Junta pre-bid obligatoria ya pasada dispara cannot_meet y razón de NO_GO."""
        notes = [
            {
                "kind": "requirement",
                "text": "Pre-bid walk-through: 10:00 AM, October 27, 2026. MANDATORY attendance. Meeting already held and passed.",
                "source": "Specs p.11 (Advertisement for Bids 0.01)",
            },
            {
                "kind": "date",
                "text": "Pre-bid meeting held October 27, 2026 at 10:00 AM. Mandatory.",
                "source": "Specs p.11",
            },
        ]
        snap = build_bid_snapshot(notes, project_name="Highline College Bldg 3")
        self.assertEqual(snap["project_name"], "Highline College Bldg 3")
        self.assertTrue(snap["dates"]["pre_bid_meeting"]["mandatory"])
        self.assertTrue(snap["dates"]["pre_bid_meeting"]["passed"])
        self.assertTrue(snap["has_blockers"])
        self.assertIsNotNone(snap["go_no_go_explanation"])
        self.assertIn("Specs p.11", snap["go_no_go_explanation"])

        cannot_meet = [r for r in snap["bid_requirements"] if r["status"] == "cannot_meet"]
        self.assertGreaterEqual(len(cannot_meet), 1)
        self.assertEqual(cannot_meet[0]["source"], "Specs p.11 (Advertisement for Bids 0.01)")

    def test_addenda_overrides_bid_due_date(self):
        """Addenda sobre-escribe fecha límite de los specs originales."""
        notes = [
            {
                "kind": "date",
                "text": "Bid due: November 17, 2026 at 1:00 PM PT online via portal.",
                "source": "Specs p.10 (Advertisement for Bids)",
            },
            {
                "kind": "date",
                "text": "Addendum No. 2: Bid due date is extended to November 24, 2026 at 2:00 PM PT.",
                "source": "Addendum No. 2, Section 00 11 13",
            },
        ]
        snap = build_bid_snapshot(notes, project_name="Project with Addenda")
        self.assertEqual(snap["dates"]["bid_due"]["date"], "November 24, 2026")
        self.assertEqual(snap["dates"]["bid_due"]["time"], "2:00 PM PT")

    def test_engineers_estimate_as_reference_never_anchor(self):
        """Engineer's estimate se guarda como referencia etiquetada con su fuente."""
        notes = [
            {
                "kind": "benchmark",
                "text": "Engineer's estimated bid cost range: $1,700,000 to $1,900,000 (whole project).",
                "source": "Specs p.10 Advertisement for Bids",
            }
        ]
        snap = build_bid_snapshot(notes)
        bench = snap["budget_or_engineers_estimate"]
        self.assertEqual(bench["amount"], "$1,700,000 to $1,900,000")
        self.assertEqual(bench["covers"], "whole_project")
        self.assertEqual(bench["source"], "Specs p.10 Advertisement for Bids")

    def test_contacts_parsing(self):
        """Contactos con nombre, rol, email y teléfono."""
        notes = [
            {
                "kind": "contact",
                "text": "Owner: Department of Enterprise Services. Project Manager: Jeff Potts, jeff.potts@des.wa.gov. Architect: Starling Architects, 206-812-0419, starling@swl.com.",
                "source": "Specs p.10",
            }
        ]
        snap = build_bid_snapshot(notes)
        self.assertGreaterEqual(len(snap["contacts"]), 2)
        emails = [c["email"] for c in snap["contacts"] if c.get("email")]
        self.assertIn("jeff.potts@des.wa.gov", emails)


if __name__ == "__main__":
    unittest.main()
