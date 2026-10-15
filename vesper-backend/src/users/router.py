from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user
from src.users import services
from src.users.models import User
from src.users.schemas import UserMeRead, UserMeUpdate

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me", response_model=UserMeRead)
async def users_me(user: User = Depends(get_current_user)) -> User:
    return await services.get_me(user)


@router.patch("/me", response_model=UserMeRead)
async def users_me_update(
    data: UserMeUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    return await services.update_me(db, user, data)
