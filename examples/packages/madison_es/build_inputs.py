"""Genera las 3 entradas alkan-package/1 para Madison ES Replacement (Everett SD).

Solo hay especificaciones (Vol. 1, Vol. 2, Apéndice); NO hay planos. Todas las
cantidades son paramétricas a partir de los 75,522 SF del edificio (Spec 01 1000)
y van marcadas ASSUMED en qty_source. Precios BUDGET (sin cotizar).
"""
import json
import sys
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
OUT.mkdir(parents=True, exist_ok=True)
DATE = "2026-11-17"
GSF = D("75522")

WAGE_SRC = ("L&I journey-level prevailing wage, Snohomish County, eff. 11/2/2026 - "
            "Spec 00 8100 Wage Determination (Madison ES Project Manual Vol. 1)")

# Supuestos paramétricos comunes (sin planos)
PART_LF = D("8300")        # tabiques interiores ≈ 0.11 LF/GSF (escuela primaria, 2 niveles)
FRAMED_H = D("14")         # altura enmarcada promedio (a losa/estructura)
BOARD_H = D("13")          # altura promedio de tablero (algunos muros terminan 6" sobre plafón)
VISIBLE_H = D("10")        # altura visible pintada (plafón ~10')
EXT_PERIM = D("1100")      # perímetro exterior estimado
GYP_CEIL = D("9000")       # plafones/soffits de yeso ≈ 12% GSF

PARAM = f"ASSUMED - parametric from 75,522 GSF (Spec 01 1000 1.3.A); drawings not received"


def s(x, q="0.01"):
    return str(D(x).quantize(D(q), rounding=ROUND_HALF_UP))


def h(x):
    return str(D(x).quantize(D("1"), rounding=ROUND_HALF_UP))


def project(key, title, label):
    return {
        "key": key,
        "short": "Madison ES Replacement",
        "title": title,
        "owner": "Everett School District No. 2",
        "owner_contact": "Megan Heiss, Procurement Supervisor - Capital Projects (425) 385-4190",
        "project_no": "Bid ID No. 13:26/27 - Architect DYKEMAN Inc., Job 24-037",
        "site": "616 Pecks Drive, Everett, WA 98203 (Snohomish County)",
        "county": "Snohomish",
        "prime_contractor": "GC bidders - to be confirmed (sub bid to GC)",
        "bid_date": "December 9, 2026, 2:00 PM (GC bid to Owner)",
        "wage_basis": "Snohomish County prevailing wage (WA public works, RCW 39.12), L&I rates eff. 11/2/2026",
        "scope_label": label,
        "public_works": True,
        "documents": [
            "Project Manual Vol. 1 - Divisions 00-10, Bid Set issued 11/3/2026 (737 pp)",
            "Project Manual Vol. 2 - Divisions 11-23, Bid Set issued 11/3/2026 (461 pp)",
            "Project Manual Appendix - Geotechnical report and survey (497 pp)",
            "DRAWINGS NOT RECEIVED - all quantities parametric, to be replaced by plan takeoff",
        ],
    }


MARKUPS = {"contingency_pct": "5", "overhead_pct": "10", "profit_pct": "10", "rounding": "50"}
COMMISSION = {"find_estimate_pct": "3", "coordination_pct": "3", "coordination_included": False}
RELEASE = {
    "authorized": False,
    "allow_budget_prices": True,
    "note": ("Preliminary budget from the specifications only (drawings not received). "
             "Quantities are parametric from the 75,522 SF building area; prices are Nov 2026 "
             "Puget Sound budget benchmarks pending supplier quotes. Not for submission until "
             "plan takeoff and quotes replace the ASSUMED/BUDGET lines."),
}
GENERIC_CONTRACTOR = {
    "name": "[CONTRACTOR NAME]",
    "tag": "",
    "address": "[Contractor address]",
    "license": "[WA Contractor Lic. # - UBI #]",
    "phone": "[Phone]",
    "email": "",
    "contact": "[Contact name, title]",
}


def mat(i, section, item, spec, qty, unit, price, src, qsrc):
    return {"id": f"M{i:03d}", "section": section, "item": item, "spec": spec, "qty": s(qty, "1") if D(qty) == D(qty).to_integral() else s(qty),
            "unit": unit, "unit_price": str(D(price)), "price_basis": "BUDGET", "price_source": src, "qty_source": qsrc}


def build(materials, labor_spec):
    mats = [mat(i, *m) for i, m in enumerate(materials, 1)]
    labor = [{"id": f"L{i:03d}", "task": t, "rate": r, "hours": h(hr)} for i, (t, r, hr) in enumerate(labor_spec, 1)]
    return mats, labor


def other(rows):
    return [{"id": f"O{i:03d}", "item": it, "category": c, "qty": s(q, "1"), "unit": u, "rate": s(r)}
            for i, (it, c, q, u, r) in enumerate(rows, 1)]


BOND_TAX = [
    "Performance and payment bonds (available as an add on request).",
    "Washington State sales tax (resale to GC per WAC 458-20-171; GC collects).",
]
COMMON_EXCL = [
    "Alternate No. 1 - North Parking Lot (no work of this trade).",
    "Work outside the trade sections listed in the scope.",
    "Dumpsters, temporary power, lighting, heat, sanitary facilities and hoisting (by GC).",
    "Premium / overtime time unless directed in writing by GC.",
]
COMMON_ASSUMP = [
    "DRAWINGS NOT RECEIVED. Every quantity is parametric from the 75,522 SF school (Spec 01 1000) and must be replaced by a plan takeoff before submission.",
    "Snohomish County prevailing wage, L&I rates effective 11/2/2026 per Spec 00 8100; rates are fixed at the bid date (12/9/2026) - re-check on L&I if an update is posted.",
    "Work occurs in Phase 1 (new building, 3/29/2027 - SC 6/16/2028) per Spec 00 5200; Phase 2 is demolition/site work.",
    "Owner occupies the adjacent existing school during construction; work hours 7:00 AM - 5:00 PM M-F (Spec 01 1000).",
    "Pricing valid 30 days; material escalation beyond 2027 not included.",
]


