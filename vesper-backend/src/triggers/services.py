"""Servicios del dominio `triggers`: reglas de vigilancia y scheduler."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from croniter import CroniterBadCronError, croniter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import (
    ConflictError,
    NotFoundError,
    QuotaExceededError,
    ValidationDomainError,
)
from src.core.tenancy import tenant_scoped_query
from src.repositories.models import Repository
from src.review_jobs.constants import JobStatus, JobTrigger
from src.review_jobs.models import ReviewJob
from src.review_jobs.schemas import JobCreateRequest
from src.review_jobs.services import ReviewService, enqueue_review_job, reap_stale_jobs
from src.tenants.models import Tenant
from src.triggers.models import WatchRule
from src.triggers.schemas import WatchRuleCreate, WatchRuleUpdate

logger = structlog.get_logger(__name__)


# ------------------------------------------------------------------  Scheduler


def compute_next_run(
    cron: str | None, *, enabled: bool, desde: datetime | None = None
) -> datetime | None:
    """Proxima ejecucion en UTC, o None si la regla no tiene cadencia.

    Se calcula SIEMPRE desde `desde` (por defecto, ahora) y no desde el
    `next_run_at` anterior: si el worker estuvo caido seis horas, al volver
    dispara una vez y sigue, en vez de reproducir seis ejecuciones perdidas. A
    un vigilante de repos le interesa el estado actual del repo, no su historia.
    """
    if not cron or not enabled:
        return None
    base = desde or datetime.now(UTC)
    try:
        return croniter(cron, base).get_next(datetime)
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        raise ValidationDomainError(f"Expresion cron invalida: {cron}") from exc


async def due_rules(db: AsyncSession, *, ahora: datetime | None = None) -> list[WatchRule]:
    """Reglas vencidas de TODOS los tenants.

    Unica query del sistema que no pasa por `tenant_scoped_query`, y por eso
    vive aqui y no en un service de dominio: el scheduler es un proceso de
    plataforma, no actua en nombre de un tenant. Todo lo que se hace despues
    con cada regla va scopeado por el `tenant_id` de la propia fila.
    """
    momento = ahora or datetime.now(UTC)
    q = (
        select(WatchRule)
        .where(
            WatchRule.enabled.is_(True),
            WatchRule.cron.is_not(None),
            WatchRule.next_run_at.is_not(None),
            WatchRule.next_run_at <= momento,
        )
        .order_by(WatchRule.next_run_at)
    )
    return list((await db.execute(q)).scalars().all())


async def has_active_job(db: AsyncSession, rule: WatchRule) -> bool:
    """Debounce: ya hay trabajo en curso para esta pareja (repo, tarea)."""
    q = tenant_scoped_query(ReviewJob, rule.tenant_id).where(
        ReviewJob.repository_id == rule.repository_id,
        ReviewJob.task_type == rule.task_type,
        ReviewJob.status.in_([JobStatus.queued, JobStatus.running]),
    )
    return (await db.execute(q)).first() is not None


async def dispatch_rule(db: AsyncSession, rule: WatchRule, trigger: JobTrigger) -> ReviewJob | None:
    """Crea el job de una regla, sin encolarlo todavia. None si se descarta.

    Se descarta por debounce, por cuota agotada, o si el repo ya no esta
    enrolado. Un disparo automatico NO propaga la excepcion de cuota: no hay
    nadie al otro lado del HTTP a quien devolverle un 429.
    """
    if await has_active_job(db, rule):
        logger.info("watch_rule_debounced", rule_id=str(rule.id), tenant_id=str(rule.tenant_id))
        return None

    tenant = await db.get(Tenant, rule.tenant_id)
    if tenant is None or not tenant.is_active:
        return None

    repo_q = tenant_scoped_query(Repository, rule.tenant_id).where(
        Repository.id == rule.repository_id
    )
    repo = (await db.execute(repo_q)).scalar_one_or_none()
    if repo is None or not repo.is_enrolled:
        logger.info("watch_rule_repo_not_enrolled", rule_id=str(rule.id))
        return None

    svc = ReviewService(db)
    try:
        job = await svc.create_job(
            tenant,
            JobCreateRequest(
                repository_id=rule.repository_id,
                task_type=rule.task_type,
                ref=rule.ref or repo.default_branch,
            ),
        )
    except QuotaExceededError:
        logger.warning("watch_rule_quota_exceeded", rule_id=str(rule.id))
        return None

    job.trigger = trigger
    return job


async def tick(db: AsyncSession, *, ahora: datetime | None = None) -> int:
    """Dispara las reglas vencidas. Devuelve cuantos jobs se encolaron.

    El avance de `next_run_at` va en la misma transaccion que la creacion del
    job: si el commit falla, ni hay job ni avanza el reloj. El reloj avanza
    aunque el job se descarte — si no, una regla debounceada reintentaria cada
    minuto para siempre.
    """
    momento = ahora or datetime.now(UTC)
    encolados: list[tuple[uuid.UUID, uuid.UUID]] = []

    # Antes de evaluar nada: un job colgado en `running` bloquea el debounce de
    # su (repo, tarea) y deja el repo sin vigilar en silencio.
    await reap_stale_jobs(db)

    for rule in await due_rules(db, ahora=momento):
        job = await dispatch_rule(db, rule, JobTrigger.cron)
        rule.next_run_at = compute_next_run(rule.cron, enabled=rule.enabled, desde=momento)
        rule.last_run_at = momento
        if job is not None:
            encolados.append((job.id, job.tenant_id))

    await db.commit()

    # Encolar DESPUES del commit: el worker abre su propia sesion y no veria un
    # job que todavia no esta escrito.
    for job_id, tenant_id in encolados:
        await enqueue_review_job(job_id, tenant_id)

    if encolados:
        logger.info("scheduler_tick", encolados=len(encolados))
    return len(encolados)


# -----------------------------------------------------------------------  CRUD


async def _repo_scoped(db: AsyncSession, tenant_id: uuid.UUID, repo_id: uuid.UUID) -> Repository:
    q = tenant_scoped_query(Repository, tenant_id).where(Repository.id == repo_id)
    repo = (await db.execute(q)).scalar_one_or_none()
    if repo is None:
        raise NotFoundError("Repository not found")
    return repo


async def _rule_scoped(db: AsyncSession, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> WatchRule:
    q = tenant_scoped_query(WatchRule, tenant_id).where(WatchRule.id == rule_id)
    rule = (await db.execute(q)).scalar_one_or_none()
    if rule is None:
        raise NotFoundError("Watch rule not found")
    return rule


async def list_rules(
    db: AsyncSession, tenant_id: uuid.UUID, repository_id: uuid.UUID
) -> list[WatchRule]:
    await _repo_scoped(db, tenant_id, repository_id)
    q = (
        tenant_scoped_query(WatchRule, tenant_id)
        .where(WatchRule.repository_id == repository_id)
        .order_by(WatchRule.created_at)
    )
    return list((await db.execute(q)).scalars().all())


async def create_rule(
    db: AsyncSession, tenant_id: uuid.UUID, repository_id: uuid.UUID, data: WatchRuleCreate
) -> WatchRule:
    await _repo_scoped(db, tenant_id, repository_id)
    rule = WatchRule(
        tenant_id=tenant_id,
        repository_id=repository_id,
        task_type=data.task_type,
        cron=data.cron,
        on_push=data.on_push,
        ref=data.ref,
        enabled=data.enabled,
        # Valida la expresion antes de escribir: un cron invalido guardado
        # revienta en el tick, lejos de quien lo escribio.
        next_run_at=compute_next_run(data.cron, enabled=data.enabled),
    )
    db.add(rule)
    try:
        await db.flush()
    except IntegrityError as exc:
        # `uq_watch_rules_repo_task`. Sin capturarlo, el error de Postgres sube
        # como 500 y el usuario ve un fallo del servidor por pedir algo que ya
        # tiene.
        await db.rollback()
        raise ConflictError(f"Ya existe una regla de {data.task_type.value} para ese repo") from exc
    await db.refresh(rule)
    return rule


async def update_rule(
    db: AsyncSession, tenant_id: uuid.UUID, rule_id: uuid.UUID, data: WatchRuleUpdate
) -> WatchRule:
    rule = await _rule_scoped(db, tenant_id, rule_id)
    for campo, valor in data.model_dump(exclude_unset=True).items():
        setattr(rule, campo, valor)
    # Deshabilitar apaga el reloj; reactivar lo reinicia desde ahora. Si no, una
    # regla parada un mes dispararia en cuanto se reactivase.
    rule.next_run_at = compute_next_run(rule.cron, enabled=rule.enabled)
    await db.flush()
    await db.refresh(rule)
    return rule


async def delete_rule(db: AsyncSession, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> None:
    rule = await _rule_scoped(db, tenant_id, rule_id)
    await db.delete(rule)
    await db.flush()
