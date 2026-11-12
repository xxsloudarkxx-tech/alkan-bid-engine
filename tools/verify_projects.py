"""Exercise real CLI stages, prove reproduction, and compare originals to ZIPs."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import hashlib
from io import StringIO
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bidkit.__main__ import main as cli
from bidkit.audit import sha256
from bidkit.config import ProjectConfig, find_project_root, list_projects
from bidkit.data_store import read_json, write_json


def hashes(config):
    return {p.relative_to(config.root).as_posix(): sha256(p) for p in sorted(config.output_dir.iterdir()) if p.is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", action="append")
    args = parser.parse_args()
    root = find_project_root()
    names = args.project or ["Orangegate Park Phase 1"] + [n for n in list_projects(root) if n != "Orangegate Park Phase 1"]
    result = {"projects": [], "archives": [], "policy": "Technical checks establish traceability and reproduction, not completeness of measurement or fitness for bid submission."}
    for name in names:
        c = ProjectConfig(root, name)
        original = {p: sha256(p) for p in c.source_assets}
        commands = []
        for command in ("audit", "takeoff", "estimate", "build", "validate"):
            with redirect_stdout(StringIO()):
                code = cli([command, "--root", str(root), "--project", c.id])
            if code:
                raise RuntimeError(f"{c.id}: {command} returned {code}")
            commands.append({"command": command, "exit_code": code})
        before = hashes(c)
        cached = {p: (sha256(p), p.stat().st_mtime_ns) for p in (c.data_dir / "extractions").glob("*.json")}
        def no_pdf_reparse(*args, **kwargs):
            raise AssertionError("Existing PDF cache must be reused")
        with patch("bidkit.audit.pdfium.PdfDocument", side_effect=no_pdf_reparse), redirect_stdout(StringIO()):
            assert cli(["build", "--root", str(root), "--project", c.id]) == 0
        assert before == hashes(c), f"Outputs are not byte reproducible for {c.id}"
        assert cached == {p: (sha256(p), p.stat().st_mtime_ns) for p in cached}, "Extraction cache was rewritten"
        assert original == {p: sha256(p) for p in c.source_assets}, "Original document changed"
        validation = read_json(c.output_dir / "validation_report.json")
        result["projects"].append({"project_id": c.id, "commands": commands, "technical_validation": validation["technical_validation"], "known_quantities": validation["measured_quantity_rows"], "pending_quantities": validation["pending_quantity_rows"], "byte_reproducible": True, "pdf_reparses_on_rebuild": 0, "source_documents_unchanged": True, "artifact_hashes": before})
        archive = root / "docs" / f"{c.project_name}.zip"
        if archive.exists():
            matched = []
            with zipfile.ZipFile(archive) as packed:
                for member in packed.infolist():
                    if member.is_dir() or member.filename == "/":
                        continue
                    # Archives provided here have flat names. Never extract or write them.
                    destination = c.source_root / member.filename
                    if not destination.resolve().is_relative_to(c.source_root.resolve()):
                        raise ValueError("Unexpected archive path")
                    digest = hashlib.sha256()
                    with packed.open(member) as content:
                        for block in iter(lambda: content.read(1024*1024), b""):
                            digest.update(block)
                    assert destination.is_file() and sha256(destination) == digest.hexdigest(), f"Original differs from supplied ZIP: {destination}"
                    matched.append(member.filename)
            result["archives"].append({"archive": archive.relative_to(root).as_posix(), "archive_sha256": sha256(archive), "matched_members": matched, "status": "PASS"})
        print(f"{c.id}: PASS, {validation['measured_quantity_rows']} documented/calculated rows; {validation['pending_quantity_rows']} pending", flush=True)
    write_json(root / "data" / "phase_b_validation.json", result)


if __name__ == "__main__":
    main()
