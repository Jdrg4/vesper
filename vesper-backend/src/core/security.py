from datetime import UTC, datetime, timedelta

from jose import jwt
from passlib.context import CryptContext

from src.core.config import settings

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def _encode(payload: dict, expires: timedelta) -> str:
    data = payload | {"exp": datetime.now(UTC) + expires}
    return jwt.encode(data, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, role: str, tenant_id: str) -> str:
    return _encode(
        {"sub": subject, "role": role, "tenant_id": tenant_id, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(subject: str, tenant_id: str) -> str:
    return _encode(
        {"sub": subject, "tenant_id": tenant_id, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