REV_LOG = {
    "madison_carpinteria_diaz": "Rev 2 (2026-11-17): casework install 1.2+0.3 -> 0.6+0.2 MH/LF (factory-built); countertops, brackets and grommets moved to the countertop sub (Diaz profile excludes them).",
    "madison_pintura": "Rev 2 (2026-11-17): independent review - no changes.",
    "madison_sheetrock": "Rev 2 (2026-11-17): hang 0.012 -> 0.009 MH/SF, Level 4 finish 0.013 -> 0.010 MH/SF, mold-resistant wall board 0.62 -> 0.78 $/SF, screws 0.03 -> 0.025 $/SF.",
}


SUB_COMMON = {
    "banner": "SUBCONTRACT PACKAGE \u2013 BUDGETARY",
    "header_note": ("Quantities are parametric (no drawings received). To be replaced by plan takeoff "
                    "upon GC award or receipt of drawings."),
    "basis_lead": [
        "DRAWINGS NOT RECEIVED. All quantities are parametric from the 75,522 SF building area (Spec 01 1000 1.3.A) "
        "and assumed ratios/room program shown in each line's quantity source. This is not a plan takeoff and does not "
        "claim takeoff precision; quantities must be replaced by a plan takeoff upon GC award or receipt of drawings.",
        "Material pricing is BUDGET/CATALOG until supplier quotes are received. All material lines remain open for supplier pricing.",
    ],
    "summary_note": ("This is a subcontract package prepared to support GC bidders. "
                     "Final numbers subject to plan takeoff and supplier quotes."),
}
FLAGS_HEAD = ["DRAWINGS NOT RECEIVED \u2013 all quantities parametric.",
              "All material lines BUDGET/CATALOG \u2013 replace with supplier quotes."]
FLAGS_TAIL = ["Re-check L&I prevailing wage rates (Snohomish County) on the bid/award date.",
              "Pricing valid 30 days (from November 17, 2026 through December 17, 2026); material escalation beyond 2027 not included."]
SUBPKG = {
    "madison_carpinteria_diaz": {
        "go_no_go": ["GO/NO-GO: WA Contractor License and UBI are PENDING. Public works bid requires active registration "
                     "(RCW 18.27 / 39.04.350)."],
        "basis_requirements": [
            "AWI QCP requirement: casework must be manufactured by an AWI Quality Certification Program (QCP) "
            "manufacturer and installed by an AWI Certified installer approved by that manufacturer (Spec 12 3200 1.8). "
            "Priced as furnished by an AWI QCP manufacturer (Pacific Cabinets / Genothen named in 06 4100) and installed by Diaz.",
            "Experience requirement: fabricator/installer firm with minimum 5 years of documented experience and at least "
            "one project in the past 5 years with casework value within 20% of this project's casework cost (Spec 06 4100 1.7.A).",
        ],
        "coordination_notes": ["Countertop surfaces, brackets and grommets (12 3600) are excluded and assumed by the countertop subcontractor."],
        "review_flags": ["GO/NO-GO: WA Contractor License + UBI Pending (RCW 18.27 / 39.04.350)."] + FLAGS_HEAD + [
            "Confirm AWI Certified installer status of Diaz, approved by the AWI QCP manufacturer (12 3200 1.8).",
            "Confirm 5-year experience and a past project within 20% of this casework value (06 4100 1.7.A).",
            "Confirm student cubbies (312 LF allowance) vs. metal lockers 10 5113 on drawings.",
        ] + FLAGS_TAIL,
    },
    "madison_pintura": {
        "scope_critical": [
            "CRITICAL: Section 09 9120 Painting is listed in the Table of Contents but is NOT included in the Bid Set "
            "(Vol. 1 jumps from 09 8433 to 09 9300). Paint systems, sheens and number of coats are ASSUMED "
            "(primer + 2 finish coats). RFI to Dykeman required. Scope is provisional until the full section is issued."],
        "review_flags": FLAGS_HEAD + [
            "CRITICAL: Section 09 9120 Painting missing from Bid Set \u2013 RFI to Dykeman required; scope provisional.",
            "Confirm painted CMU, exposed structure and HPC areas on drawings.",
        ] + FLAGS_TAIL,
    },
    "madison_sheetrock": {
        "coordination_notes": [],   # filled below with the sheathing value
        "review_flags": FLAGS_HEAD + [
            "Confirm with GC whether exterior glass-mat sheathing stays in this package or moves to 05 4000 cold-formed framing.",
            "Confirm elevator hoistway construction (14 2400): shaft wall not included.",
        ] + FLAGS_TAIL,
    },
}


