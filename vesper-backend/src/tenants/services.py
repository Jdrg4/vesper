from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import catalog, credentials
from src.agents.runner import split_model
from src.core.config import settings
from src.core.exceptions import ValidationDomainError
from src.tenants.models import Tenant
from src.tenants.schemas import TenantUpdate

MODEL_FIELDS = ("developer_model", "reviewer_model")


async def get_tenant(tenant: Tenant) -> Tenant:
    return tenant


async def _validate_model(db: AsyncSession, tenant: Tenant, campo: str, valor: str) -> None:
    """El modelo tiene que existir y el tenant tiene que poder pagarlo.

    Sin esto se podia guardar cualquier cadena, y el fallo aparecia minutos
    despues dentro de un job, como un error del proveedor.
    """
    partes = split_model(valor)
    provider_id, model_id = partes["providerID"], partes["modelID"]

    if not await catalog.model_exists(provider_id, model_id):
        raise ValidationDomainError(
            f"{campo}: el modelo '{valor}' no existe en el catalogo de proveedores"
        )

    configurados = {c.provider_id for c in await credentials.list_credentials(db, tenant.id)}
    if provider_id in configurados:
        return
    # Sin credencial propia, solo vale si el operador presta la de la instancia.
    if (
        settings.allow_instance_key_fallback
        and settings.opencode_zen_key
        and provider_id == credentials.INSTANCE_PROVIDER_ID
    ):
        return
    raise ValidationDomainError(
        f"{campo}: no hay ninguna API key configurada para '{provider_id}'. "
        "Añadela en Ajustes antes de elegir uno de sus modelos."
    )


async def update_tenant(db: AsyncSession, tenant: Tenant, data: TenantUpdate) -> Tenant:
    payload = data.model_dump(exclude_unset=True)
    for campo in MODEL_FIELDS:
        if payload.get(campo):
            await _validate_model(db, tenant, campo, payload[campo])

    for key, value in payload.items():
        setattr(tenant, key, value)
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)
    return tenant
