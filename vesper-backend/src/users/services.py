from sqlalchemy.ext.asyncio import AsyncSession

from src.users.models import User
from src.users.schemas import UserMeUpdate


async def get_me(user: User) -> User:
    return user


async def update_me(db: AsyncSession, user: User, data: UserMeUpdate) -> User:
    payload = data.model_dump(exclude_unset=True)
    for key, value in payload.items():
        setattr(user, key, value)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user
