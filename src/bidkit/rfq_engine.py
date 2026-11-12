"""Auditable estimation tools. Inputs are data; formulas never execute Python code.

All dimensions used by peso_acero are SI (metres); density is kg/m3.
Cut lengths/kerf must use the same user-selected unit. Cutting uses FFD,
not a claim of a mathematical optimum. Human review is never inferred.
"""
from __future__ import annotations
import ast
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from io import BytesIO
from pathlib import Path
import json
import math
import subprocess
import tempfile
import zipfile

VALIDATION_NOTE = 'Cantidades y precios sujetos a validación por ingeniero/arquitecto o estimador responsable antes de contratar u ofertar.'
VALIDATION_EN = 'Quantities and prices are subject to validation by the responsible engineer, architect or estimator before contracting or bidding.'


def number(value, *, positive=False):
    if isinstance(value, bool): raise ValueError('Booleano no es cantidad')
    try: n = Decimal(str(value))
    except (InvalidOperation, ValueError): raise ValueError('Número inválido') from None
    if not n.is_finite() or n < 0 or (positive and n == 0) or abs(n) > Decimal('1e18'):
        raise ValueError('Cantidad fuera de rango')
    return n


def integer(value, *, positive=False):
    n = number(value, positive=positive)
    if n != n.to_integral_value(): raise ValueError('Se requiere entero')
    return int(n)


