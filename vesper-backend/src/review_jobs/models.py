import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.review_jobs.constants import JobStatus, JobTrigger, TaskType
from src.shared.mixins import TenantMixin, TimestampMixin, UUIDMixin
from src.tenants.constants import DEFAULT_DEVELOPER_MODEL


class ReviewJob(TenantMixin, UUIDMixin, TimestampMixin, Base):
    __tablename__ = "review_jobs"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(
            TaskType,
            name="task_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=JobStatus.queued,
        nullable=False,
    )
    trigger: Mapped[JobTrigger] = mapped_column(
        Enum(
            JobTrigger,
            name="job_trigger",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=JobTrigger.manual,
        nullable=False,
    )
    ref: Mapped[str] = mapped_column(String(256), default="main", nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `proveedor/modelo`, igual que en `tenants`. Guarda con que corrio el job.
    model: Mapped[str] = mapped_column(String(128), default=DEFAULT_DEVELOPER_MODEL, nullable=False)

    # resultado
    branch_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pull_request_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    diff_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
