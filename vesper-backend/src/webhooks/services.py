"""Webhooks de GitHub: verificacion, filtrado y despacho.

Este es el unico endpoint del backend sin JWT: lo autentica la firma HMAC del
emisor. El orden de las defensas importa — nada del payload se cree hasta
haberlo verificado, y el tenant NUNCA sale del cuerpo del evento.
"""

from __future__ import annotations

import hashlib
import hmac

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import DomainError, UnauthorizedError
from src.core.tenancy import tenant_scoped_query
from src.repositories.models import Repository, TenantInstallation
from src.review_jobs.constants import BRANCH_PREFIX, JobTrigger
from src.review_jobs.services import enqueue_review_job
from src.triggers.models import WatchRule
from src.triggers.services import dispatch_rule

logger = structlog.get_logger(__name__)

_REF_PREFIX = "refs/heads/"


class WebhookUnavailableError(DomainError):
    """Sin secreto configurado. 503, nunca 200: falla cerrado."""

    status_code = 503
    code = "webhook_not_configured"


def verify_signature(body: bytes, header: str | None) -> None:
    """Valida `X-Hub-Signature-256` sobre el cuerpo CRUDO."""
    if not settings.github_webhook_secret:
        raise WebhookUnavailableError("GITHUB_WEBHOOK_SECRET no configurado")
    if not header:
        raise UnauthorizedError("Firma ausente")
    digest = hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    esperado = f"sha256={digest}"
    # `compare_digest` y no `==`: la comparacion corta filtra el secreto por
    # tiempo de respuesta.
    if not hmac.compare_digest(esperado, header):
        raise UnauthorizedError("Firma invalida")


def _es_el_propio_bot(sender: dict) -> bool:
    """El sender es la App de Vesper.

    Cada PR que abre el bot genera un push; sin este filtro, ese push abre otro
    job que abre otro PR. El bucle se paga en tokens del tenant. Solo se filtra
    NUESTRO bot: un push de dependabot es trabajo legitimo que vigilar.
    """
    if sender.get("type") != "Bot":
        return False
    slug = settings.github_app_slug
    return bool(slug) and sender.get("login", "").lower().startswith(slug.lower())


async def _resolve_tenant_id(db: AsyncSession, installation_id: int | None):
    """El tenant sale de la instalacion y de NINGUN otro sitio.

    `installation_id` es UNIQUE global y lo asigna GitHub; el resto del payload
    lo controla quien lo firmo.
    """
    if installation_id is None:
        return None
    q = select(TenantInstallation).where(TenantInstallation.installation_id == installation_id)
    inst = (await db.execute(q)).scalar_one_or_none()
    if inst is None:
        logger.info("webhook_unknown_installation", installation_id=installation_id)
        return None
    return inst.tenant_id


async def handle_push(db: AsyncSession, payload: dict) -> int:
    """Encola las reglas `on_push` del repo. Devuelve cuantos jobs se crearon."""
    tenant_id = await _resolve_tenant_id(db, (payload.get("installation") or {}).get("id"))
    if tenant_id is None:
        return 0

    if _es_el_propio_bot(payload.get("sender") or {}):
        logger.info("webhook_ignored_own_bot", tenant_id=str(tenant_id))
        return 0

    github_id = (payload.get("repository") or {}).get("id")
    if github_id is None:
        return 0
    repo_q = tenant_scoped_query(Repository, tenant_id).where(Repository.github_id == github_id)
    repo = (await db.execute(repo_q)).scalar_one_or_none()
    if repo is None or not repo.is_enrolled:
        logger.info("webhook_repo_not_enrolled", tenant_id=str(tenant_id), github_id=github_id)
        return 0

    rama = (payload.get("ref") or "").removeprefix(_REF_PREFIX)
    if rama != repo.default_branch or rama.startswith(f"{BRANCH_PREFIX}/"):
        logger.info("webhook_ignored_branch", tenant_id=str(tenant_id), rama=rama)
        return 0

    reglas_q = tenant_scoped_query(WatchRule, tenant_id).where(
        WatchRule.repository_id == repo.id,
        WatchRule.enabled.is_(True),
        WatchRule.on_push.is_(True),
    )
    reglas = list((await db.execute(reglas_q)).scalars().all())

    encolados: list[tuple] = []
    for rule in reglas:
        job = await dispatch_rule(db, rule, JobTrigger.webhook)
        if job is not None:
            encolados.append((job.id, job.tenant_id))

    await db.commit()

    # Encolar DESPUES del commit: el worker abre su propia sesion y no veria un
    # job que todavia no esta escrito.
    for job_id, tid in encolados:
        await enqueue_review_job(job_id, tid)

    logger.info("webhook_push_handled", tenant_id=str(tenant_id), encolados=len(encolados))
    return len(encolados)
