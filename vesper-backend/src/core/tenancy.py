"""Multi-tenant scoping — invariante de aislamiento.

Toda query de dominio que toca tablas de tenant DEBE pasar por
`tenant_scoped_query(model, tenant_id)`. Prohibido `db.execute(select(Model))`
sin filtro de tenant para tablas de tenant.

`get_current_tenant` deriva el tenant del JWT / user autenticado — NUNCA del
body/path del request.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user
from src.core.exceptions import ForbiddenError, NotFoundError
from src.shared.mixins import TenantMixin

if TYPE_CHECKING:
    from src.tenants.models import Tenant
    from src.users.models import User


def tenant_scoped_query[T: TenantMixin](model: type[T], tenant_id: uuid.UUID) -> Select[tuple[T]]:
    """SELECT `model` filtrada por `tenant_id`."""
    return select(model).where(model.tenant_id == tenant_id)


async def get_current_tenant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Deriva el tenant del user autenticado (nunca del input del request)."""
    from src.tenants.models import Tenant

    tenant = await db.get(Tenant, user.tenant_id)
    if tenant is None or not tenant.is_active:
        raise NotFoundError("Tenant no encontrado o inactivo")
    if not user.is_active:
        raise ForbiddenError("Usuario inactivo")
    return tenant
