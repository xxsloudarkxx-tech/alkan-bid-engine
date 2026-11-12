"""Editable cost workbook, separate from the preserved documentary takeoff workbook."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.workbook.properties import CalcProperties

from .costing import KINDS, conversion, evaluate
from .data_store import read_json, write_json
from .workbooks import _sheet, _save, reference


def ref_text(value):
    if not value: return None
    return value.get("reference", value.get("path"))


def editable(sheet, columns, start=2, end=None):
    for row in sheet.iter_rows(min_row=start, max_row=end or sheet.max_row):
        for cell in row:
            if cell.column in columns:
                cell.fill = PatternFill("solid", fgColor="FFF2CC")
    # Worksheet validation guides editing; the engine validates imported data again.


def build_cost_workbook(result, path):
    book = Workbook()
    book.remove(book.active)
    book.properties.category = result["mode"] + "_PRELIMINARY_COSTS"
    book.calculation = CalcProperties(calcId=191029, fullCalcOnLoad=True, calcMode="auto")
    p = result["settings"]
    _sheet(book, "Start", ["Uso", "Instrucción"], [
        ["Estado", "ESTIMADO PRELIMINAR; subtotales cubiertos NO representan la obra completa. Sin precio se muestra vacío, nunca cero implícito."],
        ["Vigencia del expediente", "HISTÓRICO DE PRUEBA; no se presenta como licitación actualmente abierta" if result.get("historical_test") else "Registros documentales suministrados; confirmar vigencia de convocatoria"],
        ["Modo", result["mode"] + (" - TODOS LOS PRECIOS DE ESTE ARCHIVO SON FICTICIOS" if result["mode"] == "FICTITIOUS" else " - referencias reales; pueden ser confirmadas, estimadas o pendientes")],
        ["Flujo", "1 Settings: fecha/moneda. 2 Quotes: referencias. 3 Resources: consumos/rendimientos y cotización. 4 Items/Scopes: revisar cobertura."],
        ["Colores", "Amarillo: entradas editables. ID, cantidades documentales y fórmulas conservan vínculos de trazabilidad."],
        ["Precios", "CONFIRMED: cotización confirmada vigente. ESTIMATED: referencia/histórico/parámetro explícito, fecha y confianza. Vacío: pendiente."],
        ["Recursos", "FACTOR = unidades de recurso por unidad de partida; PRODUCTIVITY = unidades de partida por hora de recurso/ cuadrilla. Tarifa horaria coherente con esa cuadrilla."],
        ["Desperdicio", "Fracción explícita; 0 solo si se revisó y no corresponde. No aplicar de nuevo en indirectos."],
        ["Margen", "Margen bruto sobre precio de venta: precio = costo / (1 - margen). No es un recargo sobre costo."],
        ["Rangos", "Low/High suma los intervalos ingresados SOLO del alcance con precio; no es intervalo estadístico ni reserva para lo no estimado."],
        ["Impuesto", "Se aplica solo a componentes marcados taxable y, si corresponde, al margen. El tratamiento proviene de documentos, no de otro proyecto."],
        ["Cambiar cantidades", "Items G permite escenarios; si difiere de F se bloquea oferta. Una nueva medición requiere actualizar analysis.json con fuente, sin reextraer PDFs."],
        ["Guardar trabajo", "Guardar copia y ejecutar cost-import --project ID --workbook archivo.xlsx; después build. Conserva entradas en pricing.json/quotes.json."],
        ["Límite", "La revisión documental completa y liberación comercial corresponden al estimador. El motor no presenta ofertas."],
        ["Allowances", "Registrar allowance documentado como costo FIXED separado en Indirects, con alcance y fuente. Revisar aplicabilidad; no asumir cero."],
    ])
    settings = _sheet(book, "Settings", ["Parameter", "Value"], [
        ["project_id", result["project_id"]], ["as_of YYYY-MM-DD", p.get("as_of")], ["currency", p.get("currency")], ["mode", result["mode"]],
        ["gross_margin_rate", p.get("margin_rate")], ["margin_reference", ref_text(p.get("margin_source"))],
        ["tax_rate", p.get("tax_rate")], ["tax_reference", ref_text(p.get("tax_source"))],
        ["margin_taxable", int(p["margin_taxable"]) if type(p.get("margin_taxable")) is bool else None],
        ["indirects_reviewed", int(p.get("indirects_reviewed", False))], ["scope_complete", int(p.get("scope_complete", False))],
        ["scope_reference", p.get("scope_reference")], ["documentary_scope_complete", int(result.get("documentary_scope_complete", False))],
        ["documented_tax_treatment", result["tax_treatment"]], ["tax_documented", int(result["tax_documented"])],
        ["allowances_reviewed", int(p.get("allowances_reviewed", False))],
    ])
    editable(settings, [2])
    quotes = _sheet(book, "Quotes", ["ID", "Price status", "Confidence", "Supplier / historical origin", "Reference", "Date YYYY-MM-DD", "Valid until YYYY-MM-DD", "Currency", "Unit", "Unit price", "Low", "High", "Source URL / file / record", "Applicability note", "Mode", "Source reviewed", "Usable"],
                    [[q["id"], q.get("price_status"), q.get("confidence"), q.get("supplier"), q.get("reference"), q.get("date"), q.get("valid_until"), q.get("currency"), q.get("unit"), q.get("unit_price"), q.get("unit_price_low"), q.get("unit_price_high"), ref_text(q.get("source")), q.get("applicability_note"), q.get("kind"), int(q.get("validation_status") == "VALID"), None] for q in result["quotes"]] + [[None]*17 for _ in range(p.get("quote_input_slots",10))])
    for r in range(2, quotes.max_row+1):
        quotes[f"Q{r}"] = f'=IF(A{r}="","",IF(AND(OR(B{r}="CONFIRMED",B{r}="ESTIMATED"),OR(C{r}="LOW",C{r}="MEDIUM",C{r}="HIGH"),D{r}<>"",E{r}<>"",F{r}<>"",Settings!B3<>"",Settings!B4<>"",F{r}<=Settings!B3,OR(IF(G{r}="",FALSE,Settings!B3<=G{r}),AND(G{r}="",B{r}="ESTIMATED",N{r}<>"")),H{r}=Settings!B4,I{r}<>"",OR(J{r}<>"",AND(K{r}<>"",L{r}<>"")),J{r}>=0,M{r}<>"",O{r}=Settings!B5,P{r}=1,OR(AND(K{r}="",L{r}=""),AND(K{r}<>"",L{r}<>"",K{r}>=0,K{r}<=L{r},OR(J{r}="",AND(K{r}<=J{r},J{r}<=L{r}))))),1,0))'
    # Settings rows include the heading: as_of B3, currency B4, mode B5.
    editable(quotes, list(range(1, 17)))
    settings["B3"].number_format = "@"
    for r in range(2, quotes.max_row+1):
        for col in (6, 7): quotes.cell(r, col).number_format = "@"
    choices = DataValidation(type="list", formula1='"CONFIRMED,ESTIMATED"')
    quotes.add_data_validation(choices); choices.add(f"B2:B10000")
    units = ("LF", "FT", "IN", "SF", "SY", "CF", "CY", "H", "HR")
    conversions = []
    for a in units:
        for b in units:
            try: factor = conversion(a, b)
            except ValueError: continue
            conversions.append([a+">"+b, float(factor)])
    _sheet(book, "Conversions", ["From>To", "Quote units per resource unit"], conversions)
    item_rows = {i["id"]: n for n, i in enumerate(result["items"], 2)}
    resources = _sheet(book, "Resources", ["ID", "Item ID", "Kind", "Description", "Applicability", "Method", "Resource unit", "Factor resource/item", "Productivity item/hour", "Waste fraction", "Quote ID", "Basis", "Basis reviewed", "Taxable", "Item quantity", "Quote unit", "Unit price", "Price status", "Quote usable", "Conversion", "Resource quantity", "Purchase quantity", "Extended cost", "Missing", "Unit low", "Unit high", "Cost low", "Cost high", "Confidence", "Sign", "Signed cost", "Signed low", "Signed high", "Scope", "Basis source"],
                       [[r["id"], r["quantity_id"], r["kind"], r["description"], r["applicability"], r["method"], r.get("resource_unit"), r.get("factor"), r.get("productivity"), r.get("waste_fraction"), r.get("quote_id"), r.get("basis"), int(r["basis_valid"]), int(r["taxable"]) if type(r.get("taxable")) is bool else None]+[None]*20+[ref_text(r.get("basis_source"))] for r in result["resources"]])
    end = max(resources.max_row, 2)
    lookup = "Quotes!$A$2:$Q$10000"
    for r, resource in enumerate(result["resources"], 2):
        n = item_rows[resource["quantity_id"]]
        for col, index in (("P", 9), ("Q", 10), ("R", 2), ("S", 17), ("Y", 11), ("Z", 12), ("AC", 3)):
            # COUNTBLANK is unnecessary: quote presence plus explicit blank test prevents VLOOKUP's blank->0 coercion.
            resources[f"{col}{r}"] = f'=IF(K{r}="","",IFERROR(IF(VLOOKUP(K{r},{lookup},{index},FALSE)="","",VLOOKUP(K{r},{lookup},{index},FALSE)),""))'
        resources[f"O{r}"] = f'=IF(Items!G{n}="","",Items!G{n})'
        resources[f"AD{r}"] = f'=Items!J{n}'
        resources[f"AH{r}"] = f'=Items!D{n}'
        resources[f"T{r}"] = f'=IF(OR(G{r}="",P{r}=""),"",IF(G{r}=P{r},1,IFERROR(VLOOKUP(G{r}&">"&P{r},Conversions!$A$2:$B${len(conversions)+1},2,FALSE),"")))'
        resources[f"U{r}"] = f'=IF(OR(E{r}<>"INCLUDED",M{r}<>1,L{r}="",O{r}="",O{r}<0,J{r}="",J{r}<0,AND(F{r}="FACTOR",OR(H{r}="",H{r}<0)),AND(F{r}="PRODUCTIVITY",OR(I{r}="",I{r}<=0,AND(G{r}<>"H",G{r}<>"HR"))),AND(F{r}<>"FACTOR",F{r}<>"PRODUCTIVITY")),"",IF(F{r}="PRODUCTIVITY",O{r}/I{r},O{r}*H{r})*(1+J{r}))'
        resources[f"V{r}"] = f'=IF(OR(U{r}="",T{r}=""),"",U{r}*T{r})'
        resources[f"W{r}"] = f'=IF(E{r}="NOT_APPLICABLE",IF(AND(M{r}=1,L{r}<>""),0,""),IF(OR(V{r}="",Q{r}="",S{r}<>1),"",ROUND(V{r}*Q{r},2)))'
        resources[f"X{r}"] = f'=IF(W{r}="",1,0)'
        for col, rate in (("AA", "Y"), ("AB", "Z")):
            resources[f"{col}{r}"] = f'=IF(E{r}="NOT_APPLICABLE",IF(W{r}="","",0),IF(OR(V{r}="",S{r}<>1,AND({rate}{r}="",Q{r}="")),"",ROUND(V{r}*IF({rate}{r}="",Q{r},{rate}{r}),2)))'
        resources[f"AE{r}"] = f'=IF(W{r}="","",W{r}*AD{r})'
        resources[f"AF{r}"] = f'=IF(AA{r}="","",IF(AD{r}=-1,-AB{r},AA{r}))'
        resources[f"AG{r}"] = f'=IF(AB{r}="","",IF(AD{r}=-1,-AA{r},AB{r}))'
    editable(resources, list(range(1, 15))+[35])
    resources.cell(1, 36, "Schedule / package")
    for r, resource in enumerate(result["resources"], 2):
        resources[f"AJ{r}"] = f'=Items!C{item_rows[resource["quantity_id"]]}'
    items = _sheet(book, "Items", ["ID", "Description", "Schedule / package", "Pricing scope", "Unit", "Document quantity", "Scenario quantity", "Composition reviewed", "Composition reference", "Sign", "Material known", "Labor known", "Equipment known", "Subcontract known", "Other known", "Known direct partial", "Complete direct", "Missing resources", "Quantity changed", "Price classes", "Low covered", "High covered", "Quantity evidence"],
                   [[i["id"], i["item"], i["package"], i["pricing_scope"], i["unit"], i["quantity"], i["quantity"], int(i["composition_complete"]), i.get("composition_reference"), -1 if i["effect"] == "DEDUCT" else 1]+[None]*12+[reference(i["sources"])] for i in result["items"]])
    for r in range(2, items.max_row+1):
        for col, kind in zip(("K", "L", "M", "N", "O"), KINDS):
            items[f"{col}{r}"] = f'=IF(COUNTIFS(Resources!$B$2:$B${end},A{r},Resources!$C$2:$C${end},"{kind}",Resources!$W$2:$W${end},"<>")=0,"",SUMIFS(Resources!$AE$2:$AE${end},Resources!$B$2:$B${end},A{r},Resources!$C$2:$C${end},"{kind}"))'
        items[f"P{r}"] = f'=IF(COUNTIFS(Resources!$B$2:$B${end},A{r},Resources!$W$2:$W${end},"<>")=0,"",SUM(K{r}:O{r}))'
        items[f"R{r}"] = f'=SUMIF(Resources!$B$2:$B${end},A{r},Resources!$X$2:$X${end})'
        items[f"S{r}"] = f'=IF(G{r}=F{r},0,1)'
        items[f"Q{r}"] = f'=IF(OR(G{r}="",H{r}<>1,I{r}="",R{r}>0,COUNTIF(Resources!$B$2:$B${end},A{r})=0),"",P{r})'
        items[f"T{r}"] = f'=IF(COUNTIFS(Resources!$B$2:$B${end},A{r},Resources!$R$2:$R${end},"ESTIMATED",Resources!$W$2:$W${end},"<>")>0,"ESTIMATED",IF(P{r}="","PENDING","CONFIRMED / REVIEW"))'
        for col, source in (("U", "AF"), ("V", "AG")):
            items[f"{col}{r}"] = f'=IF(COUNTIFS(Resources!$B$2:$B${end},A{r},Resources!${source}$2:${source}${end},"<>")=0,"",SUMIF(Resources!$B$2:$B${end},A{r},Resources!${source}$2:${source}${end}))'
    editable(items, [7, 8, 9])
    indirect = _sheet(book, "Indirects", ["ID", "Description", "Scope", "Applicability", "Method", "Value / fraction", "Basis", "Basis source", "Basis reviewed", "Taxable", "Scope direct", "Extended cost", "Missing"],
                      [[i["id"], i["description"], i["scope"], i["applicability"], i["method"], i.get("value"), i.get("basis"), ref_text(i.get("basis_source")), int(i["basis_valid"]), int(i["taxable"]) if type(i.get("taxable")) is bool else None, None, None, None] for i in result["indirects"]])
    ie = max(indirect.max_row, 2)
    scope_rows = {s["scope"]: r for r, s in enumerate(result["summaries"], 2)}
    for r in range(2, indirect.max_row+1):
        indirect[f"K{r}"] = f'=IFERROR(IF(VLOOKUP(C{r},Scopes!$A$2:$I${len(scope_rows)+1},9,FALSE)="","",VLOOKUP(C{r},Scopes!$A$2:$I${len(scope_rows)+1},9,FALSE)),"")'
        indirect[f"L{r}"] = f'=IF(OR(I{r}<>1,G{r}=""),"",IF(D{r}="NOT_APPLICABLE",0,IF(OR(D{r}<>"INCLUDED",F{r}="",F{r}<0),"",IF(E{r}="FIXED",ROUND(F{r},2),IF(OR(E{r}<>"PERCENT_DIRECT",K{r}=""),"",ROUND(K{r}*F{r},2))))))'
        indirect[f"M{r}"] = f'=IF(L{r}="",1,0)'
    editable(indirect, list(range(3, 11)))
    se = max(items.max_row, 2)
    scopes = _sheet(book, "Scopes", ["Scope", "Selected", "Item count", "Priced components", "Incomplete items", "KNOWN DIRECT PARTIAL", "Low covered", "High covered", "Complete direct", "Complete indirect", "Cost", "Gross margin amount", "Candidate price", "Tax", "Payment with tax", "Missing indirects", "Taxable cost", "Confirmed partial", "Estimated partial"],
                    [[s["scope"], int(s["scope"] == "base" or s["scope"] in p.get("selected_alternates", []))]+[None]*17 for s in result["summaries"]])
    for r in range(2, scopes.max_row+1):
        scopes[f"C{r}"] = f'=COUNTIF(Items!$D$2:$D${se},A{r})'
        scopes[f"D{r}"] = f'=COUNTIFS(Resources!$AH$2:$AH${end},A{r},Resources!$E$2:$E${end},"INCLUDED",Resources!$W$2:$W${end},"<>")'
        scopes[f"E{r}"] = f'=COUNTIFS(Items!$D$2:$D${se},A{r},Items!$Q$2:$Q${se},"")'
        for col, src in (("F", "AE"), ("G", "AF"), ("H", "AG")):
            scopes[f"{col}{r}"] = f'=IF(COUNTIFS(Resources!$AH$2:$AH${end},A{r},Resources!${src}$2:${src}${end},"<>")=0,"",SUMIF(Resources!$AH$2:$AH${end},A{r},Resources!${src}$2:${src}${end}))'
        scopes[f"I{r}"] = f'=IF(OR(C{r}=0,E{r}>0),"",SUMIF(Items!$D$2:$D${se},A{r},Items!$Q$2:$Q${se}))'
        scopes[f"P{r}"] = f'=SUMIF(Indirects!$C$2:$C${ie},A{r},Indirects!$M$2:$M${ie})'
        scopes[f"J{r}"] = f'=IF(OR(P{r}>0,Settings!B11<>1),"",SUMIF(Indirects!$C$2:$C${ie},A{r},Indirects!$L$2:$L${ie}))'
        scopes[f"K{r}"] = f'=IF(OR(I{r}="",J{r}=""),"",ROUND(I{r}+J{r},2))'
        scopes[f"M{r}"] = f'=IF(OR(K{r}="",Settings!B6="",Settings!B6<0,Settings!B6>=1,Settings!B7=""),"",ROUND(K{r}/(1-Settings!B6),2))'
        scopes[f"L{r}"] = f'=IF(M{r}="","",ROUND(M{r}-K{r},2))'
        scopes[f"Q{r}"] = f'=SUMIFS(Resources!$AE$2:$AE${end},Resources!$AH$2:$AH${end},A{r},Resources!$N$2:$N${end},1)+SUMIFS(Indirects!$L$2:$L${ie},Indirects!$C$2:$C${ie},A{r},Indirects!$J$2:$J${ie},1)+IF(AND(Settings!B10=1,L{r}<>""),L{r},0)'
        tax_unknown = f'COUNTIFS(Resources!$AH$2:$AH${end},A{r},Resources!$E$2:$E${end},"INCLUDED",Resources!$N$2:$N${end},"")+COUNTIFS(Indirects!$C$2:$C${ie},A{r},Indirects!$D$2:$D${ie},"INCLUDED",Indirects!$J$2:$J${ie},"")'
        scopes[f"N{r}"] = f'=IF(OR(M{r}="",Settings!B8="",Settings!B9="",Settings!B10="",Settings!B16<>1,{tax_unknown}>0),"",ROUND(Q{r}*Settings!B8,2))'
        scopes[f"O{r}"] = f'=IF(OR(M{r}="",N{r}=""),"",M{r}+N{r})'
        for col, status in (("R", "CONFIRMED"), ("S", "ESTIMATED")):
            scopes[f"{col}{r}"] = f'=IF(COUNTIFS(Resources!$AH$2:$AH${end},A{r},Resources!$R$2:$R${end},"{status}",Resources!$W$2:$W${end},"<>")=0,"",SUMIFS(Resources!$AE$2:$AE${end},Resources!$AH$2:$AH${end},A{r},Resources!$R$2:$R${end},"{status}"))'
    editable(scopes, [2])
    scopes.cell(1, 20, "Components with range coverage")
    for r in range(2, scopes.max_row+1):
        scopes[f"T{r}"] = f'=COUNTIFS(Resources!$AH$2:$AH${end},A{r},Resources!$E$2:$E${end},"INCLUDED",Resources!$AA$2:$AA${end},"<>")'
    packages = _sheet(book, "Schedules", ["Scope", "Schedule / package", "Known direct partial", "Low covered", "High covered"], [[r["scope"], r["package"], None, None, None] for r in result["packages"]])
    for r in range(2, packages.max_row+1):
        for col, src in (("C", "AE"), ("D", "AF"), ("E", "AG")):
            packages[f"{col}{r}"] = f'=IF(COUNTIFS(Resources!$AH$2:$AH${end},A{r},Resources!$AJ$2:$AJ${end},B{r},Resources!${src}$2:${src}${end},"<>")=0,"",SUMIFS(Resources!${src}$2:${src}${end},Resources!$AH$2:$AH${end},A{r},Resources!$AJ$2:$AJ${end},B{r}))'
    summary = _sheet(book, "Summary", ["Metric", "Value", "Meaning"], [
        ["Known base direct PARTIAL", "=Scopes!F2", "Covered priced resources only, missing scope excluded"],
        ["Base range low - covered only", "=Scopes!G2", "No invented contingency for pending scope"],
        ["Base range high - covered only", "=Scopes!H2", "Source intervals, not statistical confidence"],
        ["Primary concepts", len(result["items"]), "Not full project scope coverage"],
        ["Pending measurement", sum(i["quantity"] is None for i in result["items"]), "Includes grouped disciplines"],
        ["Offer total", None, "Blocked by incomplete indispensable scope; no commercial release"],
        ["Status", None, "Preliminary estimate remains useful even while offer is blocked"],
    ])
    # IF prevents a blank referenced cell from appearing as an invented zero.
    for cell, target in (("B2", "Scopes!F2"), ("B3", "Scopes!G2"), ("B4", "Scopes!H2")):
        summary[cell] = f'=IF({target}="","",{target})'
    last = scopes.max_row
    blocks = f'COUNTIFS(Scopes!$B$2:$B${last},1,Scopes!$E$2:$E${last},">0")+COUNTIFS(Scopes!$B$2:$B${last},1,Scopes!$P$2:$P${last},">0")+COUNTIFS(Scopes!$B$2:$B${last},1,Scopes!$M$2:$M${last},"")'
    tax_price = f'SUMIF(Scopes!$B$2:$B${last},1,Scopes!$O$2:$O${last})'
    price = f'SUMIF(Scopes!$B$2:$B${last},1,Scopes!$M$2:$M${last})'
    summary['B7'] = f'=IF(OR(Settings!B5<>"REAL",Settings!B12<>1,Settings!B13="",Settings!B14<>1,Settings!B16<>1,Settings!B17<>1,Scopes!B2<>1,Settings!B3="",Settings!B4="",SUM(Items!$S$2:$S${se})>0,COUNTIF(Items!$D$2:$D${se},"unallocated")>0,COUNTIF(Indirects!$C$2:$C${ie},"unallocated")>0,{blocks}>0),"",IF(OR(Settings!B15="EXCLUDED_FROM_BID_ADDED_BY_OWNER_TO_PAYMENTS",Settings!B15="EXCLUDED_FROM_ELECTRONIC_BID_CITY_APPLIES_AT_AWARD"),{price},IF(AND(Settings!B15="INCLUDED_IN_BID",COUNTIFS(Scopes!$B$2:$B${last},1,Scopes!$O$2:$O${last},"")=0),{tax_price},"")))'
    summary['B8'] = '=IF(B7="","PRELIMINARY - OFFER BLOCKED","CALCULATED - ESTIMATOR RELEASE REQUIRED")'
    _sheet(book, "Pending decisions", ["ID", "Description", "Decision required", "Source"], [[i["id"], i["item"], "; ".join(i["blockers"]), reference(i["sources"])] for i in result["items"] if i["blockers"]] + [[r["id"], r["description"], "Indirect basis / allocation pending", ""] for r in result["indirects"] if r["extended_cost"] is None])
    for sheet in book:
        sheet.freeze_panes = "C2"
    book["Start"].column_dimensions["B"].width = 110
    for row in range(2, book["Start"].max_row+1): book["Start"].row_dimensions[row].height = 45
    book.active = book.sheetnames.index("Summary")
    if any("material_specification" in r for r in result["resources"]):
        from .purchase_workbook import append_purchase_sheets
        append_purchase_sheets(book, result)
        book.active = book.sheetnames.index("Resumen_Economico")
    _save(book, Path(path))
    if "Materiales_Detalle" in book and result["mode"] == "REAL":
        book.active = book.sheetnames.index("Materiales_Detalle")
        _save(book, Path(path).parent / "Lista_Detallada_de_Materiales.xlsx")


def import_cost_workbook(config, path, analysis):
    """Persist estimator edits without changing documentary quantities or reparsing PDFs."""
    book = load_workbook(path, data_only=False)
    settings = book["Settings"]
    if book.properties.category != "REAL_PRELIMINARY_COSTS" or settings["B2"].value != config.id or settings["B5"].value != "REAL":
        raise ValueError("Workbook is fictitious or belongs to another project")
    old = read_json(config.project_dir / "pricing.json")
    p = dict(old)
    def source(value, previous=None):
        if previous and ref_text(previous) == value: return previous
        return {"reference": value} if value else None
    for key, address in (("as_of", "B3"), ("currency", "B4"), ("margin_rate", "B6"), ("tax_rate", "B8"), ("scope_reference", "B13")):
        p[key] = settings[address].value
    p["margin_source"], p["tax_source"] = source(settings["B7"].value, old.get("margin_source")), source(settings["B9"].value, old.get("tax_source"))
    p["margin_taxable"] = bool(settings["B10"].value) if settings["B10"].value is not None else None
    p["indirects_reviewed"], p["scope_complete"] = settings["B11"].value == 1, settings["B12"].value == 1
    p["allowances_reviewed"] = settings["B17"].value == 1
    p["selected_alternates"] = [row[0].value for row in book["Scopes"].iter_rows(min_row=2) if row[1].value == 1 and row[0].value != "base"]
    quantities = {r["id"]: r for r in analysis["quantities"]}
    old_components = {c["id"]: c for i in old["items"] for c in i["components"]}
    old_quotes = {q["id"]: q for q in read_json(config.project_dir / "quotes.json")["quotes"]}
    old_indirects = {r["id"]: r for r in old["indirects"]}
    p["items"] = []
    by_item = {}
    for row in book["Items"].iter_rows(min_row=2, values_only=True):
        qid = row[0]
        if qid not in quantities or row[4] != quantities[qid]["unit"] or row[6] != quantities[qid]["quantity"] or row[5] != quantities[qid]["quantity"]:
            raise ValueError("Scenario quantity/unit changed; update documentary analysis with evidence first")
        item = {"quantity_id": qid, "composition_complete": row[7] == 1, "composition_reference": row[8], "effect": "DEDUCT" if row[9] == -1 else "ADD", "components": []}
        p["items"].append(item); by_item[qid] = item
    for row in book["Resources"].iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        c = {**old_components.get(row[0], {}), **dict(zip(("id", "quantity_id", "kind", "description", "applicability", "method", "resource_unit", "factor", "productivity", "waste_fraction", "quote_id", "basis"), row[:12]))}
        qid = c.pop("quantity_id")
        c.update(basis_source=source(row[34], old_components.get(c["id"], {}).get("basis_source")), basis_reviewed=row[12] == 1, taxable=bool(row[13]) if row[13] is not None else None)
        by_item[qid]["components"].append(c)
    if "Materiales_Detalle" in book:
        notes = {row[0]: row[33] for row in book["Materiales_Detalle"].iter_rows(min_row=2, values_only=True) if row[0]}
        for item in p["items"]:
            for c in item["components"]:
                if c["id"] in notes: c["estimator_note"] = notes[c["id"]]
    p["indirects"] = []
    for row in book["Indirects"].iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        p["indirects"].append({"id": row[0], "description": row[1], "scope": row[2], "applicability": row[3], "method": row[4], "value": row[5], "basis": row[6], "basis_source": source(row[7], old_indirects.get(row[0], {}).get("basis_source")), "basis_reviewed": row[8] == 1, "taxable": bool(row[9]) if row[9] is not None else None})
    quotes = []
    for row in book["Quotes"].iter_rows(min_row=2, values_only=True):
        if not row[0]: continue
        if row[14] != "REAL":
            raise ValueError("Fictitious quotes cannot be imported into real price inputs")
        q = dict(old_quotes.get(row[0], {}))
        q.update(zip(("id", "price_status", "confidence", "supplier", "reference", "date", "valid_until", "currency", "unit", "unit_price", "unit_price_low", "unit_price_high"), row[:12]))
        q.update(source=source(row[12], old_quotes.get(q["id"], {}).get("source")), applicability_note=row[13], reviewed=row[15] == 1, kind="REAL")
        quotes.append(q)
    registry = {"schema_version": 1, "project_id": config.id, "quotes": quotes}
    evaluate(analysis, p, registry, root=config.root)  # Validate before replacing either input.
    write_json(config.project_dir / "pricing.json", p)
    write_json(config.project_dir / "quotes.json", registry)
    return {"imported_items": len(p["items"]), "imported_quotes": len(quotes), "documentary_quantities_changed": False}
