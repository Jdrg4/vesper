import uuid

from pydantic import BaseModel, ConfigDict, Field


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    developer_model: str
    reviewer_model: str
    is_active: bool


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    developer_model: str | None = Field(default=None, min_length=1, max_length=64)
    reviewer_model: str | None = Field(default=None, min_length=1, max_length=64)
