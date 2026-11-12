from pathlib import Path
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


SOURCE = Path(os.environ.get("BIDKIT_HILTON_SOURCE", str(Path.cwd() / "docs" / "hilton")))
OUTPUT = Path(os.environ.get("BIDKIT_HILTON_OUTPUT", str(Path.cwd() / "output" / "hilton-area1")))
OUTPUT.mkdir(parents=True, exist_ok=True)

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=9, leading=12))
styles["BodyText"].fontSize = 10
styles["BodyText"].leading = 14


def money(value):
    return f"${value:,.2f}"


def footer(canvas, doc):
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5D6871"))
    canvas.drawString(54, 28, "Hilton Downtown Seattle | Area 1 | Sales tax excluded")
    canvas.drawRightString(558, 28, f"Page {doc.page}")


def table(rows, widths=(350, 150)):
    rendered = [[Paragraph(str(left), styles["Small"]), Paragraph(str(right), styles["Small"])] for left, right in rows]
    result = Table(rendered, colWidths=list(widths), hAlign="LEFT")
    result.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#C9D2D9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return result


def build(path, title, subtitle, sections):
    flow = [Paragraph(title, styles["Title"]), Paragraph(subtitle, styles["BodyText"]), Spacer(1, 12)]
    for heading, content in sections:
        flow.append(Paragraph(heading, styles["Heading2"]))
        if isinstance(content, Table):
            flow.append(content)
        else:
            for paragraph in content:
                flow.append(Paragraph(paragraph, styles["BodyText"]))
        flow.append(Spacer(1, 10))
    SimpleDocTemplate(str(path), pagesize=letter, leftMargin=54, rightMargin=54, topMargin=46, bottomMargin=46).build(
        flow, onFirstPage=footer, onLaterPages=footer
    )


turnkey_rows = [
    ("Metals, including demolition, fabrication, installation and exposed-steel coatings", money(188324.66)),
    ("Concrete - prior allowance; localized limits require reconciliation", money(37946.55)),
    ("Roofing and waterproofing", money(29535.45)),
    ("Electrical", money(19550.00)),
    ("Canopy carpentry", money(3565.00)),
    ("General conditions and permit allowance", money(24325.00)),
    ("Current calculated total", money(303246.66)),
]

build(
    OUTPUT / "Hilton_Turnkey_Quote_Draft_EN.pdf",
    "Turnkey Entrance Canopy - Quote Draft",
    "Hilton Downtown Seattle | Area 1 | Prepared October 13, 2026 | S&S Custom Iron Works LLC",
    [
        ("Scope of Work", [
            "Area 1 canopy demolition; structural and architectural metals, metal roof deck, exposed-steel coatings, decorative panels and drainage metalwork; roof system; electrical lighting; canopy blocking; localized concrete repairs; coordination and permit allowances.",
            "The turnkey option includes roofing and electrical. Full entry paving and curb replacement are not included unless separately confirmed by field verification and an approved scope change.",
        ]),
        ("Current Pricing Basis", table(turnkey_rows)),
        ("Pricing Status", [
            "The requested $297,000 target remains pending documented cost adjustments that preserve the 15% overhead and profit calculation. This PDF does not present $297,000 as a firm offer.",
            "Sales tax excluded. Specialty supplier pricing, field dimensions, electrical reuse, and localized concrete quantities remain subject to confirmation.",
        ]),
    ],
)

diamond_rows = [
    ("Metals, including demolition, fabrication, installation and coatings", money(188324.66)),
    ("Three localized concrete diamond patches", money(5618.90)),
    ("Total - sales tax excluded", money(193943.56)),
]

build(
    OUTPUT / "Hilton_Steel_and_Concrete_Diamonds_Quote_Draft_EN.pdf",
    "Steel Package + Concrete Diamonds - Quote Draft",
    "Hilton Downtown Seattle | Area 1 | Prepared October 13, 2026 | S&S Custom Iron Works LLC",
    [
        ("Pricing", table(diamond_rows)),
        ("Included Scope", [
            "Existing canopy metal demolition; structural steel fabrication and installation; metal roof deck; architectural and decorative panels and supports; fabricated drainage metalwork, rain chains, and specified exposed-steel coating system.",
            "Three grade-level concrete diamond patches at the canopy posts, including selective removal, localized substrate and waterproofing repair allowance, grout or patching as applicable, isolation joint, finish to match existing, and sealer.",
        ]),
        ("Concrete Assumptions", [
            "Three patches are estimated at approximately 2 ft x 2 ft each with a 3-inch topping depth. This is an estimator allowance, subject to field verification. It is not a concrete subcontractor quotation.",
            "The three platform posts, new structural footings, excavation, below-membrane work, full concrete paving or curb replacement, roofing, electrical, and lighting are excluded.",
        ]),
    ],
)

diamond_cost_rows = [
    ("Concrete / placement consumables", money(250.00)),
    ("Grout, bond prep, isolation joint and sealants", money(250.00)),
    ("Localized waterproofing patch supplies", money(150.00)),
    ("Labor: 32 person-hours x $98/hour", money(3136.00)),
    ("Small tools / saw / equipment", money(400.00)),
    ("Debris handling and disposal", money(250.00)),
    ("Transport / mobilization", money(450.00)),
    ("Direct cost", money(4886.00)),
    ("O&P: 15%", money(732.90)),
    ("Concrete diamonds total", money(5618.90)),
]

build(
    OUTPUT / "Concrete_Diamonds_Cost_Estimate_EN.pdf",
    "Concrete Diamonds - Cost Estimate",
    "Hilton Downtown Seattle | Area 1 | Budgetary estimate | Prepared October 13, 2026",
    [
        ("Pricing", table(diamond_cost_rows)),
        ("Basis and Limits", [
            "Three localized grade-level diamond patches at the new canopy posts, estimated at approximately 2 ft x 2 ft each and a 3-inch topping depth. Field verification is required before construction.",
            "Includes selective removal, localized repair allowance, concrete placement, grout or patching, isolation joints, finish to match existing, sealer and cleanup. New structural footings, excavation, full paving or curb replacement, and conditions below the waterproofing are excluded.",
            "The cost is an estimator allowance, not a supplier or concrete subcontractor quote. It does not include a dedicated continuous traffic-control attendant, independent testing, permits, bonds, or major waterproofing replacement.",
        ]),
    ],
)

build(
    OUTPUT / "Hilton_Steel_and_Diamonds_Summary_EN.pdf",
    "Steel Package + Concrete Diamonds - Pricing Summary",
    "Hilton Downtown Seattle | Area 1 | Prepared October 13, 2026 | S&S Custom Iron Works LLC",
    [
        ("Offer Summary", table(diamond_rows)),
        ("What Is Included", [
            "Metals: existing canopy demolition, steel fabrication and erection, metal roof deck, architectural and decorative components, drainage metalwork, rain chains, and the specified exposed-steel coating system.",
            "Concrete: three localized grade-level diamond patches at the canopy posts only. This is not a price for all concrete or new structural footings.",
        ]),
        ("What Is Excluded", [
            "Electrical and lighting; PVC roofing, insulation and roofing-system flashing/coping; full paving or curb replacement; the three platform posts; concrete outside the diamonds; new structural footings; and separate canopy wood blocking.",
        ]),
    ],
)

print(OUTPUT)
