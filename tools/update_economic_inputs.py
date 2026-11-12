"""Use only documented local bases for the three requested estimates. No default prices."""
from copy import deepcopy
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from bidkit.audit import sha256,normalize
from bidkit.config import ProjectConfig
from bidkit.costing import templates
from bidkit.data_store import read_json,write_json
from finalize_deliveries import source

IDS=('orangegate-park-phase-1','gonyea-playfield','rebid-meridian')


def prepare_gonyea(c,a,p,registry):
    doc='20260925_Gonyea_Playfield_Drawings.pdf'
    review=c.data_dir/'review';review.mkdir(parents=True,exist_ok=True)
    for page in (46,49,52,67,68):
        dest=review/f'Economic-{page}.png'
        shutil.copy2(ROOT/f'data/qa/economic/gonyea-{page}.png',dest)
        s=source(c,doc,page,'SIGN SCHEDULE' if page==46 else 'DETAILS - SIGNS' if page in (67,68) else 'LAYOUT')
        write_json(dest.with_suffix('.json'),{'document':doc,'page':page,'source_sha256':s['sha256'],'image_sha256':sha256(dest)})
    schedule=source(c,doc,46,'SIGN SCHEDULE')
    text=normalize(read_json(c.data_dir/'extractions'/f"{schedule['sha256']}.json")['pages'][45]['text'])
    schedule['excerpt']=text[text.index('SIGN SCHEDULE'):text.index('LAYOUT NOTES')]
    specs=[('S1','Park entry sign - vehicle scale',1,20000,None,None,'1/L3.25 sign; 2/L3.25 footing; approx. 30 SF in legend'),
           ('S2','Park info and rules sign - pedestrian scale',1,20000,None,None,'3/L3.25 sign; 4/L3.25 footing; approx. 21 SF in legend'),
           ('S3','Playground info and rules sign - pedestrian scale',2,None,5000,7500,'1/L3.26 sign; 2/L3.26 footing; approx. 8 SF in legend'),
           ('S5','Bioretention sign',1,None,5000,7500,'4/L3.26; Pierce County Parks sign standards')]
    p['conceptual_cost_references']=[]
    registry['quotes']=[q for q in registry['quotes'] if q['id'] not in {'DOC-S1','DOC-S2','DOC-S3','DOC-S5'}]
    for n,(tag,desc,count,central,low,high,detail) in enumerate(specs,1):
        qid=f'GP-SIGN-{tag}'
        plan=source(c,doc,49,'LAYOUT')
        image=review/'Economic-49.png'
        plan.update(sheet='L1.12',evidence_type='visual_transcription',review_image=image.relative_to(ROOT).as_posix(),review_image_sha256=sha256(image),region_bbox=[.53,.035,.73,.43],region='Sign callouts in the L1.12 plan, not the repeated L1.21 enlargement',transcription=f'{count} EA {tag}. Count of magenta sign leaders in L1.12. S1=1; S2=1; S3=2; S5=1. Black S3 lighting callout at shelter excluded. L1.21 repeats the northern signs and is not added.')
        quantity={'id':qid,'item':desc,'package':'Base - counted signage; price basis unresolved','pricing_scope':'base','unit':'EA','quantity':count,'quantity_status':'CALCULATED_FROM_DOCUMENT','calculation':{'operation':'sum','operands':[1]*count},'basis':'Count of unique sign leaders on L1.12 (PDF 49), checked against L1.00 (PDF 46) and L1.21 (PDF 52); no duplicate enlarged views. Documentary count; not field verified. Counts do not establish the unit basis of the conceptual ESTIMATED COST column.','sources':[plan]}
        old=next((q for q in a['quantities'] if q['id']==qid),None)
        if old is None:a['quantities'].append(quantity)
        else:old.update(quantity)
        material={'id':'M-'+qid,'quantity_id':qid,'description':desc,'unit':'EA','specification':detail+'; fabrication, foundation, supply and installation price inclusions unresolved','sources':[schedule,plan]}
        old=next((m for m in a['materials'] if m['quantity_id']==qid),None)
        if old is None:a['materials'].append(material)
        else:old.update(material)
        item=next((i for i in p['items'] if i['quantity_id']==qid),None)
        if item is None:
            item={'quantity_id':qid,'effect':'ADD','components':[]};p['items'].append(item)
        item.update(composition_complete=False,composition_reference='Counted physical sign assembly only. No supported unit price; clarify conceptual cost basis and fabrication/supply/foundation/installation scope.')
        component=next((r for r in item['components'] if r['id']==qid+'-package'),None)
        if component is None:
            component={'id':qid+'-package'};item['components'].append(component)
        component.update(kind='material',description=desc+' — counted assembly, price pending',applicability='INCLUDED',method='FACTOR',resource_unit='EA',factor=1,productivity=None,waste_fraction=None,quote_id=None,basis='One physical sign assembly per counted sign, not a price assumption. Waste and purchase inclusions require review.',basis_source={'reference':f'{doc} PDF 49 L1.12; SHA256 {schedule["sha256"]}'},taxable=None,material_package=True,material_specification=detail,material_sources=[schedule,plan],procurement_key=tag+'|sign-assembly',procurement_note='Precio pendiente. Referencias_Conceptuales conserva el importe del diseñador sin unidad ni inclusiones económicas definidas. Confirmar si es por unidad/tipo/conjunto y si comprende fabricación, suministro, cimentación, instalación, permisos, flete e impuestos. No multiplicar ni sumar esas referencias.')
        p['conceptual_cost_references'].append({'id':'CONCEPT-'+tag,'quantity_id':qid,'tag':tag,'description':desc,'central':central,'low':low,'high':high,'unit':None,'date':'2026-09-25','classification':'CONCEPTUAL_REFERENCE_NOT_UNIT_PRICE','cost_basis':'UNSPECIFIED; not confirmed per sign, per type or per set','fabrication':'NOT_SPECIFIED','supply':'NOT_SPECIFIED','installation':'NOT_SPECIFIED','aggregation_allowed':False,'sources':[schedule],'detail_sources':[source(c,doc,67 if tag in ('S1','S2') else 68,'DETAILS - SIGNS')],'note':'Different sign-type rows, not evidence of duplicated text. ESTIMATED COST does not define unit or included services; do not extend by count or aggregate until clarified. L3.25/L3.26 show construction details but do not define monetary scope. L1.00 legend references to L3.27/L3.28 do not match the supplied alternate-detail sheets; use direct sign details and request confirmation.'})
    for q in a['quantities']:
        if q['id']=='P-Q-05':
            q['item']='Remaining furnishings, fences and retaining work; excludes counted GP-SIGN-S1/S2/S3/S5 packages'
            q['missing_information']='Measure remaining site furnishings/fences/retaining work and unpriced dog-waste stations. Exclude the five signs already counted in GP-SIGN-S1/S2/S3/S5; do not add L1.21 duplicates.'
    for m in a['materials']:
        if m['quantity_id']=='P-Q-05':m['description']=next(q['item'] for q in a['quantities'] if q['id']=='P-Q-05')
    if 'GP-SIGN-S1' not in a['coverage']:a['coverage']+='; expanded economic subset GP-SIGN-S1/S2/S3/S5 from L1.00/L1.12, separate from remaining pending scope.'
    for pending in a['pending']:
        if pending['id']=='P-01':pending.update(issue='Full takeoff incomplete; planting subset plus five signs in four physical sign types counted.',action='Measure remaining work; exclude GP-SIGN-S1/S2/S3/S5 and duplicate enlargements.')
        if pending['id']=='P-02':pending.update(issue='All item costs pending. Four conceptual sign references lack a monetary unit and included-services definition; they are not usable unit prices.',action='Clarify sign reference basis and obtain quotes and resource compositions. Keep owner global budget and unaggregated conceptual references separate from calculated costs.')


