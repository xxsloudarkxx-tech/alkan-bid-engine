"""Dry-run by default. Restore code only, retaining dossiers and later user work."""
from pathlib import Path
from datetime import datetime, UTC
import argparse
import hashlib
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--apply",action="store_true");args=parser.parse_args()
    audit=ROOT/"data/v2_audit";manifest=json.loads((audit/"release_manifest.json").read_text(encoding="utf-8"))
    rows=[r for r in manifest["files"] if r["status"]!="unchanged"]
    for row in rows:
        target=(ROOT/row["path"]).resolve()
        if not target.is_relative_to(ROOT): raise ValueError("Ruta inválida en manifiesto")
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=row["sha256"]:
            raise ValueError("Hay cambios posteriores; conservar y conciliar antes de revertir: "+row["path"])
    print("Code files to restore or archive:",len(rows))
    if not args.apply:
        for row in rows:print(row["status"],row["path"])
        print("Dry run. No files changed. Use --apply only after stopping the local server.")
        return
    backup=audit/("reverted_v2_code_"+datetime.now(UTC).strftime("%Y%m%dT%H%M%S"));backup.mkdir()
    with zipfile.ZipFile(audit/"before_v2_code.zip") as z:
        originals=set(z.namelist())
        for row in rows:
            target=ROOT/row["path"]
            if target.exists():
                archived=backup/row["path"];archived.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,archived)
            if row["path"] in originals:
                target.write_bytes(z.read(row["path"]))
            elif row["path"]==".gitignore":
                lines=target.read_text(encoding="utf-8").splitlines()
                target.write_text("\n".join(l for l in lines if l not in ("tmp/","projects/*/intelligence/"))+"\n",encoding="utf-8")
            elif target.exists(): target.unlink()
    print("Previous code restored. All project documents, revisions and exports retained.")


if __name__=="__main__":main()
