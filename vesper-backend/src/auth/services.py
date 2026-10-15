import re
import uuid

from jose import JWTError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.schemas import RegisterRequest, TokenResponse
from src.core.config import settings
from src.core.exceptions import DomainError, ForbiddenError, ValidationDomainError
from src.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from src.shared.enums import UserRole
from src.tenants.constants import DEFAULT_DEVELOPER_MODEL, DEFAULT_REVIEWER_MODEL, Plan
from src.tenants.models import Tenant
from src.users.models import User


class InvalidCredentials(DomainError):
    status_code = 401
    code = "invalid_credentials"


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:80] or "workspace"


async def register_tenant_with_admin(
    db: AsyncSession, data: RegisterRequest
) -> tuple[User, Tenant]:
    """Self-serve: crea tenant + primer user como tenant_admin en una transacción."""
    if not settings.registration_enabled:
        # Con el registro cerrado solo entra la primera cuenta: sin ella nadie
        # podria usar la instancia recien desplegada. Consulta global a
        # proposito (no `tenant_scoped_query`): pregunta si la INSTANCIA esta
        # vacia y no devuelve datos de nadie.
        # Lock de transaccion: dos altas simultaneas en una instancia vacia
        # verian las dos "sin usuarios" y crearian dos cuentas.
        await db.execute(text("SELECT pg_advisory_xact_lock(7243001)"))
        has_users = (await db.execute(select(User.id).limit(1))).first() is not None
        if has_users:
            raise ForbiddenError("El registro está cerrado en esta instancia")
    email = data.email.lower().strip()
    exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists is not None:
        raise ValidationDomainError("El email ya está registrado")

    slug = data.tenant_slug or slugify(data.tenant_name)
    if not slug:
        raise ValidationDomainError("slug de tenant inválido")

    slug_taken = (await db.execute(select(Tenant).where(Tenant.slug == slug))).scalar_one_or_none()
    if slug_taken is not None:
        raise ValidationDomainError("El slug del tenant ya está en uso")

    tenant = Tenant(
        name=data.tenant_name.strip(),
        slug=slug,
        plan=Plan.free,
        developer_model=DEFAULT_DEVELOPER_MODEL,
        reviewer_model=DEFAULT_REVIEWER_MODEL,
        is_active=True,
    )
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ValidationDomainError("El slug del tenant ya está en uso") from exc

    user = User(
        tenant_id=tenant.id,
        email=email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name.strip(),
        role=UserRole.tenant_admin,
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ValidationDomainError("El email ya está registrado") from exc
    return user, tenant


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    user = (
        await db.execute(select(User).where(User.email == email.lower().strip()))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        raise InvalidCredentials("Credenciales inválidas")
    if not user.is_active:
        raise InvalidCredentials("Credenciales inválidas")
    return user


def issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(str(user.id), user.role.value, str(user.tenant_id)),
        refresh_token=create_refresh_token(str(user.id), str(user.tenant_id)),
    )


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> TokenResponse:
    try:
        payload = decode_token(refresh_token)
    except JWTError as exc:
        raise ValidationDomainError("Refresh token inválido") from exc
    if payload.get("type") != "refresh":
        raise ValidationDomainError("Tipo de token inválido")
    try:
        user_id = uuid.UUID(payload.get("sub"))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValidationDomainError("Refresh token inválido") from exc
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise ValidationDomainError("Usuario inválido")
    return issue_tokens(user)
