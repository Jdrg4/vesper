from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.shared.mixins import TimestampMixin, UUIDMixin
from src.tenants.constants import (
    DEFAULT_DEVELOPER_MODEL,
    DEFAULT_REVIEWER_MODEL,
    Plan,
)


class Tenant(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    plan: Mapped[Plan] = mapped_column(
        Enum(
            Plan,
            name="plan",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        default=Plan.free,
        nullable=False,
    )
    # `proveedor/modelo`. 128 y no 64: algunos ids de OpenRouter se pasan.
    developer_model: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_DEVELOPER_MODEL, nullable=False
    )
    reviewer_model: Mapped[str] = mapped_column(
        String(128), default=DEFAULT_REVIEWER_MODEL, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
