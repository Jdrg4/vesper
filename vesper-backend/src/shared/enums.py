"""Enums cross-dominio.

F1: solo `UserRole` (referenciado por `auth`/`users` en F2). Los enums de
dominio (p.ej. `TaskType`, `JobStatus`) viven en el `constants.py` de su
dominio correspondiente.
"""

from enum import StrEnum


class UserRole(StrEnum):
    """Rol de un usuario dentro de un tenant."""

    tenant_admin = "tenant_admin"
    user = "user"
