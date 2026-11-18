"""Admin settings for the ALKAN Bid Engine app (engine, delivery, connections).

Settings live in ``<root>/data/settings.json`` (no secrets).  API keys are kept
in memory for the running server; if the user ticks "recordar en esta PC" they
are also written to the user's profile folder (``%APPDATA%\\ALKAN\\BidEngine``
on Windows), never inside the engine folder, which may be synced or zipped.
"""
from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path

MODELS = [
    {"id": "claude-fable-5-2", "label": "Claude Fable 5.2 — máxima precisión (recomendado para planos)"},
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5 — muy capaz, menor costo"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5 — económico, proyectos chicos o de puro texto"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5 — solo pruebas de conexión"},
]
EFFORTS = ("low", "medium", "high", "xhigh", "max")

DEFAULTS = {
    "engine": {
        "model": "claude-fable-5-2",
        "review_model": "",                 # vacío = mismo modelo, contexto nuevo
        "effort": "high",
        "max_turns": 140,
        "budget_tokens": 6_000_000,
        "keep_images": 8,
        "web_search": True,
        "web_search_uses": 15,
        "web_search_tool": "web_search_20250305",
        "prompt_cache": True,
        "preflight_stop": True,             # detenerse si hay requisito obligatorio ya vencido (pre-bid, etc.)
        "independent_review": True,         # revisión con contexto nuevo antes de entregar
        "review_fix_rounds": 1,
        "price_deviation_pct": 35,          # alerta si un precio se aleja del libro de precios
        "extra_instructions": "",
    },
    "delivery": {
        "output_dir": os.environ.get("BIDKIT_DELIVERY_DIR", "").strip() or "ENTREGAS/AGENTE",
        "default_profile": "",
        "report_pdf": True,
        "zip_include_package_json": True,
        "zip_include_log": False,
        "zip_include_index": False,
        "local_time_label": "Ciudad de México",
        "local_time_offset_from_pacific_h": 2,
    },
    "legacy": {
        "api_base": os.environ.get("ANTHROPIC_BASE_URL", "https://apikey.vnaipro.app/v1"),
        "model": "",
        "audit_model": "",
        "vision": False,
    },
}
_INT_LIMITS = {
    ("engine", "max_turns"): (10, 400), ("engine", "budget_tokens"): (200_000, 40_000_000),
    ("engine", "keep_images"): (2, 40), ("engine", "web_search_uses"): (0, 60),
    ("engine", "review_fix_rounds"): (0, 3), ("engine", "price_deviation_pct"): (5, 300),
    ("delivery", "local_time_offset_from_pacific_h"): (-12, 12),
}


def _secrets_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ALKAN" / "BidEngine"


