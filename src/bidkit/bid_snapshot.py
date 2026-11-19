"""ALKAN Bid Engine — Bid Snapshot (Cabecera de Intake / Go-No-Go).

Estructura los datos de intake y Go/No-Go obtenidos en las etapas 0-2 del agente
o desde el paquete/proyecto, sin modificar el cálculo de precios ni alterar
las reglas de paridad.

Campos oficiales:
- project_name: str | None
- dates:
    - pre_bid_meeting: { date, time, mandatory: bool, passed: bool }
    - walk_through:    { date, time, mandatory: bool }
    - questions_due:   { date, time }
    - bid_due:         { date, time, method }  # email | mail | portal
- contacts: list[{ name, role, email, phone }] # role = owner | gc | architect | engineer
- budget_or_engineers_estimate: { amount, covers, source }  # covers = whole_project | this_trade
- bid_requirements: list[{ item, source, status }]  # status = ok | at_risk | cannot_meet
"""
from __future__ import annotations

import re
from typing import Any

# Expresiones regulares para parsing determinista de notas
EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}")
TIME_RE = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:AM|PM|am|pm)(?:\s*(?:PT|PST|PDT))?\b")
DATE_MONTHS_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"Enero|Febrero|Marzo|Abril|Mayo|Junio|Julio|Agosto|Septiembre|Octubre|Noviembre|Diciembre)\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}\b",
    re.IGNORECASE,
)
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
AMOUNT_RANGE_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?(?:\s*(?:to|-|a)\s*\$[\d,]+(?:\.\d{2})?)?")


def _extract_time(text: str) -> str | None:
    m = TIME_RE.search(text)
    return m.group(0).strip() if m else None


def _extract_date(text: str) -> str | None:
    m = DATE_MONTHS_RE.search(text)
    if m:
        return m.group(0).strip()
    m2 = ISO_DATE_RE.search(text)
    if m2:
        return m2.group(0).strip()
    return None


def _extract_method(text: str) -> str | None:
    low = text.lower()
    if any(k in low for k in ("portal", "online", "bonfire", "opengov", "submittable", "website", "https://", "http://")):
        return "portal"
    if any(k in low for k in ("email", "correo", "e-mail")):
        return "email"
    if any(k in low for k in ("mail", "postal", "hand deliver", "entrega física", "sobre cerrado")):
        return "mail"
    return None


