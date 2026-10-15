import uuid

from pydantic import BaseModel, ConfigDict, Field

from src.shared.enums import UserRole


class UserMeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    tenant_id: uuid.UUID


class UserMeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
