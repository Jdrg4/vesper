from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import src.agents.models  # noqa: F401
import src.auth.models  # noqa: F401
import src.repositories.models  # noqa: F401
import src.review_jobs.models  # noqa: F401
import src.reviews.models  # noqa: F401
import src.tenants.models  # noqa: F401
import src.triggers.models  # noqa: F401
import src.users.models  # noqa: F401
from alembic import context
from src.core.config import settings
from src.core.database import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Usa el driver sync psycopg (Alembic no soporta engines async out of the box);
# la app en runtime sigue usando +asyncpg (src/core/database.py).
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+asyncpg", "+psycopg"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
