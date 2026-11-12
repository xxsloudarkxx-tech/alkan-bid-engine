"""Material views of the very same cost resources; no independent quantity/price inputs."""
from collections import defaultdict

from openpyxl.styles import PatternFill

from .workbooks import _sheet,reference


def material_resources(result):
    return [(row,r) for row,r in enumerate(result['resources'],2) if r['kind']=='material' or r.get('material_package')]


def append_purchase_sheets(book,result):
    item_rows={i['id']:n for n,i in enumerate(result['items'],2)}
    quotes={q['id']:q for q in result['quotes']}
    instructions=_sheet(book,'LEEME_Materiales',['Tema','Instrucción'],[
        ['Proyecto',result['project_id']],['Fingerprint de entradas',result['pricing_fingerprint']],['Sincronización','Materiales_Detalle y Resumen_de_Compras usan las mismas filas de Resources, Items y Quotes del presupuesto. No tienen precios o mediciones independientes.'],
        ['Editar','Edite los parámetros amarillos de Resources/Quotes y las observaciones AH de Materiales_Detalle. Conserve IDs y fórmulas. cost-import y build conservan los cambios y regeneran estas hojas.'],
        ['Cantidad neta','La cantidad neta documentada puede conocerse aunque la compra final siga pendiente por merma, presentación o desglose. Un área sembrada no se convierte en peso de semilla sin dosificación.'],
        ['Paquetes','Los conjuntos de señalización conservan sus conteos físicos. Las cifras conceptuales sin unidad o inclusiones económicas definidas se muestran en Referencias_Conceptuales, fuera de Quotes y de los subtotales. No son precios de material o instalación.'],
        ['Alternativos','Se agrupa por material, especificación, unidad, alcance y signo. Base, cada alternativo y lo no asignado nunca se agregan entre sí. No hay total automático de compras de todos los alternativos.'],
        ['Estado','CONFIRMADO exige precio confirmado utilizable; ESTIMADO admite referencia real aproximada o rango. PENDIENTE conserva importes vacíos, no cero. Ninguna fila autoriza una compra.'],
        ['Referencia global','Referencia_Global contiene presupuestos del propietario/A-E. No se asignan a partidas ni se suman al subtotal calculado.'],
    ])
    headers=['ID recurso','Partida','Especialidad','Alcance','Schedule / paquete','Material / paquete','Especificación documentada','Tipo de recurso','Cantidad partida','Unidad partida','Consumo recurso/partida','Unidad recurso','Cantidad neta recurso','Desperdicio fracción','Cantidad desperdicio','Cantidad total recurso','Conversión compra/recurso','Unidad compra','Cantidad para compra','Precio unitario','Costo extendido','Costo inferior','Costo superior','ID precio','Proveedor / origen','Fecha precio','Confianza','Clase del precio','Estado medición','Estado económico','Condición de compra','Documento / página / lámina / adenda','Aclaración técnica','Observaciones estimador','Clave agrupación','Precio inferior unitario','Precio superior unitario','Localidad precio','Signo ADD/DEDUCT','Clase en presupuesto']
    rows=[];groups=defaultdict(list)
    for original_row,r in material_resources(result):
        quote=quotes.get(r.get('quote_id'),{})
        specialty='Plantación / paisajismo' if r['quantity_id'].startswith(('LP-','GP-PL','MER-PL')) else ('Drenaje' if r['quantity_id'].startswith('CD03') else ('Señalización' if r.get('material_package') else 'Urbanización / alcance por desglosar'))
        unit=quote.get('unit') or r.get('resource_unit')
        item=next(i for i in result['items'] if i['id']==r['quantity_id'])
        key='|'.join(str(v or '') for v in (r.get('procurement_key',r['description']),r['pricing_scope'],item['effect'],r.get('resource_unit'),unit))
        groups[key].append((len(rows)+2,r))
        rows.append([r['id'],r['quantity_id'],specialty,r['pricing_scope'],r['package'],r['description'],r.get('material_specification'), 'Conjunto físico sin desglose' if r.get('material_package') else 'Material / conjunto', None,r['item_unit'],None,r.get('resource_unit')]+[None]*19+[reference(r.get('material_sources',item['sources'])),r.get('procurement_note'),r.get('estimator_note'),key,None,None,quote.get('locality'),item['effect'],r['kind']])
    detail=_sheet(book,'Materiales_Detalle',headers,rows)
    for row,(source_row,r) in enumerate(material_resources(result),2):
        n=item_rows[r['quantity_id']]
        for col,formula in {
            'I':f'=IF(Items!G{n}="","",Items!G{n})', 'K':f'=IF(Resources!H{source_row}="","",Resources!H{source_row})',
            'M':f'=IF(OR(I{row}="",K{row}=""),"",I{row}*K{row})', 'N':f'=IF(Resources!J{source_row}="","",Resources!J{source_row})',
            'O':f'=IF(OR(M{row}="",N{row}=""),"",M{row}*N{row})', 'P':f'=IF(O{row}="","",M{row}+O{row})',
            'Q':f'=IF(OR(L{row}="",R{row}=""),"",IF(L{row}=R{row},1,IFERROR(VLOOKUP(L{row}&">"&R{row},Conversions!$A$2:$B$100,2,FALSE),"")))',
            'R':f'=IF(Resources!P{source_row}="",L{row},Resources!P{source_row})',
            'S':f'=IF(OR(P{row}="",Q{row}=""),"",P{row}*Q{row})',
            'T':f'=IF(Resources!Q{source_row}="","",Resources!Q{source_row})',
            'U':f'=IF(Resources!W{source_row}="","",Resources!W{source_row})',
            'V':f'=IF(Resources!AA{source_row}="","",Resources!AA{source_row})',
            'W':f'=IF(Resources!AB{source_row}="","",Resources!AB{source_row})',
            'X':f'=IF(Resources!K{source_row}="","",Resources!K{source_row})',
            'Y':f'=IF(X{row}="","",IFERROR(VLOOKUP(X{row},Quotes!$A$2:$Q$10000,4,FALSE),""))',
            'Z':f'=IF(X{row}="","",IFERROR(VLOOKUP(X{row},Quotes!$A$2:$Q$10000,6,FALSE),""))',
            'AA':f'=IF(Resources!AC{source_row}="","",Resources!AC{source_row})',
            'AB':f'=IF(Resources!R{source_row}="","",Resources!R{source_row})',
            'AC':f'=IF(I{row}="","PENDIENTE_MEDICION",IF(K{row}="","PENDIENTE_CONSUMO_DESGLOSE","NETO_DOCUMENTADO"))',
            'AD':f'=IF(OR(Resources!S{source_row}<>1,AND(U{row}="",V{row}="")),"PENDIENTE",IF(AB{row}="CONFIRMED","CONFIRMADO","ESTIMADO"))',
            'AE':f'=IF(AC{row}<>"NETO_DOCUMENTADO",AC{row},IF(N{row}="","PENDIENTE_MERMA",IF(AD{row}="PENDIENTE","PENDIENTE_COTIZACION","REVISAR_ALCANCE_Y_PROVEEDOR_ANTES_DE_COMPRA")))',
            'AJ':f'=IF(Resources!Y{source_row}="","",Resources!Y{source_row})',
            'AK':f'=IF(Resources!Z{source_row}="","",Resources!Z{source_row})',
        }.items():detail[f'{col}{row}']=formula
        detail[f'AH{row}'].fill=PatternFill('solid',fgColor='FFF2CC')
        detail[f'N{row}'].number_format='0.00%'
    end=max(detail.max_row,2)
    summary_rows=[]
    for key,members in groups.items():
        r=members[0][1];quote=quotes.get(r.get('quote_id'),{})
        summary_rows.append([key,r['pricing_scope'],next(i['effect'] for i in result['items'] if i['id']==r['quantity_id']),r['description'],r.get('material_specification'),r.get('resource_unit'),quote.get('unit') or r.get('resource_unit')]+[None]*10+['Totales por grupo/alcance. Compra completa solo si no faltan consumos o merma. Revisar filas fuente y no sumar alternativos incompatibles.'])
    purchase=_sheet(book,'Resumen_de_Compras',['Clave','Alcance','Efecto','Material representativo','Especificación','Unidad neta','Unidad compra','Filas detalle','Neto cubierto','Filas sin neto','Cantidad compra completa','Filas sin compra','Costo puntual cubierto','Costo inferior cubierto','Costo superior cubierto','Filas con referencia valorizada','Filas pendientes de precio/consumo','Observaciones'],summary_rows)
    for row in range(2,purchase.max_row+1):
        cond=f'Materiales_Detalle!$AI$2:$AI${end},A{row}'
        purchase[f'H{row}']=f'=COUNTIF(Materiales_Detalle!$AI$2:$AI${end},A{row})'
        for col,src in (('I','M'),('M','U'),('N','V'),('O','W')):
            purchase[f'{col}{row}']=f'=IF(COUNTIFS({cond},Materiales_Detalle!${src}$2:${src}${end},"<>")=0,"",SUMIF(Materiales_Detalle!$AI$2:$AI${end},A{row},Materiales_Detalle!${src}$2:${src}${end}))'
        for col,src in (('J','M'),('L','S')):purchase[f'{col}{row}']=f'=COUNTIFS({cond},Materiales_Detalle!${src}$2:${src}${end},"")'
        purchase[f'K{row}']=f'=IF(L{row}>0,"",SUMIF(Materiales_Detalle!$AI$2:$AI${end},A{row},Materiales_Detalle!$S$2:$S${end}))'
        purchase[f'Q{row}']=f'=COUNTIFS({cond},Materiales_Detalle!$AD$2:$AD${end},"PENDIENTE")'
        purchase[f'P{row}']=f'=H{row}-Q{row}'
    items=book['Items']
    for col,title,src in ((24,'Directo parcial unitario','P'),(25,'Directo completo unitario','Q')):
        items.cell(1,col,title)
        for row in range(2,items.max_row+1):items.cell(row,col,f'=IF(OR(G{row}="",G{row}=0,{src}{row}=""),"",ROUND({src}{row}/G{row},2))')
    refs=result['settings'].get('documentary_cost_references',[])
    _sheet(book,'Referencia_Global',['ID','Alcance','Referencia central USD','Inferior USD','Superior USD','Fecha impresa','Vigencia / fecha por verificar','Tratamiento fiscal de referencia','Documento original','Clase','Límite'],[[r['id'],r['scope'],r['central'],r['low'],r['high'],r.get('date'),r['date_note'],r['tax'],reference(r['sources']),'ESTIMADO_DOCUMENTAL_DEL_PROPIETARIO_AE','No calculado desde partidas; no añadir a subtotales ni distribuir por porcentajes inventados.'] for r in refs])
    conceptual=result['settings'].get('conceptual_cost_references',[])
    _sheet(book,'Referencias_Conceptuales',['ID','Tipo señal','Partida de conteo, no de precio','Descripción','Importe aproximado publicado USD','Inferior publicado USD','Superior publicado USD','Unidad económica','Fabricación incluida','Suministro incluido','Instalación incluida','Fecha del plano','Fuente del importe','Detalles revisados','Decisión'],[[r['id'],r['tag'],r['quantity_id'],r['description'],r['central'],r['low'],r['high'],'NO DEFINIDA',r['fabrication'],r['supply'],r['installation'],r['date'],reference(r['sources']),reference(r['detail_sources']),'NO MULTIPLICAR NI SUMAR; pedir aclaración de base e inclusiones. '+r['note']] for r in conceptual])
    n=items.max_row
    economic=_sheet(book,'Resumen_Economico',['Métrica','Valor','Interpretación'],[
        ['Conceptos principales identificados',len(result['items']),'No representa alcance completo de obra'],
        ['Con precio puntual parcial',None,'Recursos cubiertos; no necesariamente composición completa'],
        ['Con precio puntual o rango parcial',None,'Incluye referencias exclusivamente por rango'],
        ['Porcentaje conceptos valorizados',None,'Sobre conceptos identificados, NO porcentaje del costo total'],
        ['Pendientes de medición',None,'Cantidad documental no disponible'],
        ['Pendientes sin precio/rango',None,'Incluye partidas sin medir; revisar desglose en pendientes'],
        ['Apto para revisión','SI, PRELIMINAR','Revisar referencias globales, costos parciales y pendientes'],
        ['Apto para oferta','NO','Sin liberación, composición completa ni precio total sustentado'],
        ['Referencia de costo global','Ver Referencia_Global','Información real publicada por propietario/A-E; separada de cálculo por partida'],
        ['Con cantidad documental',None,'Incluye conteos/mediciones documentales; no garantiza material listo para comprar'],
        ['Porcentaje conceptos con cantidad',None,'Sobre conceptos identificados; NO cobertura total de obra ni económica'],
        ['Referencias conceptuales sin base de precio',len(conceptual),'Ver Referencias_Conceptuales; no se cuentan como precios respaldados'],
    ])
    economic['B3']=f'=COUNTIF(Items!$P$2:$P${n},"<>")'
    economic['B4']=f'=COUNTIF(Items!$U$2:$U${n},"<>")'
    economic['B5']='=IF(B2=0,"",B4/B2)';economic['B5'].number_format='0.00%'
    economic['B6']=f'=COUNTIF(Items!$G$2:$G${n},"")'
    economic['B7']='=B2-B4'
    economic['B11']='=B2-B6'
    economic['B12']='=IF(B2=0,"",B11/B2)';economic['B12'].number_format='0.00%'
    economic.append(['SEPARACIÓN ECONÓMICA','Ubicación','Criterio'])
    for row in [
        ['1. Presupuesto publicado por propietario/A-E','Referencia_Global','Referencia externa documental, no estimado independiente ALKAN'],
        ['2. Estimado independiente ALKAN','Items / Resources','Solo composiciones calculadas con cantidades y bases económicas utilizables; vacío = no estimado'],
        ['3. Subtotales parciales documentados','Scopes / tabla siguiente','Solo costos utilizables de recursos; no incluyen referencias globales o conceptuales sin base definida'],
        ['4. Costos sin referencia suficiente','Pending decisions / Referencias_Conceptuales','No se convierten en cero; incluyen referencias monetarias sin unidad o servicios definidos'],
    ]:economic.append(row)
    economic.append(['Alcance','Subtotal puntual cubierto','Inferior cubierto','Superior cubierto','Confirmado puntual','Estimado puntual'])
    for source_row,s in enumerate(result['summaries'],2):
        row=economic.max_row+1;economic.cell(row,1,s['scope'])
        for col,src in ((2,'F'),(3,'G'),(4,'H'),(5,'R'),(6,'S')):economic.cell(row,col,f'=IF(Scopes!{src}{source_row}="","",Scopes!{src}{source_row})')
    economic.append([])
    economic.append(['REFERENCIAS GLOBALES, NO SUBTOTALES','Central publicado USD','Inferior publicado USD','Superior publicado USD','Tipo','Fuente'])
    for r in refs:economic.append([r['scope'],r['central'],r['low'],r['high'],'Presupuesto propietario/A-E; no distribuir ni sumar al parcial',reference(r['sources'])])
