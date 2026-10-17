"""F6b: el veredicto de la suite (antes/después) decide si el job abre PR."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.engine import EngineResult, FakeEngine
from src.agents.verification import SuiteRun, TestCommand, Verification
from src.review_jobs import services
from src.review_jobs.constants import JobStatus, TaskType
from src.review_jobs.schemas import JobCreateRequest
from src.tenants.models import Tenant
from tests import test_f4_review_jobs as f4
from tests.test_f4_review_jobs import _FakeWorkspace, _make_repo, _un

# Fixtures de f4 reutilizadas.
_no_background_jobs = f4._no_background_jobs
patched_github = f4.patched_github

_DIFF = [{"file": "src/util.py", "patch": "@@ -1 +1 @@"}]
_CMD = TestCommand("pip install -e .", "python -m pytest -q")


def _checks(before: int | None, after: int | None, *, cmds=True, log="boom", timeout=False):
    return Verification(
        commands=[_CMD] if cmds else [],
        before=SuiteRun(before),
        after=SuiteRun(after, log_tail=log, timed_out=timeout),
    )


async def _run(db: AsyncSession, patched_github, checks: Verification | None):
    tenant = Tenant(name="V WS", slug=f"v-{_un()}")
    db.add(tenant)
    await db.flush()
    repo = await _make_repo(db, tenant.id)
    svc = services.ReviewService(
        db,
        workspace_svc=_FakeWorkspace(_DIFF),
        engine_factory=lambda _jid: FakeEngine(checks=checks),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.quality)
    )
    await db.commit()
    await svc.run_job(job.id, tenant.id)
    await db.refresh(job)
    return job


async def test_verified_abre_pr_con_seccion(db_session, patched_github, monkeypatch):
    bodies = []
    orig = services.create_pull_request

    async def spy(token, owner, repo, head, base, title, body):
        bodies.append(body)
        return await orig(token, owner, repo, head, base, title, body)

    monkeypatch.setattr(services, "create_pull_request", spy)
    job = await _run(db_session, patched_github, _checks(0, 0))
    assert job.status == JobStatus.completed
    assert job.pull_request_url
    assert "## Verificación" in bodies[0]
    assert "python -m pytest -q" in bodies[0]
    assert "✅" in bodies[0]


async def test_broke_no_abre_pr_y_guarda_el_log(db_session, patched_github):
    job = await _run(db_session, patched_github, _checks(0, 1, log="FAILED test_x"))
    assert job.status == JobStatus.needs_review
    assert job.pull_request_url is None
    assert "pr" not in patched_github
    assert "WARNING: la suite pasaba y ahora falla" in job.diff_summary
    assert job.error_message["suite_log"] == "FAILED test_x"
    assert job.error_message["error"]


async def test_already_red_abre_pr_con_aviso(db_session, patched_github, monkeypatch):
    bodies = []

    async def spy(token, owner, repo, head, base, title, body):
        bodies.append(body)
        return {"html_url": "https://github.com/a/b/pull/1"}

    monkeypatch.setattr(services, "create_pull_request", spy)
    job = await _run(db_session, patched_github, _checks(1, 1))
    assert job.status == JobStatus.completed
    assert "❌" in bodies[0]
    assert "ya fallaba" in bodies[0]


async def test_unverified_sin_tests_lo_dice(db_session, patched_github, monkeypatch):
    bodies = []

    async def spy(token, owner, repo, head, base, title, body):
        bodies.append(body)
        return {"html_url": "https://github.com/a/b/pull/1"}

    monkeypatch.setattr(services, "create_pull_request", spy)
    job = await _run(db_session, patched_github, _checks(None, None, cmds=False))
    assert job.status == JobStatus.completed
    assert "Sin verificar: no se detectaron tests" in bodies[0]


async def test_sin_checks_el_cuerpo_no_cambia(db_session, patched_github, monkeypatch):
    bodies = []

    async def spy(token, owner, repo, head, base, title, body):
        bodies.append(body)
        return {"html_url": "https://github.com/a/b/pull/1"}

    monkeypatch.setattr(services, "create_pull_request", spy)
    job = await _run(db_session, patched_github, None)
    assert "Verificación" not in bodies[0]
    assert bodies[0] == services._pr_body("quality", job.model, job.diff_summary)


def test_build_prompt_run_tests_solo_si_se_pide():
    base = services.build_prompt("quality", "a/b", "main")
    con = services.build_prompt("quality", "a/b", "main", run_tests=True)
    assert "corre los tests" not in base
    assert "corre los tests del repo si existen" in con


def test_engine_result_checks_por_defecto_none():
    assert EngineResult().checks is None


@pytest.mark.parametrize("motor,esperado", [("docker", True), ("opencode", False)])
def test_run_tests_sigue_al_motor(monkeypatch, motor, esperado):
    monkeypatch.setattr(services.settings, "agent_engine", motor)
    assert services.wants_tests() is esperado


def test_default_engine_factory_elige_motor_y_pasa_tenant(monkeypatch, tmp_path):
    from src.agents.docker_engine import DockerOpencodeEngine
    from src.agents.opencode_engine import OpencodeEngine

    monkeypatch.setattr(services.settings, "agent_engine", "opencode")
    local = services.default_engine_factory(tmp_path)("job-1", "tenant-a")
    assert type(local) is OpencodeEngine
    assert local.job_id == "job-1"

    monkeypatch.setattr(services.settings, "agent_engine", "docker")
    cont = services.default_engine_factory(tmp_path)("job-2", "tenant-b")
    assert isinstance(cont, DockerOpencodeEngine)
    assert cont.job_id == "job-2"
    assert cont.tenant_id == "tenant-b"
    with pytest.raises(ValueError, match="tenant_id"):
        services.default_engine_factory(tmp_path)("job-3")


async def test_run_job_pasa_tenant_id_a_la_factory_y_decide_run_tests_al_ejecutar(
    db_session: AsyncSession, patched_github, monkeypatch
):
    """Deuda de seguridad §11: si un job se encola con `AGENT_ENGINE=docker` y luego se
    cambia a `opencode` antes de ejecutarlo, el motor local NO debe recibir la orden de
    correr tests del repo en el servidor."""
    tenant = Tenant(name="V WS", slug=f"v-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    calls: list[tuple[str, str]] = []
    engines: list[FakeEngine] = []

    def factory(job_id: str, tenant_id: str):
        calls.append((job_id, tenant_id))
        eng = FakeEngine(checks=None)
        engines.append(eng)
        return eng

    svc = services.ReviewService(
        db_session, workspace_svc=_FakeWorkspace(_DIFF), engine_factory=factory
    )

    # 1. Creado con docker, ejecutado con opencode → NO pide correr tests.
    monkeypatch.setattr(services.settings, "agent_engine", "docker")
    job1 = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.quality)
    )
    assert "corre los tests" not in (job1.prompt or "")
    await db_session.commit()

    monkeypatch.setattr(services.settings, "agent_engine", "opencode")
    await svc.run_job(job1.id, tenant.id)
    assert calls[0] == (str(job1.id), str(tenant.id))
    assert "corre los tests" not in engines[0].prompts[0]

    # 2. Creado con opencode, ejecutado con docker → SÍ pide correr tests al ejecutar.
    monkeypatch.setattr(services.settings, "agent_engine", "opencode")
    job2 = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.quality)
    )
    await db_session.commit()

    monkeypatch.setattr(services.settings, "agent_engine", "docker")
    await svc.run_job(job2.id, tenant.id)
    assert calls[1] == (str(job2.id), str(tenant.id))
    assert "corre los tests del repo si existen" in engines[1].prompts[0]
