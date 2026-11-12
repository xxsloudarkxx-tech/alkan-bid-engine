"""Source-backed records seeded only from verified local documents."""
from __future__ import annotations

from typing import Any


SPEC = "072026-1044_specs.pdf"
DRAWINGS = "072026-1044_drawings-(1).pdf"


def source(document: str, page: int | str, confidence: str = "HIGH") -> dict[str, Any]:
    return {"document": document, "page": page, "confidence": confidence}


REQUIREMENTS: list[dict[str, Any]] = [
    {"id": "BID-001", "phase": "with_bid", "requirement": "Submit on the Port Bid Form; complete all blanks, in figures.", "status": "PENDING", "source": source(SPEC, 14)},
    {"id": "BID-002", "phase": "with_bid", "requirement": "Acknowledge receipt and acceptance of all addenda through the last addendum number.", "status": "PENDING", "source": source(SPEC, 28)},
    {"id": "BID-003", "phase": "with_bid", "requirement": "Bid security of at least 5% of Base Bid Subtotal; check or compliant bid bond.", "status": "BLOCKING", "source": source(SPEC, 15)},
    {"id": "BID-004", "phase": "with_bid", "requirement": "Authorized signature, legal entity, address, license and ESD number on official Bid Form.", "status": "BLOCKING", "source": source(SPEC, 28)},
    {"id": "BID-005", "phase": "with_bid", "requirement": "No oral, email, telephone, fax or electronic bid; timely delivery to designated location.", "status": "PENDING", "source": source(SPEC, 16)},
    {"id": "POST-001", "phase": "after_apparent_low", "requirement": "Responsibility Detail Form and backup documentation electronically within 24 hours after selection notification.", "status": "BLOCKING", "source": source(SPEC, 34)},
    {"id": "POST-002", "phase": "after_apparent_low", "requirement": "Recent similar-project resume, PM and superintendent resumes.", "status": "BLOCKING", "source": source(SPEC, 34)},
    {"id": "POST-003", "phase": "after_apparent_low", "requirement": "Verify responsibility criteria for major subcontractors and submit checklist when requested.", "status": "PENDING", "source": source(SPEC, 34)},
    {"id": "AWARD-001", "phase": "after_award", "requirement": "Performance bond from qualified WA surety; power of attorney attached.", "status": "BLOCKING", "source": source(SPEC, 42)},
    {"id": "AWARD-002", "phase": "after_award", "requirement": "Labor and Material Payment Bond in official form.", "status": "BLOCKING", "source": source(SPEC, 43)},
    {"id": "AWARD-003", "phase": "after_award", "requirement": "Insurance certificate and required bonds within Contract Document time.", "status": "BLOCKING", "source": source(SPEC, 20)},
    {"id": "PERF-001", "phase": "performance", "requirement": "Substantial Completion in 180 calendar days from execution; Final Completion within 30 days after Substantial Completion.", "status": "PENDING", "source": source(SPEC, 38)},
]

AMENDMENTS: list[dict[str, Any]] = [
    {"addendum": "01", "date": "2026-10-02", "change": "TMP MS-200 mechanically seamed .040 aluminum panel accepted as noted: coastal warranty, 180-degree seam, metallic silver SRI 60, region load-chart and purlin-spacing confirmation, thermal spacer blocks. Other components substantially similar.", "precedence": "active", "source": source("072026-1044_addendum_no._01.pdf", 2)},
    {"addendum": "02", "date": "2026-10-13", "change": "Drexel DMC 200S substitution package issued for Section 07 41 00. Q&A states it is approved; use the addendum package and obtain project-specific confirmation as applicable.", "precedence": "active", "source": source("072026-1044_addendum_02.pdf", 1)},
    {"addendum": "03", "date": "2026-10-14", "change": "Moves sealed bid receipt to October 22, 2026, 2:00 PM at Port Administration Office. Header incorrectly labels itself Addendum Number 02.", "precedence": "superseded_by_04", "source": source("072026-1044_addendum_03.pdf", 1)},
    {"addendum": "04", "date": "2026-10-21", "change": "Moves sealed bid receipt to October 29, 2026, 2:00 PM at Port Administration Office, One Sitcum Plaza, Tacoma WA 98421.", "precedence": "active_final_for_bid_time", "source": source("072026-1044_addendum_04.pdf", 1)},
]