def write(name, pkg):
    sub = {**SUB_COMMON, **SUBPKG[name]}
    if name == "madison_sheetrock":
        mat_ = sum(D(m["qty"]) * D(m["unit_price"]) for m in pkg["materials"] if "glass-mat" in m["item"])
        hrs = sum(D(l["hours"]) for l in pkg["labor"] if "sheathing" in l["task"].lower())
        rate = D(pkg["labor_rates"]["DA"]["rate"]) * D("1.15")
        sell = (mat_ + hrs * rate) * D("1.05") * D("1.10") * D("1.10")
        sub["coordination_notes"] = [
            f"Exterior glass-mat sheathing (09 2116 1.1.B) is CARRIED in this package: about ${mat_:,.0f} material + "
            f"{hrs:,.0f} hr, roughly ${(sell / 50).quantize(D('1')) * 50:,.0f} of the sell price. Confirm with the GC whether it stays "
            "here or moves to the 05 4000 cold-formed framing package; if it moves, deduct it from this package."]
    pkg["subcontract_package"] = sub
    pkg["revision"] = 2
    pkg["revision_log"] = [{"rev": 1, "date": DATE, "note": "Rev 1 - first budget from specifications"},
                           {"rev": 2, "date": DATE, "note": REV_LOG[name]}]
    (OUT / f"{name}.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")


