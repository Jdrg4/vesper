"""Credenciales de IA por tenant (BYOK) y su resolucion.

`resolve_credentials` es **el punto unico** por el que pasa todo el sistema para
saber con que credenciales corre un job. Cuando exista el modelo de plataforma
—key propia con cuotas por plan— el cambio entra aqui y en ningun otro sitio.
Por eso vive en su modulo y no como un metodo de `ReviewService`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import catalog
from src.agents.models import TenantCredential
from src.core.config import settings
from src.core.crypto import decrypt, encrypt, key_hint
from src.core.exceptions import NotFoundError, ValidationDomainError
from src.core.tenancy import tenant_scoped_query

logger = structlog.get_logger(__name__)

# Proveedor al que corresponde la key de instancia (la pasarela Zen).
INSTANCE_PROVIDER_ID = "opencode-go"

SIN_CREDENCIALES = (
    "Este workspace no tiene ninguna credencial de IA configurada. "
    "Añade la API key de tu proveedor en Ajustes antes de lanzar un job."
)


async def list_credentials(db: AsyncSession, tenant_id: uuid.UUID) -> list[TenantCredential]:
    q = tenant_scoped_query(TenantCredential, tenant_id).order_by(TenantCredential.provider_id)
    return list((await db.execute(q)).scalars().all())


async def _get_by_provider(
    db: AsyncSession, tenant_id: uuid.UUID, provider_id: str
) -> TenantCredential | None:
    q = tenant_scoped_query(TenantCredential, tenant_id).where(
        TenantCredential.provider_id == provider_id
    )
    return (await db.execute(q)).scalar_one_or_none()


async def upsert_credential(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    provider_id: str,
    api_key: str,
    label: str | None = None,
) -> TenantCredential:
    """Crea o reemplaza la credencial del tenant para ese proveedor.

    No se verifica la key contra el proveedor: con 174 proveedores no hay una
    forma uniforme de hacerlo, y una comprobacion que acierte en OpenAI y mienta
    en los demas es peor que ninguna. El primer job da un error claro.
    """
    api_key = api_key.strip()
    if not api_key:
        raise ValidationDomainError("La API key no puede estar vacia")
    if not await catalog.provider_exists(provider_id):
        raise ValidationDomainError(f"Proveedor desconocido: {provider_id}")

    cred = await _get_by_provider(db, tenant_id, provider_id)
    if cred is None:
        cred = TenantCredential(tenant_id=tenant_id, provider_id=provider_id)
        db.add(cred)
    cred.encrypted_key = encrypt(api_key)
    cred.key_hint = key_hint(api_key)
    cred.label = label
    # La key anterior ya no vale: quien la usara ya no existe.
    cred.last_used_at = None
    await db.flush()
    await db.refresh(cred)
    logger.info("tenant_credential_saved", tenant_id=str(tenant_id), provider_id=provider_id)
    return cred


async def delete_credential(db: AsyncSession, tenant_id: uuid.UUID, provider_id: str) -> None:
    cred = await _get_by_provider(db, tenant_id, provider_id)
    if cred is None:
        raise NotFoundError("Credencial no encontrada")
    await db.delete(cred)
    await db.flush()
    logger.info("tenant_credential_deleted", tenant_id=str(tenant_id), provider_id=provider_id)


async def resolve_credentials(db: AsyncSession, tenant_id: uuid.UUID) -> dict[str, str]:
    """`provider_id -> api key` con lo que debe correr un job de este tenant.

    1. Las credenciales del tenant.
    2. Si no tiene ninguna y el operador activo el fallback, la key de instancia.
    3. Si no, error de dominio accionable.

    Aqui es donde entrara la comprobacion de cuota cuando la key sea de la
    plataforma.
    """
    creds = await list_credentials(db, tenant_id)
    if creds:
        return {c.provider_id: decrypt(c.encrypted_key) for c in creds}

    if settings.allow_instance_key_fallback and settings.opencode_zen_key:
        logger.info("credentials_instance_fallback_used", tenant_id=str(tenant_id))
        return {INSTANCE_PROVIDER_ID: settings.opencode_zen_key}

    raise ValidationDomainError(SIN_CREDENCIALES)


async def mark_used(db: AsyncSession, tenant_id: uuid.UUID, provider_id: str) -> None:
    """Sella la credencial que acaba de usar un job. Nunca rompe el job."""
    cred = await _get_by_provider(db, tenant_id, provider_id)
    if cred is not None:
        cred.last_used_at = datetime.now(UTC)
        await db.flush()
