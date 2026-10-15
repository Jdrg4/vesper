"""Router review_jobs (prefijo /api/v1/jobs)."""

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import NotFoundError
from src.core.tenancy import get_current_tenant
from src.review_jobs import services
from src.review_jobs.schemas import JobCreateRequest, JobRead
from src.tenants.models import Tenant

router = APIRouter(prefix="/api/v1/jobs", tags=["review_jobs"])

# Cadencia del stream SSE de progreso y techo de duracion (2s * 300 = 10 min).
_SSE_POLL_SECONDS = 2
_SSE_MAX_POLLS = 300


def _svc(db: AsyncSession) -> services.ReviewService:
    return services.ReviewService(db)


@router.post("", response_model=JobRead, status_code=201)
async def create_job(
    data: JobCreateRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> JobRead:
    svc = _svc(db)
    job = await svc.trigger_job(tenant, data)
    return JobRead.model_validate(job)


@router.get("", response_model=list[JobRead])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[JobRead]:
    svc = _svc(db)
    jobs = await svc.list_jobs(tenant.id)
    return [JobRead.model_validate(j) for j in jobs]


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> JobRead:
    svc = _svc(db)
    job = await svc.get_job(job_id, tenant.id)
    if job is None:
        raise NotFoundError("Job not found")
    return JobRead.model_validate(job)


@router.get("/{job_id}/events")
async def job_events(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> StreamingResponse:
    """SSE de progreso del job.

    Autenticado y con scope de tenant: sin esto, cualquiera que adivinara un
    `job_id` leia el progreso, los warnings y la URL del PR de otro tenant.
    `EventSource` no manda headers, pero si la cookie `access_token`, que es lo
    que resuelve `get_current_tenant`.
    """
    svc = _svc(db)
    if await svc.get_job(job_id, tenant.id) is None:
        raise NotFoundError("Job not found")

    key = str(job_id)

    async def event_stream() -> AsyncIterator[str]:
        offset = 0
        for _ in range(_SSE_MAX_POLLS):
            batch = await services.get_events(key, offset)
            for ev in batch:
                yield f"data: {json.dumps(ev)}\n\n"
            offset += len(batch)
            if batch and batch[-1]["event"] in services.TERMINAL_EVENTS:
                await services.clear_events(key)
                return
            await asyncio.sleep(_SSE_POLL_SECONDS)
        yield f"data: {json.dumps({'event': 'timeout', 'data': None})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{job_id}/abort")
async def abort_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> dict:
    """Cancela el job en vuelo: mata el proceso opencode y libera su puerto.

    `aborted: false` significa que este proceso no tenia el job. Con la cola de
    F5 eso es lo normal —lo corre un worker—, asi que se publica ademas la orden
    en `ABORT_CHANNEL` para que la atienda quien de verdad lo tenga.
    """
    svc = _svc(db)
    if await svc.get_job(job_id, tenant.id) is None:
        raise NotFoundError("Job not found")
    aborted = await services.abort_job(job_id)
    if not aborted:
        await services.publish_abort(job_id)
    return {"aborted": aborted}