# ════════════════════════════════════════════════════ 1. CARPINTERÍA (Díaz)
CLASS = 26  # aulas/espacios de aprendizaje supuestos
base_lf = CLASS * 16 + 220
wall_lf = CLASS * 12 + 160
tall_lf = CLASS * 6 + 60
cw_lf = base_lf + wall_lf + tall_lf
pl_top = D("700")
ss_top = D("80")
cubby = CLASS * 12
prog = f"ASSUMED program: {CLASS} classrooms/learning spaces + admin/support; Spec 12 3200 / 06 4100"
SA = "A. Manufactured Wood Casework (Sec 12 3200 / 06 4100)"
SB = "B. Countertops (Sec 12 3600)"
SC = "B. Finish Carpentry (Sec 06 2000)"
SD = "C. FRP Paneling (Sec 06 8316)"
AWI = "Budget - AWI QCP manufacturer furnish (Pacific Cabinets / Genothen named in 06 4100), Nov 2026, pending quote"
carp_m = [
    (SA, "P-lam base cabinets, premium grade AWI QCP, delivered", "HPDL PL1 Formica Woodline / PL2 Laminart, 1\" MDF MR10 core, square edge thick band, BHMA A156.9 hardware", base_lf, "LF", "360.00", AWI, f"{prog}: {CLASS} x 16 LF + 220 LF admin/support"),
    (SA, "P-lam wall cabinets, premium grade AWI QCP, delivered", "Same construction; adj. shelves Knape & Vogt 346NP pins", wall_lf, "LF", "290.00", AWI, f"{prog}: {CLASS} x 12 LF + 160 LF"),
    (SA, "P-lam tall storage / wardrobe cabinets, delivered", "Same construction; keyed locks", tall_lf, "LF", "520.00", AWI, f"{prog}: {CLASS} x 6 LF + 60 LF"),
    (SA, "Student cubbies / open storage units (allowance)", "P-lam open units - VERIFY vs. 10 5113 metal lockers", cubby, "LF", "275.00", AWI, f"ASSUMED {CLASS} x 12 LF - verify on drawings"),
    (SA, "Custom benches (Sec 06 4100 1.1.B)", "P-lam / maple per drawings", "120", "LF", "210.00", AWI, "ASSUMED allowance - verify on drawings"),
    (SA, "Keyed cabinet locks, master keyed, 2 keys each", "Spec 06 4100 2.9.I, steel w/ chrome", "400", "EA", "28.00", "Budget - hardware distributor, Nov 2026", "ASSUMED ~1 lock per 3 LF casework"),
    (SA, "Shelf standards & cantilever brackets K&V 87/187", "Spec 06 4100 2.9.D, satin chrome", "1", "LS", "3500.00", "Budget - hardware distributor, Nov 2026", "ASSUMED allowance"),
    (SA, "Furring, blocking, shims, hanging strips for casework", "Spec 12 3200 1.1.D", "1", "LS", "2500.00", "Budget - Home Depot / lumber yard, Nov 2026", "Spec 12 3200 1.1.D"),
    (SC, "Clear maple chair rail WD2, stain grade", "Spec 06 2000 2.1.C.1, 6% MC, Custom Grade", "1800", "LF", "8.50", "Budget - hardwood supplier (maple), Nov 2026", "ASSUMED corridors / classrooms"),
    (SC, "Maple casings and miscellaneous trim WD2", "Spec 06 2000 2.1.C.1", "1200", "LF", "6.50", "Budget - hardwood supplier, Nov 2026", "ASSUMED allowance"),
    (SC, "Maple benches WD2 with colored stain", "Spec 06 2000 2.1.C.2", "80", "LF", "165.00", "Budget - millwork shop, Nov 2026", "ASSUMED - extent per drawings"),
    (SC, "Solid surface window sills SSM1", "Spec 06 2000 2.7; thickness per drawings", "700", "LF", "42.00", "Budget - solid surface fabricator, Nov 2026", "ASSUMED ~140 windows x 5 LF"),
    (SC, "Richlite W8A 1/4\" wainscot, Browns Point, leather finish", "Spec 06 2000 2.9.A", "2000", "SF", "30.00", "Budget - Richlite distributor, Nov 2026, pending quote", "ASSUMED - extent per drawings"),
    (SC, "Richlite W8B 1/2\" panels", "Spec 06 2000 2.9.B", "400", "SF", "42.00", "Budget - Richlite distributor, Nov 2026, pending quote", "ASSUMED - extent per drawings"),
    (SC, "Fiber reinforced laminate panels W1A / W1B", "Spec 06 2000 2.8 with accessories", "1500", "SF", "11.00", "Budget - panel distributor, Nov 2026", "ASSUMED - extent per drawings"),
    (SC, "MDF paneling W10 and P-lam faced panels", "Spec 06 2000 2.5 / 2.6", "800", "SF", "14.00", "Budget - Nov 2026", "ASSUMED allowance"),
    (SC, "Adhesives, fasteners, plastic/aluminum edge trims", "Spec 06 2000 2.10-2.11", "1", "LS", "4000.00", "Budget - Nov 2026", "ASSUMED allowance"),
    (SD, "FRP panels Class A with trims and adhesive", "Spec 06 8316, ASTM D5319, FDA food code at kitchen", "3000", "SF", "3.10", "Budget - FRP distributor, Nov 2026", "ASSUMED kitchen, custodial, service rooms"),
]
carp_l = [
    ("Receive, unload, distribute casework to 2 floors", "FC", 120),
    (f"Install factory-built base/wall/tall casework {cw_lf} LF @ 0.6 MH/LF (rev 2: was 1.2)", "FC", cw_lf * D("0.6")),
    (f"Install student cubbies {cubby} LF @ 0.8 MH/LF", "FC", cubby * D("0.8")),
    ("Install benches 200 LF @ 0.6 MH/LF", "FC", 120),
    (f"Scribes, fillers, adjustment, hardware {cw_lf} LF @ 0.2 MH/LF (rev 2: was 0.3)", "FC", cw_lf * D("0.2")),
    ("Chair rail and trim 3,000 LF @ 0.06 MH/LF", "FC", 180),
    ("Solid surface sills 140 EA @ 0.75 MH/EA", "FC", 105),
    ("Richlite wainscot/panels 2,400 SF @ 0.12 MH/SF", "FC", 288),
    ("FRL / MDF / P-lam panels 2,300 SF @ 0.08 MH/SF", "FC", 184),
    ("FRP panels 3,000 SF @ 0.035 MH/SF", "FC", 105),
    ("Lead carpenter non-working supervision (~20 weeks)", "FC", 200),
    ("Submittals, AWI coordination, samples, mock-up, certified payroll, closeout", "ADMIN", 180),
]
m, l = build(carp_m, carp_l)
write("madison_carpinteria_diaz", {
    "schema": "alkan-package/1",
    "estimate_id": "DIAZ-EST-2026-MES-01",
    "date": DATE,
    "relationship": "sub_to_gc",
    "tier": "competitive",
    "contractor": {
        "name": "DIAZ FINISH CARPENTER",
        "tag": "FINISH CARPENTRY - MILLWORK - CASEWORK",
        "address": "Federal Way, WA",
        "license": "WA Contractor Lic. Pending - UBI Pending",
        "phone": "(253) 797-2766",
        "email": "luisdiaz7870@gmail.com",
        "contact": "Luis Daniel Diaz Lopez",
    },
    "project": {**project("MES-CARP", "Madison ES Replacement - Finish Carpentry & Casework",
                          "finish carpentry, casework & FRP scope"), "distance_miles": "52"},
    "labor_rates": {
        "FC": {"label": "Carpenter (prevailing wage)", "kind": "prevailing_wage", "trade": "carpenter",
               "rate": "87.71", "burden_pct": "15", "source": WAGE_SRC + " - Carpenters, General Carpenter $87.71"},
        "ADMIN": {"label": "PM / admin", "kind": "loaded", "rate": "75.00", "source": "Office / submittals / certified payroll"},
    },
    "markups": MARKUPS, "tax": {"mode": "excluded_resale"},
    "materials": m, "labor": l,
    "other": other([
        ("Mobilization / travel Federal Way - Everett (~52 mi), 4 mobs", "Mobilization", 4, "EA", "1500.00"),
        ("Installation tools, carts, panel lift, seismic anchors", "Equipment", 1, "LS", "4500.00"),
        ("Protection of finished casework until turnover", "Other", 1, "LS", "2500.00"),
        ("L&I Statement of Intent + Affidavit (verify current fee)", "Fees", 2, "EA", "65.10"),
    ]),
    "scope": [
        {"title": "Manufactured & Architectural Casework (12 3200 / 06 4100)",
         "text": f"Furnish (through an AWI QCP manufacturer) and install P-lam base ({base_lf} LF), wall ({wall_lf} LF) and tall ({tall_lf} LF) cabinets, student cubbies ({cubby} LF allowance), custom benches, keyed locks, shelf standards, scribes and fillers, blocking and hanging strips per 12 3200 1.1.D."},
        {"title": "Finish Carpentry (06 2000)",
         "text": "Clear maple chair rail, casings and trim (stain grade), maple benches, solid surface window sills, Richlite W8A/W8B wainscot and panels, FRL W1A/W1B, MDF and P-lam panels, shop finishing per 06 2000 2.13."},
        {"title": "FRP Paneling (06 8316)", "text": "Class A FRP panels with trims and adhesive at kitchen, custodial and service rooms (3,000 SF allowance)."},
    ],
    "exclusions": COMMON_EXCL + [
        "Countertop support brackets and grommets - furnished with the countertops (12 3600).",
        "Field painting and staining of trim (09 9120 / 09 9300) beyond shop finishing in 06 2000.",
        "Metal lockers (10 5113), toilet accessories (FOIC), appliances (11 3013).",
    ],
    "assumptions": COMMON_ASSUMP + [
        "12 3200 requires an AWI QCP-certified manufacturer AND an AWI Certified installer approved by the manufacturer; 06 4100 requires 5 years experience and a past project within 20% of this casework value. Casework is priced as furnished by Pacific Cabinets / Genothen (named in 06 4100) and installed by Diaz - Diaz must confirm AWI installer status before bidding.",
        "Diaz WA contractor registration and UBI are shown as pending: a public works bid requires active registration (RCW 18.27 / 39.04.350). GO/NO-GO item.",
        f"Room program assumed: {CLASS} classrooms/learning spaces plus admin, library, health, staff and specialty rooms.",
    ],
    "alkan_commission": COMMISSION, "release": RELEASE, "validity_days": 30,
})

