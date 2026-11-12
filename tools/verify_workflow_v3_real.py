"""Real local PDF through EstimateWorkflow, isolated; no invented prices or approvals."""
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from hashlib import sha256
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bidkit.estimate_workflow import EstimateWorkflow
from bidkit.config import ProjectConfig, list_projects
from bidkit.audit import validate_source_integrity


def main():
    configs=[ProjectConfig(ROOT,name) for name in list_projects(ROOT) if 'synthetic' not in name.lower()]
    original=min((p for c in configs for p in c.source_files),key=lambda p:p.stat().st_size)
    digest=sha256(original.read_bytes()).hexdigest()
    with TemporaryDirectory(dir=ROOT/'tmp') as temp:
        flow=EstimateWorkflow(Path(temp));row=flow.create({'name':'Isolated real document QA','work_type':'other','contractual_relationship':'general_contractor'},'Local QA',str(uuid4()))
        pid=row['project_id'];row=flow.upload(pid,row['revision'],'Local QA',[(original.name,original.read_bytes())],str(uuid4()))
        row=flow.execute(pid,row['revision'],'Local QA','analyze',{},str(uuid4()))
        assert row['workflow_view']['analyzed']
        assert not row['workflow_view']['ready_for_approval']
        blocked=False
        try:flow.export(pid,row['revision'],'Local QA',['proposal'],'en',True,str(uuid4()))
        except ValueError:blocked=True
        assert blocked
        exported=flow.export(pid,row['revision'],'Local QA',['internal','supplier'],'en',False,str(uuid4()))
        for a in exported['artifacts']:assert flow.store.child(pid,'exports',a['name']).read_bytes().startswith(b'%PDF-')
        reopened=EstimateWorkflow(Path(temp)).get(pid)
        assert reopened['revision']==exported['row']['revision']
        assert sha256(original.read_bytes()).hexdigest()==digest
        result={'status':'PASS','real_document':original.relative_to(ROOT).as_posix(),'sha256':digest,'original_unchanged':True,
                'pages':len(row['state']['documents'][0]['pages']),'text_characters':sum(len(p['text']) for p in row['state']['documents'][0]['pages']),
                'workflow_analysis_persisted':True,'reopened_from_disk':True,'drafts':['internal','supplier'],'final_proposal_blocked':blocked,
                'real_estimate_approved':False,'external_supplier_connection':False,'existing_projects':[]}
    for c in configs:
        rows=validate_source_integrity(c);assert all(r['status']=='PASS' for r in rows)
        result['existing_projects'].append({'project_id':c.id,'original_files':len(rows),'integrity_pass':True})
    audit=ROOT/'data/v3_audit';audit.mkdir(exist_ok=True)
    (audit/'real_workflow_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
