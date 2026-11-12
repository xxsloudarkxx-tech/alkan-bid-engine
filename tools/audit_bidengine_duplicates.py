"""Read-only by-content audit of the Bid Engine workspace. No deletion."""
from pathlib import Path
from collections import defaultdict
import os, hashlib, json
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "issues" / "bidengine_duplicate_audit_2026-11-06.json"
buckets=defaultdict(lambda: {"bytes":0, "count":0})
by_size=defaultdict(list)
files=[]
errors=[]
for base,dirs,names in os.walk(ROOT,followlinks=False):
    dirs[:]=[x for x in dirs if not (Path(base)/x).is_symlink()]
    for fn in names:
        p=Path(base)/fn
        try:
            if p.is_symlink():continue
            st=p.stat()
        except OSError as ex:
            errors.append({"path":str(p.relative_to(ROOT)),"error":str(ex)});continue
        rel=p.relative_to(ROOT).as_posix()
        key=rel.split("/")[0] if "/" in rel else "(root)"
        buckets[key]["bytes"]+=st.st_size
        buckets[key]["count"]+=1
        files.append((p,rel,st.st_size))
        if st.st_size>=65536: by_size[st.st_size].append((p,rel))
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()
groups=[]
for size,items in by_size.items():
    if len(items)<2:continue
    byhash=defaultdict(list)
    for path,rel in items:
        try:byhash[sha(path)].append(rel)
        except OSError as ex:errors.append({"path":rel,"error":str(ex)})
    for digest,paths in byhash.items():
        if len(paths)>1:groups.append({"size":size,"count":len(paths),"reclaimable_bytes":size*(len(paths)-1),"sha256":digest,"paths":sorted(paths)})
groups.sort(key=lambda r:r["reclaimable_bytes"],reverse=True)
biggest=sorted(({"size":size,"path":rel} for _,rel,size in files),key=lambda v:v["size"],reverse=True)[:40]
summary={"total_files":len(files),"total_logical_bytes":sum(x[2] for x in files),
         "folders":dict(sorted(buckets.items(),key=lambda z:z[1]["bytes"],reverse=True)),
         "potential_bytes":sum(g["reclaimable_bytes"] for g in groups),
         "duplicate_groups":groups,"largest_files":biggest,"errors":errors}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")
print("TOTAL_FILES",summary["total_files"],"LOGICAL_GiB",round(summary["total_logical_bytes"]/2**30,3),"ERRORS",len(errors))
print("TOP_FOLDERS")
for key,v in list(summary["folders"].items())[:22]:print(key,"files",v["count"],"GiB",round(v["bytes"]/2**30,3))
print("DUP_GROUPS>=64KiB",len(groups),"THEORETICAL_GiB",round(summary["potential_bytes"]/2**30,3))
for g in groups[:45]:
    print("DUP",round(g["reclaimable_bytes"]/2**20,2),"MiB",g["count"],"x",round(g["size"]/2**20,2),"MiB","PATHS",repr(g["paths"][:8]))
print("LARGEST_FILES")
for item in biggest[:25]:print("LARGE",round(item["size"]/2**20,1),"MiB",item["path"])
print("REPORT",OUT)