# ════════════════════════════════════════════════════ 2. PINTURA (genérico)
walls = PART_LF * VISIBLE_H * 2 + EXT_PERIM * 2 * VISIBLE_H * D("0.7")   # dos caras + cara interior muro ext.
walls_net = (walls * D("0.88")).quantize(D("1000"))                         # -12% azulejo/FRP/Richlite
SG = D("8000")
walls_eg = walls_net - SG
PI = "A. Interior Painting (Sec 09 9120 - NOT IN BID SET)"
PS = "B. Staining & Transparent Finish (Sec 09 9300)"
PH = "C. High-Performance Coatings (Sec 09 9600)"
PE = "D. Exterior Painting"
SW = "Budget - Sherwin-Williams / Rodda / Miller commercial pricing, Nov 2026, pending quote"
paint_m = [
    (PI, "Gyp. board walls - PVA primer + 2 coats eggshell latex (zero-VOC)", "MPI system TBD - Section 09 9120 missing; assumed MPI INT 9.2A", walls_eg, "SF", "0.30", SW,
     f"{PARAM}: {PART_LF} LF partitions x {VISIBLE_H}' x 2 faces + {EXT_PERIM} LF ext. wall x 2 fl x 70%, less 12% tile/FRP/wainscot, less semi-gloss"),
    (PI, "Gyp. board walls - primer + 2 coats semi-gloss (restrooms, kitchen, custodial; Level 5)", "Assumed MPI INT 9.2A semi-gloss", SG, "SF", "0.38", SW, "ASSUMED wet areas"),
    (PI, "Gyp. board ceilings and soffits - primer + 2 coats flat", "Assumed MPI INT 9.2A flat", GYP_CEIL, "SF", "0.30", SW, f"{PARAM}: ~12% of GSF"),
    (PI, "Exposed deck, joists, ducts - dryfall spray (gym, commons)", "Assumed waterborne dryfall", "16000", "SF", "0.22", SW, "ASSUMED ~11,500 SF exposed areas x 1.4 flute factor"),
    (PI, "CMU - block filler + 2 coats", "Assumed MPI INT 4.2", "6000", "SF", "0.55", SW, "ASSUMED - verify painted CMU on drawings (04 2200)"),
    (PI, "Hollow metal frames - prime touch-up + 2 coats DTM/alkyd", "Spec 08 1113 field painting", "250", "EA", "16.00", SW, "ASSUMED ~1 opening per 300 GSF"),
    (PI, "Hollow metal doors - both faces", "Spec 08 1113", "70", "EA", "28.00", SW, "ASSUMED (wood doors 08 1416 assumed factory finished)"),
    (PS, "Site stain + transparent finish on exposed wood / dimension lumber", "Spec 09 9300 2.5, water-based satin", "1500", "SF", "0.80", SW, "ASSUMED allowance (finish carpentry shop-finished per 06 2000)"),
    (PH, "HPC at steel columns and stair railings - epoxy primer + urethane", "Spec 09 9600 3.x; match Architect samples", "3500", "SF", "1.40", "Budget - Tnemec / Sherwin-Williams HPC, Nov 2026", "ASSUMED - verify on drawings"),
    (PE, "Exterior steel: covered play structure, canopies, bollards, misc. metals, gas pipe", "Spec 09 9113 referenced (missing); assumed DTM acrylic over primer", "6000", "SF", "0.65", SW, "ASSUMED - 4,854 SF covered play (Spec 01 1000) + misc."),
    (PI, "Sundries: masking, plastic, caulk, patch, abrasives", "Paintable acrylic latex caulk, 3M masking, 6-mil poly, setting-type patch", "1", "LS", "6000.00", "Budget - Nov 2026", "ASSUMED ~$0.03/SF painted"),
    (PI, "Mock-ups, draw-downs and touch-up stock", "Spec 09 9300 / 09 9600 mock-ups", "1", "LS", "1500.00", "Budget - Nov 2026", "Specs 09 9300 1.x, 09 9600 1.x"),
]
paint_l = [
    (f"Walls eggshell {walls_eg} SF @ 0.011 MH/SF (prime + 2 coats)", "PTR", walls_eg * D("0.011")),
    (f"Walls semi-gloss {SG} SF @ 0.012 MH/SF", "PTR", SG * D("0.012")),
    (f"Ceilings / soffits {GYP_CEIL} SF @ 0.014 MH/SF", "PTR", GYP_CEIL * D("0.014")),
    ("Dryfall spray 16,000 SF @ 0.006 MH/SF (with lift)", "PTR", 96),
    ("CMU 6,000 SF @ 0.016 MH/SF", "PTR", 96),
    ("HM frames 250 EA @ 1.0 MH/EA", "PTR", 250),
    ("HM doors 70 EA @ 1.5 MH/EA", "PTR", 105),
    ("Stain / clear finish 1,500 SF @ 0.02 MH/SF", "PTR", 30),
    ("HPC 3,500 SF @ 0.03 MH/SF", "PTR", 105),
    ("Exterior steel 6,000 SF @ 0.015 MH/SF", "PTR", 90),
    ("Prep walkdown: caulk, spot prime, protection", "PTR", 160),
    ("Punch list and touch-up after trades / owner move-in", "PTR", 240),
    ("Foreman non-working supervision (~30 weeks)", "PTR", 300),
    ("Submittals, product lists (MPI), samples, certified payroll", "ADMIN", 120),
]
m, l = build(paint_m, paint_l)
write("madison_pintura", {
    "schema": "alkan-package/1",
    "estimate_id": "ALKAN-PRE-2026-MES-PNT-01",
    "date": DATE, "relationship": "sub_to_gc", "tier": "competitive",
    "contractor": GENERIC_CONTRACTOR,
    "project": project("MES-PAINT", "Madison ES Replacement - Painting, Staining & High-Performance Coatings",
                       "painting, staining & high-performance coatings scope"),
    "labor_rates": {
        "PTR": {"label": "Painter (prevailing wage)", "kind": "prevailing_wage", "trade": "painter",
                "rate": "58.84", "burden_pct": "15", "source": WAGE_SRC + " - Painters, Journey Level $58.84"},
        "ADMIN": {"label": "PM / admin", "kind": "loaded", "rate": "75.00", "source": "Generic office rate - submittals, certified payroll"},
    },
    "markups": MARKUPS, "tax": {"mode": "excluded_resale"},
    "materials": m, "labor": l,
    "other": other([
        ("Scissor lifts 19'/26' - 2 units x 8 months", "Equipment", 16, "MO", "900.00"),
        ("Boom lift for gym / commons - 1 month", "Equipment", 1, "MO", "4500.00"),
        ("Airless sprayers, small tools", "Equipment", 1, "LS", "3000.00"),
        ("Mobilization - 3 mobs (interiors, exterior, punch)", "Mobilization", 3, "EA", "1200.00"),
        ("L&I Statement of Intent + Affidavit (verify current fee)", "Fees", 2, "EA", "65.10"),
    ]),
    "scope": [
        {"title": "Interior painting", "text": f"Prime and finish painted gypsum board walls ({walls_net} SF) and ceilings/soffits ({GYP_CEIL} SF), dryfall on exposed structure (16,000 SF), CMU (6,000 SF), hollow metal frames (250) and doors (70)."},
        {"title": "Staining & transparent finishing (09 9300)", "text": "Site finishing of exposed wood and dimension lumber not shop-finished (1,500 SF allowance)."},
        {"title": "High-performance coatings (09 9600)", "text": "Epoxy/urethane system at steel columns and stair railings (3,500 SF allowance)."},
        {"title": "Exterior painting", "text": "Exterior steel at the 4,854 SF covered play structure, canopies, bollards, misc. metals and exposed gas piping (6,000 SF allowance)."},
    ],
    "exclusions": BOND_TAX + COMMON_EXCL + [
        "Shop priming of structural steel, joists and deck (by steel fabricator per 05 1200 / 05 2100 / 05 3100).",
        "Factory-finished items: wood doors, casework, toilet partitions, lockers, louvers, storefront.",
        "Pavement markings (32 1723), water repellents (07 1900), resinous / fluid-applied flooring (09 67xx).",
        "Pipe and duct identification painting/labels (Div. 22/23).",
        "Wallcoverings and tackable wall systems (09 7200).",
    ],
    "assumptions": COMMON_ASSUMP + [
        "SECTION 09 9120 PAINTING IS LISTED IN THE TABLE OF CONTENTS BUT NOT INCLUDED IN THE BID SET (Vol. 1 jumps from 09 8433 to 09 9300). Other sections also reference 09 9113 Exterior Painting and 09 9123 Interior Painting. Paint systems, sheens and number of coats are ASSUMED (primer + 2 finish coats) - submit RFI to Dykeman.",
        "Gypsum finish levels per 09 2116 3.6: Level 5 at semi-gloss areas, Level 4 elsewhere; Level 5 high-build surfacer is by the drywall contractor.",
        "Wood doors (08 1416) and casework assumed factory/shop finished.",
    ],
    "alkan_commission": COMMISSION, "release": RELEASE, "validity_days": 30,
})

