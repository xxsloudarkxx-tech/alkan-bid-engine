"""V3.1A material-list import adapter: read-only preview + guarded apply to lines."""
from copy import deepcopy
from pathlib import Path
import unittest

import test_intelligence_v2 as v2
from bidkit import material_import
from bidkit.material_import import load_material_rows

ROOT = Path(__file__).resolve().parents[1]


class MaterialImportTests(v2.IntelligenceTests):
    @unittest.skipUnless((ROOT / "data/Imports/materiales/04_Tacoma_Gonyea.csv").exists() and (ROOT / "data/Imports/materiales/05_Tacoma_Orangegate.csv").exists(), "CSV de proyectos no incluidos en ZIP de código")
    def test_read_gonyea_rows_and_preview(self):
        file, rows = load_material_rows(str(ROOT), "04_Tacoma_Gonyea.csv")
        self.assertEqual(len(rows), 15)
        p = material_import.preview(self.service, self.pid, file, rows)
        self.assertEqual(p["total_rows"], 15)
        self.assertEqual(p["would_add"], 15)
        self.assertFalse(p["has_current_approval"])
        # documentary rows map to PENDING_VERIFICATION with a quantity, not field-confirmed
        sample = p["proposed"][0]
        self.assertEqual(sample["state"], "PENDING_VERIFICATION")
        self.assertTrue(sample["quantity"] is not None)
        self.assertTrue(sample["source_url"].startswith("http"))
        self.assertTrue(sample["evidence"])  # documentary source preserved

    @unittest.skipUnless((ROOT / "data/Imports/materiales/04_Tacoma_Gonyea.csv").exists() and (ROOT / "data/Imports/materiales/05_Tacoma_Orangegate.csv").exists(), "CSV de proyectos no incluidos en ZIP de código")
    def test_preview_is_read_only_and_apply_adds_then_skips_duplicates(self):
        file, rows = load_material_rows(str(ROOT), "04_Tacoma_Gonyea.csv")
        before = deepcopy(self.service.store.load(self.pid))
        material_import.preview(self.service, self.pid, file, rows)
        self.assertEqual(self.service.store.load(self.pid), before)

        res = material_import.apply(self.service, self.pid, self.row["revision"], "Test reviewer", file, rows)
        self.assertEqual(res["added"], 15)
        # all new lines are documentary pending; no quotes/suppliers/prices created
        state = self.service.store.load(self.pid)["state"]
        self.assertEqual(len(state["suppliers"]), 0)
        self.assertEqual(len(state["quotes"]), 0)
        added = [l for l in state["lines"] if l.get("material_import_sig")]
        self.assertEqual(len(added), 15)
        self.assertTrue(all(l["quantity_status"] in ("PENDING_VERIFICATION",) for l in added))
        # documentary rows keep their documentary quantity; none reported as field-confirmed
        self.assertTrue(all(not l.get("reviewed_by") for l in added))
        # second apply is idempotent (skips duplicates)
        res2 = material_import.apply(self.service, self.pid, res["revision"], "Test reviewer", file, rows)
        self.assertTrue(res2.get("duplicate_apply") or res2["added"] == 0)

    @unittest.skipUnless((ROOT / "data/Imports/materiales/04_Tacoma_Gonyea.csv").exists() and (ROOT / "data/Imports/materiales/05_Tacoma_Orangegate.csv").exists(), "CSV de proyectos no incluidos en ZIP de código")
    def test_pending_measurement_keeps_none_quantity(self):
        file, rows = load_material_rows(str(ROOT), "05_Tacoma_Orangegate.csv")
        p = material_import.preview(self.service, self.pid, file, rows)
        # orangegate rows are PENDIENTE DE MEDICIÓN -> quantity stays None
        self.assertTrue(p["proposed"])
        self.assertTrue(all(pr["state"] is None for pr in p["proposed"]))
        self.assertTrue(all(pr["quantity"] is None for pr in p["proposed"]))

    @unittest.skipUnless((ROOT / "data/Imports/materiales/04_Tacoma_Gonyea.csv").exists() and (ROOT / "data/Imports/materiales/05_Tacoma_Orangegate.csv").exists(), "CSV de proyectos no incluidos en ZIP de código")
    def test_apply_requires_confirmation_when_approval_exists(self):
        self.ready(); self.act("approve", {"human_confirmation": True})
        file, rows = load_material_rows(str(ROOT), "04_Tacoma_Gonyea.csv")
        with self.assertRaises(ValueError):
            material_import.apply(self.service, self.pid, self.row["revision"], "Test reviewer", file, rows)
        # after an explicit human confirmation it applies without overwriting existing lines
        before_lines = len(self.service.store.load(self.pid)["state"]["lines"])
        res = material_import.apply(self.service, self.pid, self.row["revision"], "Test reviewer", file, rows, confirm=True)
        self.assertEqual(res["added"], 15)
        self.assertEqual(len(self.service.store.load(self.pid)["state"]["lines"]), before_lines + 15)


if __name__ == "__main__":
    unittest.main()