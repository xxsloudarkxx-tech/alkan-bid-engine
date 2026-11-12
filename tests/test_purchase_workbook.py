from copy import deepcopy
from pathlib import Path

import pytest
from openpyxl import load_workbook

from bidkit.costing import evaluate
from bidkit.cost_workbooks import build_cost_workbook,import_cost_workbook
from bidkit.data_store import read_json,write_json
from test_costing import fixture_inputs


def setup_book(c,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'tools'))
    from qa_excel_formulas import Evaluator
    a,p,q=fixture_inputs(c)
    p['items'][0]['components'][0].update(material_specification='FICTITIOUS specified material',procurement_key='same-test-material',procurement_note='FICTITIOUS QA; never a production quotation')
    return a,p,q,Evaluator


def test_materials_are_exact_live_cost_resources_and_convert_units(project_factory,monkeypatch):
    c=project_factory();a,p,q,Evaluator=setup_book(c,monkeypatch)
    r=evaluate(a,p,q);path=c.output_dir/'TEST_FICTITIOUS.xlsx';build_cost_workbook(r,path)
    b=load_workbook(path);e=Evaluator(b)
    assert b['Materiales_Detalle']['A2'].value==r['resources'][0]['id']
    assert e.cell('Materiales_Detalle','M2')==14
    assert e.cell('Materiales_Detalle','S2')==pytest.approx(15.4/9)
    assert e.cell('Materiales_Detalle','U2')==r['resources'][0]['extended_cost']==15.4
    b['Quotes']['J2']=18
    assert Evaluator(b).cell('Materiales_Detalle','U2')==30.8


def test_unknown_waste_preserves_net_quantity_without_inventing_purchase(project_factory,monkeypatch):
    c=project_factory();a,p,q,Evaluator=setup_book(c,monkeypatch)
    p['items'][0]['components'][0]['waste_fraction']=None
    path=c.output_dir/'TEST_FICTITIOUS.xlsx';build_cost_workbook(evaluate(a,p,q),path)
    e=Evaluator(load_workbook(path))
    assert e.cell('Materiales_Detalle','M2')==14
    assert e.cell('Materiales_Detalle','S2')==e.cell('Materiales_Detalle','U2')==''
    assert e.cell('Resumen_de_Compras','I2')==14
    assert e.cell('Resumen_de_Compras','K2')==''


def test_purchase_summary_never_pools_base_with_incompatible_alternates(project_factory,monkeypatch):
    c=project_factory();a,p,q,Evaluator=setup_book(c,monkeypatch)
    alt=deepcopy(a['quantities'][0]);alt.update(id='ALT-Q',pricing_scope='alternate_1');a['quantities'].append(alt)
    item=deepcopy(p['items'][0]);item['quantity_id']='ALT-Q'
    for resource in item['components']:resource['id']+='-ALT'
    p['items'].append(item)
    path=c.output_dir/'TEST_FICTITIOUS.xlsx';build_cost_workbook(evaluate(a,p,q),path)
    b=load_workbook(path);e=Evaluator(b)
    assert b['Resumen_de_Compras'].max_row==3
    assert [b['Resumen_de_Compras'][f'B{i}'].value for i in (2,3)]==['base','alternate_1']
    assert e.cell('Resumen_de_Compras','I2')==e.cell('Resumen_de_Compras','I3')==14


def test_import_preserves_material_metadata_and_estimator_notes(project_factory,monkeypatch):
    c=project_factory();a,p,q,Evaluator=setup_book(c,monkeypatch)
    p['mode']='REAL'
    for quote in q['quotes']:quote['kind']='REAL'
    write_json(c.project_dir/'pricing.json',p);write_json(c.project_dir/'quotes.json',q)
    path=c.output_dir/'Cost_Budget.xlsx';build_cost_workbook(evaluate(a,p,q,root=c.root),path)
    assert (c.output_dir/'Lista_Detallada_de_Materiales.xlsx').exists()
    b=load_workbook(path);b['Materiales_Detalle']['AH2']='FICTITIOUS QA estimator note';b.save(path)
    import_cost_workbook(c,path,a)
    r=read_json(c.project_dir/'pricing.json')['items'][0]['components'][0]
    assert r['material_specification']=='FICTITIOUS specified material'
    assert r['procurement_key']=='same-test-material'
    assert r['estimator_note']=='FICTITIOUS QA estimator note'


def test_range_only_documented_estimate_without_expiration_recalculates(project_factory,monkeypatch):
    c=project_factory();a,p,q,Evaluator=setup_book(c,monkeypatch)
    q['quotes'][0].update(valid_until=None,applicability_note='FICTITIOUS test of explicitly reviewed historical applicability',unit_price=None,unit_price_low=8,unit_price_high=10)
    r=evaluate(a,p,q);path=c.output_dir/'TEST_FICTITIOUS.xlsx';build_cost_workbook(r,path)
    e=Evaluator(load_workbook(path))
    assert e.cell('Quotes','Q2')==1
    assert e.cell('Materiales_Detalle','U2')==''
    assert e.cell('Materiales_Detalle','V2')==r['resources'][0]['cost_low']==13.69
    assert e.cell('Materiales_Detalle','W2')==r['resources'][0]['cost_high']==17.11


def test_conceptual_sign_cost_without_unit_never_becomes_an_item_price(project_factory,monkeypatch):
    c=project_factory();a,p,q,Evaluator=setup_book(c,monkeypatch)
    a['quantities'][0]['quantity']=2
    for item in p['items']:
        for resource in item['components']:resource['quote_id']=None
    q['quotes']=[]
    p['conceptual_cost_references']=[{'id':'CONCEPT-FICTITIOUS-QA','tag':'FICTITIOUS-QA','quantity_id':a['quantities'][0]['id'],'description':'FICTITIOUS QA only','central':20000,'low':None,'high':None,'date':'2026-10-01','fabrication':'NOT_SPECIFIED','supply':'NOT_SPECIFIED','installation':'NOT_SPECIFIED','sources':[],'detail_sources':[],'note':'FICTITIOUS conceptual reference; unit basis unknown'}]
    result=evaluate(a,p,q);path=c.output_dir/'TEST_FICTITIOUS.xlsx';build_cost_workbook(result,path)
    b=load_workbook(path);e=Evaluator(b)
    assert b['Referencias_Conceptuales']['E2'].value==20000
    assert b['Referencias_Conceptuales']['H2'].value=='NO DEFINIDA'
    assert e.cell('Materiales_Detalle','U2')==e.cell('Scopes','F2')==''
    assert e.cell('Resumen_Economico','B4')==e.cell('Resumen_Economico','B5')==0
    assert e.cell('Resumen_Economico','B11')==1
    assert e.cell('Resumen_Economico','B12')==1
    assert result['offer_total'] is None