# ════════════════════════════════════════════════════ 3. SHEETROCK (genérico)
framed = PART_LF * FRAMED_H
face = PART_LF * BOARD_H
ext_inner = (EXT_PERIM * D("28") * D("0.7")).quantize(D("100"))
ABUSE, MR, CEM = D("50000"), D("10000"), D("6000")
std = face * 2 + ext_inner - ABUSE - MR - CEM
sheath = (EXT_PERIM * D("30") * D("0.7")).quantize(D("100"))
studs_lf = (PART_LF / D("1.333") * D("1.12")).quantize(D("1")) * FRAMED_H   # 16" o.c. + 12% jambas/esquinas
finish_sf = std + ABUSE + MR + GYP_CEIL
GW = "Budget - L&W Supply / GMS (Gypsum Supply), Nov 2026, pending quote"
SF_ = "A. Non-Structural Metal Framing (Sec 09 2216)"
SG_ = "B. Gypsum Board Assemblies (Sec 09 2116)"
SJ = "C. Joint Treatment & Accessories (Sec 09 2116)"
gyp_m = [
    (SF_, "6\" steel studs 20 ga EQ (0.031\" / 0.035\") @ 16\" o.c.", "ASTM C645, SSMA certified, AISI S220", studs_lf, "LF", "1.15", GW,
     f"{PARAM}: {PART_LF} LF partitions / 1.333 x 1.12 jambs x {FRAMED_H}' framed height"),
    (SF_, "6\" bottom track 20 ga EQ", "ASTM C645", PART_LF * D("1.05"), "LF", "1.10", GW, f"{PART_LF} LF partitions + 5% waste"),
    (SF_, "Slotted deflection track (ClarkDietrich BlazeFrame / MaxTrak)", "Spec 09 2216 2.x.3, rated where required", PART_LF, "LF", "3.40", GW, f"{PART_LF} LF partitions"),
    (SF_, "Heavy-duty jamb studs and headers (ClarkDietrich HDS / RedHeader PRO)", "Spec 09 2216 2.x", "250", "EA", "65.00", GW, "ASSUMED ~1 opening per 300 GSF"),
    (SF_, "Bridging, clips, PAFs, screws, backing plates", "Spec 09 2216", framed, "SF", "0.08", GW, f"{framed} SF framed wall"),
    (SF_, "Drywall suspension grid for gyp ceilings (Armstrong / USG)", "Spec 09 2116 / 09 5113 2.x", GYP_CEIL, "SF", "1.35", GW, f"{PARAM}: ~12% of GSF"),
    (SG_, "5/8\" Type X mold-resistant gypsum board, walls", "ASTM C1396, mold score 10 (D3273); UL/WH listed", std * D("1.10"), "SF", "0.78", GW,
     f"{PARAM}: {PART_LF} LF x {BOARD_H}' x 2 faces + {ext_inner} SF ext. wall inner face, less abuse/MR/cement; +10% waste"),
    (SG_, "5/8\" Type X abuse-resistant board (corridors, custodial, gym, cafeteria)", "ASTM C1629 Level 1 min., mold score 10", ABUSE * D("1.10"), "SF", "1.20", GW, "ASSUMED areas per 09 2116 2.1.C; +10% waste"),
    (SG_, "5/8\" Type X moisture/mold-resistant board", "Spec 09 2116 2.1.D", MR * D("1.10"), "SF", "0.78", GW, "ASSUMED wet areas; +10% waste"),
    (SG_, "5/8\" cementitious backer board (tile, restrooms, custodial sinks)", "ANSI A118.9, Durock / PermaBase / Hardiebacker", CEM * D("1.08"), "SF", "1.55", GW, "ASSUMED tiled areas; +8% waste"),
    (SG_, "5/8\" sag-resistant ceiling board", "Spec 09 2116 2.1.F", GYP_CEIL * D("1.12"), "SF", "0.70", GW, f"{GYP_CEIL} SF gyp ceilings +12% waste"),
    (SG_, "5/8\" Type X glass-mat exterior sheathing (DensGlass / Securock)", "ASTM C1177, square edge", sheath * D("1.08"), "SF", "1.15", GW, f"ASSUMED {EXT_PERIM} LF x 30' x 70% solid wall; +8% waste"),
    (SG_, "5/8\" exterior soffit board (protected exterior areas)", "Spec 09 2116 2.1.I", "2200", "SF", "0.85", GW, "ASSUMED covered entries; +10% waste"),
    (SG_, "GypSorb perforated acoustic gypsum ceiling, NRC 0.70 (allowance)", "Spec 09 2116 2.1.G, Strata Random 8-15-20", "2500", "SF", "13.50", "Budget - GypSorb distributor, Nov 2026, pending quote", "ASSUMED allowance - verify on RCPs"),
    (SG_, "Acoustic insulation 3-1/2\" mineral fiber, unfaced", "ASTM C665, 80% recycled", "65000", "SF", "0.72", GW, "ASSUMED ~60% of partitions (classroom STC walls)"),
    (SJ, "Joint compound (setting type) and paper / fiberglass tape", "ASTM C475", finish_sf, "SF", "0.09", GW, "All finished board SF"),
    (SJ, "Corner beads, L-trim, 1/2\" reveals, rated 093V expansion joints", "ASTM C1047; Trim-Tex / Phillips / Fry", "1", "LS", "14000.00", GW, "ASSUMED allowance; control joints max 30' o.c. (09 2116 3.5)"),
    (SJ, "Drywall screws", "ASTM C1002", finish_sf + sheath + CEM, "SF", "0.025", GW, "All board SF"),
    (SJ, "Level 5 high-build surfacer (CertainTeed Level V)", "Spec 09 2116 2.2.F / 3.6.D", "8000", "SF", "0.14", GW, "ASSUMED semi-gloss areas"),
    (SJ, "Acoustic sealant (acrylic latex)", "Spec 09 2116 2.2.B", "450", "EA", "8.50", GW, "ASSUMED both sides at acoustic walls"),
]
gyp_l = [
    (f"Layout and frame partitions {framed} SF @ 0.028 MH/SF", "DA", framed * D("0.028")),
    (f"Deflection / head-of-wall track {PART_LF} LF @ 0.04 MH/LF", "DA", PART_LF * D("0.04")),
    ("Openings: HD jambs and headers 250 EA @ 1.5 MH/EA", "DA", 375),
    (f"Ceiling grid {GYP_CEIL} SF @ 0.03 MH/SF", "DA", GYP_CEIL * D("0.03")),
    (f"Hang wall board {std + ABUSE + MR} SF @ 0.009 MH/SF (rev 2: was 0.012)", "DA", (std + ABUSE + MR) * D("0.009")),
    ("Abuse-resistant board weight factor 50,000 SF @ 0.003 MH/SF", "DA", 150),
    ("Cement backer board 6,000 SF @ 0.02 MH/SF", "DA", 120),
    (f"Ceiling board {GYP_CEIL} SF @ 0.02 MH/SF", "DA", GYP_CEIL * D("0.02")),
    (f"Exterior sheathing {sheath} SF @ 0.011 MH/SF", "DA", sheath * D("0.011")),
    ("Exterior soffit 2,000 SF @ 0.025 MH/SF", "DA", 50),
    ("GypSorb ceiling 2,500 SF @ 0.05 MH/SF", "DA", 125),
    ("Acoustic insulation 65,000 SF @ 0.006 MH/SF", "DA", 390),
    ("Acoustic sealant 16,600 LF @ 0.01 MH/LF", "DA", 166),
    ("Tape and finish Level 4 walls 165,000 SF @ 0.010 MH/SF (rev 2: was 0.013)", "DT", D("165000") * D("0.010")),
    ("Level 1 fire-tape above ceilings 50,000 SF @ 0.004 MH/SF", "DT", 200),
    ("Level 2 behind casework / tile 16,000 SF @ 0.007 MH/SF", "DT", 112),
    ("Ceilings Level 4 11,000 SF @ 0.016 MH/SF", "DT", 176),
    ("Level 5 surfacer add 8,000 SF @ 0.008 MH/SF", "DT", 64),
    ("Beads, trims, reveals, control joints", "DT", 200),
    ("Stocking assist, scrap to GC dumpster, daily cleanup", "LAB", 400),
    ("Foremen non-working supervision (~24 weeks)", "DA", 600),
    ("Submittals, SSMA certs, mock-ups, certified payroll", "ADMIN", 200),
]
m, l = build(gyp_m, gyp_l)
write("madison_sheetrock", {
    "schema": "alkan-package/1",
    "estimate_id": "ALKAN-PRE-2026-MES-GYP-01",
    "date": DATE, "relationship": "sub_to_gc", "tier": "competitive",
    "contractor": GENERIC_CONTRACTOR,
    "project": project("MES-GYP", "Madison ES Replacement - Metal Framing, Gypsum Board & Acoustic Insulation",
                       "non-structural framing, gypsum board & acoustic insulation scope"),
    "labor_rates": {
        "DA": {"label": "Drywall applicator / framer (PW)", "kind": "prevailing_wage", "trade": "drywall_applicator",
               "rate": "84.77", "burden_pct": "15", "source": WAGE_SRC + " - Drywall Applicator, Journey Level $84.77"},
        "DT": {"label": "Drywall taper (PW)", "kind": "prevailing_wage", "trade": "drywall_taper",
               "rate": "84.77", "burden_pct": "15", "source": WAGE_SRC + " - Drywall Tapers, Journey Level $84.77"},
        "LAB": {"label": "Laborer (PW)", "kind": "prevailing_wage", "trade": "laborer",
                "rate": "71.10", "burden_pct": "15", "source": WAGE_SRC + " - Laborers, General Laborer $71.10"},
        "ADMIN": {"label": "PM / admin", "kind": "loaded", "rate": "75.00", "source": "Generic office rate - submittals, certified payroll"},
    },
    "markups": MARKUPS, "tax": {"mode": "excluded_resale"},
    "materials": m, "labor": l,
    "other": other([
        ("Scissor lifts - 3 units x 8 months", "Equipment", 24, "MO", "950.00"),
        ("Baker scaffolds, stilts, screw guns, tools", "Equipment", 1, "LS", "6000.00"),
        ("Mobilization - 2 mobs (Phase 1 framing/board, finish/punch)", "Mobilization", 2, "EA", "2500.00"),
        ("L&I Statement of Intent + Affidavit (verify current fee)", "Fees", 2, "EA", "65.10"),
    ]),
    "scope": [
        {"title": "Non-structural metal framing (09 2216)", "text": f"Interior partitions ({PART_LF} LF, {framed} SF framed) with 20 ga EQ studs, slotted deflection track, HD jambs/headers at openings, bracing and backing; drywall suspension grid for gypsum ceilings."},
        {"title": "Gypsum board assemblies (09 2116)", "text": "5/8\" Type X mold-resistant board, abuse-resistant board at corridors, custodial, gym and cafeteria, moisture-resistant board, cement backer at tile, sag-resistant ceiling board, glass-mat exterior sheathing, exterior soffit board, GypSorb acoustic ceiling allowance and acoustic insulation."},
        {"title": "Joint treatment", "text": "Finish levels per 09 2116 3.6 (Level 5 at semi-gloss, Level 4 typical, Level 2 behind casework/tile, Level 1 above ceilings), beads, reveals, rated expansion joints and acoustic sealant."},
    ],
    "exclusions": BOND_TAX + COMMON_EXCL + [
        "Cold-formed structural metal framing / exterior load-bearing studs (05 4000, delegated design).",
        "Thermal insulation and air/weather barriers (07 2100 / 07 2500 / 07 2726).",
        "Acoustical panel ceilings (09 5113) and sound absorbing panels (09 8433).",
        "Firestopping of penetrations and head-of-wall joint systems (07 8400) beyond rated deflection track.",
        "Painting (09 9120) and wall protection (10 2600).",
        "Fire-retardant wood blocking (06 1053).",
    ],
    "assumptions": COMMON_ASSUMP + [
        "Mold-resistant board is used throughout because board will be installed before the building is enclosed and conditioned (09 2116 2.1.B.2).",
        "Fire-rated assemblies: Type X per tested design; multi-layer and shaft walls assumed limited (included in waste factor) - verify on life-safety plans.",
        "Exterior glass-mat sheathing included because it is in 09 2116 1.1.B; confirm with GC whether it goes with the 05 4000 framing package.",
    ],
    "alkan_commission": COMMISSION, "release": RELEASE, "validity_days": 30,
})
print("ok", OUT)
