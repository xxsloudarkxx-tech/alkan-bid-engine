"""Focused arithmetic/link verification of the three economic deliveries. No PDF audits."""
from decimal import Decimal
from pathlib import Path
import sys

from openpyxl import load_workbook
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bidkit.audit import sha256,load_audit,normalize
from bidkit.config import ProjectConfig
from bidkit.data_store import read_json,write_json
from bidkit.purchase_workbook import material_resources
from bidkit.reports import validation_report
from economic_deliveries import valued_items
from update_economic_inputs import IDS
from finalize_deliveries import FOLDERS
from qa_excel_formulas import Evaluator


def main():
    results=[];checks=0
    for pid in IDS:
        c=ProjectConfig(ROOT,pid);base=ROOT/'ENTREGAS'/c.project_name
        assert validation_report(c)['technical_validation']=='PASS'
        cost=read_json(c.data_dir/'estimate/cost_result.json')
        book=load_workbook(base/FOLDERS[1]/'Presupuesto_Principal.xlsx')
        materials=load_workbook(base/FOLDERS[2]/'Lista_Detallada_de_Materiales.xlsx')
        assert materials.active.title=='Materiales_Detalle' and book.active.title=='Resumen_Economico'
        assert book.sheetnames==materials.sheetnames
        for sheet in book:
            assert list(sheet.values)==list(materials[sheet.title].values),sheet.title
        assert book['LEEME_Materiales']['B3'].value==cost['pricing_fingerprint']
        e=Evaluator(book);count=0
        for sheet in book:
            for row in sheet:
                for cell in row:
                    if cell.data_type=='f':e.cell(sheet.title,cell.coordinate);count+=1
        for row,(_,resource) in enumerate(material_resources(cost),2):
            assert book['Materiales_Detalle'][f'A{row}'].value==resource['id']
            expected=resource['item_quantity']*resource['factor'] if resource['item_quantity'] is not None and resource.get('factor') is not None else ''
            got=e.cell('Materiales_Detalle',f'M{row}')
            assert got==expected if expected=='' else abs(got-expected)<1e-8
            for col,key in (('U','extended_cost'),('V','cost_low'),('W','cost_high')):
                expected=resource[key] if resource[key] is not None else ''
                actual=e.cell('Materiales_Detalle',f'{col}{row}')
                assert actual==expected if expected=='' else abs(actual-expected)<.011,(pid,resource['id'],key,actual,expected)
                checks+=1
            if resource.get('waste_fraction') is None:assert e.cell('Materiales_Detalle',f'S{row}')==''
        # Documentary cost references must be present in this project's original cached page.
        docs={d['name']:d for d in load_audit(c)['documents']}
        for quote in cost['quotes']:
            assert quote['kind']=='REAL' and not quote['id'].startswith(('FICT','TEST'))
            for source in quote.get('document_sources',[]):
                doc=docs[source['document']];assert doc['sha256']==source['sha256']
                page=read_json(c.data_dir/'extractions'/f"{doc['sha256']}.json")['pages'][source['page']-1]['text']
                assert normalize(source['excerpt']) in normalize(page)
                for key in ('unit_price','unit_price_low','unit_price_high'):
                    if quote.get(key) is not None:assert f'{quote[key]:,.0f}' in page.replace(' ','')
        assert e.cell('Summary','B7')==''
        assert not valued_items(cost)
        measured=sum(i['quantity'] is not None for i in cost['items'])
        assert e.cell('Resumen_Economico','B11')==measured
        assert abs(e.cell('Resumen_Economico','B12')-measured/len(cost['items']))<1e-12
        assert e.cell('Resumen_Economico','B5')==0
        for ref in cost['settings']['documentary_cost_references']+cost['settings'].get('conceptual_cost_references',[]):
            for source in ref['sources']:
                doc=docs[source['document']];assert doc['sha256']==source['sha256']
                page=read_json(c.data_dir/'extractions'/f"{doc['sha256']}.json")['pages'][source['page']-1]['text']
                assert normalize(source['excerpt']) in normalize(page)
                for field in ('central','low','high'):
                    if ref.get(field) is not None:assert f"{ref[field]:,.0f}" in page.replace(' ','')
        if pid=='gonyea-playfield':
            s=cost['summaries'][0]
            assert (s['known_direct_partial'],s['known_direct_low'],s['known_direct_high'])==(None,None,None)
            assert all(e.cell('Scopes',cell)=='' for cell in ('F2','G2','H2'))
            refs=cost['settings']['conceptual_cost_references'];assert len(refs)==4
            assert {r['tag']:r['central'] for r in refs}=={'S1':20000,'S2':20000,'S3':None,'S5':None}
            assert all(r['unit'] is None and r['aggregation_allowed'] is False for r in refs)
            assert not cost['quotes']
            assert {i['id']:i['quantity'] for i in cost['items'] if i['id'].startswith('GP-SIGN-')}=={'GP-SIGN-S1':1,'GP-SIGN-S2':1,'GP-SIGN-S3':2,'GP-SIGN-S5':1}
            assert (measured,len(cost['items']))==(19,25)
        if pid=='orangegate-park-phase-1':
            rows={book['Materiales_Detalle'][f'A{r}'].value:r for r in range(2,book['Materiales_Detalle'].max_row+1)}
            assert abs(e.cell('Materiales_Detalle',f'M{rows["LP-A-11-material"]}')-2911/81)<1e-9
            assert abs(e.cell('Materiales_Detalle',f'M{rows["LP-B-13-material"]}')-6397/81)<1e-9
            assert e.cell('Materiales_Detalle',f'M{rows["LP-A-11-soil-preparation"]}')==''
            groups=[(book['Resumen_de_Compras'][f'B{r}'].value,e.cell('Resumen_de_Compras',f'I{r}')) for r in range(2,book['Resumen_de_Compras'].max_row+1)]
            assert any(scope=='alternate_5_supply_only' and net==15 for scope,net in groups)
            assert any(scope=='alternate_6_supply_only' and net==4 for scope,net in groups)
        originals=read_json(base/FOLDERS[5]/'Integridad_Originales.json')['originals']
        for asset in originals:assert sha256(c.source_root/asset['file'])==asset['sha256']==sha256(base/FOLDERS[6]/asset['file'])
        manifest=read_json(base/FOLDERS[5]/'MANIFIESTO_ENTREGA.json')
        for file,digest in manifest['files'].items():assert sha256(base/file)==digest,file
        pdf=PdfReader(base/FOLDERS[1]/'Resumen_Economico.pdf');assert len(pdf.pages)>0
        results.append({'project_id':pid,'status':'PASS','formulas_evaluated':count,'material_resource_rows':len(material_resources(cost)),'originals_unchanged':len(originals),'budget_materials_same_inputs_and_formulas':True,'identified_items':len(cost['items']),'document_quantity_items':measured,'percentage_items_with_quantity':100*measured/len(cost['items']),'percentage_items_with_usable_price':0,'valued_partial_items':len(valued_items(cost)),'native_excel_recalculated':False})
        print(c.project_name+': formula arithmetic, exact material links, separated scopes and original hashes PASS',flush=True)
    prior=read_json(ROOT/'data/qa/phase-d/delivery_results.json')
    west=next(p for p in prior['deliveries'] if p['project']=='W Seattle Junction Landbank Park')
    assert sha256(ROOT/west['folder']/FOLDERS[5]/'MANIFIESTO_ENTREGA.json')==west['manifest_sha256']
    write_json(ROOT/'data/qa/economic/verification.json',{'status':'PASS','projects':results,'material_cost_crosschecks':checks,'west_seattle_delivery_unchanged':True,'external_access_attempts':1,'method':'Independent XLSX formula token evaluation against actual cost resources; no native Excel recalculation certification'})


if __name__=='__main__':main()
