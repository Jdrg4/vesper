from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.review_jobs.constants import TaskType


class JobCreateRequest(BaseModel):
    repository_id: UUID
    task_type: TaskType
    # Sin `ref` se usa la rama por defecto del repo. Antes el default era "main"
    # literal, asi que en un repo con `master`/`develop` el clone fallaba.
    ref: str | None = None
    # Prompt libre desde la UI. Sustituye al cuerpo de la plantilla; el
    # `task_type` se conserva como etiqueta para filtrar en la lista de jobs.
    prompt: str | None = Field(default=None, max_length=4000)


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    repository_id: UUID
    task_type: str
    status: str
    trigger: str
    ref: str
    model: str
    # Instrucciones completas que recibio el agente (preambulo + plantilla o prompt libre).
    prompt: str | None = None
    pull_request_url: str | None = None
    branch_name: str | None = None
    diff_summary: str | None = None
    error_message: dict | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class JobEvent(BaseModel):
    job_id: str
    event: str  # progress, completed, error
    data: dict | None = None
