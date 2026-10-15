"""Cola de trabajos — punto unico de encolado.

Con `REDIS_URL` los jobs van a Arq y los ejecuta el worker de `src/worker.py`.
Sin el, degradan al `asyncio.create_task` de siempre: la API sigue funcionando
en local y los tests no necesitan Redis. Es la misma degradacion documentada
para el bus de eventos, no un bug.

Cuando haya que cambiar de backend de cola, se cambia AQUI y en ningun otro
sitio.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from src.core.config import settings

logger = structlog.get_logger(__name__)

_pool: Any = None
_pool_unavailable = False

# Nombre de funcion -> callable que la ejecuta en este mismo proceso. Lo rellena
# quien registra la funcion (ver `src/review_jobs/services.py`), para que este
# modulo no importe dominio: al reves se cerraria un ciclo de imports.
LOCAL_FALLBACKS: dict[str, Callable[..., Any]] = {}


def reset_queue() -> None:
    """Limpia el pool cacheado (tests)."""
    global _pool, _pool_unavailable
    _pool = None
    _pool_unavailable = False


async def get_pool():
    """Pool de Arq compartido, o None si no hay Redis o no responde."""
    global _pool, _pool_unavailable
    if not settings.redis_url or _pool_unavailable:
        return None
    if _pool is None:
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        except Exception as exc:
            # Degradar, nunca tumbar la API porque la cola no responda.
            _pool_unavailable = True
            logger.warning("queue_redis_unavailable", error=str(exc))
            return None
    return _pool


async def enqueue(fn_name: str, *args, defer_seconds: int = 0) -> str | None:
    """Encola `fn_name`. Devuelve el id de Arq, o None si corrio in-process."""
    pool = await get_pool()
    if pool is None:
        # KeyError explicito: un nombre sin fallback registrado seria trabajo
        # que se pierde en silencio.
        fallback = LOCAL_FALLBACKS[fn_name]
        fallback(*args)
        return None
    job = await pool.enqueue_job(fn_name, *args, _defer_by=defer_seconds or None)
    return job.job_id if job else None
