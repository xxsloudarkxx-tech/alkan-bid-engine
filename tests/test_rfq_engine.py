from decimal import Decimal
from datetime import datetime, timezone
import json, zipfile
import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas
from bidkit import rfq_engine as e
from bidkit.rfq_documents import generar_rfq_pdf, generar_excel
from bidkit.rfq_cli import main


def take():
    return {**e.calcular_takeoff('Rail','runs*length',{'runs':2,'length':10},'LF','A1 detail 2',5),'id':'T1','aprobado_por':'Fixture reviewer'}

def control():
    return {'takeoff':[take()],'qc':{k:{'ok':True,'fuente':'Fixture review','responsable':'Test reviewer'} for k in e.QC_KEYS}}

def rfq():
    return {'solicitante':{'razon_social':'DEMO ONLY','direccion':'Demo','licencia':'Demo','telefono':'Demo'},'rfq':{'numero':'DEMO-2026-01','fecha':'2026-11-08'},'proyecto':{'nombre':'Synthetic project','entidad':'Demo','numero':'DEMO','direccion':'Demo','regimen_salarial':'Demo'},'devolver_a':{'nombre':'Demo','empresa':'DEMO','telefono':'Demo','direccion':'Demo'},'dirigido_a':{'tipo_proveedor':'Steel supplier'},'entrega_y_requisitos':['Confirm freight, access and tax.'],'secciones':[{'id':'A','titulo':'STEEL','nota':'Demo destination','items':[{'n':1,'item':'Rail','spec':'Demo specification','qty':'21','unit':'LF','takeoff_id':'T1'}]}],'resumen_tecnico':[{'parametro':'Finish','requisito':'Pending approval'}]}

@pytest.mark.parametrize('formula',['__import__("os").system("echo bad")','x.__class__','[x][0]','sum(x)','x**100','x/0','x-x-1','True'])
def test_bad_formula(formula):
    with pytest.raises((ValueError,SyntaxError)):e.calcular_takeoff('x',formula,{'x':2},'EA','A1',0)

def test_decimal_missing_waste():
    r=e.calcular_takeoff('Concrete','length*width',{'length':'.1','width':'.2'},'m2','S1')
    assert Decimal(r['cantidad_neta'])==Decimal('.02') and r['cantidad_compra'] is None
    assert Decimal(take()['cantidad_compra'])==21

@pytest.mark.parametrize('value',[True,'NaN','Infinity',-1])
def test_invalid_number(value):
    with pytest.raises(ValueError):e.number(value)

def test_cut_balance():
    r=e.optimizar_cortes([{'longitud':6,'cantidad':5}],[10,21],'.1')
    assert sum(len(b['cortes']) for b in r['barras'])==5
    for b in r['barras']:assert Decimal(b['longitud_comercial'])==sum(map(Decimal,b['cortes']))+Decimal(b['kerf_total'])+Decimal(b['sobrante'])
    assert e.optimizar_cortes([{'longitud':6,'cantidad':3}],[10,21])['piezas_comerciales']==1

@pytest.mark.parametrize('length,count,kerf',[(22,1,0),(2,1.1,0),(21,1,'.1')])
def test_impossible_cuts(length,count,kerf):
    with pytest.raises(ValueError):e.optimizar_cortes([{'longitud':length,'cantidad':count}],[21],kerf)

def test_weight():
    assert Decimal(e.peso_acero('placa',{'ancho':1,'espesor':'.01'},2)['kg'])==157
    with pytest.raises(ValueError):e.peso_acero('perfil',{'area':1})
    with pytest.raises(ValueError):e.peso_acero('tubo',{'diametro_exterior':1,'espesor':'.5'})

def test_price_missing():
    assert e.buscar_precio('rail') is None
    assert e.buscar_precio('rail',catalogo=[{'concepto':'rail','precio':10}]) is None

def test_qc():
    d=control();d['rfq']=rfq()
    assert e.validar_entregable('rfq',d)['estado']=='APTO'
    d['takeoff'][0]['cantidad_compra']='22'
    assert e.validar_entregable('rfq',d)['estado']=='BLOQUEADO'
    assert e.validar_entregable('rfq',{})['estado']=='BLOQUEADO'
    d=control();d['rfq']=rfq();d['qc']['fecha_verificada']=True
    assert 'QC:fecha_verificada' in e.validar_entregable('rfq',d)['fallas']

def test_pdf_gate_blank_prices(tmp_path):
    path=tmp_path/'rfq.pdf'
    with pytest.raises(ValueError):generar_rfq_pdf(rfq(),path,borrador=False)
    assert not path.exists()
    generar_rfq_pdf(rfq(),path,borrador=False,control=control())
    text=''.join(p.extract_text() for p in PdfReader(path).pages)
    assert 'REQUEST FOR QUOTATION' in text and '________' in text and 'Page 1 / 1' in text and 'DRAFT' not in text

