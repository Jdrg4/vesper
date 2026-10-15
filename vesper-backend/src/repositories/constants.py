"""Constantes del dominio `repositories`."""

from enum import StrEnum


class Provider(StrEnum):
    """Proveedor del repo. Hoy solo GitHub; futuro: GitLab, Bitbucket."""

    github = "github"


# TODO(F3): limite de repos enrollables por plan.
