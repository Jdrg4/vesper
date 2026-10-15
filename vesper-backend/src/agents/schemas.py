"""Schemas Pydantic v2 del dominio `agents`.

F6 añadira `AgentConfigCreate`/`AgentConfigRead` y `SkillTemplateRead`.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CredentialUpsert(BaseModel):
    provider_id: str = Field(min_length=1, max_length=64)
    api_key: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=80)


class CredentialRead(BaseModel):
    """Lo unico que sale de la BD sobre una credencial.

    No hay campo con la key ni endpoint que la devuelva: se escribe y se
    sustituye, nunca se consulta.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: str
    label: str | None = None
    key_hint: str
    last_used_at: datetime | None = None
    created_at: datetime


class ModelRead(BaseModel):
    id: str
    name: str


class ProviderRead(BaseModel):
    id: str
    name: str
    models: list[ModelRead]
    # Si el tenant ya tiene credencial para este proveedor. La UI filtra por
    # esto al ofrecer modelos.
    configured: bool = False
