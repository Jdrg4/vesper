"""Catalogo de proveedores y modelos de IA.

La fuente es **models.dev**, el mismo registro que usa `opencode`. Eso importa:
si el catalogo saliera de una lista nuestra, podriamos ofrecerle al tenant un
modelo que el runtime no sabe ejecutar.

El JSON son ~3 MB y 174 proveedores. Se descarga como mucho una vez al dia por
proceso y se sirve **recortado**: al navegador solo le hacen falta el nombre del
proveedor y la lista de ids de modelo.

Si models.dev no responde se sirve la ultima copia; si nunca hubo copia, una
semilla minima para que la UI no aparezca vacia. Esta pantalla nunca debe
romperse porque un tercero se caiga.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)

MODELS_DEV_URL = "https://models.dev/api.json"
CACHE_TTL_SECONDS = 24 * 3600
FETCH_TIMEOUT_SECONDS = 30

# Semilla de emergencia: solo se usa si nunca se pudo descargar el catalogo.
# Deliberadamente corta — no es una lista que mantener, es un salvavidas.
SEED_CATALOG: dict[str, dict] = {
    "opencode-go": {
        "name": "OpenCode Zen",
        "models": [
            {"id": "glm-5.2", "name": "GLM 5.2"},
            {"id": "minimax-m3", "name": "MiniMax M3"},
            {"id": "kimi-k3", "name": "Kimi K3"},
        ],
    },
    "openai": {"name": "OpenAI", "models": [{"id": "gpt-5", "name": "GPT-5"}]},
    "anthropic": {
        "name": "Anthropic",
        "models": [{"id": "claude-opus-5", "name": "Claude Opus 5"}],
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": [{"id": "deepseek-chat", "name": "DeepSeek Chat"}],
    },
}

_cache: dict[str, dict] | None = None
_fetched_at: float = 0.0
_lock = asyncio.Lock()


def _trim(raw: dict) -> dict[str, dict]:
    """Deja {provider_id: {name, models: [{id, name}]}} y tira el resto.

    models.dev trae precios, limites de contexto, paquetes npm y modalidades por
    modelo. Nada de eso lo necesita el selector.
    """
    catalogo: dict[str, dict] = {}
    for provider_id, provider in raw.items():
        if not isinstance(provider, dict):
            continue
        modelos = provider.get("models") or {}
        if not isinstance(modelos, dict):
            continue
        # opencode oculta los obsoletos: ofrecerlos acababa en "Model not found".
        modelos = {
            model_id: m
            for model_id, m in modelos.items()
            if (m or {}).get("status") != "deprecated"
        }
        if not modelos:
            continue
        catalogo[provider_id] = {
            "name": provider.get("name") or provider_id,
            "models": sorted(
                (
                    {"id": model_id, "name": (m or {}).get("name") or model_id}
                    for model_id, m in modelos.items()
                ),
                key=lambda m: m["id"],
            ),
        }
    return catalogo


async def _fetch(client: httpx.AsyncClient | None = None) -> dict[str, dict]:
    async def _get(c: httpx.AsyncClient) -> dict[str, dict]:
        r = await c.get(MODELS_DEV_URL, timeout=FETCH_TIMEOUT_SECONDS)
        r.raise_for_status()
        return _trim(r.json())

    if client is not None:
        return await _get(client)
    async with httpx.AsyncClient() as c:
        return await _get(c)


async def get_catalog(client: httpx.AsyncClient | None = None) -> dict[str, dict]:
    """Catalogo recortado. Nunca lanza."""
    global _cache, _fetched_at
    fresco = _cache is not None and (time.monotonic() - _fetched_at) < CACHE_TTL_SECONDS
    if fresco:
        return _cache  # type: ignore[return-value]

    async with _lock:
        # Otro coroutine pudo refrescarlo mientras esperabamos el lock.
        if _cache is not None and (time.monotonic() - _fetched_at) < CACHE_TTL_SECONDS:
            return _cache
        try:
            _cache = await _fetch(client)
            _fetched_at = time.monotonic()
            logger.info("model_catalog_refreshed", providers=len(_cache))
        except Exception as exc:
            logger.warning("model_catalog_fetch_failed", error=str(exc))
            if _cache is None:
                _cache = dict(SEED_CATALOG)
                _fetched_at = 0.0  # reintentar en la proxima peticion
    return _cache or dict(SEED_CATALOG)


def reset_catalog_cache() -> None:
    """Limpia la cache (tests)."""
    global _cache, _fetched_at
    _cache = None
    _fetched_at = 0.0


async def provider_exists(provider_id: str) -> bool:
    return provider_id in await get_catalog()


async def model_exists(provider_id: str, model_id: str) -> bool:
    provider = (await get_catalog()).get(provider_id)
    if provider is None:
        return False
    return any(m["id"] == model_id for m in provider["models"])
