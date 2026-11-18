"""Minimal Anthropic Messages API client (stdlib only, like the rest of the engine).

The key comes from the caller or the environment (ANTHROPIC_API_KEY); it is never
written to logs.  Retries 429/5xx/529 with backoff and tracks token usage.

v3.6: default model Claude Fable 5.2; adaptive thinking + effort for current
models (``thinking.type = "enabled"`` returns HTTP 400 on models numbered 4.7
and later); prompt caching of the method, tools and conversation prefix; and a
safe fallback that drops an optional feature the API rejects instead of
aborting a run that already cost money.
"""
from __future__ import annotations

import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://apikey.vnaipro.app/v1/messages"
MODELS_URL = "https://apikey.vnaipro.app/v1/models"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
# Models that only accept manual thinking (type "enabled" + budget_tokens).
_MANUAL_THINKING = re.compile(r"claude-(3|(opus|sonnet|haiku)-4(-[015])?(-\d{8})?$)")
_CACHE = {"type": "ephemeral"}


class APIError(RuntimeError):
    pass


def thinking_params(model: str, effort: str = "", budget: int = 0) -> dict:
    """Request fields for thinking, by model generation."""
    if _MANUAL_THINKING.match(model):
        return {"thinking": {"type": "enabled", "budget_tokens": budget}} if budget else {}
    if not effort:
        return {}
    return {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}


def _with_cache_mark(messages: list) -> list:
    """Copy of ``messages`` with a cache breakpoint on the last block of the last user turn."""
    if not messages or messages[-1]["role"] != "user":
        return messages
    last = dict(messages[-1])
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
    if not blocks:
        return messages
    blocks[-1] = {**blocks[-1], "cache_control": _CACHE}
    last["content"] = blocks
    return messages[:-1] + [last]


class AnthropicClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: int = 32000,
                 timeout: int = 900, thinking_budget: int = 0, url: str | None = None, effort: str = "",
                 cache: bool = True, base_url: str | None = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise APIError("Falta la clave de la API de Anthropic. Cárguela en Administrador → Conexiones "
                           "o con .\\Configure-ClaudeAPI.ps1 en la misma ventana de PowerShell.")
        raw_base = (
            base_url
            or os.environ.get("ANTHROPIC_BASE_URL")
            or os.environ.get("BIDKIT_API_BASE")
            or "https://apikey.vnaipro.app/v1"
        ).strip().rstrip("/")
        root_base = raw_base[:-3] if raw_base.endswith("/v1") else raw_base
        self.base_url = raw_base
        resolved_url = url or f"{root_base}/v1/messages"
        self.models_url = f"{root_base}/v1/models"
        self.model = model or os.environ.get("BIDKIT_CLAUDE_MODEL", DEFAULT_MODEL)
        self.max_tokens, self.timeout, self.thinking_budget, self.url = max_tokens, timeout, thinking_budget, resolved_url
        self.effort, self.cache = effort, cache
        self.warnings: list[str] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0, "calls": 0}

    # ───────────────────────────── request
    def _body(self, system, messages, tools, max_tokens=None) -> dict:
        body = {"model": self.model, "max_tokens": max_tokens or self.max_tokens}
        if system:
            body["system"] = ([{"type": "text", "text": system, "cache_control": _CACHE}]
                              if self.cache and isinstance(system, str) else system)
        body["messages"] = _with_cache_mark(messages) if self.cache else messages
        if tools:
            body["tools"] = tools
        body.update(thinking_params(self.model, self.effort, self.thinking_budget))
        return body

    def _headers(self) -> dict:
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "user-agent": "ALKAN-BidEngine/3.11",
        }
        if "api.anthropic.com" not in self.base_url:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def _degrade(self, detail: str) -> bool:
        """Drop an optional feature the API rejected.  True if the request should be retried."""
        low = detail.lower()
        if self.cache and "cache_control" in low:
            self.cache = False
            self.warnings.append("La API rechazó el caché de prompt; se desactivó para esta corrida.")
            return True
        if (self.effort or self.thinking_budget) and any(w in low for w in ("thinking", "effort", "output_config")):
            self.effort, self.thinking_budget = "", 0
            self.warnings.append(f"La API rechazó el ajuste de razonamiento ({detail[:120]}); se usó el default del modelo.")
            return True
        return False

    def create(self, system, messages, tools, max_tokens=None) -> dict:
        for attempt in range(8):
            data = json.dumps(self._body(system, messages, tools, max_tokens)).encode()
            try:
                with urlopen(Request(self.url, data, self._headers(), method="POST"), timeout=self.timeout) as r:
                    out = json.loads(r.read())
                u = out.get("usage", {})
                for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    self.usage[k] += int(u.get(k) or 0)
                self.usage["calls"] += 1
                return out
            except HTTPError as exc:
                detail = ""
                try:
                    detail = (json.loads(exc.read()).get("error", {}).get("message", "") or "")[:400]
                except Exception:  # noqa: BLE001
                    pass
                if exc.code == 400 and self._degrade(detail):
                    continue
                if exc.code in (429, 500, 502, 503, 504, 529) and attempt < 5:
                    time.sleep(min(60, 2 ** attempt * 3))
                    continue
                hint = {401: "clave inválida o revocada", 403: "la clave no tiene permiso para este modelo",
                        404: f"modelo '{self.model}' no disponible para esta clave"}.get(exc.code, "revise clave, modelo y saldo")
                raise APIError(f"API HTTP {exc.code}: {detail or hint}") from None
            except (URLError, TimeoutError):
                if attempt < 5:
                    time.sleep(5)
                    continue
                raise APIError(f"No se pudo conectar con {self.base_url}") from None
        raise APIError("Reintentos agotados")

    # ───────────────────────────── admin helpers
    def ping(self) -> dict:
        """Smallest possible call: confirms key, model access and billing."""
        saved = (self.effort, self.thinking_budget, self.cache)
        self.effort, self.thinking_budget, self.cache = "", 0, False
        try:
            out = self.create("", [{"role": "user", "content": "Reply with the single word: OK"}], [], max_tokens=512)
        finally:
            self.effort, self.thinking_budget, self.cache = saved
        text = " ".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text").strip()
        return {"ok": True, "model": out.get("model", self.model), "reply": text[:60], "usage": out.get("usage", {})}

    def list_models(self) -> list[dict]:
        try:
            with urlopen(Request(self.models_url + "?limit=100", headers=self._headers()), timeout=30) as r:
                rows = json.loads(r.read()).get("data", [])
        except HTTPError as exc:
            raise APIError(f"API HTTP {exc.code} al listar modelos") from None
        except (URLError, TimeoutError):
            raise APIError(f"No se pudo conectar con {self.base_url}") from None
        return [{"id": m.get("id"), "label": m.get("display_name") or m.get("id")} for m in rows]


def equivalent_tokens(usage: dict) -> int:
    """Tokens weighted by price: cache reads cost ~0.1x, cache writes ~1.25x."""
    return int(usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
               + 0.1 * usage.get("cache_read_input_tokens", 0) + 1.25 * usage.get("cache_creation_input_tokens", 0))