def enrich(c,a,p):
    materials={m['quantity_id']:m for m in a['materials']}
    quantities={q['id']:q for q in a['quantities']}
    for item in p['items']:
        q=quantities[item['quantity_id']];m=materials[q['id']]
        for resource in item['components']:
            if resource['kind']!='material':continue
            if resource['id']=='LP-A-11-soil-preparation':continue
            resource['description']=m['description']
            resource.update(material_specification=m['specification'],material_sources=m['sources'])
            resource.setdefault('procurement_note','Cantidad documental neta. No incluye merma no documentada; confirmar presentación, dimensiones, flete, impuestos y condiciones de compra.')
            if q['quantity'] is not None and q['unit'] in ('EA','LF','SF','PILE') and resource.get('factor') is None:
                resource.update(method='FACTOR',resource_unit=q['unit'],factor=1,basis='Dimensional identity: one unit of the scheduled material/assembly per identical takeoff unit; not a production rate or waste assumption.',basis_source={'reference':m['sources'][0]['document']+' PDF '+str(m['sources'][0]['page'])+'; '+q['id']},applicability='INCLUDED')
            if 'seed mix' in m['description'].lower():
                resource.update(factor=None,resource_unit=None,basis='Scheduled seeded area is not seed purchase weight. Application rate/mix weight and bag size must be documented.',basis_source={'reference':m['sources'][0]['document']+' PDF '+str(m['sources'][0]['page'])})
            if c.id=='orangegate-park-phase-1' and q['id'] in ('LP-A-11','LP-B-13'):
                resource.update(description='Mulch — '+q['id'],resource_unit='CY',factor=1/81,material_specification=m['specification'],basis='Documented 4 inch depth: SF * (4/12) / 27 = CY; factor 1/81. Net design volume, no waste inferred.',basis_source={'reference':m['sources'][0]['document']+' PDF '+str(m['sources'][0]['page'])+' LP02; auxiliary LP-C-02/03 not charged twice.'})
                resource['procurement_note']='Volumen neto a 4 pulgadas; tipo/granulometría, densidad, compactación, suministro y merma por confirmar. No reutilizar el precio ficticio de QA. Preparación del suelo no incluida en este recurso.'
            # Only demonstrably identical physical plants are pooled; scopes are still separate.
            botanical=m['description'].split(' / ')[0].split(' - ')[0].casefold()
            stock=re.search(r'#\d+|4 inch pot|36 inch live stakes',m['specification'],re.I)
            key=(botanical+'|'+stock.group(0).casefold()) if stock and (q['id'].startswith('GP-PL') or q['id'].startswith('MER-PL') or q['id'].startswith('LP-')) else m['description'].casefold()+'|'+m['specification'].casefold()
            if 'frond' in m['specification'].lower():key+='|minimum 3 green fronds'
            resource['procurement_key']=key
        if c.id=='orangegate-park-phase-1' and q['id']=='LP-A-11' and not any(r['id']=='LP-A-11-soil-preparation' for r in item['components']):
            resource=deepcopy(item['components'][0]);resource.update(id='LP-A-11-soil-preparation',description='Enmiendas y preparación de suelo — composición por confirmar',resource_unit=None,factor=None,quote_id=None,applicability='PENDING',material_specification='A4 section 32 91 13; soil tests and amendment composition required',procurement_key='soil-preparation-LP-A-11',procurement_note='Pendiente de composición y consumo; no incluido en el volumen de mulch.',basis='No amendment consumption inferred from surface area.')
            item['components'].append(resource)


