"""Structured RFQ and calculation records; supplier prices remain blank."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from .rfq_engine import VALIDATION_NOTE, VALIDATION_EN, validar_entregable


def rfq_bytes(rfq, idioma='en', borrador=True, control=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.pdfgen.canvas import Canvas
    if idioma not in ('en','es'): raise ValueError('Idioma inválido')
    qc=validar_entregable('rfq',{**(control or {}),'rfq':rfq})
    if not borrador and qc['estado']!='APTO': raise ValueError('RFQ bloqueado: '+', '.join(qc['fallas']))
    en=idioma=='en'; styles=getSampleStyleSheet()
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font_dir=Path('/usr/share/fonts/truetype/dejavu')
    if (font_dir/'DejaVuSans.ttf').exists():
        pdfmetrics.registerFont(TTFont('RfqSans',str(font_dir/'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('RfqSansBold',str(font_dir/'DejaVuSans-Bold.ttf')))
        for name in styles.byName: styles[name].fontName='RfqSansBold' if name in ('Title','Heading1','Heading2','Heading3') else 'RfqSans'
    for name,size,leading in [('Title',18,22),('Heading1',15,19),('Heading2',12,15),('Heading3',10,13)]:
        styles[name].fontSize=size;styles[name].leading=leading;styles[name].spaceBefore=7;styles[name].spaceAfter=5
    small=styles['BodyText'];small.fontSize=8;small.leading=10;small.spaceAfter=4
    def p(value): return Paragraph(escape(str(value if value not in (None,'') else ('PENDING' if en else 'PENDIENTE'))).replace('\n','<br/>'),small)
    def table(rows,widths=None):
        t=Table([[p(c) for c in r] for r in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e4edef')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#b8cacc')),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
        return t
    requester=rfq.get('solicitante',{}); project=rfq.get('proyecto',{}); meta=rfq.get('rfq',{})
    story=[Paragraph(escape(str(requester.get('razon_social') or 'PENDING')),styles['Title'])]
    for key in ('giro','direccion','licencia','telefono'):
        story.append(p(requester.get(key)))
    if requester.get('logo'):
        from reportlab.platypus import Image
        image=Image(requester['logo']);image._restrictSize(90,45);story.append(image)
    story+=[Spacer(1,10),Paragraph('REQUEST FOR QUOTATION - MATERIALS' if en else 'SOLICITUD DE COTIZACIÓN - MATERIALES',styles['Heading1']),p(f"{meta.get('numero','PENDING')} | {meta.get('fecha','PENDING')}")]
    if borrador: story.append(Paragraph('DRAFT - NOT FOR ISSUE' if en else 'BORRADOR - NO EMITIR',styles['Heading2']))
    story.append(Paragraph(escape(str(project.get('nombre') or 'PENDING')),styles['Heading2']))
    for key in ('entidad','numero','direccion','regimen_salarial','aditivos_excluidos'): story.append(p(project.get(key)))
    recipient=rfq.get('dirigido_a',{}); back=rfq.get('devolver_a',{})
    story.extend([Spacer(1,10),table([['Quote requested from' if en else 'Cotización solicitada a','Return quote to' if en else 'Devolver cotización a'],['\n'.join(str(recipient.get(k) or 'PENDING') for k in ('tipo_proveedor','nota')),'\n'.join(str(back.get(k) or 'PENDING') for k in ('nombre','cargo','empresa','telefono','direccion'))]],[260,260]),p('Requested by: '+str(back.get('nombre') or '________'))])
    story.append(Paragraph('Delivery & Requirements' if en else 'Entrega y requisitos',styles['Heading2']))
    for requirement in rfq.get('entrega_y_requisitos',[]): story.append(p('- '+requirement))
    story.append(p('Include unit and extended prices, lead time, freight and quote validity. Identify substitutions.' if en else 'Incluir precio unitario y extendido, plazo, flete y vigencia. Identificar sustituciones.'))
    story.append(Paragraph('Materials List' if en else 'Lista de materiales',styles['Heading2']))
    for section in rfq.get('secciones',[]):
        story.append(Paragraph(escape(str(section.get('id',''))+'. '+str(section.get('titulo',''))),styles['Heading3']))
        story.append(p(section.get('nota')))
        rows=[['#','Item','Specification' if en else 'Especificación','Qty' if en else 'Cant.','Unit' if en else 'Unidad','Unit price' if en else 'P. unitario','Lead time' if en else 'Plazo']]
        for item in section.get('items',[]): rows.append([item.get('n'),item.get('item'),item.get('spec'),item.get('qty'),item.get('unit'),'________','________'])
        story.extend([table(rows,[22,100,164,42,40,76,76]),Spacer(1,8)])
    story.append(Paragraph('Technical Summary' if en else 'Resumen técnico',styles['Heading2']))
    story.append(table([['Parameter' if en else 'Parámetro','Requirement' if en else 'Requisito']]+[[r.get('parametro'),r.get('requisito')] for r in rfq.get('resumen_tecnico',[])],[170,350]))
    story.extend([Spacer(1,12),p('Supplier / Representative / Total / Validity / Date: ______________________' if en else 'Proveedor / Representante / Total / Vigencia / Fecha: ______________________'),p(VALIDATION_EN if en else VALIDATION_NOTE)])
    raw=BytesIO()
    class NumberedCanvas(Canvas):
        def __init__(self,*a,**kw): kw['invariant']=1;super().__init__(*a,**kw);self.states=[]
        def showPage(self): self.states.append(dict(self.__dict__));self._startPage()
        def save(self):
            total=len(self.states)
            for state in self.states:
                self.__dict__.update(state); self.setFont('Helvetica',7)
                label=f"{requester.get('razon_social','')} | {project.get('nombre','')}"
                self.drawString(46,25,label[:100]);self.drawRightString(566,25,f"{'Page' if en else 'Página'} {self._pageNumber} / {total}");super().showPage()
            super().save()
    SimpleDocTemplate(raw,pagesize=letter,leftMargin=46,rightMargin=46,topMargin=36,bottomMargin=45).build(story,canvasmaker=NumberedCanvas)
    return raw.getvalue()


def generar_rfq_pdf(rfq,ruta_salida,idioma='en',borrador=True,control=None):
    output=Path(ruta_salida);output.parent.mkdir(parents=True,exist_ok=True)
    raw=rfq_bytes(rfq,idioma,borrador,control);output.write_bytes(raw)
    return {'ruta':str(output),'borrador':borrador,'qc':validar_entregable('rfq',{**(control or {}),'rfq':rfq})}


def generar_excel(proyecto,hojas,ruta_salida):
    """Python runtime export, matching the project's existing openpyxl dependency.

    Six sheets; purchase and APU extend live linked quantities. Missing prices
    remain empty and incomplete totals remain PENDIENTE, never silently zero.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.workbook.properties import CalcProperties
    from .rfq_engine import calcular_takeoff
    wb=Workbook();wb.remove(wb.active)
    for name in ('Resumen','Takeoff','Memoria de cálculo','APU','Compras por proveedor','Supuestos'): wb.create_sheet(name)
    wb.calculation=CalcProperties(calcId=0,fullCalcOnLoad=True)
    summary=wb['Resumen'];summary.append(['Proyecto',proyecto]);summary.append(['Validación',VALIDATION_NOTE])
    take=wb['Takeoff'];take.append(['ID','Concepto','Unidad','Cantidad neta','Desperdicio %','Cantidad compra','Fuente','Tamaño empaque','Unidad compra','Redondeo','Múltiplo compra'])
    memory=wb['Memoria de cálculo'];memory.append(['ID','Fórmula','Variables','Fuente','Resultado'])
    apu=wb['APU'];apu.append(['ID','Cantidad','Material / unidad','MO / unidad','Equipo / unidad','Subcontrato / unidad','Fuente precios','APU','Importe'])
    buy=wb['Compras por proveedor'];buy.append(['ID','Proveedor','Cantidad','Unidad','Precio unitario','Importe'])
    assumptions=wb['Supuestos'];assumptions.append(['Tipo','Descripción','Fuente','Impacto','Responsable','Estado'])
    for i,row in enumerate(hojas.get('takeoff',[]),2):
        calc=calcular_takeoff(**{k:row[k] for k in ('concepto','formula','variables','unidad','fuente')},desperdicio_pct=row.get('desperdicio_pct'), **{k:row[k] for k in ('tamano_empaque','unidad_compra','redondeo','multiplo_compra') if k in row})
        take.append([row['id'],row['concepto'],row['unidad'],f"='Memoria de cálculo'!E{i}",None if calc['desperdicio_pct'] is None else float(calc['desperdicio_pct']),
            f'=IF(E{i}="","PENDIENTE",IF(J{i}="arriba",CEILING(D{i}*(1+E{i}/100)/H{i},K{i}),D{i}*(1+E{i}/100)/H{i}))',row['fuente'],
            float(calc['tamano_empaque'] or 1),calc['unidad_compra'],calc['redondeo'],float(calc['multiplo_compra'])])
        from openpyxl.utils import get_column_letter
        import re
        cells={name:f'{get_column_letter(6+j)}{i}' for j,name in enumerate(row['variables'])}
        formula=re.sub(r'\b[A-Za-z_][A-Za-z_0-9]*\b',lambda m:cells.get(m[0],m[0]),row['formula']).replace('**','^')
        memory.append([row['id'],row['formula'],str(row['variables']),row['fuente'],'='+formula,*[float(v) for v in row['variables'].values()]])
        for j in range(len(cells)):memory.cell(1,6+j,'Entrada '+str(j+1)+' (ver Variables)')
        prices=row.get('apu',{});src=prices.get('fuente')
        apu.append([row['id'],f"='Takeoff'!F{i}",*[float(prices[k]) if src and prices.get(k) is not None else None for k in ('material','mano_obra','equipo','subcontratos')],src,f'=IF(COUNT(C{i}:F{i})<4,"PENDIENTE",SUM(C{i}:F{i}))',f'=IF(OR(ISTEXT(B{i}),ISTEXT(H{i})),"PENDIENTE",B{i}*H{i})'])
        buy.append([row['id'],row.get('proveedor'),f"='Takeoff'!F{i}",calc['unidad_compra'],float(prices['material']) if src and prices.get('material') is not None else None,f'=IF(OR(E{i}="",ISTEXT(C{i})),"PENDIENTE",C{i}*E{i})'])
    for row in hojas.get('supuestos',[]): assumptions.append([row.get(k) for k in ('tipo','descripcion','fuente','impacto','responsable','estado')])
    if take.max_row>1:
        end=take.max_row;summary.append(['Costo directo',f'=IF(COUNT(APU!I2:I{end})<COUNTA(APU!A2:A{end}),"PENDIENTE",SUM(APU!I2:I{end}))'])
    else: summary.append(['Costo directo','PENDIENTE'])
    summary.append(['Indirectos / financiamiento / utilidad / impuestos','PENDIENTE - usar expediente de costos con respaldo'])
    for ws in wb:
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]: cell.font=Font(color='FFFFFF',bold=True);cell.fill=PatternFill('solid',fgColor='164E63')
        for col in ws.columns:
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(col[0].column)].width= min(55,max(16,max(len(str(c.value or '')) if c.data_type!='f' else 18 for c in col)+2))
            for cell in col:
                allowed={'Takeoff':{4,6},'Memoria de cálculo':{5},'APU':{2,8,9},'Compras por proveedor':{3,6},'Resumen':{2}}
                trusted=cell.column in allowed.get(ws.title,set()) and cell.row>=2
                if ws.title=='Resumen': trusted=cell.coordinate=='B3'
                if isinstance(cell.value,str) and cell.value.startswith(('=','+','-','@')) and not trusted: cell.data_type='s'
                cell.alignment=Alignment(vertical='top',wrap_text=True)
        for row in ws.iter_rows(min_row=2): ws.row_dimensions[row[0].row].height=32
    output=Path(ruta_salida);output.parent.mkdir(parents=True,exist_ok=True);wb.save(output)
    return {'ruta':str(output),'nota':VALIDATION_NOTE}


