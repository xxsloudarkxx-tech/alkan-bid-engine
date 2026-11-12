"""Calibrated full-sheet pixel geometry bound to the PDF SHA256 and page.

Points are selected by a person (or supplied as unapproved candidates), not
inferred from OCR. Single-scale calibration assumes an undistorted sheet.
"""
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
from pathlib import Path
from .rfq_engine import number, integer, rasterizar_pagina
from .units import unit, FACTORS

def _points(points, width, height, minimum):
    if not isinstance(points,list) or not minimum<=len(points)<=10000: raise ValueError(f'Se requieren {minimum} a 10000 puntos [x,y]')
    result=[]
    for point in points:
        if not isinstance(point,(list,tuple)) or len(point)!=2: raise ValueError('Punto inválido; use [x,y]')
        x,y=map(number,point)
        if x>width or y>height: raise ValueError('Punto fuera de la imagen completa calibrada')
        result.append((x,y))
    return result

def _distance(a,b): return ((a[0]-b[0])**2+(a[1]-b[1])**2).sqrt()

def calibrar_escala(ruta,pagina,puntos_referencia,distancia_real,unidad_real,fuente,dpi=150,incertidumbre_pct=None):
    key=unit(unidad_real)
    if FACTORS[key][0]!='length': raise ValueError('unidad_real debe ser de longitud, por ejemplo ft')
    if not str(fuente).strip(): raise ValueError('Indique hoja y cota escrita que calibra la escala')
    real=number(distancia_real,positive=True)
    image=rasterizar_pagina(ruta,pagina,dpi)
    points=_points(puntos_referencia,image.width,image.height,2)
    if len(points)!=2: raise ValueError('Calibración requiere exactamente dos puntos')
    pixels=_distance(*points)
    if pixels<=0: raise ValueError('Puntos de referencia coincidentes')
    error=number(incertidumbre_pct) if incertidumbre_pct is not None else None
    if error is not None and error>100: raise ValueError('Incertidumbre fuera de 0-100%')
    return {'ruta':str(Path(ruta).resolve()),'sha256':sha256(Path(ruta).read_bytes()).hexdigest(),
            'pagina':integer(pagina,positive=True),'dpi':integer(dpi,positive=True),'ancho_px':image.width,'alto_px':image.height,
            'puntos_referencia':puntos_referencia,'distancia_real':str(real),'unidad_real':key,'fuente':fuente,
            'unidades_por_pixel':str(real/pixels),'incertidumbre_pct':None if error is None else str(error),
            'estado':'CALCULADO_PENDIENTE_REVISION','supuesto':'Escala uniforme; no usar en escaneo deformado, perspectiva ni imagen recortada/redimensionada'}

def _cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])

def _intersects(a,b,c,d):
    def on(a,b,c): return min(a[0],b[0])<=c[0]<=max(a[0],b[0]) and min(a[1],b[1])<=c[1]<=max(a[1],b[1])
    x,y,z,w=_cross(a,b,c),_cross(a,b,d),_cross(c,d,a),_cross(c,d,b)
    return ((x*y<0 and z*w<0) or (x==0 and on(a,b,c)) or (y==0 and on(a,b,d)) or (z==0 and on(c,d,a)) or (w==0 and on(c,d,b)))

def medir_plano(calibracion,puntos,tipo,fuente):
    c=calibracion
    if sha256(Path(c['ruta']).read_bytes()).hexdigest()!=c['sha256']: raise ValueError('El PDF cambió; vuelva a calibrar la página')
    # Recompute rather than trusting an editable JSON scale factor.
    expected=calibrar_escala(**{k:c[k] for k in ('ruta','pagina','puntos_referencia','distancia_real','unidad_real','fuente','dpi','incertidumbre_pct')})
    if any(c.get(k)!=expected[k] for k in ('unidades_por_pixel','ancho_px','alto_px')): raise ValueError('Calibración alterada; vuelva a calibrar')
    if tipo not in ('longitud','area'): raise ValueError('tipo debe ser longitud o area')
    if not str(fuente).strip(): raise ValueError('Indique hoja/detalle de la medición')
    pts=_points(puntos,number(c['ancho_px']),number(c['alto_px']),2 if tipo=='longitud' else 3)
    if tipo=='area' and pts[0]==pts[-1]: pts.pop()
    if tipo=='area':
        if len(set(pts))!=len(pts) or len(pts)<3: raise ValueError('Polígono con vértices repetidos o insuficientes')
        size=len(pts)
        for i in range(size):
            for j in range(i+1,size):
                if j==i+1 or (i==0 and j==size-1): continue
                if _intersects(pts[i],pts[(i+1)%size],pts[j],pts[(j+1)%size]): raise ValueError('Polígono se cruza a sí mismo')
        raw=abs(sum(pts[i][0]*pts[(i+1)%size][1]-pts[(i+1)%size][0]*pts[i][1] for i in range(size)))/2
        value=raw*number(c['unidades_por_pixel'])**2
        result_unit=c['unidad_real']+'2'
    else:
        value=sum((_distance(a,b) for a,b in zip(pts,pts[1:])),Decimal(0))*number(c['unidades_por_pixel'])
        result_unit=c['unidad_real']
    if value<=0: raise ValueError('Geometría sin longitud/área positiva')
    error=None if c['incertidumbre_pct'] is None else number(c['incertidumbre_pct'])/100
    power=2 if tipo=='area' else 1
    return {'cantidad':str(value),'unidad':result_unit,'tipo':tipo,'puntos':puntos,'fuente':fuente,'calibracion':c,
            'rango':None if error is None else [str(value*(1-error)**power),str(value*(1+error)**power)],
            'estado':'CALCULADO_PENDIENTE_REVISION','metodo':'Polilínea euclidiana' if tipo=='longitud' else 'Polígono (shoelace); sin huecos'}

def contar_espaciamiento(longitudes_tramos,espaciamiento_max,fuente,extremos_compartidos=0,terminales_extra=0,conteo_grafico=None,unidad='ft'):
    if not longitudes_tramos or not str(fuente).strip(): raise ValueError('Tramos y fuente obligatorios')
    lengths=[number(v,positive=True) for v in longitudes_tramos];spacing=number(espaciamiento_max,positive=True)
    shared=integer(extremos_compartidos);extra=integer(terminales_extra)
    if shared>len(lengths)-1: raise ValueError('Para este modelo de tramos abiertos, extremos_compartidos no puede exceder tramos - 1')
    intervals=[int((v/spacing).to_integral_value(rounding=ROUND_CEILING)) for v in lengths]
    line=sum(max(0,n-1) for n in intervals)
    terminal=2*len(lengths)-shared+extra;total=line+terminal
    graphical=None if conteo_grafico is None else integer(conteo_grafico)
    return {'total':total,'postes_linea':line,'terminales':terminal,'intervalos_por_tramo':intervals,
            'espaciamiento_real_por_tramo':[str(v/n) for v,n in zip(lengths,intervals)],'unidad':unidad,'fuente':fuente,
            'conteo_grafico':graphical,'coincide_con_plano':None if graphical is None else graphical==total,
            'estado':'CALCULADO_PENDIENTE_REVISION','verificacion':'PENDIENTE_CONTEO_GRAFICO' if graphical is None else 'DISCREPANCIA_CON_PLANO' if graphical!=total else 'PENDIENTE_REVISION',
            'supuesto':'Tramos abiertos, sin portones ni huecos; restar únicamente extremos realmente compartidos. Terminales extra son adicionales.'}
