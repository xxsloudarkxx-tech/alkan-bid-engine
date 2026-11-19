"""Tests unitarios para el reciclador y purgador de estimados."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from bidkit.recycler import purge_raw_uploads, purge_superseded_runs, slim_run_artifacts, recycle_all


class TestRecycler(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.runs_dir = self.tmp / "ENTREGAS" / "AGENTE"
        self.runs_dir.mkdir(parents=True)
        self.uploads_dir = self.tmp / "data" / "uploads"
        self.uploads_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _create_mock_run(self, run_id: str, key: str, status: str, started_at: str, files: dict[str, str] = None):
        rdir = self.runs_dir / run_id
        rdir.mkdir(parents=True, exist_ok=True)
        state = {
            "id": run_id,
            "key": key,
            "status": status,
            "started_at": started_at,
        }
        (rdir / "run.json").write_text(json.dumps(state), encoding="utf-8")
        if files:
            for fname, content in files.items():
                p = rdir / fname
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
        return rdir

    def test_purge_superseded_when_approved_exists(self):
        # 1 borrador antiguo, 1 borrador reciente, 1 aprobada
        self._create_mock_run("GONYEA_20261118_100000", "GONYEA", "lista", "2026-11-18T10:00:00Z")
        self._create_mock_run("GONYEA_20261118_110000", "GONYEA", "lista", "2026-11-18T11:00:00Z")
        self._create_mock_run("GONYEA_20261118_120000", "GONYEA", "autorizada", "2026-11-18T12:00:00Z")

        res = purge_superseded_runs(self.runs_dir, project_key="GONYEA", dry_run=False)
        self.assertEqual(res["count"], 2)
        # La aprobada debe existir
        self.assertTrue((self.runs_dir / "GONYEA_20261118_120000").exists())
        # Los borradores deben haber sido purgados
        self.assertFalse((self.runs_dir / "GONYEA_20261118_100000").exists())
        self.assertFalse((self.runs_dir / "GONYEA_20261118_110000").exists())

    def test_purge_keeps_latest_draft_when_none_approved(self):
        # 3 borradores sucesivos de un proyecto
        self._create_mock_run("MERIDIAN_20261118_090000", "MERIDIAN", "lista", "2026-11-18T09:00:00Z")
        self._create_mock_run("MERIDIAN_20261118_100000", "MERIDIAN", "lista", "2026-11-18T10:00:00Z")
        self._create_mock_run("MERIDIAN_20261118_110000", "MERIDIAN", "lista", "2026-11-18T11:00:00Z")

        res = purge_superseded_runs(self.runs_dir, project_key="MERIDIAN", keep_latest_drafts=1, dry_run=False)
        self.assertEqual(res["count"], 2)
        # El más reciente sobrevive
        self.assertTrue((self.runs_dir / "MERIDIAN_20261118_110000").exists())
        # Los dos anteriores se purgaron
        self.assertFalse((self.runs_dir / "MERIDIAN_20261118_090000").exists())
        self.assertFalse((self.runs_dir / "MERIDIAN_20261118_100000").exists())

    def test_purge_discardable_runs(self):
        self._create_mock_run("TEST_20261118_080000", "TEST", "cancelada", "2026-11-18T08:00:00Z")
        self._create_mock_run("TEST_20261118_083000", "TEST", "interrumpida", "2026-11-18T08:30:00Z")
        self._create_mock_run("TEST_20261118_090000", "TEST", "lista", "2026-11-18T09:00:00Z")

        res = purge_superseded_runs(self.runs_dir, project_key="TEST", purge_failed=True, dry_run=False)
        self.assertEqual(res["count"], 2)
        self.assertTrue((self.runs_dir / "TEST_20261118_090000").exists())

    def test_dry_run_does_not_delete(self):
        self._create_mock_run("TEST_20261118_080000", "TEST", "cancelada", "2026-11-18T08:00:00Z")
        res = purge_superseded_runs(self.runs_dir, dry_run=True)
        self.assertEqual(res["count"], 1)
        self.assertTrue((self.runs_dir / "TEST_20261118_080000").exists())

    def test_slim_run_artifacts(self):
        rdir = self._create_mock_run(
            "TEST_RUN", "TEST", "lista", "2026-11-18T10:00:00Z",
            files={
                "drawings_zip/sheet1.pdf": "raw bytes...",
                "temp.tmp": "temporary...",
                "TEST_01_Cost_Analysis.pdf": "pdf...",
            }
        )
        res = slim_run_artifacts(rdir, dry_run=False)
        self.assertTrue((rdir / "TEST_01_Cost_Analysis.pdf").exists())
        self.assertFalse((rdir / "drawings_zip").exists())
        self.assertFalse((rdir / "temp.tmp").exists())
        self.assertGreater(res["freed_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