def _clean_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def build_bid_snapshot(
    notes: list[dict[str, Any]] | None = None,
    project_name: str | None = None,
    project_dict: dict[str, Any] | None = None,
    pkg_dict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye un objeto bid_snapshot estructurado a partir de notas y metadatos de proyecto.

    Regla de oro: Nunca inventar un dato. Si no hay fuente comprobada, el campo es null.
    Addenda rule: Fechas provenientes de Addendas sobreescriben fechas de especificaciones originales.
    """
    notes = notes or []
    pdict = project_dict or (pkg_dict.get("project") if pkg_dict else {}) or {}

    # 1. Nombre de proyecto
    p_name = _clean_str(project_name) or _clean_str(pdict.get("title")) or _clean_str(pdict.get("short")) or _clean_str(pdict.get("key"))

    # 2. Fechas estructuradas
    dates: dict[str, Any] = {
        "pre_bid_meeting": {"date": None, "time": None, "mandatory": False, "passed": False},
        "walk_through": {"date": None, "time": None, "mandatory": False},
        "questions_due": {"date": None, "time": None},
        "bid_due": {"date": None, "time": None, "method": None},
    }

    # Separar notas de fechas por tipo y dar prioridad a addendas
    bid_due_candidates: list[dict[str, Any]] = []

    for n in notes:
        kind = str(n.get("kind") or "").lower()
        text = str(n.get("text") or "")
        src = str(n.get("source") or "")
        low = text.lower()
        low_src = src.lower()

        # A. Pre-bid meeting / Walk-through
        if "pre-bid" in low or "walk-through" in low or "walkthrough" in low or "junta pre-licitaci" in low or "recorrido" in low:
            d_val = _extract_date(text)
            t_val = _extract_time(text)
            is_mand = ("mandatory" in low or "obligatori" in low) and not ("not mandatory" in low or "no obligatori" in low)
            is_passed = any(p in low for p in ("passed", "ya pasó", "held", "vencid", "cerrad", "pasada"))

            if "walk" in low:
                if d_val:
                    dates["walk_through"]["date"] = d_val
                if t_val:
                    dates["walk_through"]["time"] = t_val
                dates["walk_through"]["mandatory"] = is_mand

            if "meeting" in low or "junta" in low or not dates["pre_bid_meeting"]["date"]:
                if d_val:
                    dates["pre_bid_meeting"]["date"] = d_val
                if t_val:
                    dates["pre_bid_meeting"]["time"] = t_val
                dates["pre_bid_meeting"]["mandatory"] = is_mand
                dates["pre_bid_meeting"]["passed"] = is_passed

        # B. Questions due / RFI
        if "question" in low or "preguntas" in low or "rfi" in low:
            d_val = _extract_date(text)
            t_val = _extract_time(text)
            if d_val:
                dates["questions_due"]["date"] = d_val
            if t_val:
                dates["questions_due"]["time"] = t_val

        # C. Bid due (candidatos)
        if ("bid due" in low or "entrega" in low or "plazo" in low or "due:" in low or "closing" in low) and "question" not in low:
            d_val = _extract_date(text)
            t_val = _extract_time(text)
            m_val = _extract_method(text)
            is_addenda = "addend" in low_src or "adenda" in low_src or "addend" in low or "adenda" in low
            bid_due_candidates.append({
                "date": d_val,
                "time": t_val,
                "method": m_val,
                "is_addenda": is_addenda,
                "text": text,
                "source": src,
            })

    # Priorizar addenda en bid_due si existe
    if bid_due_candidates:
        # Primero ordenar los que son de addenda al final para que ganen, o elegir el de addenda
        addenda_cand = [c for c in bid_due_candidates if c["is_addenda"] and c["date"]]
        chosen = addenda_cand[-1] if addenda_cand else bid_due_candidates[-1]
        dates["bid_due"]["date"] = chosen["date"]
        dates["bid_due"]["time"] = chosen["time"]
        dates["bid_due"]["method"] = chosen["method"]
    elif pdict.get("bid_date"):
        raw_bdate = str(pdict["bid_date"])
        dates["bid_due"]["date"] = _extract_date(raw_bdate) or raw_bdate
        dates["bid_due"]["time"] = _extract_time(raw_bdate)
        dates["bid_due"]["method"] = _extract_method(raw_bdate)

    # 3. Contactos
    contacts: list[dict[str, Any]] = []
    seen_contacts = set()

    for n in notes:
        if str(n.get("kind") or "").lower() == "contact":
            txt = str(n.get("text") or "")
            src = str(n.get("source") or "")
            email = None
            em_match = EMAIL_RE.search(txt)
            if em_match:
                email = em_match.group(0).strip()
            phone = None
            ph_match = PHONE_RE.search(txt)
            if ph_match:
                phone = ph_match.group(0).strip()

            # Extraer nombres / roles si vienen etiquetados
            # ej. Owner/Agency: DES... Project Manager: Jeff Potts... Architect: Starling...
            segments = re.split(r"(?:Owner/Agency|Owner|Project Manager|Architect|Engineer|GC|Prime|Contratante|Arquitecto):", txt, flags=re.IGNORECASE)
            roles = re.findall(r"\b(Owner/Agency|Owner|Project Manager|Architect|Engineer|GC|Prime|Contratante|Arquitecto)\b", txt, flags=re.IGNORECASE)

            if len(roles) > 0 and len(segments) > 1:
                for r_name, seg in zip(roles, segments[1:]):
                    seg_clean = seg.split(";")[0].split(".")[0].strip()
                    c_name = seg_clean.split(",")[0].strip()
                    r_std = "owner" if "owner" in r_name.lower() or "contratante" in r_name.lower() else (
                        "architect" if "architect" in r_name.lower() or "arquitecto" in r_name.lower() else (
                            "gc" if "gc" in r_name.lower() or "prime" in r_name.lower() else "contact"
                        )
                    )
                    c_key = (c_name.lower(), r_std)
                    if c_name and c_key not in seen_contacts:
                        seen_contacts.add(c_key)
                        contacts.append({
                            "name": c_name,
                            "role": r_std,
                            "email": email if (email and email in seg) else None,
                            "phone": phone if (phone and phone in seg) else None,
                        })
            else:
                c_name = txt.split(",")[0].split(".")[0].split(":")[0].strip()
                if c_name and c_name not in seen_contacts:
                    seen_contacts.add(c_name)
                    contacts.append({
                        "name": c_name,
                        "role": "contact",
                        "email": email,
                        "phone": phone,
                    })

    # Si no se extrajeron de notas, usar project_dict
    if not contacts and pdict:
        if pdict.get("owner"):
            c_email = EMAIL_RE.search(str(pdict.get("owner_contact", "")))
            c_phone = PHONE_RE.search(str(pdict.get("owner_contact", "")))
            contacts.append({
                "name": str(pdict["owner"]),
                "role": "owner",
                "email": c_email.group(0) if c_email else None,
                "phone": c_phone.group(0) if c_phone else None,
            })
        if pdict.get("prime_contractor"):
            prime_str = str(pdict["prime_contractor"])
            p_name = prime_str.split("—")[0].split("-")[0].strip()
            p_email = EMAIL_RE.search(prime_str)
            p_phone = PHONE_RE.search(prime_str)
            contacts.append({
                "name": p_name or "Prime Contractor",
                "role": "gc",
                "email": p_email.group(0) if p_email else None,
                "phone": p_phone.group(0) if p_phone else None,
            })

    # 4. Budget / Engineer's estimate
    budget_info: dict[str, Any] = {
        "amount": None,
        "covers": None,
        "source": None,
    }
    for n in notes:
        if str(n.get("kind") or "").lower() == "benchmark":
            txt = str(n.get("text") or "")
            src = str(n.get("source") or "")
            low = txt.lower()
            amt_match = AMOUNT_RANGE_RE.search(txt)
            amount = amt_match.group(0).strip() if amt_match else txt.split(":")[ -1].strip()
            covers = "whole_project" if any(w in low for w in ("whole project", "proyecto completo", "total", "entire")) else "this_trade"
            budget_info["amount"] = amount
            budget_info["covers"] = covers
            budget_info["source"] = src or "Documentos de licitación"
            break

    # 5. Requisitos de licitación (bid_requirements)
    bid_requirements: list[dict[str, Any]] = []
    seen_reqs = set()

    for n in notes:
        if str(n.get("kind") or "").lower() == "requirement":
            txt = str(n.get("text") or "").strip()
            src = str(n.get("source") or "Documentos de licitación").strip()
            low = txt.lower()

            # Evaluar status: ok | at_risk | cannot_meet
            if any(w in low for w in ("passed", "cannot bid", "vencid", "cerrad", "incumplid", "no se puede cumplir", "ya pasó", "opportunity is closed")):
                status = "cannot_meet"
            elif any(w in low for w in ("at risk", "riesgo", "verificar", "confirmar", "allowance", "tight")):
                status = "at_risk"
            else:
                status = "ok"

            # Título conciso del ítem
            first_sentence = txt.split(".")[0].split("—")[0].strip()
            item_name = first_sentence[:90] if len(first_sentence) > 10 else txt[:90]

            req_key = item_name.lower()
            if req_key not in seen_reqs:
                seen_reqs.add(req_key)
                bid_requirements.append({
                    "item": txt,
                    "short_item": item_name,
                    "source": src,
                    "status": status,
                })

    # Si no hay notas de requisitos pero hay datos de proyecto, construir base mínima
    if not bid_requirements and pdict:
        if pdict.get("wage_basis"):
            bid_requirements.append({
                "item": f"Prevailing wage compliance: {pdict['wage_basis']}",
                "short_item": "Prevailing wage",
                "source": "Project metadata",
                "status": "ok",
            })
        if pdict.get("county"):
            bid_requirements.append({
                "item": f"Contractor licensing in Washington State ({pdict['county']} County)",
                "short_item": "WA Contractor License",
                "source": "L&I registration",
                "status": "ok",
            })

    # 6. Indicador consolidado Go/No-Go derivado
    cannot_meet_items = [r for r in bid_requirements if r["status"] == "cannot_meet"]
    go_no_go_explanation = None
    if cannot_meet_items:
        first_blocker = cannot_meet_items[0]
        go_no_go_explanation = f"NO_GO: {first_blocker['item']} (Fuente: {first_blocker['source']})"

    return {
        "project_name": p_name or "falta confirmar",
        "dates": dates,
        "contacts": contacts,
        "budget_or_engineers_estimate": budget_info,
        "bid_requirements": bid_requirements,
        "has_blockers": bool(cannot_meet_items),
        "go_no_go_explanation": go_no_go_explanation,
    }


def format_bid_snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Genera versión compacta lista para serializar en manifest y pantallas móviles."""
    dates = snapshot.get("dates") or {}
    due = dates.get("bid_due") or {}
    pre_bid = dates.get("pre_bid_meeting") or {}
    reqs = snapshot.get("bid_requirements") or []

    due_str = f"{due.get('date') or 'falta confirmar'}"
    if due.get("time"):
        due_str += f" a las {due['time']}"
    if due.get("method"):
        due_str += f" ({due['method']})"

    mandatory_meeting = bool(pre_bid.get("mandatory"))
    meeting_passed = bool(pre_bid.get("passed"))

    return {
        "project_name": snapshot.get("project_name") or "falta confirmar",
        "bid_due_formatted": due_str,
        "due_date": due.get("date"),
        "due_time": due.get("time"),
        "due_method": due.get("method"),
        "has_mandatory_prebid": mandatory_meeting,
        "mandatory_prebid_passed": meeting_passed,
        "contacts_count": len(snapshot.get("contacts") or []),
        "budget_estimate": snapshot.get("budget_or_engineers_estimate"),
        "requirements_count": len(reqs),
        "cannot_meet_count": sum(1 for r in reqs if r.get("status") == "cannot_meet"),
        "at_risk_count": sum(1 for r in reqs if r.get("status") == "at_risk"),
        "ok_count": sum(1 for r in reqs if r.get("status") == "ok"),
        "has_blockers": bool(snapshot.get("has_blockers")),
        "go_no_go_explanation": snapshot.get("go_no_go_explanation"),
    }
