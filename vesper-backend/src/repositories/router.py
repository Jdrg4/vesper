"""Router del dominio repositories (prefijo /api/v1/repositories)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import RoleChecker
from src.core.tenancy import get_current_tenant
from src.repositories import schemas, services
from src.repositories.schemas import CallbackRequest
from src.shared.enums import UserRole
from src.tenants.models import Tenant

router = APIRouter(prefix="/api/v1/repositories", tags=["repositories"])

_require_tenant_admin = RoleChecker([UserRole.tenant_admin])


@router.get("/install-url", response_model=schemas.InstallUrlResponse)
async def install_url() -> schemas.InstallUrlResponse:
    return schemas.InstallUrlResponse(url=services.build_install_url())


@router.post("/callback", response_model=schemas.InstallationRead)
async def callback(
    data: CallbackRequest,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> schemas.InstallationRead:
    inst = await services.store_installation(db, tenant, data)
    return schemas.InstallationRead.model_validate(inst)


@router.get("/installation", response_model=schemas.InstallationRead | None)
async def installation(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    inst = await services.get_installation(db, tenant.id)
    return schemas.InstallationRead.model_validate(inst) if inst else None


@router.post("/sync", response_model=list[schemas.RepositoryRead])
async def sync(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _admin=Depends(_require_tenant_admin),
) -> list[schemas.RepositoryRead]:
    repos = await services.sync_repositories(db, tenant)
    return [schemas.RepositoryRead.model_validate(r) for r in repos]


@router.get("", response_model=list[schemas.RepositoryRead])
async def list_repos(
    enrolled_only: bool = Query(default=False, alias="enrolled"),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[schemas.RepositoryRead]:
    repos = await services.list_repositories(db, tenant.id, enrolled_only)
    return [schemas.RepositoryRead.model_validate(r) for r in repos]


@router.patch("/{repo_id}/enroll", response_model=schemas.RepositoryRead)
async def toggle_enroll(
    repo_id: UUID,
    enrolled: bool = Query(default=True, description="true = enroll, false = unenroll"),
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _admin=Depends(_require_tenant_admin),
) -> schemas.RepositoryRead:
    repo = await services.toggle_enrollment(db, tenant.id, repo_id, enrolled)
    if repo is None:
        from src.core.exceptions import NotFoundError

        raise NotFoundError("Repositorio no encontrado")
    return schemas.RepositoryRead.model_validate(repo)
