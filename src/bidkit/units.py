"""Explicit dimensional conversion. Internal base units: m, m2, m3, kg."""
from decimal import Decimal
import re
from .rfq_engine import number

FACTORS = {
    'm': ('length', '1'), 'mm': ('length', '.001'), 'cm': ('length', '.01'),
    'ft': ('length', '.3048'), 'in': ('length', '.0254'), 'yd': ('length', '.9144'),
    'm2': ('area', '1'), 'mm2': ('area','.000001'), 'cm2': ('area','.0001'), 'ft2': ('area', '.09290304'), 'in2': ('area', '.00064516'),
    'yd2': ('area', '.83612736'), 'm3': ('volume', '1'), 'ft3': ('volume', '.028316846592'),
    'yd3': ('volume', '.764554857984'), 'kg': ('mass', '1'), 'lb': ('mass', '.45359237'),
}
ALIASES = {'lf':'ft','feet':'ft','foot':'ft','pies':'ft', "'":'ft','inch':'in','inches':'in','pulgadas':'in','"':'in',
           'sf':'ft2','sqft':'ft2','sq ft':'ft2','cf':'ft3','cy':'yd3','sy':'yd2','lbs':'lb','pounds':'lb',
           'm²':'m2','ft²':'ft2','m³':'m3','ft³':'ft3'}

def unit(name):
    key=str(name).strip().lower()
    key=ALIASES.get(key,key)
    if key not in FACTORS: raise ValueError(f'Unidad no admitida: {name}. Use {", ".join(FACTORS)}')
    return key

def fraction(value):
    text=str(value).strip()
    match=re.fullmatch(r'(?:(\d+)\s+)?(\d+)\s*/\s*(\d+)',text)
    if match:
        whole, numerator, denominator=match.groups()
        if int(denominator)==0: raise ValueError('Fracción con denominador cero')
        return Decimal(whole or 0)+Decimal(numerator)/Decimal(denominator)
    return number(text)

def length_m(value, default_unit):
    """A feet/inches string overrides the default unit: 6\u0027-2 1/2\"."""
    if isinstance(value,str): value=value.replace("′", "'").replace("″", '"')
    if isinstance(value,str) and ("'" in value or '"' in value):
        text=value.replace('′',"'").replace('″','"').strip()
        match=re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s*'\s*-?\s*)?(?:(\d+(?:\.\d+)?|(?:\d+\s+)?\d+\s*/\s*\d+)\s*\")?",text)
        if not match or not any(match.groups()): raise ValueError(f'Medida pies/pulgadas inválida: {value}')
        feet,inches=match.groups()
        inch=fraction(inches) if inches else Decimal(0)
        if feet is not None and inch>=12: raise ValueError('Componente pulgadas debe ser menor de 12')
        return Decimal(feet or 0)*Decimal('.3048')+inch*Decimal('.0254')
    key=unit(default_unit)
    if FACTORS[key][0]!='length': raise ValueError('Se requiere unidad de longitud')
    return fraction(value)*Decimal(FACTORS[key][1])

def convertir_unidades(valor, de, a):
    source,target=unit(de),unit(a)
    if FACTORS[source][0]!=FACTORS[target][0]: raise ValueError(f'Unidades incompatibles: {de} -> {a}')
    base=length_m(valor,source) if FACTORS[source][0]=='length' else number(valor)*Decimal(FACTORS[source][1])
    return {'valor':str(base/Decimal(FACTORS[target][1])),'unidad':target,'origen':{'valor':valor,'unidad':source}}
