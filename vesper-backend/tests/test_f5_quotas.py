"""Cuotas de jobs por plan (F5).

Reutiliza los helpers de F4 para montar tenant + repo. Ningun test arranca el
agente: solo se ejercita `create_job`, que es el punto por el que pasan los
cuatro triggers.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import QuotaExceededError
from src.review_jobs.constants import JobStatus, TaskType
from src.review_jobs.models import ReviewJob
from src.review_jobs.schemas import JobCreateRequest
from src.review_jobs.services import ReviewService
from src.tenants.constants import PLAN_QUOTAS, Plan
from src.tenants.models import Tenant
from tests.test_f4_review_jobs import _make_repo, _register


async def _tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    return await db.get(Tenant, tenant_id)


def _job(tenant: Tenant, repo, status: JobStatus) -> ReviewJob:
    return ReviewJob(
        tenant_id=tenant.id,
        repository_id=repo.id,
        task_type=TaskType.quality,
        status=status,
        model=tenant.developer_model,
    )


async def test_cuota_diaria_agotada_rechaza(client, db_session):
    auth = await _register(client, "quota")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await _tenant(db_session, auth["tenant_id"])
    limite = PLAN_QUOTAS[Plan.free]["max_jobs_per_day"]

    for _ in range(limite):
        db_session.add(_job(tenant, repo, JobStatus.completed))
    await db_session.commit()

    svc = ReviewService(db_session)
    with pytest.raises(QuotaExceededError):
        await svc.create_job(
            tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.security)
        )


async def test_cuota_diaria_no_cuenta_jobs_de_otro_tenant(client, db_session):
    """Aislamiento: el gasto de A no consume la cuota de B."""
    a = await _register(client, "quota-a")
    b = await _register(client, "quota-b")
    repo_a = await _make_repo(db_session, a["tenant_id"])
    repo_b = await _make_repo(db_session, b["tenant_id"])
    tenant_a = await _tenant(db_session, a["tenant_id"])
    tenant_b = await _tenant(db_session, b["tenant_id"])

    for _ in range(PLAN_QUOTAS[Plan.free]["max_jobs_per_day"]):
        db_session.add(_job(tenant_a, repo_a, JobStatus.completed))
    await db_session.commit()

    svc = ReviewService(db_session)
    job = await svc.create_job(
        tenant_b, JobCreateRequest(repository_id=repo_b.id, task_type=TaskType.security)
    )
    assert job.status == JobStatus.queued


async def test_concurrencia_al_limite_difiere_en_vez_de_rechazar(client, db_session):
    """Al tope de concurrencia el job se crea igual: la cola es para esperar."""
    auth = await _register(client, "quota-conc")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await _tenant(db_session, auth["tenant_id"])

    db_session.add(_job(tenant, repo, JobStatus.running))
    await db_session.commit()

    svc = ReviewService(db_session)
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.security)
    )
    assert job.status == JobStatus.queued
    assert await svc.defer_seconds_for(tenant) == 60


async def test_sin_jobs_en_vuelo_no_hay_retraso(client, db_session):
    auth = await _register(client, "quota-libre")
    await _make_repo(db_session, auth["tenant_id"])
    tenant = await _tenant(db_session, auth["tenant_id"])

    assert await ReviewService(db_session).defer_seconds_for(tenant) == 0


async def test_cuota_diaria_solo_cuenta_hoy(client, db_session):
    auth = await _register(client, "quota-ayer")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await _tenant(db_session, auth["tenant_id"])

    viejo = _job(tenant, repo, JobStatus.completed)
    db_session.add(viejo)
    await db_session.flush()
    viejo.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    await db_session.commit()

    assert await ReviewService(db_session)._jobs_today(tenant.id) == 0


async def test_cuota_agotada_devuelve_429_por_http(client, db_session):
    auth = await _register(client, "quota-http")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await _tenant(db_session, auth["tenant_id"])

    for _ in range(PLAN_QUOTAS[Plan.free]["max_jobs_per_day"]):
        db_session.add(_job(tenant, repo, JobStatus.completed))
    await db_session.commit()

    r = await client.post(
        "/api/v1/jobs",
        json={"repository_id": str(repo.id), "task_type": "security"},
        headers={"Cookie": auth["cookie"]},
    )
    assert r.status_code == 429, r.text
    assert r.json()["code"] == "quota_exceeded"
