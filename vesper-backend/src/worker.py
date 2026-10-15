"""Worker de Arq: ejecuta los review jobs fuera del proceso de la API.

Arranque: `arq src.worker.WorkerSettings`

Vive aparte a proposito. Cada job spawnea un `opencode serve` con su clon del
repo; con cron y webhook llegan rafagas, y eso no puede competir por CPU con el
proceso que atiende HTTP.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from arq import cron
from arq.connections import RedisSettings

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging_config import configure_logging
from src.review_jobs.services import _run_job_standalone, listen_aborts
from src.triggers.services import tick

logger = structlog.get_logger(__name__)


async def run_review_job(ctx: dict, job_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Ejecuta un review job. Sin reintentos: ver `WorkerSettings.max_tries`."""
    logger.info("worker_job_start", job_id=str(job_id), tenant_id=str(tenant_id))
    await _run_job_standalone(job_id, tenant_id)


async def tick_scheduler(ctx: dict) -> None:
    """Evalua las `watch_rules` vencidas. Arq garantiza un solo ejecutor."""
    async with AsyncSessionLocal() as session:
        await tick(session)


async def _on_startup(ctx: dict) -> None:
    configure_logging()
    # Escucha los aborts publicados por la API o por otro worker.
    ctx["abort_listener"] = asyncio.create_task(listen_aborts())
    logger.info("worker_started")


async def _on_shutdown(ctx: dict) -> None:
    task = ctx.get("abort_listener")
    if task is not None:
        task.cancel()
    logger.info("worker_stopped")


class WorkerSettings:
    functions = [run_review_job]
    cron_jobs = [cron(tick_scheduler, second=0)]  # cada minuto, en el segundo 0
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    # Un job = un `opencode serve` + un clon del repo. Cuatro a la vez es lo que
    # aguanta comodo el servidor casero de produccion.
    max_jobs = 4
    # Reintentar un job del agente es volver a gastar tokens del tenant y el
    # resultado no es determinista. Un fallo se queda en `failed`.
    max_tries = 1
    job_timeout = 1800  # 30 min

    # Arq lo lee como ATRIBUTO (`redis_settings.host`): un metodo hacia morir al
    # worker al arrancar. Sin `REDIS_URL` (tests, dev) queda el default de Arq;
    # el worker solo se lanza donde Redis existe.
    redis_settings = (
        RedisSettings.from_dsn(settings.redis_url) if settings.redis_url else RedisSettings()
    )
