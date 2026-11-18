"""Candado de paridad motor <-> app móvil.

Garantiza que «el motor no pierde lógica nunca»: el precio y el costo directo que la
API móvil devuelve (quick-package) son EXACTAMENTE los que calcula el motor
(`package_method.compute`) sobre el mismo paquete escrito en disco. Si algún día la
capa móvil recalcula por su cuenta o se desvía del motor, esta prueba falla.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT_REPO = Path(__file__).resolve().parents[1]
if str(ROOT_REPO / "src") not in sys.path:
    sys.path.insert(0, str(ROOT_REPO / "src"))

from bidkit.mobile_api import MobileBidEngineAPI  # noqa: E402
from bidkit.package_method import compute, package_from_dict  # noqa: E402

# (especialidad, perfil) — perfiles que existen en profiles/
CASES = [
    ("metal", "ss_custom_iron_works"),
    ("tablaroca", "generico_sin_marca"),
    ("pintura", "generico_sin_marca"),
    ("molduras", "diaz_finish_carpenter"),
]


class MobileEngineParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="alkan_parity_"))
        for folder in ("profiles", "examples", "data"):
            src = ROOT_REPO / folder
            if src.exists():
                shutil.copytree(src, self.tmp / folder)
        shutil.copytree(
            ROOT_REPO / "src" / "bidkit" / "estimator_agent" / "knowledge",
            self.tmp / "src" / "bidkit" / "estimator_agent" / "knowledge",
        )
        self.api = MobileBidEngineAPI(self.tmp)
        _, est = self.api.handle_safe(
            "POST",
            "/api/mobile/auth/bootstrap",
            body={"username": "estimator", "password": "Estimator!2026"},
        )
        self.hdrs = {"Authorization": f"Bearer {est['token']}"}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_dir(self, run_id: str) -> Path:
        return self.api.app.runs.base / run_id

    def test_api_price_equals_engine_compute(self) -> None:
        for specialty, profile in CASES:
            with self.subTest(specialty=specialty):
                key = f"PAR{specialty[:3].upper()}"
                st, summary = self.api.handle_safe(
                    "POST",
                    "/api/mobile/runs/quick-package",
                    body={
                        "key": key,
                        "project_title": f"Parity {specialty}",
                        "profile": profile,
                        "specialty": specialty,
                        "county": "King",
                        "voice_notes": "Prueba de paridad.",
                    },
                    headers=self.hdrs,
                )
                self.assertEqual(st, 200, summary)
                run = summary["run"]
                fin = summary["financials"]  # lo que la app le muestra al usuario
                run_dir = self._run_dir(run["id"])

                # 1) El paquete escrito en disco, recomputado por el MOTOR directamente.
                pkg = json.loads((run_dir / f"{key.lower()}.json").read_text(encoding="utf-8"))
                engine = compute(package_from_dict(pkg))

                # 2) El manifiesto que generó build_package (lo que usa la app).
                manifest = json.loads(
                    (run_dir / f"{key}_package_manifest.json").read_text(encoding="utf-8")
                )
                man_totals = manifest["computation"]["totals"]

                # Paridad exacta: lo que muestra la app == manifest == motor.
                self.assertEqual(
                    str(fin["sell_price"]),
                    str(engine["price"]),
                    f"{specialty}: precio app {fin['sell_price']} != motor {engine['price']}",
                )
                self.assertEqual(
                    str(fin["direct_cost"]),
                    str(engine["direct"]),
                    f"{specialty}: directo app {fin['direct_cost']} != motor {engine['direct']}",
                )
                self.assertEqual(str(man_totals["price"]), str(engine["price"]))
                self.assertEqual(str(man_totals["direct"]), str(engine["direct"]))

    def test_api_does_not_invent_qa_or_totals_keys(self) -> None:
        """El manifiesto trae la estructura del motor (totals con price/direct), no una inventada."""
        _, summary = self.api.handle_safe(
            "POST",
            "/api/mobile/runs/quick-package",
            body={
                "key": "PARCHK",
                "project_title": "Parity keys",
                "profile": "ss_custom_iron_works",
                "specialty": "metal",
                "county": "King",
            },
            headers=self.hdrs,
        )
        run_dir = self._run_dir(summary["run"]["id"])
        manifest = json.loads((run_dir / "PARCHK_package_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("computation", manifest)
        self.assertLessEqual({"price", "direct"}, set(manifest["computation"]["totals"]))


if __name__ == "__main__":
    unittest.main()
