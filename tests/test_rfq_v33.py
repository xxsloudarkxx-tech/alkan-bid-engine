from copy import deepcopy
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
from threading import Thread
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from reportlab.pdfgen import canvas
from bidkit.rfq_engine import calcular_takeoff,peso_acero,validar_entregable
from bidkit.units import convertir_unidades,length_m
from bidkit.plan_measurement import calibrar_escala,medir_plano,contar_espaciamiento
from bidkit.rfq_tools import invoke,ToolInputError,schemas
from bidkit.rfq_cli import main
from bidkit.rfq_agent import PhaseRunner,ChatProvider,ProviderError,validate_audit
from bidkit.rfq_documents import generar_excel

@pytest.fixture
def sheet(tmp_path):
    path=tmp_path/'plan.pdf';p=canvas.Canvas(str(path),pagesize=(400,400));p.line(0,100,100,100);p.save();return path

def audit(verdict='APROBABLE'):
    keys=('addenda_aplicados','fecha_verificada','fuente_en_cada_cantidad','unidades_de_compra_enteras','sin_duplicados_ni_faltantes_vs_forma_de_oferta','normas_coinciden_con_especificacion','pendientes_marcados_como_pendientes','comprobaciones_cruzadas_presentes','nota_validacion_profesional')
    return {'veredicto':verdict,'fallas':[],'comprobaciones':{k:'ok' for k in keys}}

def takeoff_args(**kwargs):
    return {'concepto':'Malla','formula':'longitud','variables':{'longitud':230},'unidad':'LF','fuente':'A1','desperdicio_pct':5,**kwargs}

@pytest.mark.parametrize('formula,variables,pack,unit', [('longitud',{'longitud':230},50,'rollos'),('longitud / rollo',{'longitud':230,'rollo':50},1,'rollos')])
def test_rolls_round_up(formula,variables,pack,unit):
    r=calcular_takeoff(**takeoff_args(formula=formula,variables=variables,tamano_empaque=pack,unidad_compra=unit))
    assert Decimal(r['cantidad_compra'])==5
    assert Decimal(r['cantidad_sin_redondeo'])==Decimal('4.83')

def test_legacy_fraction_unchanged_and_waste_pending():
    r=calcular_takeoff(**takeoff_args(formula='longitud/rollo',variables={'longitud':230,'rollo':50}))
    assert Decimal(r['cantidad_compra'])==Decimal('4.83')
    assert calcular_takeoff(**takeoff_args(desperdicio_pct=None,tamano_empaque=50,unidad_compra='rollos'))['cantidad_compra'] is None

@pytest.mark.parametrize('bad',[0,-1,'NaN'])
def test_bad_pack(bad):
    with pytest.raises(ValueError):calcular_takeoff(**takeoff_args(tamano_empaque=bad,unidad_compra='rollos'))

def test_pack_multiples_and_surplus():
    r=calcular_takeoff(**takeoff_args(tamano_empaque=50,unidad_compra='rollos',multiplo_compra=2))
    assert Decimal(r['cantidad_compra'])==6 and Decimal(r['cantidad_cubierta'])==300 and Decimal(r['sobrante_compra'])==Decimal('58.5')
    r=calcular_takeoff(**takeoff_args(tamano_empaque=50,unidad_compra='rollos'))
    assert Decimal(r['sobrante_compra'])==Decimal('8.5')

@pytest.mark.parametrize('value,source,target,expected',[(1,'ft','in','12'),(1,'lb','kg','.45359237'),(1,'yd3','m3','.764554857984'),(1,'ft2','m2','.09290304'),(1,'m','mm','1000')])
def test_exact_unit_conversion(value,source,target,expected):assert Decimal(convertir_unidades(value,source,target)['valor'])==Decimal(expected)

@pytest.mark.parametrize('source,target',[('ft','kg'),('bogus','m')])
def test_reject_dimension_mismatch(source,target):
    with pytest.raises(ValueError):convertir_unidades(1,source,target)

def test_feet_inches_and_steel_equivalence():
    assert length_m('6\'-2 1/2"','ft')==Decimal('1.8923')
    us=peso_acero('tubo',{'od':2,'wall':'1/8'},21,unidades='us')
    si=peso_acero('tubo',{'diametro_exterior':'.0508','espesor':'.003175'},'6.4008')
    assert Decimal(us['kg'])==Decimal(si['kg'])
    assert abs(Decimal(us['lb'])*Decimal('.45359237')-Decimal(us['kg']))<Decimal('1e-20')