TAKEOFF: list[dict[str, Any]] = [
    {"building": "Building 1 - 5301 8th St E", "item": "Standing seam metal roof", "unit": "SF plan", "quantity": 8139.44, "quantity_status": "VERIFIED PLAN AREA", "basis": "81 ft 8 in x 99 ft 8 in rectangular plan footprint; no slope factor applied.", "source": source(DRAWINGS, "A1-401 / PDF 5")},
    {"building": "Building 1 - 5301 8th St E", "item": "Roof pitch / sloped surface area", "unit": "SF", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "Plan shows 1:12 arrows but no certified field verification; do not convert plan area to sloped area until estimator confirms takeoff method.", "source": source(DRAWINGS, "A1-401 / PDF 5", "MEDIUM")},
    {"building": "Building 1 - 5301 8th St E", "item": "6 in aluminum gutter", "unit": "LF", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "New 6 in gutter is called out; perimeter and exclusions require a controlled measurement.", "source": source(DRAWINGS, "A1-401 / A-530", "HIGH")},
    {"building": "Building 1 - 5301 8th St E", "item": "4 in x 4 in downspouts", "unit": "EA", "quantity": 4, "quantity_status": "VERIFIED COUNT", "basis": "Four DS symbols at roof corners.", "source": source(DRAWINGS, "A1-401 / PDF 5")},
    {"building": "Building 1 - 5301 8th St E", "item": "Pipe penetration flashing", "unit": "EA", "quantity": 1, "quantity_status": "VERIFIED COUNT", "basis": "One PIPE symbol; drawing notes require field verification of all penetrations.", "source": source(DRAWINGS, "A1-401 / PDF 5")},
    {"building": "Building 1 - 5301 8th St E", "item": "Gable rake board and flashing", "unit": "LF", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "Called out; length to be controlled from plan/detail dimensions.", "source": source(DRAWINGS, "A1-401 / A-530", "HIGH")},
    {"building": "Building 2 - 5216 7th St E", "item": "Standing seam metal roof", "unit": "SF plan", "quantity": 4998.0, "quantity_status": "VERIFIED PLAN AREA", "basis": "98 ft x 51 ft rectangular plan footprint; no slope factor applied.", "source": source(DRAWINGS, "A2-401 / PDF 7")},
    {"building": "Building 2 - 5216 7th St E", "item": "Roof pitch / sloped surface area", "unit": "SF", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "Drawing shows roof geometry; field verification is expressly required and no slope factor is applied.", "source": source(DRAWINGS, "A2-401 / PDF 7", "MEDIUM")},
    {"building": "Building 2 - 5216 7th St E", "item": "6 in aluminum gutter", "unit": "LF", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "New 6 in gutter is called out; final lengths require controlled measurement.", "source": source(DRAWINGS, "A2-401 / A-530")},
    {"building": "Building 2 - 5216 7th St E", "item": "4 in x 4 in downspouts", "unit": "EA", "quantity": 4, "quantity_status": "VERIFIED COUNT", "basis": "Four DS symbols at roof corners.", "source": source(DRAWINGS, "A2-401 / PDF 7")},
    {"building": "Building 2 - 5216 7th St E", "item": "Pipe penetration flashing", "unit": "EA", "quantity": 4, "quantity_status": "VERIFIED COUNT", "basis": "Four PIPE symbols shown; notes require field verification.", "source": source(DRAWINGS, "A2-401 / PDF 7", "MEDIUM")},
    {"building": "Building 2 - 5216 7th St E", "item": "Temporary relocation / curb flashing at mechanical units", "unit": "LS", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "Existing mechanical units require temporary relocation; quantity and responsible trade need field coordination.", "source": source(DRAWINGS, "A2-401 keynote 01")},
    {"building": "Both buildings", "item": "Thermal blocks, floating clips, fastening, sealant, ridge/rake flashing", "unit": "per design", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "Details require manufacturer-designed clips / thermal blocks, field verification and approved system-specific attachment spacing.", "source": source(DRAWINGS, "A-530", "HIGH")},
    {"building": "Both buildings", "item": "Demolition, disposal, lifting, fall protection, temporary protection", "unit": "LS", "quantity": None, "quantity_status": "PENDIENTE DE MEDICIÓN", "basis": "Scope needs site logistics and field verification; no quantity is inferred from imagery.", "source": source(DRAWINGS, "A-005 / A1-401 / A2-401", "MEDIUM")},
]

RISKS: list[dict[str, Any]] = [
    {"id": "R-01", "status": "BLOCKING", "risk": "Bidder entity, license, ESD, UBI, industrial insurance and statutory responsibility answers are unknown.", "action": "Eligible contractor must provide verifiable documents and authorized signer.", "source": source(SPEC, 28)},
    {"id": "R-02", "status": "BLOCKING", "risk": "Bid security / surety capacity is not supplied.", "action": "Obtain compliant bid bond or certified/cashier check before submission.", "source": source(SPEC, 15)},
    {"id": "R-03", "status": "BLOCKING", "risk": "No supplier quotations, crew rates, equipment rates, tax basis confirmation, or approved unit prices are supplied.", "action": "Estimator must load supported quotes and approve prices.", "source": source(SPEC, 27)},
    {"id": "R-04", "status": "BLOCKING", "risk": "Plans require field verification of dimensions, penetrations, utilities and conditions; drawings do not support a fully measured procurement takeoff.", "action": "Perform documented site measurement and reconcile to controlled takeoff.", "source": source(DRAWINGS, "A1-401 / A2-401")},
    {"id": "R-05", "status": "PENDING", "risk": "Addendum 03 filename conflicts with internal addendum number.", "action": "Confirm acknowledgement sequence with Port; acknowledge through 04 unless written correction states otherwise.", "source": source("072026-1044_addendum_03.pdf", 1)},
    {"id": "R-06", "status": "PENDING", "risk": "Substitution selection and project-specific system compatibility are unselected.", "action": "Choose basis-of-design or approved alternate; obtain load, clip spacing, warranty and system confirmation.", "source": source("072026-1044_addendum_no._01.pdf", 2)},
]
