import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.core.database import Base, get_db
from src.main import app

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://vesper:vesper@localhost:55432/vesper_test"
)


@pytest.fixture(scope="function")
async def _engine():
    assert "localhost" in TEST_DB_URL, "Los tests solo corren contra BD local"
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    # importa todos los modelos antes de create_all (F1: ninguno declara tablas;
    # F2+ los modelos reales se importan aqui).
    import src.agents.models  # noqa: F401
    import src.auth.models  # noqa: F401
    import src.repositories.models  # noqa: F401
    import src.review_jobs.models  # noqa: F401
    import src.reviews.models  # noqa: F401
    import src.tenants.models  # noqa: F401
    import src.triggers.models  # noqa: F401
    import src.users.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(_engine) -> AsyncGenerator[AsyncSession, None]:
    sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session
        await session.rollback()


@pytest.fixture(autouse=True)
async def _override_get_db(_engine) -> AsyncGenerator[None, None]:
    """Redirige la app a la BD de tests.

    Sin esto la app resolveria `get_db` contra el engine global de
    `src.core.database`, que apunta a `vesper_dev` (o peor, a lo que diga
    `.env`): los tests fallaban con `UndefinedTableError` y, con un `.env`
    presente, habrian escrito en la BD de desarrollo.
    """
    sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)

    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
