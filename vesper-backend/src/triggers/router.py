"""Router del dominio `triggers`: reglas de vigilancia de un repo."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.tenancy import get_current_tenant
from src.tenants.models import Tenant
from src.triggers import services
from src.triggers.schemas import WatchRuleCreate, WatchRuleRead, WatchRuleUpdate

router = APIRouter(prefix="/api/v1", tags=["triggers"])


@router.get("/repositories/{repository_id}/watch-rules", response_model=list[WatchRuleRead])
async def list_watch_rules(
    repository_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> list[WatchRuleRead]:
    rules = await services.list_rules(db, tenant.id, repository_id)
    return [WatchRuleRead.model_validate(r) for r in rules]


@router.post(
    "/repositories/{repository_id}/watch-rules",
    response_model=WatchRuleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_watch_rule(
    repository_id: UUID,
    data: WatchRuleCreate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> WatchRuleRead:
    rule = await services.create_rule(db, tenant.id, repository_id, data)
    return WatchRuleRead.model_validate(rule)


@router.patch("/watch-rules/{rule_id}", response_model=WatchRuleRead)
async def update_watch_rule(
    rule_id: UUID,
    data: WatchRuleUpdate,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> WatchRuleRead:
    rule = await services.update_rule(db, tenant.id, rule_id, data)
    return WatchRuleRead.model_validate(rule)


@router.delete("/watch-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch_rule(
    rule_id: UUID,
    db: AsyncSession = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
) -> None:
    await services.delete_rule(db, tenant.id, rule_id)
