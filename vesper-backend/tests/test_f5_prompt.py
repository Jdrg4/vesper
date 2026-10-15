"""Composicion del prompt (F5): preambulo comun y prompt libre."""

import pytest

from src.review_jobs.constants import JobTrigger, TaskType
from src.review_jobs.schemas import JobCreateRequest
from src.review_jobs.services import ReviewService, build_prompt
from src.tenants.models import Tenant
from tests.test_f4_review_jobs import _make_repo, _register


@pytest.mark.parametrize("task_type", ["security", "quality", "deps", "perf", "docs"])
def test_todas_las_plantillas_llevan_preambulo(task_type):
    prompt = build_prompt(task_type, "acme/api", "main")
    assert "acme/api" in prompt
    assert "main" in prompt
    assert "No hagas commit" in prompt


def test_prompt_libre_sustituye_el_cuerpo_pero_conserva_el_preambulo():
    prompt = build_prompt("quality", "acme/api", "develop", custom="Migra a Pydantic v2")
    assert "Migra a Pydantic v2" in prompt
    assert "No hagas commit" in prompt
    assert "develop" in prompt
    # El cuerpo de la plantilla `quality` no debe colarse.
    assert "dead code" not in prompt


def test_prompt_en_blanco_cae_a_la_plantilla():
    """Un textarea vacio no puede dejar al agente sin instrucciones."""
    prompt = build_prompt("quality", "acme/api", "main", custom="   ")
    assert "dead code" in prompt


async def test_job_con_prompt_nace_con_trigger_prompt(client, db_session):
    auth = await _register(client, "prompt")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await db_session.get(Tenant, auth["tenant_id"])

    job = await ReviewService(db_session).create_job(
        tenant,
        JobCreateRequest(
            repository_id=repo.id, task_type=TaskType.quality, prompt="Migra a Pydantic v2"
        ),
    )
    assert job.trigger == JobTrigger.prompt
    assert "Migra a Pydantic v2" in job.prompt


async def test_job_sin_prompt_sigue_siendo_manual(client, db_session):
    auth = await _register(client, "manual")
    repo = await _make_repo(db_session, auth["tenant_id"])
    tenant = await db_session.get(Tenant, auth["tenant_id"])

    job = await ReviewService(db_session).create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.quality)
    )
    assert job.trigger == JobTrigger.manual


def test_prompt_mas_largo_del_limite_se_rechaza():
    import uuid

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        JobCreateRequest(repository_id=uuid.uuid4(), task_type=TaskType.quality, prompt="x" * 4001)