class AppSettings:
    """Thread-safe settings + secrets holder."""

    def __init__(self, root: Path, secrets_dir: Path | None = None):
        self.root = Path(root).resolve()
        self.path = self.root / "data" / "settings.json"
        self.secrets_path = (Path(secrets_dir) if secrets_dir else (self.root / "data" / "security")) / "secrets.json"
        self._lock = threading.RLock()
        self._memory: dict[str, str] = {}
        self._saved: dict[str, str] = {}
        for candidate in (self.secrets_path, _secrets_dir() / "secrets.json"):
            try:
                if candidate.exists():
                    self._saved = json.loads(candidate.read_text(encoding="utf-8"))
                    break
            except (OSError, ValueError):
                continue
        self.apply_legacy_env()

    # ───────────────────────────── settings
    def load(self) -> dict:
        with self._lock:
            data = deepcopy(DEFAULTS)
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                stored = {}
            for section, values in stored.items():
                if section in data and isinstance(values, dict):
                    data[section].update({k: v for k, v in values.items() if k in data[section]})
            env_dir = os.environ.get("BIDKIT_DELIVERY_DIR", "").strip()
            stored_out = ((stored.get("delivery") or {}).get("output_dir") or "").strip()
            if env_dir and stored_out in ("", "ENTREGAS/AGENTE"):
                data["delivery"]["output_dir"] = env_dir
            return data

    def save(self, patch: dict) -> dict:
        with self._lock:
            data = self.load()
            for section, values in (patch or {}).items():
                if section not in data or not isinstance(values, dict):
                    raise ValueError(f"Sección desconocida: {section}")
                for key, value in values.items():
                    if key not in data[section]:
                        raise ValueError(f"Ajuste desconocido: {section}.{key}")
                    data[section][key] = self._clean(section, key, value, DEFAULTS[section][key])
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.apply_legacy_env()
            return data

    @staticmethod
    def _clean(section, key, value, default):
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{section}.{key}: se espera sí/no")
            return value
        if isinstance(default, int):
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{section}.{key}: se espera un número entero") from None
            low, high = _INT_LIMITS.get((section, key), (0, 10 ** 9))
            if not low <= number <= high:
                raise ValueError(f"{section}.{key}: fuera de rango ({low}–{high})")
            return number
        text = str(value or "").strip()
        if (section, key) == ("engine", "effort") and text not in EFFORTS:
            raise ValueError(f"engine.effort debe ser uno de {EFFORTS}")
        if (section, key) == ("engine", "model") and not text:
            raise ValueError("engine.model requerido")
        if len(text) > 4000:
            raise ValueError(f"{section}.{key}: texto demasiado largo")
        return text

    # ───────────────────────────── secrets
    def secret(self, name: str) -> tuple[str, str]:
        """(value, source) — memory first, then environment, then the saved file."""
        env = {"anthropic": "ANTHROPIC_API_KEY", "legacy": "BIDKIT_API_KEY"}[name]
        with self._lock:
            if self._memory.get(name):
                return self._memory[name], "sesión"
            if name == "anthropic" and os.environ.get(env):
                return os.environ[env], "variable de entorno"
            if self._saved.get(name):
                return self._saved[name], "guardada en esta PC"
            return "", ""

    def set_secret(self, name: str, value: str, remember: bool) -> None:
        if name not in ("anthropic", "legacy"):
            raise ValueError("Credencial desconocida")
        value = (value or "").strip()
        if not value or len(value) > 400 or any(ch.isspace() for ch in value):
            raise ValueError("Clave vacía o con formato inválido")
        with self._lock:
            self._memory[name] = value
            if remember:
                self._saved[name] = value
                self._write_saved()
            self.apply_legacy_env()

    def clear_secret(self, name: str) -> None:
        with self._lock:
            self._memory.pop(name, None)
            if self._saved.pop(name, None) is not None:
                self._write_saved()
            if name == "legacy":
                os.environ.pop("BIDKIT_API_KEY", None)

    def _write_saved(self) -> None:
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets_path.write_text(json.dumps(self._saved), encoding="utf-8")
        try:
            os.chmod(self.secrets_path, 0o600)
        except OSError:
            pass

    def secret_view(self, name: str) -> dict:
        value, source = self.secret(name)
        return {"configured": bool(value), "source": source, "hint": ("…" + value[-4:]) if len(value) >= 12 else ""}

    def apply_legacy_env(self) -> None:
        """The phase orchestrator (rfq_agent) reads its provider from the environment."""
        legacy = self.load()["legacy"] if self.path.exists() else DEFAULTS["legacy"]
        if legacy["api_base"]:
            os.environ["BIDKIT_API_BASE"] = legacy["api_base"]
            os.environ["BIDKIT_MODEL"] = legacy["model"]
            os.environ["BIDKIT_AUDIT_MODEL"] = legacy["audit_model"]
            os.environ["BIDKIT_VISION"] = "1" if legacy["vision"] else "0"
        key = self._memory.get("legacy") or self._saved.get("legacy") or ""
        if key:
            os.environ["BIDKIT_API_KEY"] = key
