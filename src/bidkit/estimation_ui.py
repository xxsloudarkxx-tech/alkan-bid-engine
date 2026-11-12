"""Loopback handlers for calibrated measurement and phase orchestration."""
import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from .rfq_tools import invoke
from .rfq_cli import record_operation
from .rfq_agent import ChatProvider, PhaseRunner

MEASURE_TOOLS={'rasterizar_pagina','calibrar_escala','medir_plano','medir_polilinea','medir_poligono','contar_espaciamiento','contar_por_espaciamiento','convertir_unidades','calcular_takeoff','peso_acero'}

def child(root,value):
    base=Path(root).resolve();p=Path(value);p=(p if p.is_absolute() else base/p).resolve()
    if not p.is_relative_to(base):raise ValueError('Archivo fuera de la carpeta del motor')
    return p

def measurement_upload(root,encoded):
    raw=base64.b64decode(encoded,validate=True)
    if not raw.startswith(b'%PDF-') or len(raw)>25*1024*1024:raise ValueError('Cargue PDF válido de hasta 25 MB')
    from pypdf import PdfReader
    try:reader=PdfReader(BytesIO(raw))
    except Exception as exc:raise ValueError('PDF inválido o incompleto') from exc
    if reader.is_encrypted or not 1<=len(reader.pages)<=500:raise ValueError('PDF cifrado o fuera de 1-500 páginas')
    base=Path(root).resolve();path=child(base,'data/measurements/'+sha256(raw).hexdigest()+'.pdf');path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(raw)
    return {'ruta':str(path.relative_to(base)),'paginas':len(reader.pages)}

def measurement_tool(root,name,arguments):
    if name not in MEASURE_TOOLS:raise ValueError('Herramienta no disponible en medición')
    args=dict(arguments)
    if 'ruta' in args:args['ruta']=str(child(root,args['ruta']))
    if 'calibracion' in args:
        args['calibracion']=dict(args['calibracion']);args['calibracion']['ruta']=str(child(root,args['calibracion']['ruta']))
    result=invoke(name,args)
    if name=='rasterizar_pagina':
        image=result;raw=BytesIO();image.save(raw,format='PNG');result={'imagen':'data:image/png;base64,'+base64.b64encode(raw.getvalue()).decode(),'ancho_px':image.width,'alto_px':image.height}
        record_operation(Path(root)/'data/rfq_operations.jsonl',name,args,{'ancho_px':image.width,'alto_px':image.height})
    else:record_operation(Path(root)/'data/rfq_operations.jsonl',name,args,result)
    return result

def agent_status():
    import os
    return {'configurado':all(os.environ.get(k) for k in ('BIDKIT_API_BASE','BIDKIT_API_KEY','BIDKIT_MODEL')),
            'modelo':os.environ.get('BIDKIT_MODEL') or 'PENDIENTE','auditor':os.environ.get('BIDKIT_AUDIT_MODEL') or 'Llamada nueva al mismo modelo',
            'vision':os.environ.get('BIDKIT_VISION')=='1'}

def run_agent(root,request):
    import os
    runner=PhaseRunner(root,ChatProvider.from_env(),max_calls=12,vision=os.environ.get('BIDKIT_VISION')=='1',text_mode=request.get('text_mode') is True)
    return runner.run_phase(request['phase'],request['inputs'],request.get('sources'),request.get('images'))
