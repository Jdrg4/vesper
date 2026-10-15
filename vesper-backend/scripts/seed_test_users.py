"""Seed de usuarios de prueba (idempotente).

Crea tenant `vesper-demo` + admin `admin@vesper.example` / user
`demo@vesper.example`. Aborta si DATABASE_URL no es local (guard anti-prod).

Run:
    cd vesper-backend
    $env:PYTHONPATH="."
    .venv\\Scripts\\python.exe scripts\\seed_test_users.py
"""

import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.security import hash_password
from src.shared.enums import UserRole
from src.tenants.constants import DEFAULT_DEVELOPER_MODEL, DEFAULT_REVIEWER_MODEL, Plan
from src.tenants.models import Tenant
from src.users.models import User

ADMIN_EMAIL = "admin@vesper.example"
ADMIN_PASSWORD = "changeme123"
ADMIN_NAME = "Admin Demo"

USER_EMAIL = "demo@vesper.example"
USER_PASSWORD = "changeme123"
USER_NAME = "Demo User"

TENANT_NAME = "Vesper Demo"
TENANT_SLUG = "vesper-demo"


def _abort_if_not_local() -> None:
    if "localhost" not in settings.database_url and "127.0.0.1" not in settings.database_url:
        print(
            "ABORT: DATABASE_URL no es local. Los seeds solo corren contra BD "
            "local de pruebas (vesper_dev / vesper_test).",
            file=sys.stderr,
        )
        sys.exit(2)


async def _seed(session: AsyncSession) -> None:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.slug == TENANT_SLUG))
    ).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            name=TENANT_NAME,
            slug=TENANT_SLUG,
            plan=Plan.free,
            developer_model=DEFAULT_DEVELOPER_MODEL,
            reviewer_model=DEFAULT_REVIEWER_MODEL,
            is_active=True,
        )
        session.add(tenant)
        await session.flush()
        print(f"  Tenant creado: {TENANT_SLUG}")
    else:
        print(f"  Tenant ya existe: {TENANT_SLUG}")

    admin = (
        await session.execute(select(User).where(User.email == ADMIN_EMAIL))
    ).scalar_one_or_none()
    if admin is None:
        admin = User(
            tenant_id=tenant.id,
            email=ADMIN_EMAIL,
            hashed_password=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_NAME,
            role=UserRole.tenant_admin,
            is_active=True,
        )
        session.add(admin)
        await session.flush()
        print(f"  Admin creado: {ADMIN_EMAIL}")
    else:
        print(f"  Admin ya existe: {ADMIN_EMAIL}")

    user = (
        await session.execute(select(User).where(User.email == USER_EMAIL))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            tenant_id=tenant.id,
            email=USER_EMAIL,
            hashed_password=hash_password(USER_PASSWORD),
            full_name=USER_NAME,
            role=UserRole.user,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        print(f"  User creado: {USER_EMAIL}")
    else:
        print(f"  User ya existe: {USER_EMAIL}")


async def main() -> int:
    _abort_if_not_local()
    print("Seed de usuarios de prueba (F2)")
    async with AsyncSessionLocal() as session:
        try:
            await _seed(session)
            await session.commit()
            print("Seed completado (idempotente).")
        except Exception:
            await session.rollback()
            raise
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(main()))