def test_error_missing_dimension_actionable(tmp_path,capsys):
    request=tmp_path/'request.json';request.write_text(json.dumps({'tipo':'tubo','dimensiones':{'espesor':1}}))
    with pytest.raises(SystemExit) as caught:main(['peso_acero','--input',str(request)])
    assert caught.value.code==2
    error=json.loads(capsys.readouterr().err)['error']
    assert error['herramienta']=='peso_acero' and error['campo']=='dimensiones.diametro_exterior' and error['ejemplo_minimo']

def calibration(sheet):return calibrar_escala(str(sheet),1,[[0,0],[100,0]],10,'ft','S1 cota 10 ft',dpi=72,incertidumbre_pct=1)

def test_calibrated_length_area(sheet):
    c=calibration(sheet)
    line=medir_plano(c,[[0,0],[100,0],[100,100]],'longitud','S1')
    area=medir_plano(c,[[0,0],[100,0],[100,100],[0,100]],'area','S1')
    assert Decimal(line['cantidad'])==20 and line['unidad']=='ft'
    assert Decimal(area['cantidad'])==100 and area['unidad']=='ft2'
    assert Decimal(area['rango'][0])==Decimal('98.01')
    assert line['estado']=='CALCULADO_PENDIENTE_REVISION'

def test_altered_calibration_pdf_and_bad_polygon(sheet):
    c=calibration(sheet);modified=deepcopy(c);modified['unidades_por_pixel']='2'
    with pytest.raises(ValueError,match='alterada'):medir_plano(modified,[[0,0],[100,0]],'longitud','S1')
    with pytest.raises(ValueError,match='cruza'):medir_plano(c,[[0,0],[100,100],[100,0],[0,100]],'area','S1')
    sheet.write_bytes(sheet.read_bytes()+b'\n%changed')
    with pytest.raises(ValueError,match='cambió'):medir_plano(c,[[0,0],[100,0]],'longitud','S1')

def test_outside_points(sheet):
    with pytest.raises(ValueError,match='fuera'):medir_plano(calibration(sheet),[[0,0],[500,0]],'longitud','S1')

def test_spacing_shared_endpoints():
    result=contar_espaciamiento([150,80],10,'S1',extremos_compartidos=1,conteo_grafico=24)
    assert result['total']==24 and result['postes_linea']==21 and result['terminales']==3 and result['coincide_con_plano']
    assert invoke('contar_por_espaciamiento',{'longitud':20,'espaciamiento':10,'fuente':'S1','extremos':False})['total']==1

def test_excel_pack_formula(tmp_path):
    from openpyxl import load_workbook
    row={**calcular_takeoff(**takeoff_args(tamano_empaque=50,unidad_compra='rollos')),'id':'T1'}
    path=tmp_path/'pack.xlsx';generar_excel('Demo',{'takeoff':[row]},path);wb=load_workbook(path)
    assert 'CEILING' in wb['Takeoff']['F2'].value and wb['Takeoff']['H2'].value==50 and wb['Takeoff']['I2'].value=='rollos'
    assert wb['Compras por proveedor']['D2'].value=='rollos'

class ScriptedProvider:
    model='test-model'
    def __init__(self,replies):self.replies=list(replies);self.messages=[]
    def complete(self,messages,tools=None,model=None):
        self.messages.append({'messages':deepcopy(messages),'tools':tools,'model':model})
        return self.replies.pop(0)