def generar_documento(tipo,contenido,formato,ruta_salida):
    if tipo not in ('propuesta','memoria_tecnica','resumen_ejecutivo','registro_conflictos') or formato not in ('docx','pdf'): raise ValueError('Tipo/formato inválido')
    if tipo=='propuesta' and validar_entregable('propuesta',contenido)['estado']!='APTO': raise ValueError('Propuesta bloqueada por QC')
    output=Path(ruta_salida);output.parent.mkdir(parents=True,exist_ok=True)
    sections=contenido.get('secciones',[])
    if formato=='docx':
        from docx import Document
        doc=Document();doc.add_heading(contenido.get('titulo',tipo),0)
        for section in sections:
            doc.add_heading(section['titulo'],1);doc.add_paragraph(section['texto'])
        doc.add_paragraph(VALIDATION_NOTE);doc.save(output)
    else:
        from reportlab.platypus import SimpleDocTemplate,Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        styles=getSampleStyleSheet();story=[Paragraph(escape(contenido.get('titulo',tipo)),styles['Title'])]
        for section in sections: story.extend([Paragraph(escape(section['titulo']),styles['Heading2']),Paragraph(escape(section['texto']),styles['BodyText'])])
        story.append(Paragraph(VALIDATION_NOTE,styles['BodyText']));SimpleDocTemplate(str(output)).build(story)
    return {'ruta':str(output),'nota':VALIDATION_NOTE}