def expression(formula, variables):
    if not isinstance(formula, str) or len(formula) > 1000: raise ValueError('Fórmula inválida')
    tree = ast.parse(formula, mode='eval')
    if len(list(ast.walk(tree))) > 150: raise ValueError('Fórmula demasiado compleja')
    values = {k: number(v) for k, v in variables.items()}
    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Name) and node.id in values: return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float): return number(ast.get_source_segment(formula, node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add): return a+b
            if isinstance(node.op, ast.Sub): return a-b
            if isinstance(node.op, ast.Mult): return a*b
            if isinstance(node.op, ast.Div): return a/b
            if isinstance(node.op, ast.Pow) and b == int(b) and abs(b) <= 12: return a**int(b)
        raise ValueError('Solo variables, números y + - * / ** entero hasta 12')
    try:
        with localcontext() as ctx:
            ctx.prec = 36
            result = visit(tree)
        return number(result)
    except ArithmeticError as exc: raise ValueError('Fórmula indefinida') from exc


def calcular_takeoff(concepto, formula, variables, unidad, fuente, desperdicio_pct=None,
                     tamano_empaque=None, unidad_compra=None, redondeo=None, multiplo_compra=1):
    if not all(str(v or '').strip() for v in (concepto, unidad, fuente)): raise ValueError('Concepto, unidad y fuente obligatorios')
    net = expression(formula, variables)
    waste = number(desperdicio_pct) if desperdicio_pct is not None else None
    if waste is not None and waste > 100: raise ValueError('Desperdicio mayor de 100%')
    pack=number(tamano_empaque if tamano_empaque is not None else 1,positive=True)
    multiple=number(multiplo_compra,positive=True)
    discrete={'ea','each','pieza','piezas','pz','pza','pc','pcs','rollo','rollos','roll','rolls','bolsa','bolsas','bag','bags','saco','sacos','box','boxes','caja','cajas'}
    buy_unit=unidad_compra or unidad
    rounding=(redondeo or 'arriba') if tamano_empaque is not None else 'ninguno'
    if rounding not in ('arriba','ninguno'): raise ValueError('redondeo: use arriba o ninguno')
    if tamano_empaque is not None and not unidad_compra: raise ValueError('tamano_empaque requiere unidad_compra (rollos, bolsas, piezas...)')
    if tamano_empaque is not None and (rounding!='arriba' or multiple!=multiple.to_integral_value()):
        raise ValueError('Empaques/piezas requieren redondeo arriba y múltiplo entero')
    required=None if waste is None else net*(1+waste/100)
    exact=None if required is None else required/pack
    purchase=None if exact is None else (exact/multiple).to_integral_value(rounding=ROUND_CEILING)*multiple if rounding=='arriba' else exact
    return {'concepto':concepto,'formula':formula,'variables':{k:str(number(v)) for k,v in variables.items()},
            'unidad':unidad,'fuente':fuente,'cantidad_neta':str(net),'desperdicio_pct':None if waste is None else str(waste),
            'cantidad_requerida':None if required is None else str(required),'cantidad_sin_redondeo':None if exact is None else str(exact),
            'tamano_empaque':None if tamano_empaque is None else str(pack),'unidad_compra':buy_unit,'redondeo':rounding,'multiplo_compra':str(multiple),
            'cantidad_compra':None if purchase is None else str(purchase),'cantidad_cubierta':None if purchase is None else str(purchase*pack),
            'sobrante_compra':None if purchase is None else str(purchase*pack-required),
            'estado':'PENDIENTE_DESPERDICIO' if waste is None else 'CALCULADO_PENDIENTE_REVISION'}


def optimizar_cortes(cortes, longitudes_comerciales, kerf=0):
    stocks = sorted(set(number(s, positive=True) for s in longitudes_comerciales))
    if not stocks: raise ValueError('Sin longitudes comerciales')
    blade = number(kerf); pieces = []
    for row in cortes:
        length = number(row['longitud'], positive=True); count = integer(row['cantidad'])
        if len(pieces)+count > 10000: raise ValueError('Límite de 10000 cortes por lote')
        if length+blade > stocks[-1]: raise ValueError('Corte más kerf excede barra comercial')
        pieces.extend([length]*count)
    bars = []
    for length in sorted(pieces, reverse=True):
        available = [b for b in bars if b['restante'] >= length+blade]
        if available: bar = min(available, key=lambda b:b['restante'])
        else:
            # Largest stock for packing, shrink each completed bar to the shortest feasible stock.
            bar = {'longitud':stocks[-1], 'cortes':[], 'restante':stocks[-1]}; bars.append(bar)
        bar['cortes'].append(length); bar['restante'] -= length+blade
    result=[]
    for bar in bars:
        used = sum(bar['cortes']) + blade*len(bar['cortes'])
        stock = next(s for s in stocks if s >= used)
        result.append({'longitud_comercial':str(stock), 'cortes':[str(c) for c in bar['cortes']],
                       'kerf_total':str(blade*len(bar['cortes'])), 'sobrante':str(stock-used)})
    return {'metodo':'First Fit Decreasing / best remaining fit; heurística, no óptimo garantizado',
            'convencion_kerf':'Un corte de sierra por pieza, incluso la última; conservador',
            'barras':result, 'piezas_comerciales':len(result), 'longitud_requerida':str(sum(pieces)),
            'longitud_comprada':str(sum(Decimal(b['longitud_comercial']) for b in result)),
            'sobrante_total':str(sum(Decimal(b['sobrante']) for b in result))}


def peso_acero(tipo, dimensiones, longitud=1, cantidad=1, unidades='si', unidad_dimensiones=None, unidad_longitud=None, unidad_area=None):
    from .units import length_m, convertir_unidades
    if unidades not in ('si','us'): raise ValueError('peso_acero: unidades debe ser si o us')
    if not isinstance(dimensiones,dict): raise ValueError('peso_acero: dimensiones debe ser objeto')
    aliases={'od':'diametro_exterior','outside_diameter':'diametro_exterior','wall_thickness':'espesor','wall':'espesor',
             'thickness':'espesor','width':'ancho','area_source':'fuente_area'}
    d={}
    for key,value in dimensiones.items():
        canonical=aliases.get(key,key)
        if canonical in d and d[canonical]!=value: raise ValueError('peso_acero: dimensiones conflictivas en '+canonical)
        d[canonical]=value
    def required(key):
        if key not in d: raise ValueError('peso_acero: falta campo dimensiones.'+key)
        return d[key]
    dim_unit=unidad_dimensiones or ('in' if unidades=='us' else 'm')
    len_unit=unidad_longitud or ('ft' if unidades=='us' else 'm')
    def dimension(key):
        value=length_m(required(key),dim_unit)
        if value<=0: raise ValueError('peso_acero: dimensiones.'+key+' debe ser positiva')
        return value
    density=number(d.get('densidad',7850),positive=True)
    if tipo=='placa': area=dimension('ancho')*dimension('espesor')
    elif tipo=='tubo':
        outer,wall=dimension('diametro_exterior'),dimension('espesor')
        if 2*wall>=outer: raise ValueError('peso_acero: dimensiones.espesor incompatible con diametro_exterior')
        area=Decimal(str(math.pi))/4*(outer**2-(outer-2*wall)**2)
    elif tipo=='perfil':
        if not d.get('fuente_area'): raise ValueError('peso_acero: dimensiones.fuente_area es obligatoria para área de catálogo')
        area=number(convertir_unidades(required('area'),unidad_area or ('in2' if unidades=='us' else 'm2'),'m2')['valor'],positive=True)
    else: raise ValueError('peso_acero: tipo debe ser tubo, placa o perfil')
    length=length_m(longitud,len_unit)
    if length<=0: raise ValueError('peso_acero: longitud debe ser positiva')
    weight=area*length*integer(cantidad,positive=True)*density
    return {'kg':str(weight),'lb':convertir_unidades(weight,'kg','lb')['valor'],'area_m2':str(area),'longitud_m':str(length),
            'densidad_kg_m3':str(density),'unidades_entrada':{'dimensiones':dim_unit,'longitud':len_unit},
            'base_densidad':'Supuesto ajustable 7850 kg/m3' if 'densidad' not in d else 'Proporcionada por usuario (kg/m3)',
            'metodo':'Geometría ideal; OD real y espesor real, no diámetro nominal ni schedule inferido. Verificar catálogo/certificado'}


def _pdf_info(raw):
    from pypdf import PdfReader
    reader=PdfReader(BytesIO(raw))
    if reader.is_encrypted: raise ValueError('PDF cifrado')
    if len(reader.pages)>500: raise ValueError('PDF excede 500 páginas')
    pages=[]
    for i,p in enumerate(reader.pages,1):
        text=p.extract_text() or ''
        pages.append({'pagina':i,'ancho_pt':float(p.mediabox.width),'alto_pt':float(p.mediabox.height),
                      'capa_texto':bool(text.strip()), 'revision_visual_requerida':True})
    return pages


def inventario_archivos(ruta):
    path=Path(ruta); rows=[]
    def entry(name,size,read):
        row={'nombre':name,'bytes':size,'paginas':None}
        if name.lower().endswith('.pdf'):
            if size>25*1024*1024: row['error']='PDF excede 25 MB; dividir por disciplina'
            else:
                try: row['paginas']=_pdf_info(read())
                except Exception as exc: row['error']=str(exc)
        rows.append(row)
    if path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            infos=[i for i in archive.infolist() if not i.is_dir()]
            if len(infos)>10000: raise ValueError('ZIP excede 10000 entradas')
            for i in infos: entry(i.filename,i.file_size,lambda i=i:archive.read(i))
    elif path.is_dir():
        for p in sorted(path.rglob('*')):
            if p.is_file() and not p.is_symlink(): entry(str(p.relative_to(path)),p.stat().st_size,p.read_bytes)
    elif path.is_file(): entry(path.name,path.stat().st_size,path.read_bytes)
    else: raise FileNotFoundError(ruta)
    return rows


def leer_texto_pdf(ruta,pagina_inicio,pagina_fin,conservar_layout=False):
    from pypdf import PdfReader
    if Path(ruta).stat().st_size>25*1024*1024: raise ValueError('Dividir PDF mayor de 25 MB')
    reader=PdfReader(ruta)
    start=integer(pagina_inicio,positive=True); end=integer(pagina_fin,positive=True)
    if not start<=end<=len(reader.pages) or end-start>=50: raise ValueError('Rango inválido o mayor de 50 páginas')
    return [{'pagina':i,'texto':reader.pages[i-1].extract_text(extraction_mode='layout' if conservar_layout else 'plain') or ''} for i in range(start,end+1)]


def buscar_en_pdf(ruta,terminos):
    from pypdf import PdfReader
    if not terminos or any(not str(t).strip() for t in terminos): raise ValueError('Términos vacíos')
    if Path(ruta).stat().st_size>25*1024*1024: raise ValueError('Dividir PDF mayor de 25 MB')
    reader=PdfReader(ruta); found=[]
    if len(reader.pages)>500: raise ValueError('Dividir PDF mayor de 500 páginas')
    for i,p in enumerate(reader.pages,1):
        text=p.extract_text() or ''
        for term in terminos:
            pos=text.casefold().find(term.casefold())
            if pos>=0: found.append({'pagina':i,'termino':term,'contexto':text[max(0,pos-100):pos+len(term)+180]})
    return found


def rasterizar_pagina(ruta,pagina,dpi=150,region=None):
    import pypdfium2 as pdfium
    from PIL import Image
    page_number=integer(pagina,positive=True); resolution=integer(dpi,positive=True)
    if resolution>300: raise ValueError('DPI máximo 300')
    with pdfium.PdfDocument(ruta) as doc:
        if page_number>len(doc): raise ValueError('Página fuera de rango')
        page=doc[page_number-1]
        if page.get_width()*page.get_height()*(resolution/72)**2 > 60_000_000: raise ValueError('Render excede 60 megapíxeles; reduzca DPI')
        bitmap=page.render(scale=resolution/72)
        im=bitmap.to_pil().copy(); bitmap.close(); page.close()
    if region is not None:
        if len(region)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=1 for v in region) or not (region[0]<region[2] and region[1]<region[3]): raise ValueError('Región inválida')
        im=im.crop(tuple(int(v*(im.width if i%2==0 else im.height)) for i,v in enumerate(region)))
    return im


