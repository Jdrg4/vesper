"""Modelos del dominio `auth`.

F2: `User` (UUIDMixin, TimestampMixin, TenantMixin) con
`email` (unique por tenant), `password_hash`, `role` (UserRole),
`is_active`. La migracion que crea la tabla llega en F2.
"""

# TODO(F2): declarar `class User(Base, UUIDMixin, TimestampMixin, TenantMixin):`
# con email/password_hash/role/is_active. Importar UserRole de
# src.shared.enums. Mientras tanto, este modulo se mantiene importable
# para que `alembic/env.py` no se rompa.