def tool_message(name,args):return {'content':None,'tool_calls':[{'id':'call_1','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}

def takeoff_output():
    return {'partida':'P1','conceptos':[{'id':'T1','concepto':'Malla','formula':'longitud','variables':{'longitud':230},'fuente':'A1','cantidad_neta':230,'cantidad_a_comprar':5,'unidad_de_compra':'rollos','estado':'CALCULADO'}],'comprobaciones_cruzadas':[{'disponible':250,'requerido':241.5,'ok':True}],'conflictos':[],'pendientes':[]}

def test_orchestrator_real_tools_fresh_audit_and_persistence(tmp_path):
    provider=ScriptedProvider([tool_message('calcular_takeoff',takeoff_args(tamano_empaque=50,unidad_compra='rollos')),{'content':json.dumps(takeoff_output())},{'content':json.dumps(audit())}])
    runner=PhaseRunner(tmp_path,provider,audit_model='different-auditor');result=runner.run_phase('takeoff',{'spec':'A1'})
    assert result['estado']=='PENDIENTE_REVISION_HUMANA' and result['calls']==3
    assert json.loads(Path(result['result']).read_text())['conceptos'][0]['cantidad_a_comprar']==5
    assert json.loads(runner.log.read_text())['result']['cantidad_compra']=='5'
    auditor=provider.messages[-1]
    assert auditor['tools'] is None and auditor['model']=='different-auditor'
    assert all(m['role']!='assistant' for m in auditor['messages'])
    assert json.loads(runner.state_path.read_text())['takeoff']['estado']=='PENDIENTE_REVISION_HUMANA'

def test_orchestrator_rejects_fabricated_calculation(tmp_path):
    provider=ScriptedProvider([{'content':json.dumps(takeoff_output())}]*3)
    with pytest.raises(ValueError,match='resultado real'):PhaseRunner(tmp_path,provider).run_phase('takeoff',{})

def test_orchestrator_path_escape_and_review_forgery(tmp_path):
    runner=PhaseRunner(tmp_path,ScriptedProvider([]))
    with pytest.raises(ValueError,match='fuera'):runner._execute('leer_texto_pdf',{'ruta':'../secret.pdf','pagina_inicio':1,'pagina_fin':1})
    result=runner._execute('validar_entregable',{'entregable':'rfq','datos':{'qc':{'fecha_verificada':{'ok':True,'fuente':'fake','responsable':'AI'}}}})
    assert result['estado']=='BLOQUEADO'
    assert runner._execute('generar_documento',{'tipo':'propuesta'})['estado']=='BLOQUEADO'

def test_blocked_audit_not_saved_as_success(tmp_path):
    result=takeoff_output();result['conceptos'][0]['estado']='PENDIENTE'
    bad=audit('BLOQUEADO');bad['fallas']=[{'descripcion':'Missing source','severidad':'alta'}]
    runner=PhaseRunner(tmp_path,ScriptedProvider([{'content':json.dumps(result)},{'content':json.dumps(bad)}]))
    entry=runner.run_phase('takeoff',{})
    assert entry['estado']=='BLOQUEADO' and 'takeoff' not in runner.state

def test_text_mode_executes_tools(tmp_path):
    request={'herramienta':'calcular_takeoff','argumentos':takeoff_args(tamano_empaque=50,unidad_compra='rollos')}
    provider=ScriptedProvider([{'content':json.dumps(request)},{'content':json.dumps(takeoff_output())},{'content':json.dumps(audit())}])
    assert PhaseRunner(tmp_path,provider,text_mode=True).run_phase('takeoff',{})['calls']==3
    assert all(r['tools'] is None for r in provider.messages)

def test_bad_audit_cannot_approve():
    invalid=audit();invalid['comprobaciones']['fecha_verificada']='no_verificable'
    with pytest.raises(ValueError):validate_audit(invalid)

def test_http_provider_contract_and_auth():
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            seen.append((self.path,self.headers.get('Authorization'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            raw=json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{}'}}]}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        provider=ChatProvider(f'http://127.0.0.1:{server.server_port}/v1','test-placeholder','test-model')
        assert provider.complete([{'role':'user','content':'test'}])['content']=='{}'
        assert seen[0][0]=='/v1/chat/completions' and seen[0][1]=='Bearer test-placeholder' and seen[0][2]['model']=='test-model'
    finally:server.shutdown();server.server_close();thread.join()

@pytest.mark.parametrize('url',['http://example.com/v1','https://u:p@example.com/v1','https://example.com/v1?key=secret'])
def test_provider_rejects_unsafe_endpoint(url):
    with pytest.raises(ProviderError):ChatProvider(url,'placeholder','test-model')

def test_measurement_http_and_session_protection(tmp_path,sheet):
    from bidkit.intelligence_ui import make_handler
    from http.client import HTTPConnection
    import base64
    server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(tmp_path));thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    def request(path,data=None,token=None):
        c=HTTPConnection('127.0.0.1',server.server_port);headers={}
        if data is not None:headers={'Content-Type':'application/json','X-ALKAN-Token':token or ''}
        c.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers)
        r=c.getresponse();raw=r.read();kind=r.getheader('Content-Type');status=r.status;c.close()
        return status,json.loads(raw) if 'application/json' in kind else raw
    try:
        token=request('/api/session')[1]['token']
        assert request('/herramientas')[0]==200
        assert request('/estimation_tools.js')[0]==200
        assert request('/api/agent/status')[1]['configurado'] is False
        req={'actor':'Test','content':base64.b64encode(sheet.read_bytes()).decode()}
        assert request('/api/measurement/upload',req)[0]==403
        status,result=request('/api/measurement/upload',req,token)
        assert status==200 and result['paginas']==1
        status,raster=request('/api/measurement/tool',{'actor':'Test','name':'rasterizar_pagina','arguments':{'ruta':result['ruta'],'pagina':1,'dpi':72}},token)
        assert status==200 and raster['ancho_px']==400 and raster['imagen'].startswith('data:image/png')
        assert request('/api/measurement/tool',{'actor':'Test','name':'rasterizar_pagina','arguments':{'ruta':'../secret.pdf','pagina':1}},token)[0]==400
    finally:server.shutdown();server.server_close();thread.join()

def test_state_lock_and_error_checkpoint(tmp_path):
    runner=PhaseRunner(tmp_path,ScriptedProvider([]));runner.state_path.parent.mkdir(parents=True,exist_ok=True)
    lock=runner.state_path.with_suffix('.lock');lock.write_text('busy')
    with pytest.raises(ValueError,match='ejecutándose'):runner.run_phase('takeoff',{})
    lock.unlink()
    with pytest.raises(ValueError,match='takeoff_aprobado'):runner.run_phase('rfq',{})
    assert not lock.exists() and (runner.run_dir/'error.json').exists()

def test_rfq_phase_checks_approved_ids_and_renders_only_draft(tmp_path):
    import test_rfq_engine as original
    payload=original.rfq();payload['borrador']=True;payload['cierre']={}
    approved={'aprobado_por':'Test reviewer','conceptos':[{'id':'T1','cantidad_a_comprar':21,'unidad_de_compra':'LF'}]}
    runner=PhaseRunner(tmp_path,ScriptedProvider([{'content':json.dumps(payload)},{'content':json.dumps(audit())}]))
    result=runner.run_phase('rfq',{'takeoff_aprobado':approved})
    assert result['estado']=='PENDIENTE_REVISION_HUMANA' and len(result['artifacts'])==1
    from pypdf import PdfReader
    assert 'DRAFT' in PdfReader(result['artifacts'][0]).pages[0].extract_text()
    forged=deepcopy(payload);forged['secciones'][0]['items'][0]['qty']=22
    with pytest.raises(ValueError,match='no concilia'):runner._verify_rfq(forged,{'takeoff_aprobado':approved})

def test_inventory_executes_before_model(tmp_path):
    (tmp_path/'spec.txt').write_text('Demo source')
    blocked={'estado':'BLOQUEADO','motivo':'Falta fecha vigente','necesito':['Div 00']}
    provider=ScriptedProvider([{'content':json.dumps(blocked)}]);runner=PhaseRunner(tmp_path,provider)
    assert runner.run_phase('inventario',{'ruta_paquete':'.'})['estado']=='BLOQUEADO'
    assert json.loads(runner.log.read_text())['tool']=='inventario_archivos'
    assert any('Inventario ejecutado' in str(m.get('content')) for m in provider.messages[0]['messages'])

def test_vision_image_reaches_fresh_auditor(tmp_path):
    from PIL import Image
    image=tmp_path/'sheet.png';Image.new('RGB',(100,100),'white').save(image)
    output={'hoja':{'titulo':'DEMO','legible':True},'datos':[],'notas_generales_relevantes':[],'referencias_a_otras_hojas':[],'elementos_ilegibles':[]}
    provider=ScriptedProvider([{'content':json.dumps(output)},{'content':json.dumps(audit())}]);runner=PhaseRunner(tmp_path,provider,vision=True)
    runner.run_phase('hoja',{},images=['sheet.png'])
    assert provider.messages[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert provider.messages[-1]['messages'][1]['content'][1]['type']=='image_url'
