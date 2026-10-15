"""Logica de negocio del dominio repositories."""

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import ForbiddenError, ValidationDomainError
from src.core.tenancy import tenant_scoped_query
from src.repositories.github_client import (
    exchange_oauth_code,
    get_installation_token,
    list_installation_repos,
    list_user_installations,
)
from src.repositories.models import Repository, TenantInstallation
from src.repositories.schemas import CallbackRequest
from src.tenants.models import Tenant

logger = structlog.get_logger(__name__)


async def get_installation(db: AsyncSession, tenant_id) -> TenantInstallation | None:
    return (
        await db.execute(tenant_scoped_query(TenantInstallation, tenant_id))
    ).scalar_one_or_none()


async def verify_installation_ownership(data: CallbackRequest) -> None:
    """Comprueba contra GitHub que quien instala controla esa instalacion.

    El `installation_id` viaja en el body del callback y es un entero
    secuencial: sin esta verificacion, un tenant podia reclamar la instalacion
    de otra cuenta que aun no estuviera registrada y, con ella, pedir
    installation tokens sobre repos ajenos y abrirles PRs.

    Falla cerrado: si la App no tiene credenciales OAuth configuradas no se
    puede verificar nada, y entonces no se acepta la instalacion.
    """
    if not settings.github_app_client_id or not settings.github_app_client_secret:
        raise ValidationDomainError(
            "GitHub App sin credenciales OAuth: no se puede verificar la instalacion"
        )

    user_token = await exchange_oauth_code(data.code)
    installations = await list_user_installations(user_token)
    owned = {inst.get("id") for inst in installations}
    if data.installation_id not in owned:
        logger.warning(
            "github_installation_ownership_rejected",
            installation_id=data.installation_id,
        )
        raise ForbiddenError("Esa instalacion de GitHub App no pertenece a tu cuenta")


async def store_installation(
    db: AsyncSession, tenant: Tenant, data: CallbackRequest
) -> TenantInstallation:
    await verify_installation_ownership(data)

    existing = await get_installation(db, tenant.id)
    if existing is not None:
        raise ValidationDomainError("El tenant ya tiene una instalacion de GitHub App conectada")

    # El `installation_id` llega en el body: sin este chequeo, un tenant que
    # reclamara el de otro rompia contra el UNIQUE de la tabla con un 500 de
    # asyncpg en vez de un error de dominio.
    taken = (
        await db.execute(
            select(TenantInstallation).where(
                TenantInstallation.installation_id == data.installation_id
            )
        )
    ).scalar_one_or_none()
    if taken is not None:
        raise ValidationDomainError("Esa instalacion de GitHub App ya esta conectada a otra cuenta")

    inst = TenantInstallation(
        tenant_id=tenant.id,
        installation_id=data.installation_id,
        installed_by=tenant.slug,
    )
    db.add(inst)
    await db.flush()
    await db.refresh(inst)
    return inst


async def sync_repositories(db: AsyncSession, tenant: Tenant) -> list[Repository]:
    inst = await get_installation(db, tenant.id)
    if inst is None:
        raise ValidationDomainError("No hay instalacion de GitHub App conectada")
    token = await get_installation_token(inst.installation_id)
    gh_repos = await list_installation_repos(token)

    saved: list[Repository] = []
    for gh in gh_repos:
        # Scoped por tenant: sin el filtro, el sync de un tenant encontraba (y
        # mutaba) la fila de otro que tuviera acceso al mismo repo de GitHub.
        existing = await db.execute(
            tenant_scoped_query(Repository, tenant.id).where(Repository.github_id == gh["id"])
        )
        repo = existing.scalar_one_or_none()
        if repo is None:
            repo = Repository(
                tenant_id=tenant.id,
                installation_id=inst.installation_id,
                github_id=gh["id"],
                full_name=gh["full_name"],
                default_branch=gh.get("default_branch", "main"),
                private=gh.get("private", False),
                is_enrolled=False,
            )
            db.add(repo)
        else:
            repo.full_name = gh["full_name"]
            repo.default_branch = gh.get("default_branch", repo.default_branch)
            repo.private = gh.get("private", repo.private)
        saved.append(repo)
    await db.flush()
    return saved


async def list_repositories(
    db: AsyncSession, tenant_id, enrolled_only: bool = False
) -> list[Repository]:
    q = tenant_scoped_query(Repository, tenant_id)
    if enrolled_only:
        q = q.where(Repository.is_enrolled.is_(True))
    return list((await db.execute(q.order_by(Repository.full_name))).scalars().all())


async def toggle_enrollment(
    db: AsyncSession, tenant_id, repo_id, enrolled: bool
) -> Repository | None:
    q = tenant_scoped_query(Repository, tenant_id).where(Repository.id == repo_id)
    repo = (await db.execute(q)).scalar_one_or_none()
    if repo is None:
        return None
    repo.is_enrolled = enrolled
    await db.flush()
    await db.refresh(repo)
    return repo


def build_install_url() -> str:
    slug = settings.github_app_slug
    if not slug:
        return ""
    return f"https://github.com/apps/{slug}/installations/new"
