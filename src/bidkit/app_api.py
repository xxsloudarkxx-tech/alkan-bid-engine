"""HTTP API of the unified app (``/api/app/*``): status, admin, profiles, knowledge and runs.

Mounted by ``intelligence_ui`` next to the dossier API; same loopback, origin
and session-token checks apply there.  Returns ``None`` for paths it does not
own so the caller can continue with its own routes.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from pathlib import Path

from .agent_jobs import RunManager
from .alkan_method import RELATIONSHIPS, TIERS
from .app_settings import DEFAULTS, EFFORTS, MODELS, AppSettings
from .estimator_agent.anthropic_client import AnthropicClient, APIError
from .estimator_agent.tools import KB_DIR, KB_TABLES, _load_kb
from .package_method import _d

VERSION = "3.6.0"
KNOWLEDGE_FIELDS = {
    "wages": {"required": ("county", "trade", "rate", "source"), "decimal": ("rate",),
              "fields": ("county", "trade", "classification", "rate", "effective", "source", "verified")},
    "price_book": {"required": ("item", "unit", "unit_price", "price_basis"), "decimal": ("unit_price",),
                   "fields": ("item", "spec", "unit", "unit_price", "price_basis", "source", "date", "county")},
    "productivity": {"required": ("task", "rate", "unit"), "decimal": ("rate",),
                     "fields": ("task", "rate", "unit", "trade", "source")},
}
FILE_TYPES = {".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8", ".zip": "application/zip",
              ".json": "application/json; charset=utf-8"}


class Download:
    """A file response (the handler sends bytes with this content type and name)."""
    def __init__(self, path: Path):
        self.path, self.kind = Path(path), FILE_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


class AppAPI:
    def __init__(self, root: Path, settings: AppSettings | None = None, client_factory=None):
        self.root = Path(root).resolve()
        self.settings = settings or AppSettings(self.root)
        self.runs = RunManager(self.root, self.settings, client_factory)
        self.last_test: dict | None = None

    # ───────────────────────────── routing
    def get(self, path: str, q: dict):
        one = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        if path == "/api/app/status": return self.status()
        if path == "/api/app/settings": return self.settings_view()
        if path == "/api/app/profiles": return self.profiles()
        if path == "/api/app/profile": return self.profile(one("name"))
        if path == "/api/app/knowledge": return self.knowledge(one("table"))
        if path == "/api/app/runs": return {"runs": self.runs.list(), "active": self.runs.active()}
        if path == "/api/app/run": return self.runs.get(one("id"))
        if path == "/api/app/run/file": return Download(self.runs.file(one("id"), one("name")))
        return None

    def post(self, path: str, req: dict, actor: str):
        if path == "/api/app/settings": self.settings.save(req.get("settings") or {}); return self.settings_view()
        if path == "/api/app/key": self.settings.set_secret(req.get("name", "anthropic"), req.get("key", ""), bool(req.get("remember"))); return self.status()
        if path == "/api/app/key/clear": self.settings.clear_secret(req.get("name", "anthropic")); return self.status()
        if path == "/api/app/test": return self.test_connection(req.get("model"))
        if path == "/api/app/models": return self.models()
        if path == "/api/app/profile/save": return self.save_profile(req["name"], req["profile"], req.get("logo"))
        if path == "/api/app/knowledge/save": return self.save_knowledge(req["table"], req["rows"])
        if path == "/api/app/knowledge/reset": return self.reset_knowledge(req["table"])
        if path == "/api/app/upload": return self.runs.upload_chunk(req["upload_id"], req["name"], req["index"], req["content"])
        if path == "/api/app/run/start": return self.runs.start(req["spec"], actor)
        if path == "/api/app/run/cancel": return self.runs.cancel(req["id"])
        if path == "/api/app/run/authorize": return self.runs.authorize(req["id"], actor, req.get("note", ""))
        if path == "/api/app/run/rebrand": return self.runs.rebrand(req["id"], req["profile"], actor)
        return None

    # ───────────────────────────── status
    def status(self) -> dict:
        cfg = self.settings.load()
        key = self.settings.secret_view("anthropic")
        profiles = self.profiles()["profiles"]
        wages, prices = self._table("wages"), self._table("price_book")
        basis = {b: sum(1 for p in prices if p.get("price_basis") == b) for b in ("QUOTE", "CATALOG", "BUDGET")}
        unverified = [f"{w['county']} · {w['trade']}" for w in wages if not w.get("verified")]
        legacy = cfg["legacy"]
        try:
            self.runs.base.mkdir(parents=True, exist_ok=True)
            writable = True
        except OSError:
            writable = False
        checks = [
            {"id": "key", "label": "Clave de la API de Anthropic", "ok": key["configured"],
             "detail": f"Cargada ({key['source']}) {key['hint']}" if key["configured"] else "Falta: sin ella el agente no puede leer planos.", "go": "conexiones"},
            {"id": "test", "label": "Prueba de conexión con el modelo", "ok": bool(self.last_test and self.last_test.get("ok")),
             "detail": (f"OK con {self.last_test['model']} · {self.last_test['at']}" if self.last_test and self.last_test.get("ok")
                        else (self.last_test or {}).get("error") or "Aún no se prueba en esta sesión."), "go": "conexiones"},
            {"id": "profiles", "label": "Perfiles de contratista", "ok": any(not p["generic"] for p in profiles),
             "detail": f"{len(profiles)} perfiles ({sum(1 for p in profiles if p['generic'])} sin marca).", "go": "contratistas"},
            {"id": "wages", "label": "Tarifas de prevailing wage (L&I)", "ok": not unverified,
             "detail": f"{len(wages)} tarifas." + (f" Sin verificar: {', '.join(unverified[:6])}." if unverified else " Todas verificadas."), "go": "tarifas"},
            {"id": "prices", "label": "Libro de precios", "ok": basis["QUOTE"] > 0,
             "detail": f"{len(prices)} renglones · {basis['QUOTE']} cotizados, {basis['CATALOG']} de catálogo, {basis['BUDGET']} de presupuesto."
                       + ("" if basis["QUOTE"] else " Cargue cotizaciones reales: son las que el agente usa primero."), "go": "precios"},
            {"id": "output", "label": "Carpeta de entregas", "ok": writable, "detail": str(self.runs.base), "go": "entrega"},
            {"id": "legacy", "label": "Proveedor para fases IA de medición (opcional)", "ok": bool(legacy["api_base"] and legacy["model"]),
             "optional": True, "detail": f"{legacy['model']} en {legacy['api_base']}" if legacy["api_base"] else "No configurado; solo afecta la pantalla de medición por fases.", "go": "conexiones"},
        ]
        return {"version": VERSION, "checks": checks, "ready": checks[0]["ok"] and bool(profiles), "active_run": self.runs.active(),
                "model": cfg["engine"]["model"], "key": key, "legacy_key": self.settings.secret_view("legacy"),
                "default_profile": cfg["delivery"]["default_profile"]}

    def settings_view(self) -> dict:
        return {"settings": self.settings.load(), "defaults": DEFAULTS, "models": MODELS, "efforts": EFFORTS,
                "relationships": {k: v["label"] for k, v in RELATIONSHIPS.items()},
                "tiers": {k: f"{k} ({v['precision']})" for k, v in TIERS.items()}}

    def _client(self, model=None) -> AnthropicClient:
        key, _ = self.settings.secret("anthropic")
        return AnthropicClient(api_key=key or None, model=model or self.settings.load()["engine"]["model"])

    def test_connection(self, model=None) -> dict:
        at = datetime.now().strftime("%Y-%m-%d %H:%M")
        try:
            out = self._client(model).ping()
            self.last_test = {"ok": True, "model": out["model"], "at": at}
        except APIError as exc:
            self.last_test = {"ok": False, "error": str(exc), "at": at}
        return self.last_test

    def models(self) -> dict:
        try:
            return {"models": self._client().list_models()}
        except APIError as exc:
            raise ValueError(str(exc)) from None

    # ───────────────────────────── profiles
    def profiles(self) -> dict:
        rows = []
        folder = self.root / "profiles"
        for f in sorted(folder.glob("*.json")) if folder.exists() else []:
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                rows.append({"name": f.stem, "label": p.get("profile") or p["contractor"]["name"],
                             "contractor": p["contractor"]["name"], "generic": bool(p.get("generic")),
                             "markups": p.get("markups", {}), "has_logo": bool(p["contractor"].get("logo")),
                             "trade": " ".join(p.get("scope_policy", []))[:160]})
            except (OSError, ValueError, KeyError):
                continue
        return {"profiles": rows}

    def profile(self, name: str) -> dict:
        if not re.fullmatch(r"[a-z0-9_]{1,60}", name or ""):
            raise ValueError("Perfil inválido")
        return {"name": name, "profile": json.loads((self.root / "profiles" / f"{name}.json").read_text(encoding="utf-8"))}

    def save_profile(self, name: str, profile: dict, logo: dict | None = None) -> dict:
        name = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")[:60]
        if not name:
            raise ValueError("Dé un nombre corto al perfil (letras y números)")
        if not isinstance(profile, dict):
            raise ValueError("Perfil inválido")
        c = profile.get("contractor") or {}
        for k, label in (("name", "nombre"), ("address", "dirección"), ("license", "licencia / UBI"), ("phone", "teléfono"), ("contact", "contacto")):
            if not str(c.get(k, "")).strip():
                raise ValueError(f"Contratista: falta {label}")
        mk = profile.get("markups") or {}
        for k in ("contingency_pct", "overhead_pct", "profit_pct"):
            if _d(mk.get(k), f"markups.{k}") > 100:
                raise ValueError(f"markups.{k}: porcentaje fuera de rango")
        _d(mk.get("rounding", "50"), "markups.rounding", allow_zero=False)
        if _d(profile.get("burden_pct"), "burden_pct") > 100:
            raise ValueError("burden_pct fuera de rango")
        for key, r in (profile.get("labor_rates") or {}).items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,15}", key) or not str(r.get("label", "")).strip():
                raise ValueError(f"Tarifa {key}: clave en mayúsculas y etiqueta requeridas")
            _d(r.get("rate"), f"labor_rates.{key}.rate", allow_zero=False)
            r.setdefault("kind", "loaded")
        com = profile.get("alkan_commission")
        if com:
            for k in ("find_estimate_pct", "coordination_pct"):
                _d(com.get(k, "0"), f"alkan_commission.{k}")
        if not str(profile.get("estimate_prefix", "")).strip():
            raise ValueError("Falta el prefijo de folio (p. ej. SS-EST-2026)")
        profile["scope_policy"] = [str(x).strip() for x in profile.get("scope_policy", []) if str(x).strip()]
        profile.setdefault("date", "AUTO")
        profile.setdefault("profile", c["name"])
        folder = self.root / "profiles"
        (folder / "assets").mkdir(parents=True, exist_ok=True)
        if logo and logo.get("content"):
            raw = base64.b64decode(logo["content"], validate=True)
            ext = ".png" if raw.startswith(b"\x89PNG") else ".jpg" if raw.startswith(b"\xff\xd8") else ""
            if not ext or len(raw) > 3 * 1024 * 1024:
                raise ValueError("Logo: use PNG o JPG de hasta 3 MB")
            (folder / "assets" / f"{name}_logo{ext}").write_bytes(raw)
            c["logo"] = f"assets/{name}_logo{ext}"
        elif logo and logo.get("remove"):
            c.pop("logo", None)
        (folder / f"{name}.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.profile(name)

    # ───────────────────────────── knowledge tables
    def _table(self, table: str) -> list[dict]:
        if table not in KB_TABLES:
            raise ValueError("Tabla desconocida")
        folder = self.root / "data" / "knowledge"
        return _load_kb(f"{table}.json", folder if folder.exists() else None)

    def knowledge(self, table: str) -> dict:
        rows = self._table(table)
        edited = (self.root / "data" / "knowledge" / f"{table}.json").exists()
        return {"table": table, "rows": rows, "fields": KNOWLEDGE_FIELDS[table]["fields"], "edited": edited}

    def save_knowledge(self, table: str, rows: list) -> dict:
        if table not in KB_TABLES or not isinstance(rows, list):
            raise ValueError("Tabla desconocida")
        spec, clean = KNOWLEDGE_FIELDS[table], []
        for i, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError(f"Fila {i}: formato inválido")
            item = {}
            for f in spec["fields"]:
                value = row.get(f, False if f == "verified" else "")
                item[f] = bool(value) if f == "verified" else str(value).strip()
            for f in spec["required"]:
                if not item[f]:
                    raise ValueError(f"Fila {i}: falta «{f}»")
            for f in spec["decimal"]:
                item[f] = str(_d(item[f].replace(",", "").replace("$", ""), f"Fila {i} · {f}"))
            if table == "price_book":
                item["price_basis"] = item["price_basis"].upper()
                if item["price_basis"] not in ("QUOTE", "CATALOG", "BUDGET"):
                    raise ValueError(f"Fila {i}: base de precio debe ser QUOTE, CATALOG o BUDGET")
            clean.append(item)
        if not clean:
            raise ValueError("La tabla no puede quedar vacía")
        folder = self.root / "data" / "knowledge"
        (folder / "_historial").mkdir(parents=True, exist_ok=True)
        current = folder / f"{table}.json"
        previous = current.read_text(encoding="utf-8") if current.exists() else (KB_DIR / f"{table}.json").read_text(encoding="utf-8")
        (folder / "_historial" / f"{table}_{datetime.now():%Y%m%d_%H%M%S}.json").write_text(previous, encoding="utf-8")
        current.write_text(json.dumps(clean, indent=1, ensure_ascii=False), encoding="utf-8")
        return self.knowledge(table)

    def reset_knowledge(self, table: str) -> dict:
        if table not in KB_TABLES:
            raise ValueError("Tabla desconocida")
        folder = self.root / "data" / "knowledge"
        current = folder / f"{table}.json"
        if current.exists():
            (folder / "_historial").mkdir(parents=True, exist_ok=True)
            current.replace(folder / "_historial" / f"{table}_{datetime.now():%Y%m%d_%H%M%S}_antes_de_restaurar.json")
        return self.knowledge(table)
