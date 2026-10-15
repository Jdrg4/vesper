"""Router del dominio `agents` (prefijo `/api/v1/agents`).

Credenciales de IA del tenant (BYOK) y catalogo de proveedores.
F6 añadira el CRUD de configuraciones de agente.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import catalog, credentials, schemas
from src.core.database import get_db
from src.core.deps import RoleChecker
from src.core.tenancy import get_current_tenant
from src.shared.enums import UserRole
from src.tenants.models import Tenant

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

_require_tenant_admin = RoleChecker([UserRole.tenant_admin])


@router.get("/providers", response_model=list[schemas.ProviderRead])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[schemas.ProviderRead]:
    """Catalogo de proveedores, marcando los que el tenant ya configuro."""
    configurados = {c.provider_id for c in await credentials.list_credentials(db, tenant.id)}
    catalogo = await catalog.get_catalog()
    return [
        schemas.ProviderRead(
            id=provider_id,
            name=datos["name"],
            models=[schemas.ModelRead(**m) for m in datos["models"]],
            configured=provider_id in configurados,
        )
        for provider_id, datos in sorted(catalogo.items())
    ]


@router.get("/credentials", response_model=list[schemas.CredentialRead])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[schemas.CredentialRead]:
    creds = await credentials.list_credentials(db, tenant.id)
    return [schemas.CredentialRead.model_validate(c) for c in creds]


@router.put(
    "/credentials", response_model=schemas.CredentialRead, status_code=status.HTTP_201_CREATED
)
async def upsert_credential(
    data: schemas.CredentialUpsert,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _admin=Depends(_require_tenant_admin),
) -> schemas.CredentialRead:
    """Guarda (o reemplaza) la API key del tenant para un proveedor."""
    cred = await credentials.upsert_credential(
        db, tenant.id, data.provider_id, data.api_key, data.label
    )
    return schemas.CredentialRead.model_validate(cred)


@router.delete("/credentials/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    _admin=Depends(_require_tenant_admin),
) -> None:
    await credentials.delete_credential(db, tenant.id, provider_id)
