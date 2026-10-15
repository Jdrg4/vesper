from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.review_jobs.constants import TaskType


class WatchRuleCreate(BaseModel):
    task_type: TaskType
    cron: str | None = Field(default=None, max_length=128)
    on_push: bool = False
    ref: str | None = Field(default=None, max_length=256)
    enabled: bool = True


class WatchRuleUpdate(BaseModel):
    cron: str | None = Field(default=None, max_length=128)
    on_push: bool | None = None
    ref: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None


class WatchRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    task_type: str
    cron: str | None = None
    on_push: bool
    ref: str | None = None
    enabled: bool
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    created_at: datetime