def main():
    for pid in IDS:
        c=ProjectConfig(ROOT,pid);a=read_json(c.project_dir/'analysis.json');p=read_json(c.project_dir/'pricing.json');registry=read_json(c.project_dir/'quotes.json')
        if pid=='gonyea-playfield':prepare_gonyea(c,a,p,registry)
        enrich(c,a,p)
        p.update(as_of='2026-10-26',currency='USD')
        p['quote_input_slots']=max(10,len(p['items'])*2+10)
        if pid=='orangegate-park-phase-1':
            refs=[{'id':'OWNER-BASE','scope':'Project advertisement; base/alternate split not stated','central':None,'low':6000000,'high':6700000,'date':None,'date_note':'Advertisement does not state an issue date on cited page; procurement 2026-MPW-241. No escalation inferred.','tax':'Excludes WA State sales tax','sources':[source(c,'SPECS DIV 00 - Cover and Pages 1-112.pdf',4,'PROJECT ESTIMATE:')]}]
        elif pid=='gonyea-playfield':
            refs=[{'id':'OWNER-BASE','scope':'Basic Work','central':3390000,'low':None,'high':None,'date':None,'date_note':'Invitation issue date not printed on cited page; procurement 2026-MPW-244. No escalation inferred.','tax':'Excludes Washington State sales tax','sources':[source(c,'Invite to Bid.pdf',1,'PROJECT ESTIMATE:')]}]
        else:
            refs=[{'id':rid,'scope':scope,'central':value,'low':None,'high':None,'date':None,'date_note':'Advertisement identifies bid opening 2026-09-02; issue date not printed on cited page. Supplied record, not confirmation of current procurement status.','tax':'Tax inclusion in A/E reference not stated on cited page; confirm, do not apply a rate.','sources':[source(c,'Specs - Unlocked.pdf',9,'A/E ESTIMATE:')]} for rid,scope,value in [('AE-BASE','Base',940347),('AE-ALT1','Alternate 1 sidewalk replacement in lieu of repair',82250),('AE-ALT2','Alternate 2 EWF/PIP surfacing substitution',392728)]]
        p['documentary_cost_references']=refs
        p['economic_note']='Documentary owner/A-E reference values are benchmarks, not calculated item totals. They are not allocated to measured items and must never be added to the partial estimate. No material, productivity, indirect, contingency, margin or tax rate is invented.'
        write_json(c.project_dir/'analysis.json',a);write_json(c.project_dir/'pricing.json',p);write_json(c.project_dir/'quotes.json',registry)
        print(pid+': documentary references and exact material compositions prepared')


if __name__=='__main__':main()