def ocr_pagina(ruta,pagina,region=None,idioma='eng'):
    import re
    if not re.fullmatch(r'[a-z]{3}(?:\+[a-z]{3})*',idioma): raise ValueError('Idioma OCR inválido')
    image=rasterizar_pagina(ruta,pagina,region=region)
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'page.png';image.save(path)
        try: result=subprocess.run(['tesseract',str(path),'stdout','-l',idioma],capture_output=True,text=True,check=True,timeout=90)
        except FileNotFoundError: return {'estado':'PENDIENTE_OCR','motivo':'Instale Tesseract y sus idiomas; no se infieren cotas'}
        except subprocess.TimeoutExpired: return {'estado':'PENDIENTE_OCR','motivo':'OCR excedió 90 segundos; reduzca región'}
        except subprocess.CalledProcessError: return {'estado':'PENDIENTE_OCR','motivo':'Tesseract no pudo procesar la página; revise idioma instalado y archivo'}
    return {'texto':result.stdout,'estado':'PENDIENTE_REVISION_VISUAL','pagina':pagina,'region':region}


def buscar_precio(concepto,unidad=None,region=None,catalogo=None):
    if not catalogo: return None
    matches=[r for r in catalogo if r.get('concepto','').casefold()==concepto.casefold() and (unidad is None or r.get('unidad')==unidad) and (region is None or r.get('region')==region) and r.get('fuente') and r.get('precio') is not None]
    for row in matches: number(row['precio'])
    return {'coincidencias':matches,'estado':'VALIDACION_LOCAL_REQUERIDA'} if matches else None


