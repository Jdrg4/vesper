"""Dependencies de FastAPI para auth/RBAC."""

from __future__ import annotations

import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.core.security import decode_token
from src.shared.enums import UserRole

_bearer = HTTPBearer(auto_error=False)


def _extract_access_token(
    request: Request,
    creds: HTTPAuthorizationCredentials | None,
) -> str | None:
    if creds is not None and creds.scheme.lower() == "bearer":
        return creds.credentials
    return request.cookies.get("access_token")


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    from src.users.models import User

    token = _extract_access_token(request, creds)
    if token is None:
        raise UnauthorizedError("Falta el token")
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise UnauthorizedError("Token inválido") from exc
    if payload.get("type") != "access":
        raise UnauthorizedError("Tipo de token inválido")
    sub = payload.get("sub")
    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError, AttributeError) as exc:
        raise UnauthorizedError("Token inválido") from exc
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise UnauthorizedError("Usuario inválido o inactivo")
    return user


class RoleChecker:
    def __init__(self, roles: list[UserRole | str]) -> None:
        self.roles = {r.value if isinstance(r, UserRole) else r for r in roles}

    async def __call__(self, user=Depends(get_current_user)):
        role_val = user.role.value if hasattr(user.role, "value") else str(user.role)
        if role_val not in self.roles:
            raise ForbiddenError("Rol no autorizado")
        return user
