import re
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.shared.enums import UserRole

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    tenant_name: str = Field(min_length=1, max_length=120)
    tenant_slug: str | None = Field(default=None, max_length=80)

    @field_validator("tenant_slug")
    @classmethod
    def _slug_format(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("slug debe ser lowercase alfanumérico con guiones")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TenantBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str
    developer_model: str
    reviewer_model: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    tenant_id: uuid.UUID
    tenant: TenantBrief | None = None
