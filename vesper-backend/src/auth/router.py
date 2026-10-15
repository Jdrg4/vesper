from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import services
from src.auth.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TenantBrief,
    TokenResponse,
    UserRead,
)
from src.core.config import settings
from src.core.database import get_db
from src.core.deps import get_current_user
from src.core.exceptions import ValidationDomainError
from src.tenants.models import Tenant
from src.users.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_ACCESS_MAX_AGE = 15 * 60
_REFRESH_MAX_AGE = 7 * 24 * 60 * 60


def _secure_cookie() -> bool:
    return settings.environment == "production"


def _set_auth_cookies(response: Response, tokens: TokenResponse) -> None:
    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        max_age=_ACCESS_MAX_AGE,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        max_age=_REFRESH_MAX_AGE,
        path="/api/v1/auth",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth")


async def _user_read(db: AsyncSession, user: User) -> UserRead:
    tenant = await db.get(Tenant, user.tenant_id)
    base = UserRead.model_validate(user)
    if tenant is None:
        return base
    # `model_copy(update=...)` NO valida: pasar un dict crudo dejaba a Pydantic
    # serializando un `dict` donde el schema declara `TenantBrief` (warning en
    # cada respuesta). `model_validate` construye el submodelo de verdad.
    return base.model_copy(update={"tenant": TenantBrief.model_validate(tenant)})


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    data: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> UserRead:
    user, _tenant = await services.register_tenant_with_admin(db, data)
    tokens = services.issue_tokens(user)
    _set_auth_cookies(response, tokens)
    return await _user_read(db, user)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await services.authenticate(db, data.email, data.password)
    tokens = services.issue_tokens(user)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    data: RefreshRequest | None = None,
) -> TokenResponse:
    token = None
    if data is not None and data.refresh_token:
        token = data.refresh_token
    if not token:
        token = request.cookies.get("refresh_token")
    if not token:
        raise ValidationDomainError("Falta refresh token")
    tokens = await services.refresh_tokens(db, token)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    _clear_auth_cookies(response)


@router.get("/me", response_model=UserRead)
async def me(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserRead:
    return await _user_read(db, user)
