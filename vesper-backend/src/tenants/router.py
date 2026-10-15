from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import RoleChecker
from src.core.tenancy import get_current_tenant
from src.shared.enums import UserRole
from src.tenants import services
from src.tenants.models import Tenant
from src.tenants.schemas import TenantRead, TenantUpdate

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

_require_tenant_admin = RoleChecker([UserRole.tenant_admin])


@router.get("/me", response_model=TenantRead)
async def tenants_me(tenant: Tenant = Depends(get_current_tenant)) -> Tenant:
    return await services.get_tenant(tenant)


@router.patch("/me", response_model=TenantRead)
async def tenants_me_update(
    data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _admin=Depends(_require_tenant_admin),
) -> Tenant:
    return await services.update_tenant(db, tenant, data)
