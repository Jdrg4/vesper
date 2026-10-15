"""Modelos del dominio `agents`.

`TenantCredential` — BYOK: la API key que cada tenant trae para un proveedor de
IA (OpenAI, Anthropic, Google, DeepSeek, MiniMax, Kimi, la pasarela Zen...).
Tabla de tenant: siempre scoped.

F6 añadira `AgentConfig` (config de agente por tenant) y `SkillTemplate`
(catalogo global de skills).
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.shared.mixins import TenantMixin, TimestampMixin, UUIDMixin


class TenantCredential(UUIDMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "tenant_credentials"
    __table_args__ = (
        # POR TENANT, nunca global: un UNIQUE global sobre `provider_id`
        # impediria que dos tenants usaran OpenAI. Es la misma leccion que dejo
        # el sync de repositorios en F3.
        UniqueConstraint("tenant_id", "provider_id", name="uq_tenant_credentials_tenant_provider"),
    )

    # Id de proveedor tal cual lo nombra models.dev / opencode: `openai`,
    # `anthropic`, `google`, `deepseek`, `minimax`, `moonshotai`, `opencode-go`...
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Ultimos 4 caracteres. Es lo unico de la key que sale de la BD.
    key_hint: Mapped[str] = mapped_column(String(8), nullable=False, default="?")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
