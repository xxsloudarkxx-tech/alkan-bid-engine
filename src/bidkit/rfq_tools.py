"""Shared validated dispatch for CLI, UI and the model orchestrator."""
import inspect
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from . import rfq_engine as engine, rfq_documents as documents, plan_measurement as plans, units

BASE_NAMES=('inventario_archivos','leer_texto_pdf','buscar_en_pdf','rasterizar_pagina','ocr_pagina','calcular_takeoff','optimizar_cortes','peso_acero','buscar_precio','generar_excel','generar_rfq_pdf','generar_documento','registrar_supuesto','validar_entregable','resolver_jerarquia','alertas_fechas')
EXTRA_NAMES=('convertir_unidades','calibrar_escala','medir_plano','medir_polilinea','medir_poligono','contar_espaciamiento','contar_por_espaciamiento')
NAMES=BASE_NAMES+EXTRA_NAMES

def medir_polilinea(calibracion,puntos,fuente): return plans.medir_plano(calibracion,puntos,'longitud',fuente)
def medir_poligono(calibracion,puntos,fuente): return plans.medir_plano(calibracion,puntos,'area',fuente)
def contar_por_espaciamiento(longitud,espaciamiento,fuente,extremos=True):
    if type(extremos) is not bool: raise ValueError('extremos debe ser booleano')
    result=plans.contar_espaciamiento([longitud],espaciamiento,fuente)
    result['total']=result['intervalos_por_tramo'][0]+(1 if extremos else -1)
    result['terminales']=2 if extremos else 0
    return result

TOOLS={}
for name in NAMES:
    TOOLS[name]=next((getattr(module,name) for module in (engine,documents,plans,units) if hasattr(module,name)),None) or globals()[name]

def schemas(): return json.loads(Path(__file__).with_name('rfq_tools.schema.json').read_text(encoding='utf-8'))

class ToolInputError(ValueError):
    def __init__(self,tool,field,message):
        self.tool,self.field,self.message=tool,field,message
        super().__init__(f'{tool}: {field}: {message}')
    def data(self):
        schema=next((s['input_schema'] for s in schemas() if s['name']==self.tool),{})
        examples={'ruta':'planos.pdf','pagina':1,'tipo':'tubo','dimensiones':{'od':2,'wall':'.125'},'formula':'largo','variables':{'largo':230},'unidad':'LF','fuente':'S1 detalle 2'}
        example={key:examples.get(key,'VALOR_REQUERIDO') for key in schema.get('required',[])}
        return {'codigo':'ENTRADA_INVALIDA','herramienta':self.tool,'campo':self.field,'mensaje':self.message,'ejemplo_minimo':example}

def invoke(name,arguments):
    if name not in TOOLS: raise ToolInputError(name,'herramienta','Herramienta desconocida')
    if not isinstance(arguments,dict): raise ToolInputError(name,'entrada','Debe ser un objeto JSON')
    fn=TOOLS[name];parameters=inspect.signature(fn).parameters
    missing=[key for key,p in parameters.items() if p.default is inspect.Parameter.empty and key not in arguments]
    if missing: raise ToolInputError(name,missing[0],'Falta campo obligatorio')
    unknown=set(arguments)-set(parameters)
    if unknown: raise ToolInputError(name,sorted(unknown)[0],'Campo no reconocido; revise esquemas')
    schema=next((s['input_schema'] for s in schemas() if s['name']==name),None)
    if schema:
        error=next(iter(Draft202012Validator(schema).iter_errors(arguments)),None)
        if error:
            field='.'.join(map(str,error.absolute_path)) or 'entrada'
            raise ToolInputError(name,field,error.message)
    try: return fn(**arguments)
    except KeyError as exc: raise ToolInputError(name,str(exc.args[0]),'Falta campo anidado obligatorio') from None
    except (ValueError,TypeError,SyntaxError,ArithmeticError) as exc:
        import re
        missing=re.search(r'falta campo ([A-Za-z_.]+)',str(exc))
        raise ToolInputError(name,missing[1] if missing else 'entrada',str(exc)) from None
