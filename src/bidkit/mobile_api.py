"""Mobile-first API gateway exposing ALKAN Bid Engine to Flutter Android clients.

Reuses ``AppAPI`` (``/api/app/*``), ``V4API`` (``/api/v4/*``), ``RunManager``,
``contrato``, ``package_build``, ``security`` and ``domain`` without modifying
the vertical Washington calculation engine.

Run locally or on Render/Railway:
    python -m bidkit.mobile_api --host 0.0.0.0 --port 8000
    uvicorn bidkit.mobile_api:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from . import contrato, delivery
from .app_api import AppAPI, Download
from .app_settings import AppSettings
from .criterio import review as review_criterio, write_report as write_criterio_report
from .deliverables_v4 import ImmutableVersionError
from .domain import AuditLedger, InvalidStateTransitionError
from .estimator_agent.tools import _load_kb
from .package_build import build as build_package
from .package_method import PACKAGE_SCHEMA
from .pricebook import PriceGovernanceError
from .rfi_rfq import UnAuthorizedOutboundError
from .security import (
    AuthenticationError,
    AuthorizationError,
    RateLimitError,
    SecurityContext,
    SecurityError,
    SelfApprovalError,
    require_permission,
    sanitize_filename,
)

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, Response
    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - stdlib HTTP fallback keeps local execution zero-dep
    FASTAPI_AVAILABLE = False

MOBILE_API_VERSION = "3.11.0-mobile1"

SPECIALTIES: tuple[dict[str, Any], ...] = (
    {
        "id": "metal",
        "label": "Metal / Acero",
        "trade_scope": "Metal fabrication, structural steel, railings, fences and gates",
        "default_profile": "ss_custom_iron_works",
        "suppliers": ["farwest_steel"],
        "template": "examples/packages/wsj.json",
    },
    {
        "id": "techado",
        "label": "Techado (Roofing)",
        "trade_scope": "Commercial and residential roofing, TPO, shingles, flashing",
        "default_profile": "pj_roofing",
        "suppliers": ["abc_supply", "conway"],
        "template": None,
    },
    {
        "id": "tablaroca",
        "label": "Tablaroca (Drywall)",
        "trade_scope": "Metal framing, gypsum board, taping, finishing and acoustic insulation",
        "default_profile": "diaz_finish_carpenter",
        "suppliers": ["lw_supply", "gms_supply"],
        "template": "examples/packages/madison_es/madison_sheetrock.json",
    },
    {
        "id": "pintura",
        "label": "Pintura / Recubrimientos",
        "trade_scope": "Interior and exterior architectural painting and high-performance coatings",
        "default_profile": "diaz_finish_carpenter",
        "suppliers": ["sherwin_williams", "rodda_paint"],
        "template": "examples/packages/madison_es/madison_pintura.json",
    },
    {
        "id": "molduras",
        "label": "Carpintería / Molduras",
        "trade_scope": "Finish carpentry, wood trim, millwork and casework",
        "default_profile": "diaz_finish_carpenter",
        "suppliers": ["dunn_lumber", "home_depot"],
        "template": "examples/packages/madison_es/madison_carpinteria_diaz.json",
    },
    {
        "id": "cubiertas",
        "label": "Cubiertas (Countertops)",
        "trade_scope": "Stone, quartz and solid surface countertops fabrication and installation",
        "default_profile": "jc_granite_design",
        "suppliers": [],
        "template": "examples/packages/hc3_jcgranite.json",
    },
)

WA_COUNTIES: tuple[str, ...] = (
    "King",
    "Pierce",
    "Snohomish",
    "Kitsap",
    "Thurston",
    "Spokane",
    "Clark",
    "Whatcom",
    "Skagit",
)
VERIFIED_WAGE_COUNTIES: tuple[str, ...] = ("King", "Snohomish")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
QUOTE_IMPORT_SUFFIXES = {".csv", ".xlsx", ".xlsm", ".pdf"}
PUBLIC_GET_PATHS = {"/api/mobile/health", "/"}
PUBLIC_POST_PATHS = {"/api/v4/auth/login", "/api/mobile/auth/bootstrap", "/api/mobile/auth/change-password"}

PROGRESS_STEPS: tuple[dict[str, str], ...] = (
    {"id": "reading", "label": "Leyendo planos"},
    {"id": "addenda", "label": "Revisando adendas"},
    {"id": "takeoff", "label": "Takeoff"},
    {"id": "pricing", "label": "Precios L&I"},
    {"id": "pdfs", "label": "Generando 3 PDFs"},
)


class BinaryResponse:
    """In-memory bytes or file response with explicit media type."""

    def __init__(self, data: bytes, media_type: str, filename: str | None = None):
        self.data = data
        self.media_type = media_type
        self.filename = filename


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_root() -> Path:
    env = os.environ.get("BIDKIT_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "profiles").is_dir() and (cwd / "src" / "bidkit").is_dir():
        return cwd
    return Path(__file__).resolve().parents[2]


def _status_badge(state: dict[str, Any]) -> tuple[str, str]:
    """Map RunManager status onto the 4 core mobile traffic-light cards."""
    raw = str(state.get("status") or "").lower()
    decision = str(state.get("decision") or "").upper()
    if raw in ("en cola", "indexando", "estimando"):
        return "analyzing", "Analizando planos"
    if raw in ("autorizada", "exportada"):
        return "approved", "Autorizado"
    if raw in ("no-go", "rechazada") or decision == "NO_GO":
        return "no_go", "NO-GO"
    if raw == "lista":
        return "draft_ready", "Listo para revisión (DRAFT)"
    return "error", f"Requiere atención ({raw or 'error'})"


def _compute_progress(state: dict[str, Any]) -> dict[str, Any]:
    """Translate RunManager status + stage into the 5 visible mobile progress steps."""
    raw_status = str(state.get("status") or "").lower()
    stage = str(state.get("stage") or "").lower()

    if raw_status in ("lista", "autorizada", "exportada"):
        active_idx = 5
        percent = 100
    elif raw_status in ("no-go", "rechazada", "error", "cancelada", "interrumpida", "incompleta"):
        active_idx = 4 if "paquete" in stage or "pdf" in stage else 1
        percent = 100 if raw_status in ("no-go", "rechazada") else 0
    elif raw_status in ("en cola", "indexando") or "inventario" in stage:
        active_idx = 0
        percent = 15 if raw_status == "indexando" else 5
    elif any(k in stage for k in ("fecha", "adenda", "addend", "spec", "bid form", "alcance")):
        active_idx = 1
        percent = 35
    elif any(k in stage for k in ("takeoff", "plano", "medici")):
        active_idx = 2
        percent = 55
    elif any(k in stage for k in ("precio", "mano de obra", "l&i", "tarifa", "nota")):
        active_idx = 3
        percent = 75
    elif any(k in stage for k in ("paquete", "pdf", "reporte", "verificaci")):
        active_idx = 4
        percent = 90
    else:
        active_idx = 1
        percent = 25

    steps = []
    for idx, step in enumerate(PROGRESS_STEPS):
        if active_idx >= 5 or idx < active_idx:
            st = "done"
        elif idx == active_idx:
            st = "error" if raw_status in ("error", "cancelada", "interrumpida") else "active"
        else:
            st = "pending"
        steps.append({**step, "index": idx, "state": st})

    return {
        "steps": steps,
        "active_step_index": min(active_idx, len(PROGRESS_STEPS) - 1),
        "percent": percent,
        "stage": state.get("stage") or "",
        "is_running": raw_status in ("en cola", "indexando", "estimando"),
    }


def _find_logo_bytes(app: AppAPI, profile_name: str) -> tuple[bytes, str] | None:
    if not re.fullmatch(r"[a-z0-9_]{1,60}", profile_name or ""):
        raise ValueError("Perfil inválido")
    profiles_dir = app.runs.profiles_dir()
    path = profiles_dir / f"{profile_name}.json"
    if not path.exists():
        raise ValueError(f"Perfil no encontrado: {profile_name}")
    prof = json.loads(path.read_text(encoding="utf-8"))
    logo_path = contrato.find_logo(profile_name, prof, profiles_dir)
    if not logo_path or not logo_path.exists():
        return None
    ext = logo_path.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg" if ext in (".jpg", ".jpeg") else "image/webp"
    return logo_path.read_bytes(), mime


class MobileBidEngineAPI:
    """Facade wrapping AppAPI and V4API with mobile-specific endpoints and Bearer auth."""

    def __init__(self, root: Path | None = None, settings: AppSettings | None = None, client_factory=None):
        self.root = Path(root or _default_root()).resolve()
        self.app = AppAPI(self.root, settings=settings, client_factory=client_factory)
        self._init_storage_and_env_users()

    def _init_storage_and_env_users(self) -> None:
        """Ensure persistent folders exist and seed users from ALKAN_INITIAL_USERS_JSON if store is empty."""
        (self.root / "data" / "security").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "uploads").mkdir(parents=True, exist_ok=True)
        self.app.runs.base.mkdir(parents=True, exist_ok=True)

        raw_users = os.environ.get("ALKAN_INITIAL_USERS_JSON", "").strip()
        if not raw_users:
            return
        auth = self.app.v4.auth
        with auth._lock:
            data = auth._load()
            if data.get("users"):
                return
            try:
                entries = json.loads(raw_users)
            except ValueError:
                return
            if not isinstance(entries, list):
                return
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                uname = str(entry.get("username") or "").strip()
                pwd = str(entry.get("password") or "")
                role = str(entry.get("role") or "estimator").strip()
                org_id = str(entry.get("org_id") or "default").strip() or "default"
                must_change = bool(entry.get("must_change_password", True))
                if uname and len(pwd) >= 8:
                    auth.create_user(
                        uname,
                        pwd,
                        role=role,
                        org_id=org_id,
                        must_change_password=must_change,
                    )

    # ───────────────────────────── auth helpers
    def _auth_headers(self, headers: dict[str, str] | None) -> dict[str, str]:
        out: dict[str, str] = {}
        for k, v in (headers or {}).items():
            kl = k.lower()
            if kl == "authorization":
                out["Authorization"] = v
            elif kl == "x-alkan-api-key":
                out["X-ALKAN-API-Key"] = v
            elif kl == "x-alkan-actor":
                out["X-ALKAN-Actor"] = v
            else:
                out[k] = v
        return out

    def authenticate(self, headers: dict[str, str] | None) -> SecurityContext:
        hdrs = self._auth_headers(headers)
        auth_hdr = (hdrs.get("Authorization") or "").strip()
        if auth_hdr.startswith("Bearer "):
            tok = auth_hdr[7:].strip()
            ctx = self.app.v4.auth.authenticate_service_key(tok) or self.app.v4.auth.authenticate_session(tok)
            if ctx is None:
                raise AuthenticationError("Token Bearer inválido o expirado.")
            return ctx
        api_key = (hdrs.get("X-ALKAN-API-Key") or "").strip()
        if api_key:
            ctx = self.app.v4.auth.authenticate_service_key(api_key)
            if ctx is None:
                raise AuthenticationError("API Key inválida.")
            return ctx
        raise AuthenticationError("Autenticación requerida: envíe Authorization: Bearer <token>.")

    def bootstrap_auth(self, req: dict[str, Any]) -> dict[str, Any]:
        """Seed initial estimator/reviewer/admin accounts once on empty store (if allowed) and sign in."""
        allow_bootstrap = os.environ.get("ALKAN_ALLOW_BOOTSTRAP", "true").lower() not in ("0", "false", "no")
        auth = self.app.v4.auth
        seeded = False
        with auth._lock:
            data = auth._load()
            if not data.get("users") and allow_bootstrap:
                auth.create_user("estimator", "Estimator!2026", role="estimator", org_id="default", must_change_password=False)
                auth.create_user("reviewer", "Reviewer!2026", role="reviewer", org_id="default", must_change_password=False)
                auth.create_user("admin", "Admin!2026", role="admin", org_id="default", must_change_password=False)
                seeded = True
        username = str(req.get("username") or "").strip().lower()
        password = str(req.get("password") or "")
        if not username or not password:
            raise AuthenticationError("Ingrese usuario y contraseña.")
        token, ctx = auth.authenticate_password(username, password)
        return {
            "token": token,
            "actor": ctx.actor,
            "role": ctx.role,
            "org_id": ctx.org_id,
            "seeded": seeded,
            "must_change_password": auth.must_change_password(ctx.actor),
        }

    def change_password_mobile(self, req: dict[str, Any]) -> dict[str, Any]:
        """Verify current credentials, rotate password, clear must_change_password and issue new session."""
        username = str(req.get("username") or "").strip().lower()
        current_password = str(req.get("current_password") or "")
        new_password = str(req.get("new_password") or "")
        if not username or not current_password or not new_password:
            raise ValueError("Usuario, contraseña actual y nueva contraseña requeridos.")
        token, ctx = self.app.v4.auth.change_password(username, current_password, new_password)
        self.app.v4._org_ledger(ctx.org_id).record(
            org_id=ctx.org_id,
            project_id="AUTH",
            actor=ctx.actor,
            role=ctx.role,
            action="USER_PASSWORD_CHANGED",
            state_from="Active",
            state_to="Active",
            resource_type="user",
            resource_id=ctx.actor,
            detail={"must_change_password": False},
        )
        return {
            "token": token,
            "actor": ctx.actor,
            "role": ctx.role,
            "org_id": ctx.org_id,
            "must_change_password": False,
        }

    # ───────────────────────────── uploads (resumable + camera photo -> PDF)
    def _upload_folder(self, upload_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{16,40}", upload_id or ""):
            raise ValueError("upload_id inválido")
        return self.root / "data" / "uploads" / upload_id

    def _read_upload_meta(self, folder: Path) -> dict[str, Any]:
        meta_path = folder / ".upload_meta.json"
        if not meta_path.exists():
            return {"files": {}}
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def _write_upload_meta(self, folder: Path, meta: dict[str, Any]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".upload_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    def upload_status(self, upload_id: str) -> dict[str, Any]:
        folder = self._upload_folder(upload_id)
        if not folder.exists():
            return {"upload_id": upload_id, "exists": False, "files": [], "total_bytes": 0}
        meta = self._read_upload_meta(folder)
        files = []
        total_bytes = 0
        for p in sorted(folder.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            size = p.stat().st_size
            total_bytes += size
            fmeta = (meta.get("files") or {}).get(p.name, {})
            files.append({
                "name": p.name,
                "bytes": size,
                "next_index": int(fmeta.get("next_index", 0)),
                "complete": bool(fmeta.get("complete", p.suffix.lower() in (".pdf", ".zip"))),
            })
        return {"upload_id": upload_id, "exists": True, "files": files, "total_bytes": total_bytes}

    def upload_chunk(self, req: dict[str, Any]) -> dict[str, Any]:
        upload_id = str(req.get("upload_id") or "")
        raw_name = str(req.get("name") or "")
        index = int(req.get("index", 0))
        content = str(req.get("content") or "")
        is_last = bool(req.get("is_last", True))

        folder = self._upload_folder(upload_id)
        folder.mkdir(parents=True, exist_ok=True)
        clean_name = sanitize_filename(raw_name, fallback="archivo.pdf")
        ext = Path(clean_name).suffix.lower()

        if ext in (".pdf", ".zip"):
            meta = self._read_upload_meta(folder)
            fmeta = meta.setdefault("files", {}).get(clean_name, {})
            next_idx = int(fmeta.get("next_index", 0))
            if index < next_idx:
                target = folder / clean_name
                return {
                    "upload_id": upload_id,
                    "name": clean_name,
                    "bytes": target.stat().st_size if target.exists() else 0,
                    "next_index": next_idx,
                    "already_received": True,
                    "complete": bool(fmeta.get("complete", False)),
                }
            if index != next_idx:
                raise ValueError(f"Bloque fuera de secuencia (esperado {next_idx}, recibido {index})")
            res = self.app.runs.upload_chunk(upload_id, clean_name, index, content)
            meta["files"][res["name"]] = {"next_index": index + 1, "complete": is_last}
            self._write_upload_meta(folder, meta)
            return {**res, "next_index": index + 1, "complete": is_last, "converted_to_pdf": False}

        if ext in IMAGE_SUFFIXES:
            from PIL import Image

            raw = base64.b64decode(content, validate=True)
            img_dir = folder / "_images"
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = img_dir / clean_name
            meta = self._read_upload_meta(folder)
            fmeta = meta.setdefault("files", {}).get(clean_name, {})
            next_idx = int(fmeta.get("next_index", 0))
            if index < next_idx:
                return {
                    "upload_id": upload_id,
                    "name": fmeta.get("pdf_name") or clean_name,
                    "bytes": img_path.stat().st_size if img_path.exists() else 0,
                    "next_index": next_idx,
                    "already_received": True,
                    "complete": bool(fmeta.get("complete", False)),
                }
            if index == 0:
                img_path.write_bytes(raw)
            else:
                with open(img_path, "ab") as fh:
                    fh.write(raw)

            out_name = clean_name
            out_bytes = img_path.stat().st_size
            converted = False
            if is_last:
                pdf_name = f"{Path(clean_name).stem}.pdf"
                pdf_path = folder / pdf_name
                with Image.open(img_path) as im:
                    im.convert("RGB").save(pdf_path, "PDF", resolution=150.0)
                out_name = pdf_name
                out_bytes = pdf_path.stat().st_size
                converted = True
            meta["files"][clean_name] = {
                "next_index": index + 1,
                "complete": is_last,
                "pdf_name": out_name if converted else "",
            }
            self._write_upload_meta(folder, meta)
            return {
                "upload_id": upload_id,
                "name": out_name,
                "bytes": out_bytes,
                "next_index": index + 1,
                "complete": is_last,
                "converted_to_pdf": converted,
            }

        raise ValueError("Formato no soportado: suba PDF, ZIP o fotografía (JPG/PNG).")

    # ───────────────────────────── voice notes & quick package
    def _voice_notes_path(self, run_dir: Path) -> Path:
        return run_dir / "voice_notes.json"

    def _read_voice_notes(self, run_dir: Path) -> list[dict[str, Any]]:
        path = self._voice_notes_path(run_dir)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def add_voice_note(self, run_id: str, req: dict[str, Any], ctx: SecurityContext) -> dict[str, Any]:
        run_dir = self.app.runs.run_dir(run_id)
        state = self.app.runs._read(run_dir)
        transcript = str(req.get("transcript") or "").strip()
        if not transcript:
            raise ValueError("El dictado de voz está vacío.")
        kind = str(req.get("kind") or "adjustment_request").strip()
        if kind not in ("scope_note", "adjustment_request", "field_note"):
            kind = "field_note"
        entry = {
            "id": f"VN-{datetime.now():%Y%m%d%H%M%S%f}",
            "actor": ctx.actor,
            "role": ctx.role,
            "kind": kind,
            "transcript": transcript[:2000],
            "created_at": _now_iso(),
        }
        notes = self._read_voice_notes(run_dir)
        notes.append(entry)
        self._voice_notes_path(run_dir).write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")

        merged_notes = (state.get("notes") or "").strip()
        tag = "[Ajuste por voz]" if kind == "adjustment_request" else "[Nota de voz]"
        line = f"{tag} {ctx.actor}: {transcript[:500]}"
        state["notes"] = f"{merged_notes}\n{line}".strip() if merged_notes else line
        self.app.runs._write(run_dir, state)

        org_id = state.get("org_id", ctx.org_id or "default")
        self.app.v4._org_ledger(org_id).record(
            org_id=org_id,
            project_id=state["key"],
            actor=ctx.actor,
            role=ctx.role,
            action="VOICE_NOTE_RECORDED",
            state_from=state.get("canonical_state", ""),
            state_to=state.get("canonical_state", ""),
            resource_type="run",
            resource_id=run_id,
            detail={"kind": kind, "transcript": transcript[:300]},
        )
        return {"run_id": run_id, "voice_note": entry, "total_notes": len(notes)}

    def _build_roofing_starter_draft(self, key: str, county: str, docs: list[str]) -> dict[str, Any]:
        """Build a clearly labeled BUDGET starter draft for roofing using repo knowledge tables."""
        kdir = self.root / "src" / "bidkit" / "estimator_agent" / "knowledge"
        wages = _load_kb("wages.json", kdir)
        roofer = next(
            (w for w in wages if w.get("county", "").lower() == county.lower() and "roofer" in w.get("trade", "").lower()),
            next((w for w in wages if "roofer" in w.get("trade", "").lower()), None),
        )
        roofer_rate = str((roofer or {}).get("rate") or "78.50")
        roofer_src = str((roofer or {}).get("source") or f"L&I {county} County Roofer reference (verificar fecha)")
        return {
            "schema": PACKAGE_SCHEMA,
            "project": {
                "key": key,
                "short": f"{key} — Roofing Scope",
                "title": f"{key} — Commercial / Residential Roofing (DRAFT)",
                "owner": "Pending owner confirmation",
                "project_no": key,
                "site": f"{county} County, WA",
                "county": county,
                "prime_contractor": "to be confirmed at award",
                "bid_date": "Pending confirmation",
                "wage_basis": f"{county} County prevailing wage (L&I Roofer)",
                "scope_label": "roofing & flashing scope",
                "documents": docs or ["Field intake — pending plan takeoff"],
            },
            "labor_rates": {
                "RF": {
                    "label": "Roofer (prevailing wage)",
                    "kind": "prevailing_wage",
                    "trade": "roofer",
                    "rate": roofer_rate,
                    "burden_pct": "15",
                    "source": roofer_src,
                }
            },
            "materials": [
                {
                    "id": "M001",
                    "section": "A. Roofing membrane / shingles & accessories",
                    "item": "Roofing assembly & underlayment/fasteners allowance (ASSUMED starter)",
                    "spec": "Parametric BUDGET benchmark — replace with supplier quote & plan takeoff",
                    "qty": "10",
                    "unit": "SQ",
                    "unit_price": "245.00",
                    "price_basis": "BUDGET",
                    "price_source": "Puget Sound Nov 2026 BUDGET benchmark — verify with ABC Supply / Conway quote",
                    "qty_source": "ASSUMED field starter — replace with plan takeoff",
                    "supplier": "abc_supply",
                }
            ],
            "labor": [
                {"id": "L001", "task": "Field roofing installation & flashing (ASSUMED starter)", "rate": "RF", "hours": "24"},
                {"id": "L002", "task": "Submittals, L&I Intent/Affidavit & closeout", "rate": "ADMIN", "hours": "4"},
            ],
            "other": [
                {"id": "O001", "item": "Mobilization & disposal allowance", "category": "Mobilization", "qty": "1", "unit": "LS", "rate": "450.00"},
            ],
            "scope": [
                {"title": "Roofing starter scope (DRAFT)", "text": "Parametric roofing starter scope pending full plan takeoff and supplier quotes."}
            ],
            "exclusions": [
                "Structural roof deck replacement unless noted on confirmed plans.",
                "Permits, bond (1.5% if required), and WA retail sales tax per WAC 458-20-171.",
            ],
            "assumptions": ["Starter package generated for field scoping; replace BUDGET lines with supplier quotes."],
            "release": {
                "authorized": False,
                "allow_budget_prices": True,
                "note": "Field BUDGET draft pending supplier quotes and plan verification.",
            },
        }

    def _assemble_draft(self, req: dict[str, Any], ctx: SecurityContext) -> dict[str, Any]:
        """Assemble a pre-configured draft package from profile, specialties, voice notes, and P5/P6 overrides."""
        raw_key = str(req.get("key") or "FIELD").strip().upper()
        key = re.sub(r"[^A-Z0-9_-]+", "_", raw_key).strip("_")[:24] or "FIELD"
        if len(key) < 2:
            key = f"{key}_01"
        profile_name = str(req.get("profile") or "ss_custom_iron_works").strip()
        raw_specs = req.get("specialties")
        if isinstance(raw_specs, list) and raw_specs:
            specialty_ids = [str(s).strip().lower() for s in raw_specs if str(s).strip()]
        else:
            specialty_ids = [str(req.get("specialty") or "metal").strip().lower()]

        selected_specs = [
            next((s for s in SPECIALTIES if s["id"] == sid), None) for sid in specialty_ids
        ]
        selected_specs = [s for s in selected_specs if s is not None] or [SPECIALTIES[0]]
        primary_spec = selected_specs[0]

        county = str(req.get("county") or "King").strip() or "King"
        voice_transcript = str(req.get("voice_notes") or req.get("notes") or "").strip()
        project_title = str(req.get("project_title") or "").strip()
        upload_id = str(req.get("upload_id") or "").strip()

        docs_list: list[str] = []
        if upload_id:
            folder = self._upload_folder(upload_id)
            if folder.is_dir():
                docs_list = sorted(p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))

        # Load primary template and cleanly merge additional selected specialties (if mixed scope)
        def _load_spec_draft(spec_meta: dict[str, Any]) -> dict[str, Any]:
            tpl_rel = spec_meta.get("template")
            if tpl_rel and (self.root / tpl_rel).exists():
                return json.loads((self.root / tpl_rel).read_text(encoding="utf-8"))
            return self._build_roofing_starter_draft(key, county, docs_list)

        draft = _load_spec_draft(primary_spec)
        for extra_spec in selected_specs[1:]:
            extra = _load_spec_draft(extra_spec)
            for rk, rv in (extra.get("labor_rates") or {}).items():
                draft.setdefault("labor_rates", {}).setdefault(rk, rv)
            draft.setdefault("materials", []).extend(extra.get("materials") or [])
            draft.setdefault("labor", []).extend(extra.get("labor") or [])
            draft.setdefault("other", []).extend(extra.get("other") or [])
            draft.setdefault("scope", []).extend(extra.get("scope") or [])

        # Re-number IDs uniquely so multi-specialty packages never collide
        for prefix, rows in (
            ("M", draft.get("materials") or []),
            ("L", draft.get("labor") or []),
            ("O", draft.get("other") or []),
        ):
            for idx, row in enumerate(rows, 1):
                row["id"] = f"{prefix}{idx:03d}"

        # Apply user edits from P5 (Confirma cantidades & nuevas partidas)
        mat_list = draft.setdefault("materials", [])
        mat_by_id = {str(r.get("id")): r for r in mat_list}
        for item in (req.get("materials_overrides") or []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            mid = str(item.get("id")).strip()
            qty_raw = item.get("qty")
            if qty_raw in (None, ""):
                continue
            qty_val = str(qty_raw).strip()
            if Decimal(qty_val) <= 0:
                continue
            if mid in mat_by_id:
                row = mat_by_id[mid]
                row["qty"] = qty_val
                if item.get("item"):
                    row["item"] = str(item["item"]).strip()
                if item.get("unit"):
                    row["unit"] = str(item["unit"]).strip()
                if item.get("unit_price") not in (None, ""):
                    row["unit_price"] = str(item["unit_price"]).strip()
            else:
                new_mat = {
                    "id": mid,
                    "section": str(item.get("section") or "A. Field Additions").strip(),
                    "item": str(item.get("item") or f"Material {mid}").strip(),
                    "spec": str(item.get("spec") or "Added in field mobile P5").strip(),
                    "qty": qty_val,
                    "unit": str(item.get("unit") or "EA").strip(),
                    "unit_price": str(item.get("unit_price") or "0.00").strip(),
                    "price_basis": str(item.get("price_basis") or "BUDGET").strip().upper(),
                    "price_source": "Field mobile intake — verify with supplier quote",
                    "qty_source": "Field mobile P5 input",
                }
                mat_list.append(new_mat)
                mat_by_id[mid] = new_mat

        profile_obj = self.app.runs.load_profile(profile_name)
        valid_rate_keys = list((draft.get("labor_rates") or {}).keys()) + list((profile_obj.get("labor_rates") or {}).keys())
        fallback_rate = valid_rate_keys[0] if valid_rate_keys else "SHOP"

        lab_list = draft.setdefault("labor", [])
        lab_by_id = {str(r.get("id")): r for r in lab_list}
        for item in (req.get("labor_overrides") or []):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            lid = str(item.get("id")).strip()
            hrs_raw = item.get("hours")
            if hrs_raw in (None, ""):
                continue
            hrs_val = str(hrs_raw).strip()
            if Decimal(hrs_val) <= 0:
                continue
            if lid in lab_by_id:
                row = lab_by_id[lid]
                row["hours"] = hrs_val
                if item.get("task"):
                    row["task"] = str(item["task"]).strip()
            else:
                req_rate = str(item.get("rate") or fallback_rate).strip()
                if req_rate not in valid_rate_keys:
                    req_rate = fallback_rate
                new_lab = {
                    "id": lid,
                    "task": str(item.get("task") or f"Campo adicional {lid}").strip(),
                    "rate": req_rate,
                    "hours": hrs_val,
                }
                lab_list.append(new_lab)
                lab_by_id[lid] = new_lab

        spec_labels = ", ".join(s["label"] for s in selected_specs)
        draft["project"]["key"] = key
        draft["project"]["county"] = county
        client_name = str(req.get("client_name") or "").strip()
        if client_name:
            draft["project"]["prime_contractor"] = client_name[:120]
            draft["project"]["owner"] = client_name[:120]
        if project_title:
            draft["project"]["short"] = project_title[:80]
            draft["project"]["title"] = f"{project_title[:120]} — {spec_labels}"
        if docs_list:
            draft["project"]["documents"] = docs_list + list(draft["project"].get("documents") or [])[:2]
        if voice_transcript:
            draft.setdefault("scope", []).insert(
                0,
                {"title": "Field scope dictated by contractor", "text": voice_transcript[:1500]},
            )
            draft.setdefault("assumptions", []).append(f"Nota de campo por voz ({ctx.actor}): {voice_transcript[:500]}")

        draft["release"] = {
            "authorized": False,
            "allow_budget_prices": True,
            "note": f"DRAFT de campo ({spec_labels}, {county} Co.) — pendiente revisión humana y cotizaciones reales.",
        }

        if not profile_obj.get("scope_policy"):
            profile_obj["scope_policy"] = [s["trade_scope"] for s in selected_specs]

        pkg, prep_report = contrato.preparar(draft, profile_name, self.app.runs.profiles_dir())
        pkg.pop("subcontract_package", None)

        # Apply optional P6 markup / validity overrides after profile merge
        mk_override = req.get("markups")
        if isinstance(mk_override, dict):
            mk = dict(pkg.get("markups") or {})
            for fld in ("contingency_pct", "overhead_pct", "profit_pct", "rounding"):
                if mk_override.get(fld) not in (None, ""):
                    mk[fld] = str(mk_override[fld]).strip()
            pkg["markups"] = mk
        if req.get("validity_days") not in (None, ""):
            pkg["validity_days"] = max(1, int(req["validity_days"]))

        return {
            "key": key,
            "profile_name": profile_name,
            "profile_obj": profile_obj,
            "selected_specs": selected_specs,
            "spec_labels": spec_labels,
            "county": county,
            "voice_transcript": voice_transcript,
            "docs_list": docs_list,
            "pkg": pkg,
            "prep_report": prep_report,
        }

    def preview_draft(self, req: dict[str, Any], ctx: SecurityContext) -> dict[str, Any]:
        """Return pre-filled materials, labor, exclusions and defaults for P5/P6 mobile review."""
        require_permission(ctx, "estimate:create", org_id=ctx.org_id)
        assembled = self._assemble_draft(req, ctx)
        pkg = assembled["pkg"]
        prep_report = assembled["prep_report"]
        county = assembled["county"]
        county_verified = county in VERIFIED_WAGE_COUNTIES
        voice_transcript = assembled["voice_transcript"]
        detected = self._extract_voice_signals(voice_transcript)
        calibration = self.compute_profile_calibration(assembled["profile_name"], ctx.org_id)
        return {
            "key": assembled["key"],
            "estimate_id": pkg.get("estimate_id", ""),
            "contractor": (pkg.get("contractor") or {}).get("name", ""),
            "county": county,
            "county_wage_verified": county_verified,
            "county_wage_warning": (
                None
                if county_verified
                else f"En wages.json solo King y Snohomish tienen tasas L&I verificadas. Para {county} County se usa referencia preliminar; verifica en L&I antes de ofertar."
            ),
            "specialties": [s["id"] for s in assembled["selected_specs"]],
            "detected": detected,
            "calibration": calibration,
            "exclusions": pkg.get("exclusions") or [],
            "scope": pkg.get("scope") or [],
            "materials": [
                {
                    "id": m.get("id", ""),
                    "section": m.get("section", ""),
                    "item": m.get("item", ""),
                    "qty": str(m.get("qty", "1")),
                    "unit": m.get("unit", "EA"),
                    "unit_price": str(m.get("unit_price", "0.00")),
                    "price_basis": str(m.get("price_basis", "BUDGET")).upper(),
                }
                for m in (pkg.get("materials") or [])
            ],
            "labor": [
                {
                    "id": l.get("id", ""),
                    "task": l.get("task", ""),
                    "rate": l.get("rate", ""),
                    "hours": str(l.get("hours", "1")),
                }
                for l in (pkg.get("labor") or [])
            ],
            "markups": pkg.get("markups") or {},
            "validity_days": pkg.get("validity_days", 30),
            "fuera_de_alcance": prep_report.get("fuera_de_alcance") or [],
            "faltan_datos": prep_report.get("faltan_datos") or [],
        }

    def _extract_voice_signals(self, text: str) -> dict[str, Any]:
        """Extract explicit county or specialty mentions from contractor voice/text input without inventing quantities."""
        low = (text or "").lower()
        found_county = None
        for c in WA_COUNTIES:
            if re.search(rf"\b{re.escape(c.lower())}\b", low):
                found_county = c
                break
        kw_map = (
            ("metal", ("metal", "acero", "steel", "baranda", "handrail", "cerca", "fence", "porton", "gate", "herreria", "soldadura")),
            ("techado", ("techado", "techo", "roof", "roofing", "tpo", "shingle", "flashing")),
            ("tablaroca", ("tablaroca", "drywall", "sheetrock", "gypsum", "yeso", "framing", "muro")),
            ("pintura", ("pintura", "pintar", "paint", "coating", "recubrimiento", "primer")),
            ("molduras", ("moldura", "carpinter", "millwork", "casework", "trim", "puerta", "zoclo")),
            ("cubiertas", ("cubierta", "granito", "cuarzo", "quartz", "granite", "countertop", "piedra")),
        )
        found_specs: list[str] = []
        for sid, words in kw_map:
            if any(w in low for w in words):
                found_specs.append(sid)
        return {"county": found_county, "specialties": found_specs}

    def compute_profile_calibration(self, profile_name: str, org_id: str = "default") -> dict[str, Any]:
        """Compute genuine 0-100% profile readiness across 5 real checks (20% each) using contrato.missing_data."""
        profiles_dir = self.app.runs.profiles_dir()
        prof = self.app.runs.load_profile(profile_name)
        missing = contrato.missing_data(prof)
        is_generic = bool(prof.get("generic"))
        company_ok = (not is_generic) and len(missing) == 0

        logo_path = contrato.find_logo(profile_name, prof, profiles_dir)
        has_logo = bool(logo_path and logo_path.exists())

        rates = prof.get("labor_rates") or {}
        rates_ok = bool(rates) and any(
            str((v or {}).get("rate", "")).strip() not in ("", "0", "0.00")
            for v in rates.values()
        )

        mk = prof.get("markups") or {}
        markups_ok = all(
            str(mk.get(k, "")).strip() != ""
            for k in ("contingency_pct", "overhead_pct", "profit_pct")
        )

        org_quotes = [
            r for r in self.app.v4.pricebook.list_records(org_id or "default")
            if str(r.get("price_type") or r.get("price_basis") or "").upper() == "QUOTE"
        ]
        kb_quotes = [
            p for p in self.app._table("price_book")
            if str(p.get("price_basis", "")).upper() == "QUOTE"
        ]
        quote_count = len(org_quotes) + len(kb_quotes)
        quotes_ok = quote_count > 0

        modules = [
            {
                "id": "A",
                "key": "empresa",
                "label": "Empresa y Licencia WA",
                "weight": 20,
                "complete": company_ok,
                "detail": "Completo" if company_ok else ("Perfil genérico" if is_generic else f"Falta: {', '.join(missing)}"),
            },
            {
                "id": "B",
                "key": "logo",
                "label": "Identidad y Logo",
                "weight": 20,
                "complete": has_logo,
                "detail": "Logo cargado" if has_logo else "Sin logo PNG/JPG",
            },
            {
                "id": "E",
                "key": "tarifas",
                "label": "Tarifas (Taller / Oficina)",
                "weight": 20,
                "complete": rates_ok,
                "detail": f"{len(rates)} tarifa(s)" if rates_ok else "Sin tarifas configuradas",
            },
            {
                "id": "F",
                "key": "markups",
                "label": "Markups y Vigencia",
                "weight": 20,
                "complete": markups_ok,
                "detail": (
                    f"{mk.get('contingency_pct', '0')}/{mk.get('overhead_pct', '0')}/{mk.get('profit_pct', '0')}%"
                    if markups_ok
                    else "Falta configurar márgenes"
                ),
            },
            {
                "id": "G",
                "key": "proveedores",
                "label": "Cotizaciones Proveedores",
                "weight": 20,
                "complete": quotes_ok,
                "detail": f"{quote_count} QUOTE en libro" if quotes_ok else "Solo precios BUDGET",
            },
        ]
        pct = sum(m["weight"] for m in modules if m["complete"])
        return {
            "profile": profile_name,
            "contractor": (prof.get("contractor") or {}).get("name", ""),
            "percent": pct,
            "missing_data": missing,
            "has_logo": has_logo,
            "quote_count": quote_count,
            "next_pending_module": next((m["id"] for m in modules if not m["complete"]), None),
            "modules": modules,
        }

    def list_mobile_profiles(self, org_id: str = "default") -> dict[str, Any]:
        """Return profiles enriched with live calibration percent and missing_data."""
        base_rows = self.app.profiles()["profiles"]
        enriched = []
        for row in base_rows:
            cal = self.compute_profile_calibration(row["name"], org_id=org_id)
            enriched.append({
                **row,
                "calibration_pct": cal["percent"],
                "missing_data": cal["missing_data"],
                "next_pending_module": cal["next_pending_module"],
            })
        return {"profiles": enriched}

    def quick_package(self, req: dict[str, Any], ctx: SecurityContext) -> dict[str, Any]:
        """Generate a real verified 3-PDF DRAFT run synchronously from profile + specialty + voice notes + P5/P6 edits."""
        require_permission(ctx, "estimate:create", org_id=ctx.org_id)
        assembled = self._assemble_draft(req, ctx)
        key = assembled["key"]
        profile_name = assembled["profile_name"]
        profile_obj = assembled["profile_obj"]
        selected_specs = assembled["selected_specs"]
        spec_labels = assembled["spec_labels"]
        county = assembled["county"]
        voice_transcript = assembled["voice_transcript"]
        docs_list = assembled["docs_list"]
        pkg = assembled["pkg"]
        prep_report = assembled["prep_report"]

        run_id = f"{key}_{datetime.now():%Y%m%d_%H%M%S}"
        run_dir = self.app.runs.base / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        pkg_path = run_dir / f"{key.lower()}.json"
        pkg_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest = build_package(pkg_path, run_dir)
        crit = review_criterio(pkg)
        write_criterio_report(crit, run_dir, key.lower())

        report_md = run_dir / f"{key}_REPORTE_AGENTE.md"
        totals = manifest["computation"]["totals"]
        unquoted = manifest["computation"]["validation"].get("unquoted_lines") or []
        report_lines = [
            f"# Reporte de Paquete Preliminar — {key}",
            "",
            f"- **Contratista:** {pkg['contractor']['name']}",
            f"- **Especialidad:** {spec_labels} | **Condado:** {county}",
            f"- **Estado de entrega:** {manifest['proposal_release']['label']}",
            f"- **Precio de venta (DRAFT):** ${totals['price']}",
            f"- **Costo directo:** ${totals['direct']}",
            f"- **Verificación cruzada QA:** {manifest['qa']['status']}",
            f"- **Partidas sin cotización (BUDGET/CATALOG):** {len(unquoted)}",
        ]
        if voice_transcript:
            report_lines.extend(["", "## Notas de voz capturadas en campo", f"- {voice_transcript}"])
        if prep_report.get("faltan_datos"):
            report_lines.extend(["", "## Datos faltantes del perfil", f"- {', '.join(prep_report['faltan_datos'])}"])
        if crit.get("findings"):
            report_lines.extend(["", "## Alertas de criterio"])
            for fnd in crit["findings"][:8]:
                report_lines.append(f"- [{fnd['level']}] {fnd['message']}")
        report_md.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
        delivery.report_pdf(report_md)

        state = {
            "id": run_id,
            "key": key,
            "org_id": ctx.org_id,
            "status": "lista" if manifest["qa"]["status"] == "PASS" else "incompleta",
            "stage": "Entrega lista para revisión" if manifest["qa"]["status"] == "PASS" else "QA requiere revisión",
            "turn": 1,
            "max_turns": 1,
            "tokens": 0,
            "budget_tokens": 0,
            "actor": ctx.actor,
            "profile": profile_name,
            "contractor": pkg["contractor"]["name"],
            "generic": bool(profile_obj.get("generic")),
            "docs": ", ".join(docs_list) if docs_list else f"Plantilla base {spec_labels}",
            "notes": voice_transcript[:2000],
            "trade_scope": ", ".join(s["trade_scope"] for s in selected_specs),
            "county": county,
            "specialty": ",".join(s["id"] for s in selected_specs),
            "model": "quick-package-engine",
            "started_at": _now_iso(),
            "finished_at": _now_iso(),
            "decision": "GO" if not prep_report.get("fuera_de_alcance") else "REVIEW",
            "price": totals["price"],
            "direct": totals["direct"],
            "qa": manifest["qa"]["status"],
            "proposal": manifest["proposal_release"]["label"],
            "error": None,
            "authorized_by": None,
            "source_run": None,
        }
        self.app.runs._write(run_dir, state)
        delivery.make_zip(run_dir, key, package_json=True, log=False)

        if voice_transcript:
            self.add_voice_note(run_id, {"transcript": voice_transcript, "kind": "scope_note"}, ctx)

        self.app.v4._org_ledger(ctx.org_id).record(
            org_id=ctx.org_id,
            project_id=key,
            actor=ctx.actor,
            role=ctx.role,
            action="QUICK_PACKAGE_BUILT",
            state_from="Draft",
            state_to="Review Required",
            resource_type="run",
            resource_id=run_id,
            detail={"specialty": state["specialty"], "county": county, "price": totals["price"]},
        )
        return self.run_summary(run_id)

    # ───────────────────────────── executive summary & cards
    def _manifest_for_run(self, run_dir: Path, key: str) -> dict[str, Any] | None:
        mp = run_dir / f"{key}_package_manifest.json"
        if not mp.exists():
            return None
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _package_json_for_run(self, run_dir: Path, key: str) -> dict[str, Any] | None:
        pp = run_dir / f"{key.lower()}.json"
        if not pp.exists():
            return None
        try:
            return json.loads(pp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list_mobile_runs(self) -> dict[str, Any]:
        runs = self.app.runs.list()
        cards = []
        for state in runs:
            run_id = state["id"]
            run_dir = self.app.runs.run_dir(run_id)
            manifest = self._manifest_for_run(run_dir, state["key"])
            comp = (manifest or {}).get("computation") or {}
            mats = comp.get("materials") or []
            budget_count = sum(1 for m in mats if str(m.get("price_basis", "")).upper() == "BUDGET")
            catalog_count = sum(1 for m in mats if str(m.get("price_basis", "")).upper() == "CATALOG")
            quote_count = sum(1 for m in mats if str(m.get("price_basis", "")).upper() == "QUOTE")
            badge_status, badge_label = _status_badge(state)
            prog = _compute_progress(state)
            is_approved = str(state.get("status") or "").lower() in ("autorizada", "exportada")
            cards.append({
                "id": run_id,
                "key": state["key"],
                "contractor": state.get("contractor", ""),
                "profile": state.get("profile", ""),
                "specialty": state.get("specialty", ""),
                "county": state.get("county", ""),
                "status": state.get("status", ""),
                "canonical_state": state.get("canonical_state", ""),
                "badge_status": badge_status,
                "badge_label": badge_label,
                "stage": state.get("stage", ""),
                "price": state.get("price"),
                "direct": state.get("direct"),
                "decision": state.get("decision"),
                "qa": state.get("qa"),
                "actor": state.get("actor", ""),
                "authorized_by": state.get("authorized_by"),
                "started_at": state.get("started_at"),
                "finished_at": state.get("finished_at"),
                "budget_count": budget_count,
                "catalog_count": catalog_count,
                "quote_count": quote_count,
                "voice_notes_count": len(self._read_voice_notes(run_dir)),
                "client_share_unlocked": bool(is_approved and state.get("qa") == "PASS"),
                "progress_pct": prog["percent"],
            })
        return {"runs": cards, "active": self.app.runs.active()}

    def run_summary(self, run_id: str) -> dict[str, Any]:
        run_data = self.app.runs.get(run_id)
        run_dir = self.app.runs.run_dir(run_id)
        key = run_data["key"]
        manifest = self._manifest_for_run(run_dir, key)
        pkg_raw = self._package_json_for_run(run_dir, key)

        comp = (manifest or {}).get("computation") or {}
        totals = comp.get("totals") or {}
        mats = comp.get("materials") or []

        quote_lines = [m for m in mats if str(m.get("price_basis", "")).upper() == "QUOTE"]
        catalog_lines = [m for m in mats if str(m.get("price_basis", "")).upper() == "CATALOG"]
        budget_lines = [m for m in mats if str(m.get("price_basis", "")).upper() == "BUDGET"]

        sell_price = totals.get("price") or run_data.get("price")
        direct_cost = totals.get("direct") or run_data.get("direct")
        gross_margin = totals.get("gross_margin")

        raw_status = str(run_data.get("status") or "").lower()
        is_approved = raw_status in ("autorizada", "exportada")
        is_rejected = raw_status in ("rechazada", "no-go") or str(run_data.get("decision") or "").upper() == "NO_GO"
        qa_pass = run_data.get("qa") == "PASS"
        client_share_unlocked = bool(is_approved and qa_pass)

        badge_status, badge_label = _status_badge(run_data)
        progress = _compute_progress(run_data)

        doc_specs = (
            ("cost_analysis", "01 Cost Analysis", "Uso interno · costos, márgenes, L&I y alertas", f"{key}_01_COST_ANALYSIS.pdf", True),
            ("material_list", "02 Material List", "Compras · cantidades, fuentes y precios BUDGET", f"{key}_02_MATERIAL_LIST.pdf", True),
            ("proposal", "03 Estimate / Proposal", "Cliente / GC · precio único, alcance y términos", f"{key}_03_ESTIMATE_PROPOSAL.pdf", False),
        )
        documents = []
        for doc_type, title, subtitle, fname, internal_only in doc_specs:
            fpath = run_dir / fname
            documents.append({
                "doc_type": doc_type,
                "title": title,
                "subtitle": subtitle,
                "filename": fname,
                "internal_only": internal_only,
                "is_draft": not is_approved,
                "share_to_client_allowed": (not internal_only) and client_share_unlocked,
                "exists": fpath.is_file(),
                "bytes": fpath.stat().st_size if fpath.is_file() else 0,
            })

        return {
            "run": {
                "id": run_id,
                "key": key,
                "status": run_data.get("status"),
                "canonical_state": run_data.get("canonical_state"),
                "badge_status": badge_status,
                "badge_label": badge_label,
                "stage": run_data.get("stage"),
                "actor": run_data.get("actor"),
                "profile": run_data.get("profile"),
                "contractor": run_data.get("contractor"),
                "specialty": run_data.get("specialty", ""),
                "county": run_data.get("county") or ((pkg_raw or {}).get("project") or {}).get("county", ""),
                "docs": run_data.get("docs"),
                "documents_count": run_data.get("documents", 0),
                "pages_count": run_data.get("pages", 0),
                "notes": run_data.get("notes", ""),
                "decision": run_data.get("decision") or "GO",
                "qa": run_data.get("qa"),
                "proposal": run_data.get("proposal"),
                "authorized_by": run_data.get("authorized_by"),
                "authorized_at": run_data.get("authorized_at"),
                "rejected_by": run_data.get("rejected_by"),
                "rejection_reason": run_data.get("rejection_reason"),
                "started_at": run_data.get("started_at"),
                "finished_at": run_data.get("finished_at"),
                "error": run_data.get("error"),
            },
            "progress": progress,
            "events": run_data.get("events") or [],
            "financials": {
                "estimate_id": comp.get("estimate_id") or (pkg_raw or {}).get("estimate_id", ""),
                "sell_price": sell_price,
                "direct_cost": direct_cost,
                "materials_total": totals.get("materials"),
                "labor_total": totals.get("labor"),
                "other_total": totals.get("other"),
                "contingency": totals.get("contingency"),
                "overhead": totals.get("overhead"),
                "profit": totals.get("profit"),
                "total": totals.get("total"),
                "break_even": totals.get("break_even"),
                "gross_margin": gross_margin,
                "pricing_alerts": {
                    "quote_count": len(quote_lines),
                    "catalog_count": len(catalog_lines),
                    "budget_count": len(budget_lines),
                    "total_lines": len(mats),
                    "budget_items": [
                        {"id": m.get("id"), "item": m.get("item"), "extended": m.get("extended")}
                        for m in budget_lines[:15]
                    ],
                    "warnings": ((comp.get("validation") or {}).get("warnings") or [])[:10],
                },
            },
            "human_lock": {
                "is_approved": is_approved,
                "is_rejected_or_nogo": is_rejected,
                "prepared_by": run_data.get("actor", ""),
                "authorized_by": run_data.get("authorized_by"),
                "authorized_at": run_data.get("authorized_at"),
                "client_share_unlocked": client_share_unlocked,
                "requires_independent_reviewer": True,
                "lock_message": (
                    f"Autorizado por {run_data.get('authorized_by')}. Listo para compartir propuesta 03 al cliente."
                    if client_share_unlocked
                    else "BORRADOR (DRAFT): bloqueado para envío externo hasta aprobación humana independiente."
                ),
            },
            "documents": documents,
            "voice_notes": self._read_voice_notes(run_dir),
            "report_md": run_data.get("report_md", ""),
        }

    def import_mobile_quote(self, req: dict[str, Any], ctx: SecurityContext) -> dict[str, Any]:
        """Import CSV/XLSX/PDF quote or archive photo of a supplier quote."""
        require_permission(ctx, "pricebook:import", org_id=ctx.org_id)
        file_name = sanitize_filename(str(req.get("file_name") or "quote.pdf"), fallback="quote.pdf")
        ext = Path(file_name).suffix.lower()
        raw = base64.b64decode(str(req.get("content_b64") or ""), validate=True)
        supplier = str(req.get("supplier") or "Proveedor").strip()
        if ext in QUOTE_IMPORT_SUFFIXES:
            res = self.app.v4.pricebook.import_quote_file(
                org_id=ctx.org_id,
                file_name=file_name,
                raw_bytes=raw,
                supplier=supplier,
                city=str(req.get("city") or ""),
                state=str(req.get("state") or "WA"),
                quoted_date=str(req.get("quoted_date") or ""),
                valid_until=str(req.get("valid_until") or ""),
                ctx=ctx,
            )
            return {**res, "ocr_required": res.get("imported_count", 0) == 0}

        if ext in IMAGE_SUFFIXES:
            from PIL import Image

            pdf_buf = io.BytesIO()
            with Image.open(io.BytesIO(raw)) as im:
                im.convert("RGB").save(pdf_buf, "PDF", resolution=150.0)
            dest_dir = self.root / "data" / "orgs" / sanitize_filename(ctx.org_id) / "pricebook" / "originals"
            dest_dir.mkdir(parents=True, exist_ok=True)
            img_dest = dest_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{file_name}"
            img_dest.write_bytes(raw)
            pdf_name = f"{Path(file_name).stem}.pdf"
            res = self.app.v4.pricebook.import_quote_file(
                org_id=ctx.org_id,
                file_name=pdf_name,
                raw_bytes=pdf_buf.getvalue(),
                supplier=supplier,
                city=str(req.get("city") or ""),
                state=str(req.get("state") or "WA"),
                quoted_date=str(req.get("quoted_date") or ""),
                valid_until=str(req.get("valid_until") or ""),
                ctx=ctx,
            )
            return {
                **res,
                "archived_image": str(img_dest),
                "ocr_required": True,
                "note": "Foto archivada como PDF en el expediente de cotizaciones; capture renglones numéricos si el PDF es imagen.",
            }
        raise ValueError(f"Formato de cotización no soportado: {ext}")

    def quick_register_profile(self, req: dict[str, Any], ctx: SecurityContext) -> dict[str, Any]:
        """Quickly register a new contractor/client profile from the mobile app without modifying built-in profiles."""
        require_permission(ctx, "estimate:edit", org_id=ctx.org_id)
        contractor_name = str(req.get("contractor_name") or req.get("name") or "").strip()
        if not contractor_name:
            raise ValueError("Ingresa el nombre del cliente o contratista.")
        base_slug = re.sub(r"[^a-z0-9]+", "_", contractor_name.lower()).strip("_")[:50] or "cliente"
        slug = base_slug
        profiles_dir = self.app.runs.profiles_dir()
        if (profiles_dir / f"{slug}.json").exists():
            slug = f"{base_slug[:40]}_{datetime.now():%m%d%H%M%S}"
        prefix_letters = re.sub(r"[^A-Z0-9]", "", contractor_name.upper())[:4] or "ALK"
        specialty_txt = str(req.get("specialty") or "General subcontracting & field construction").strip()
        profile_dict = {
            "profile": contractor_name,
            "estimate_prefix": f"{prefix_letters}-EST-2026",
            "date": "AUTO",
            "contractor": {
                "name": contractor_name,
                "address": str(req.get("address") or "Washington State").strip(),
                "license": str(req.get("license") or "Pendiente verificar L&I").strip(),
                "phone": str(req.get("phone") or "Pendiente").strip(),
                "contact": str(req.get("contact") or contractor_name).strip(),
            },
            "relationship": "sub_to_gc",
            "tier": "competitive",
            "labor_rates": {
                "SHOP": {"label": "Shop / Taller", "kind": "loaded", "rate": "65.00"},
                "ADMIN": {"label": "PM / Oficina", "kind": "loaded", "rate": "75.00"},
            },
            "burden_pct": "15",
            "markups": {
                "contingency_pct": "5",
                "overhead_pct": "10",
                "profit_pct": "10",
                "rounding": "50",
            },
            "validity_days": 30,
            "scope_policy": [specialty_txt],
            "exclusiones_base": [
                "Permits, performance/payment bonds, and Washington State retail sales tax unless stated.",
                "Work outside confirmed trade scope or undocumented site conditions.",
            ],
            "supuestos_base": [
                "Pricing reflects base scope; alternates excluded unless listed.",
            ],
        }
        saved = self.app.save_profile(slug, profile_dict)
        self.app.v4._org_ledger(ctx.org_id).record(
            org_id=ctx.org_id,
            project_id="PROFILES",
            actor=ctx.actor,
            role=ctx.role,
            action="PROFILE_REGISTERED",
            state_from="",
            state_to="Active",
            resource_type="profile",
            resource_id=slug,
            detail={"contractor": contractor_name},
        )
        return {"profile": saved, "profiles": self.app.profiles()["profiles"]}

    # ───────────────────────────── request dispatcher
    def dispatch(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        q = query or {}
        req = body or {}
        hdrs = self._auth_headers(headers)
        one = lambda k, default="": (q.get(k) or [default])[0]

        if method == "OPTIONS":
            return 204, b""

        # Public endpoints
        if method == "GET" and path in PUBLIC_GET_PATHS:
            key_info = self.app.settings.secret_view("anthropic")
            return 200, {
                "status": "ok",
                "service": "alkan-bid-engine-mobile-api",
                "version": MOBILE_API_VERSION,
                "fastapi": FASTAPI_AVAILABLE,
                "specialties": list(SPECIALTIES),
                "counties": list(WA_COUNTIES),
                "verified_wage_counties": list(VERIFIED_WAGE_COUNTIES),
                "has_anthropic_key": bool(key_info.get("configured")),
                "anthropic_base_url": os.environ.get("ANTHROPIC_BASE_URL") or "https://apikey.vnaipro.app/v1",
                "model": self.app.settings.load()["engine"]["model"],
                "active_run": self.app.runs.active(),
            }

        if method == "POST" and path == "/api/mobile/auth/bootstrap":
            return 200, self.bootstrap_auth(req)

        if method == "POST" and path == "/api/mobile/auth/change-password":
            return 200, self.change_password_mobile(req)

        if method == "POST" and path == "/api/v4/auth/login":
            res = self.app.v4.post(path, req, str(req.get("username") or "login"), headers=hdrs)
            return 200, res

        # Authenticated endpoints
        ctx = self.authenticate(hdrs)

        if method == "GET":
            if path == "/api/mobile/auth/users":
                require_permission(ctx, "admin:users", org_id=ctx.org_id)
                return 200, {"users": self.app.v4.auth.list_users(ctx.org_id)}

            if path == "/api/mobile/runs":
                return 200, self.list_mobile_runs()

            if path == "/api/mobile/profiles":
                return 200, self.list_mobile_profiles(one("org_id") or ctx.org_id)

            if path == "/api/mobile/calibration":
                prof_name = one("profile")
                if not prof_name:
                    profs = self.app.profiles()["profiles"]
                    prof_name = profs[0]["name"] if profs else "ss_custom_iron_works"
                return 200, self.compute_profile_calibration(prof_name, one("org_id") or ctx.org_id)

            if path == "/api/mobile/upload/status":
                return 200, self.upload_status(one("upload_id"))

            m_sum = re.fullmatch(r"/api/mobile/runs/([^/]+)/summary", path)
            if m_sum:
                return 200, self.run_summary(m_sum.group(1))

            m_logo = re.fullmatch(r"/api/mobile/profiles/([^/]+)/logo", path)
            if m_logo:
                found = _find_logo_bytes(self.app, m_logo.group(1))
                if not found:
                    return 404, {"error": "Logo no configurado para este perfil"}
                return 200, BinaryResponse(found[0], found[1])

            if path.startswith("/api/app/") or path.startswith("/api/v4/"):
                result = self.app.get(path, q, hdrs)
                if isinstance(result, Download):
                    return 200, BinaryResponse(
                        result.path.read_bytes(),
                        result.kind,
                        filename=result.path.name if one("download") else None,
                    )
                if result is not None:
                    return 200, result

            return 404, {"error": f"Ruta no encontrada: {path}"}

        if method == "POST":
            if path == "/api/mobile/auth/users":
                require_permission(ctx, "admin:users", org_id=ctx.org_id)
                user_role = str(req.get("user_role") or req.get("role") or "estimator").strip()
                must_change = bool(req.get("must_change_password", True))
                created = self.app.v4.auth.create_user(
                    str(req.get("username") or ""),
                    str(req.get("password") or ""),
                    role=user_role,
                    org_id=ctx.org_id,
                    client_id=req.get("client_id"),
                    must_change_password=must_change,
                )
                self.app.v4._org_ledger(ctx.org_id).record(
                    org_id=ctx.org_id,
                    project_id="AUTH",
                    actor=ctx.actor,
                    role=ctx.role,
                    action="USER_CREATED",
                    state_from="",
                    state_to="Active",
                    resource_type="user",
                    resource_id=created["username"],
                    detail={"role": user_role, "must_change_password": must_change},
                )
                return 200, created

            if path == "/api/mobile/upload/chunk":
                require_permission(ctx, "estimate:create", org_id=ctx.org_id)
                return 200, self.upload_chunk(req)

            if path == "/api/mobile/runs/preview-draft":
                return 200, self.preview_draft(req, ctx)

            if path == "/api/mobile/runs/quick-package":
                return 200, self.quick_package(req, ctx)

            m_vn = re.fullmatch(r"/api/mobile/runs/([^/]+)/voice-note", path)
            if m_vn:
                return 200, self.add_voice_note(m_vn.group(1), req, ctx)

            if path == "/api/mobile/pricebook/import-file":
                return 200, self.import_mobile_quote(req, ctx)

            if path == "/api/mobile/profiles/register":
                return 200, self.quick_register_profile(req, ctx)

            if path == "/api/app/run/authorize":
                # Enforce strict separation of duties even through legacy /api/app/run/authorize
                require_permission(ctx, "estimate:approve", org_id=ctx.org_id)
                return 200, self.app.runs.authorize(req["id"], ctx.actor, req.get("note", ""), strict_separation=True)

            if path == "/api/app/run/start":
                require_permission(ctx, "estimate:create", org_id=ctx.org_id)

            if path == "/api/app/profile/save":
                require_permission(ctx, "estimate:edit", org_id=ctx.org_id)

            if path.startswith("/api/app/") or path.startswith("/api/v4/"):
                result = self.app.post(path, req, ctx.actor, hdrs)
                if result is not None:
                    return 200, result

            return 404, {"error": f"Ruta no encontrada: {path}"}

        return 405, {"error": f"Método no soportado: {method}"}

    def handle_safe(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]] | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        """Dispatch request converting domain/security exceptions to clean HTTP codes."""
        try:
            return self.dispatch(method, path, query, body, headers)
        except AuthenticationError as exc:
            return 401, {"error": str(exc)}
        except (SelfApprovalError, AuthorizationError, SecurityError, PermissionError) as exc:
            return 403, {"error": str(exc)}
        except RateLimitError as exc:
            return 429, {"error": str(exc)}
        except (ImmutableVersionError, InvalidStateTransitionError) as exc:
            return 409, {"error": str(exc)}
        except (PriceGovernanceError, UnAuthorizedOutboundError, ValueError, KeyError) as exc:
            return 400, {"error": str(exc)}
        except FileNotFoundError as exc:
            return 404, {"error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive boundary
            return 500, {"error": f"{type(exc).__name__}: {exc}"}


def _cors_headers() -> dict[str, str]:
    origins = os.environ.get("ALKAN_CORS_ORIGINS", "*")
    return {
        "Access-Control-Allow-Origin": origins,
        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-ALKAN-API-Key, X-ALKAN-Actor",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }


def create_fastapi_app(api: MobileBidEngineAPI | None = None):
    """Build FastAPI ASGI application for Render / Railway / Uvicorn deployments."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI no está instalado; use `pip install fastapi uvicorn` o run_http_server().")
    gateway = api or MobileBidEngineAPI()
    fapp = FastAPI(title="ALKAN Bid Engine Mobile API", version=MOBILE_API_VERSION)
    origins = [o.strip() for o in os.environ.get("ALKAN_CORS_ORIGINS", "*").split(",") if o.strip()]
    fapp.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @fapp.api_route("/{full_path:path}", methods=["GET", "POST", "OPTIONS"])
    async def _catch_all(full_path: str, request: Request):
        path = "/" + full_path.lstrip("/")
        query = {k: request.query_params.getlist(k) for k in request.query_params.keys()}
        body: dict[str, Any] = {}
        if request.method == "POST":
            raw = await request.body()
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except ValueError:
                    return JSONResponse({"error": "JSON inválido"}, status_code=400)
        status, payload = gateway.handle_safe(request.method, path, query, body, dict(request.headers))
        if isinstance(payload, BinaryResponse):
            hdrs = {}
            if payload.filename:
                hdrs["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(payload.filename)
            return Response(content=payload.data, status_code=status, media_type=payload.media_type, headers=hdrs)
        if status == 204:
            return Response(status_code=204)
        return JSONResponse(payload, status_code=status)

    return fapp


if FASTAPI_AVAILABLE:
    app = create_fastapi_app()


def run_http_server(root: Path | None = None, host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run Mobile API using FastAPI/Uvicorn when available or ThreadingHTTPServer fallback."""
    gateway = MobileBidEngineAPI(root)
    if FASTAPI_AVAILABLE:
        try:
            import uvicorn

            uvicorn.run(create_fastapi_app(gateway), host=host, port=port)
            return
        except ImportError:
            pass

    class MobileHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _write(self, status: int, payload: Any) -> None:
            cors = _cors_headers()
            if isinstance(payload, BinaryResponse):
                data = payload.data
                ctype = payload.media_type
            elif isinstance(payload, bytes):
                data = payload
                ctype = "application/octet-stream"
            else:
                data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
                ctype = "application/json; charset=utf-8"

            self.send_response(status)
            for k, v in cors.items():
                self.send_header(k, v)
            if isinstance(payload, BinaryResponse) and payload.filename:
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(payload.filename))
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def do_OPTIONS(self) -> None:
            self._write(204, b"")

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            status, payload = gateway.handle_safe("GET", url.path, parse_qs(url.query), {}, dict(self.headers))
            self._write(status, payload)

        def do_POST(self) -> None:
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length > 0 else b""
            body: dict[str, Any] = {}
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except ValueError:
                    self._write(400, {"error": "JSON inválido"})
                    return
            status, payload = gateway.handle_safe("POST", url.path, parse_qs(url.query), body, dict(self.headers))
            self._write(status, payload)

    server = ThreadingHTTPServer((host, port), MobileHandler)
    print(f"ALKAN Bid Engine Mobile API escuchando en http://{host}:{port} (root={gateway.root})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bidkit-mobile-api", description="ALKAN Bid Engine Mobile API server")
    parser.add_argument("--root", type=Path, default=None, help="Project root directory (defaults to BIDKIT_ROOT)")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    run_http_server(args.root, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