def dossier_rfq(row,language='en'):
    """Adapter uses one persisted revision, never estimates procurement quantities."""
    state=row['state'];p=state['project'];en=language=='en';pending='PENDING' if en else 'PENDIENTE'
    groups={};n=0
    for line in state['lines']:
        if not line.get('active',True) or line.get('category')!='material':continue
        n+=1;key=line.get('supplier_type') or line.get('trade') or pending
        groups.setdefault(key,[]).append({'n':n,'item':line['description'],'spec':line.get('specification') or pending,
            'qty':line.get('purchase_quantity') if line.get('purchase_quantity') is not None else pending,
            'unit':line.get('purchase_unit') or pending,'takeoff_id':line['line_id'],'unit_price':None,'lead_time':None})
    # Grouping changes presentation order; number continuously in that order.
    n=0;sections=[]
    for i,(key,items) in enumerate(groups.items(),1):
        for item in items:n+=1;item['n']=n
        sections.append({'id':str(i),'titulo':key,'nota':p.get('delivery_requirements') or pending,'items':items})
    return {'solicitante':{'razon_social':p.get('contractor'),'giro':p.get('trade'),'direccion':p.get('contractor_address'),'licencia':p.get('license') or p.get('contractor_license'),'telefono':p.get('contractor_phone')},
            'rfq':{'numero':f"RFQ-{p['project_id']}-R{row['revision']}",'fecha':row['created_at'][:10]},
            'proyecto':{'nombre':p['name'],'entidad':p.get('client'),'numero':p.get('contract_number') or p['project_id'],'direccion':p.get('address'),'regimen_salarial':p.get('wage_regime'),'aditivos_excluidos':state.get('review',{}).get('exclusions')},
            'dirigido_a':{'tipo_proveedor':', '.join(groups),'nota':'Each section may be quoted by a different supplier.' if en else 'Cada sección puede cotizarla un proveedor distinto.'},
            'devolver_a':{'nombre':p.get('estimator'),'empresa':p.get('contractor'),'telefono':p.get('contractor_phone'),'direccion':p.get('contractor_address'),'cargo':p.get('estimator_role')},
            'entrega_y_requisitos':[p.get('delivery_requirements') or pending,p.get('tax_requirements') or pending,p.get('submittal_requirements') or pending],
            'secciones':sections,'resumen_tecnico':[{'parametro':'Quantity basis / Base de cantidades','requisito':'Purchase units pending unless explicitly reviewed; work quantities are not procurement quantities.' if en else 'Unidades de compra pendientes hasta revisión expresa; cantidades de obra no equivalen a unidades de compra.'}], 'cierre':{}}