def registrar_supuesto(tipo,descripcion,fuente,impacto='medio',responsable=None):
    if tipo not in ('supuesto','conflicto','pregunta_rfi','exclusion') or impacto not in ('alto','medio','bajo'): raise ValueError('Tipo/impacto inválido')
    if not descripcion.strip() or not fuente.strip(): raise ValueError('Descripción y fuente obligatorias')
    return {'tipo':tipo,'descripcion':descripcion,'fuente':fuente,'impacto':impacto,'responsable':responsable or 'PENDIENTE','estado':'ABIERTO'}


def present(value):
    return bool(str(value or '').strip()) and str(value).strip().upper() not in ('PENDING','PENDIENTE','NO REGISTRADO','UNKNOWN')


QC_KEYS=('addenda_aplicados','fecha_verificada','alcance_declarado','unidades_verificadas','top5_recontado','cobertura_forma_oferta','desperdicio_declarado','normas_verificadas','acabados_declarados','peso_logistica_verificados','condicion_fiscal_verificada','documentacion_listada','razonabilidad_verificada')


def validar_entregable(entregable,datos):
    failures=[]; checks=datos.get('qc',{})
    for key in QC_KEYS:
        # No truthy strings, empty checklist or implicit pass.
        record=checks.get(key,{})
        if not isinstance(record,dict) or record.get('ok') is not True or not present(record.get('fuente')) or not present(record.get('responsable')): failures.append('QC:'+key)
    rows=datos.get('takeoff',[])
    if not rows: failures.append('TAKEOFF_VACIO')
    ids=[]
    for row in rows:
        rid=row.get('id');ids.append(rid)
        if not rid or not row.get('aprobado_por'): failures.append('TAKEOFF_NO_APROBADO:'+str(rid))
        try:
            calc=calcular_takeoff(**{k:row[k] for k in ('concepto','formula','variables','unidad','fuente')},desperdicio_pct=row.get('desperdicio_pct'), **{k:row[k] for k in ('tamano_empaque','unidad_compra','redondeo','multiplo_compra') if k in row})
            if calc['cantidad_compra'] is None or number(row.get('cantidad_compra')) != number(calc['cantidad_compra']): failures.append('CANTIDAD_NO_CONCILIA:'+str(rid))
        except (KeyError,TypeError,ValueError,SyntaxError): failures.append('TRAZABILIDAD_INCOMPLETA:'+str(rid))
    if len(ids)!=len(set(ids)): failures.append('IDS_DUPLICADOS')
    for issue in datos.get('supuestos',[]):
        if issue.get('impacto')=='alto' and issue.get('estado')!='RESUELTO': failures.append('RIESGO_ALTO_ABIERTO')
    for check in datos.get('comprobaciones',[]):
        try:
            if not check.get('fuente') or number(check['disponible'])<number(check['requerido']): failures.append('COBERTURA_INSUFICIENTE:'+check.get('id',''))
        except (KeyError,ValueError): failures.append('COMPROBACION_INVALIDA')
    if entregable=='rfq':
        rfq=datos.get('rfq',datos); items=[i for s in rfq.get('secciones',[]) for i in s.get('items',[])]
        index={r.get('id'):r for r in rows}
        if not items: failures.append('RFQ_VACIO')
        for n,item in enumerate(items,1):
            ref=index.get(item.get('takeoff_id'))
            if item.get('n')!=n: failures.append('NUMERACION_NO_CONTINUA')
            try:
                if not ref or item.get('unit')!=ref.get('unidad_compra',ref.get('unidad')) or number(item.get('qty'))!=number(ref.get('cantidad_compra')): failures.append('RFQ_NO_CONCILIA:'+str(n))
            except ValueError: failures.append('RFQ_CANTIDAD_INVALIDA:'+str(n))
            if not present(item.get('spec')): failures.append('ESPECIFICACION_PENDIENTE:'+str(n))
            if str(item.get('unit','')).lower() in ('rollos','rollo','rolls','roll','bolsas','bolsa','bags','bag','piezas','pieza','pcs','ea','cajas','sacos'):
                try:
                    if number(item.get('qty'))!=number(item.get('qty')).to_integral_value(): failures.append('COMPRA_FRACCIONARIA:'+str(n))
                except ValueError: pass
        refs=[i.get('takeoff_id') for i in items]
        if len(refs)!=len(set(refs)): failures.append('RFQ_TAKEOFF_DUPLICADO')
        expected={r['id'] for r in rows if r.get('incluir_rfq',True)}
        if set(refs)!=expected: failures.append('RFQ_COBERTURA_INCOMPLETA')
        for group,fields in {'solicitante':('razon_social','direccion','licencia','telefono'),'rfq':('numero','fecha'),'proyecto':('nombre','entidad','numero','direccion','regimen_salarial'),'devolver_a':('nombre','empresa','telefono','direccion'),'dirigido_a':('tipo_proveedor',)}.items():
            for key in fields:
                if not present(rfq.get(group,{}).get(key)): failures.append('CAMPO_PENDIENTE:'+group+'.'+key)
    return {'estado':'APTO' if not failures else 'BLOQUEADO','fallas':sorted(set(failures)),'nota':VALIDATION_NOTE}


