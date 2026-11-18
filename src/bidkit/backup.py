"""Verified full-state backup and restore for ALKAN Bid Engine (secrets excluded)."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

BACKUP_AREAS: tuple[str, ...] = ("data", "profiles", "projects", "engineering_docs")
_EXCLUDED_PATTERNS: tuple[str, ...] = ("secrets.json", ".vault-key", ".quickbooks-key", ".env")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_excluded(rel: str) -> bool:
    name = PurePosixPath(rel).name.lower()
    if name in _EXCLUDED_PATTERNS or name.endswith((".key", ".pem", ".p12")):
        return True
    if "/_tmp/" in rel or rel.endswith(".tmp"):
        return True
    return False


def create_backup(root: Path, out_zip: Path, *, org_id: str | None = None) -> dict:
    """Bundle workspace state folders into a SHA-256 verified backup zip archive."""
    root = Path(root).resolve()
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest_files: dict[str, dict] = {}
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for area in BACKUP_AREAS:
            base = root / area
            if not base.exists():
                continue
            for file_path in sorted(p for p in base.rglob("*") if p.is_file()):
                rel = file_path.relative_to(root).as_posix()
                if _is_excluded(rel):
                    continue
                if org_id and area == "data" and f"orgs/{org_id}/" not in rel and rel.startswith("data/orgs/"):
                    continue
                raw = file_path.read_bytes()
                manifest_files[rel] = {"sha256": _sha256_bytes(raw), "bytes": len(raw)}
                zf.writestr(rel, raw)
        manifest = {
            "schema": "alkan-backup/1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "org_filter": org_id,
            "file_count": len(manifest_files),
            "files": manifest_files,
        }
        zf.writestr("BACKUP_MANIFEST.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "zip_path": str(out_zip),
        "zip_sha256": _sha256_bytes(out_zip.read_bytes()),
        "file_count": len(manifest_files),
    }


def _safe_member_path(target_root: Path, member: str) -> Path:
    if "\\" in member or member.startswith("/") or ":" in member:
        raise ValueError(f"Unsafe backup member path: {member!r}")
    parts = PurePosixPath(member).parts
    if any(p in ("..", "") for p in parts):
        raise ValueError(f"Path traversal blocked in backup member: {member!r}")
    resolved = (target_root / member).resolve()
    if not resolved.is_relative_to(target_root.resolve()):
        raise ValueError(f"Backup member escapes target root: {member!r}")
    return resolved


def verify_backup(zip_path: Path) -> dict:
    """Validate zip paths and verify SHA-256 hashes against BACKUP_MANIFEST.json."""
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        if "BACKUP_MANIFEST.json" not in names:
            raise ValueError("Missing BACKUP_MANIFEST.json inside backup archive.")
        manifest = json.loads(zf.read("BACKUP_MANIFEST.json").decode("utf-8"))
        files = manifest.get("files") or {}
        mismatches: list[str] = []
        for rel, meta in files.items():
            if rel not in names:
                mismatches.append(f"missing:{rel}")
                continue
            digest = _sha256_bytes(zf.read(rel))
            if digest != meta.get("sha256"):
                mismatches.append(f"hash_mismatch:{rel}")
        return {
            "valid": not mismatches,
            "file_count": len(files),
            "mismatches": mismatches,
            "created_at": manifest.get("created_at"),
        }


def restore_backup(zip_path: Path, target_root: Path, *, dry_run: bool = False) -> dict:
    """Verify backup integrity and restore files safely into target_root."""
    target_root = Path(target_root).resolve()
    verification = verify_backup(zip_path)
    if not verification["valid"]:
        raise ValueError(f"Backup verification failed: {verification['mismatches']}")
    restored: list[str] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = json.loads(zf.read("BACKUP_MANIFEST.json").decode("utf-8"))
        for rel in sorted(manifest.get("files", {})):
            dest = _safe_member_path(target_root, rel)
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(rel))
            restored.append(rel)
    return {"restored_count": len(restored), "dry_run": dry_run, "files": restored}
