"""Read-only original PDF check plus isolated ingestion; never fabricates live prices."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bidkit.audit import sha256, validate_source_integrity
from bidkit.config import ProjectConfig, list_projects
from bidkit.intelligence import Intelligence
from bidkit.intelligence_reports import export_document
from bidkit.project_schema import load_analysis, validate_analysis


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--audit-dir",type=Path,default=ROOT/"data/v2_audit")
    args=parser.parse_args()
    real = [ProjectConfig(ROOT, name) for name in list_projects(ROOT) if "synthetic" not in name.lower()]
    originals = [p for config in real for p in config.source_files]
    path = min(originals, key=lambda p:p.stat().st_size)
    before = sha256(path)
    with TemporaryDirectory(dir=ROOT / "tmp") as temp:
        service=Intelligence(Path(temp))
        row=service.create({"name":"Read-only original document verification","work_type":"other","contractual_relationship":"general_contractor"},"Local QA")
        row=service.upload(row["project_id"],row["revision"],"Local QA",[(path.name,path.read_bytes())])
        row=service.transact(row["project_id"],row["revision"],"Local QA","analyze",{})
        for kind in ("supplier","internal"):
            assert export_document(service,row["project_id"],kind).read_bytes().startswith(b"%PDF-")
        assert row["state"]["result"]["status"] not in ("APPROVED","PROPOSAL_ISSUED")
        assert sha256(path)==before
        result={"real_document":path.relative_to(ROOT).as_posix(),"sha256":before,
                "original_unchanged":True,"parser":row["state"]["documents"][0]["parser"],
                "pages":len(row["state"]["documents"][0]["pages"]),
                "text_characters":sum(len(p["text"]) for p in row["state"]["documents"][0]["pages"]),
                "live_supplier_connection":False,"real_commercial_estimate_approved":False,
                "tested_flow":"Original PDF → isolated upload → extraction → candidates → persisted revision → draft internal/supplier export",
                "existing_projects":[]}
    for config in real:
        errors=validate_analysis(config,load_analysis(config))
        integrity=validate_source_integrity(config)
        result["existing_projects"].append({"project_id":config.id,"analysis_errors":errors,
            "original_files":len(integrity),"integrity_pass":all(r["status"]=="PASS" for r in integrity)})
    args.audit_dir.mkdir(parents=True,exist_ok=True)
    output=args.audit_dir/"real_document_results.json"
    output.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps(result,indent=2,ensure_ascii=True))


if __name__=="__main__": main()
