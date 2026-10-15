import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.review_jobs.constants import TaskType
from src.shared.mixins import TenantMixin, TimestampMixin, UUIDMixin


class WatchRule(TenantMixin, UUIDMixin, TimestampMixin, Base):
    """Que vigilar de un repo, con que cadencia y ante que eventos.

    Una regla por (repo, tarea): dos cadencias para la misma tarea es una
    ambiguedad sin caso de uso. `repository_id` NO lleva UNIQUE global, por el
    mismo motivo que `repositories.github_id` — dos tenants pueden tener
    enrolado el mismo repo.
    """

    __tablename__ = "watch_rules"
    __table_args__ = (
        UniqueConstraint("repository_id", "task_type", name="uq_watch_rules_repo_task"),
        # El tick del scheduler barre exactamente esta pareja cada minuto.
        Index("ix_watch_rules_enabled_next_run", "enabled", "next_run_at"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Expresion cron en UTC. Null = la regla no tiene cadencia (solo `on_push`).
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    on_push: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Null = la rama por defecto del repo.
    ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Lo calcula `compute_next_run`. El indice que lo cubre es el compuesto de
    # `__table_args__`, no uno propio.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