def resolver_jerarquia(registros):
    """Select explicit revisions per subject; retain conflicts, never silently infer dates."""
    rank={'addendum':4,'especificacion':3,'detalle':2,'plano_general':1}; chosen={};conflicts=[]
    for r in registros:
        if r.get('tipo') not in rank or not r.get('fuente') or not r.get('asunto'): raise ValueError('Documento sin tipo/fuente/asunto')
        revision=integer(r.get('revision',0)); key=r['asunto']; old=chosen.get(key)
        priority=(rank[r['tipo']],revision)
        if old:
            op=(rank[old['tipo']],integer(old.get('revision',0)))
            if old.get('valor')!=r.get('valor'):
                conflicts.append({'asunto':key,'fuentes':[old['fuente'],r['fuente']],'estado':'REQUIERE_REVISION' if op==priority else 'RESUELTO_POR_JERARQUIA'})
            if priority==op and old.get('valor')!=r.get('valor'): raise ValueError('Conflicto con igual jerarquía y revisión: '+key)
            if priority<op: continue
        chosen[key]=r
    return {'vigentes':chosen,'conflictos':conflicts}


def alertas_fechas(fecha_entrega,ahora=None):
    if not fecha_entrega: return ['PENDIENTE: fecha vigente de entrega']
    due=datetime.fromisoformat(fecha_entrega.replace('Z','+00:00'))
    now=ahora or datetime.now(timezone.utc)
    if isinstance(now,str): now=datetime.fromisoformat(now.replace('Z','+00:00'))
    if due.tzinfo is None or now.tzinfo is None: raise ValueError('Fecha requiere zona horaria explícita')
    hours=(due-now).total_seconds()/3600
    return ['VENCIDA: fecha de entrega'] if hours<0 else ['URGENTE: menos de 72 horas'] if hours<72 else []