def test_hierarchy_deadline():
    rows=[{'asunto':'due','tipo':'plano_general','fuente':'G1','valor':'old'},{'asunto':'due','tipo':'addendum','revision':2,'fuente':'AD2','valor':'new'}]
    assert e.resolver_jerarquia(rows)['vigentes']['due']['valor']=='new'
    now=datetime(2026,11,8,tzinfo=timezone.utc)
    assert e.alertas_fechas('2026-11-07T00:00:00Z',now)[0].startswith('VENCIDA')
    assert e.alertas_fechas('2026-11-09T00:00:00Z',now)[0].startswith('URGENTE')
    with pytest.raises(ValueError):e.alertas_fechas('2026-11-09',now)

def test_pdf_inventory_tools(tmp_path):
    path=tmp_path/'plans.pdf';pdf=canvas.Canvas(str(path));pdf.drawString(40,700,'Fence 230 LF');pdf.save()
    archive=tmp_path/'docs.zip'
    with zipfile.ZipFile(archive,'w') as z:z.write(path,'plans.pdf')
    assert e.inventario_archivos(archive)[0]['paginas'][0]['capa_texto']
    assert e.buscar_en_pdf(path,['fence'])[0]['pagina']==1
    assert '230' in e.leer_texto_pdf(path,1,1)[0]['texto']
    assert e.rasterizar_pagina(path,1,72,[0,0,.5,.5]).width>0
    with pytest.raises(ValueError):e.leer_texto_pdf(path,0,1)

def test_workbook(tmp_path):
    from openpyxl import load_workbook
    path=tmp_path/'takeoff.xlsx';generar_excel('Demo',control(),path);wb=load_workbook(path)
    assert len(wb.sheetnames)==6 and wb['Takeoff']['F2'].data_type=='f'
    assert wb['APU']['C2'].value is None and 'PENDIENTE' in wb['APU']['I2'].value
    assert wb['Resumen']['B3'].data_type=='f'

def test_cli(tmp_path,capsys):
    path=tmp_path/'request.json';path.write_text(json.dumps({'concepto':'x','formula':'x*2','variables':{'x':3},'unidad':'EA','fuente':'S1','desperdicio_pct':0}))
    assert main(['calcular_takeoff','--input',str(path),'--registro',str(tmp_path/'operations.jsonl')])==0
    assert json.loads(capsys.readouterr().out)['cantidad_compra']=='6'

def test_untrusted_workbook_text_is_not_formula(tmp_path):
    from openpyxl import load_workbook
    d=control();d['takeoff'][0]['concepto']='=1+1';d['takeoff'][0]['fuente']='=HYPERLINK("https://example.invalid")'
    path=tmp_path/'safe.xlsx';generar_excel('=1+1',d,path);wb=load_workbook(path)
    assert wb['Takeoff']['B2'].data_type=='s' and wb['Takeoff']['G2'].data_type=='s'
    assert wb['Resumen']['B1'].data_type=='s'
    assert wb['Memoria de cálculo']['E2'].data_type=='f'

def test_original_schemas_map_to_tools():
    import inspect
    from bidkit.rfq_cli import TOOLS
    from pathlib import Path
    schemas=json.loads((Path(e.__file__).parent/'rfq_tools.schema.json').read_text())
    assert len(schemas)>=21
    for tool in schemas:
        parameters=inspect.signature(TOOLS[tool['name']]).parameters
        assert set(tool['input_schema']['required'])<=set(parameters)

def test_rfq_duplicate_and_high_risk_block():
    data=control();data['rfq']=rfq();data['rfq']['secciones'][0]['items'].append(dict(data['rfq']['secciones'][0]['items'][0]))
    assert 'RFQ_TAKEOFF_DUPLICADO' in e.validar_entregable('rfq',data)['fallas']
    data=control();data['supuestos']=[e.registrar_supuesto('conflicto','Conflicting detail','AD1','alto')]
    assert 'RIESGO_ALTO_ABIERTO' in e.validar_entregable('takeoff',data)['fallas']

def test_multi_page_rfq_footer(tmp_path):
    from bidkit.rfq_documents import rfq_bytes
    r=rfq();r['secciones'][0]['items']=[{'n':n,'item':'Demo rail '+str(n),'spec':'Synthetic long specification to verify wrapped text and repeated table headers.','qty':1,'unit':'EA'} for n in range(1,61)]
    pages=PdfReader(__import__('io').BytesIO(rfq_bytes(r))).pages
    assert len(pages)>1
    for i,p in enumerate(pages,1): assert f'Page {i} / {len(pages)}' in p.extract_text()
