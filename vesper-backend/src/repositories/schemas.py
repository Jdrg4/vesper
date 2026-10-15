from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InstallationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    installation_id: int
    installed_by: str | None = None
    created_at: datetime


class InstallUrlResponse(BaseModel):
    url: str


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    github_id: int
    full_name: str
    default_branch: str
    private: bool
    is_enrolled: bool
    tenant_id: UUID


class CallbackRequest(BaseModel):
    installation_id: int
    # `code` del redirect de GitHub tras instalar la App. Obligatorio: el
    # `installation_id` es un entero adivinable y no acredita quien instala,
    # asi que sin el codigo no hay forma de probar la propiedad.
    code: str = Field(min_length=1)
