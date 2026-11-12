"""Verify archive contents are exactly present outside the zip. Read-only."""
from pathlib import Path
import hashlib, json, zipfile
ROOT=Path(__file__).resolve().parents[1]
docs=ROOT/"docs"
results=[]
def sha_stream(f):
    h=hashlib.sha256()
    for chunk in iter(lambda:f.read(2**20),b""):h.update(chunk)
    return h.hexdigest()
for archive in sorted(docs.glob("*.zip")):
    extracted=docs/archive.stem
    report={"archive":str(archive.relative_to(ROOT)),"extracted_dir":str(extracted.relative_to(ROOT)),"zip_bytes":archive.stat().st_size,"entries":[]}
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if item.is_dir():continue
            safe=Path(item.filename.replace("\\","/").lstrip("/"))
            if ".." in safe.parts:
                report["entries"].append({"name":item.filename,"status":"UNSAFE"});continue
            p=extracted/safe
            if not p.exists():
                report["entries"].append({"name":item.filename,"status":"MISSING"});continue
            if p.stat().st_size!=item.file_size:
                report["entries"].append({"name":item.filename,"status":"SIZE_MISMATCH"});continue
            with z.open(item) as zin, p.open("rb") as source:
                hash_zip=sha_stream(zin);hash_file=sha_stream(source)
            report["entries"].append({"name":item.filename,"status":"MATCH" if hash_zip==hash_file else "HASH_MISMATCH","sha256":hash_zip if hash_zip==hash_file else None})
    report["all_present_identical"]=bool(report["entries"]) and all(e["status"]=="MATCH" for e in report["entries"])
    print("ARCHIVE",archive.name,"MB",round(archive.stat().st_size/2**20,2),"FILES",len(report["entries"]),"EXACT",report["all_present_identical"])
    for bad in report["entries"]:
        if bad["status"]!="MATCH":print("MISMATCH",bad)
    results.append(report)
out=ROOT/"issues"/"bidengine_archives_extracted_hash_audit_2026-11-06.json"
out.write_text(json.dumps(results,indent=2),encoding="utf-8")
print("SAVINGS_IF_ARCHIVES_REMOVED_MiB",round(sum(x["zip_bytes"] for x in results if x["all_present_identical"])/2**20,2))
