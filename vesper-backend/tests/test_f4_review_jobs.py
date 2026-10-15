"""Tests de F4 — Agent runner y review jobs.

Ningun test spawnea `opencode` real ni golpea la API de GitHub: el runtime va
por `FakeOpencodeRunner` y las llamadas a GitHub se monkeypatchean.
"""

import asyncio
import tempfile
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import opencode_engine
from src.agents.models import TenantCredential
from src.agents.opencode_engine import OpencodeEngine
from src.agents.runner import FakeOpencodeRunner
from src.core.crypto import encrypt
from src.core.exceptions import NotFoundError
from src.repositories.models import Repository, TenantInstallation
from src.review_jobs import services
from src.review_jobs.constants import JobStatus, TaskType
from src.review_jobs.models import ReviewJob
from src.review_jobs.schemas import JobCreateRequest
from src.tenants.models import Tenant


def _engine_with(runner_factory):
    """Motor real de opencode sobre un runner falso: ejercita puerto, sandbox y stop."""
    base = Path(tempfile.mkdtemp(prefix="vesper-test-engine-"))
    return lambda job_id: OpencodeEngine(base, job_id, runner_factory=runner_factory)


def _un() -> str:
    return uuid.uuid4().hex[:8]


async def _register(client: AsyncClient, prefix: str) -> dict:
    """Crea tenant + admin y devuelve {cookie, tenant_id}."""
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{prefix}-{_un()}@example.com",
            "password": "changeme123",
            "full_name": prefix,
            "tenant_name": f"{prefix} WS",
            "tenant_slug": f"{prefix}-{_un()}",
        },
    )
    assert r.status_code == 201, r.text
    return {
        "cookie": f"access_token={r.cookies['access_token']}",
        "tenant_id": uuid.UUID(r.json()["tenant"]["id"]),
    }


async def _make_credential(db: AsyncSession, tenant_id: uuid.UUID, provider_id="opencode-go"):
    """Credencial de IA del tenant.

    Sin ella `run_job` no arranca: es justo el invariante de BYOK. Los tests que
    ejercitan ese rechazo estan en `test_byok_credentials.py`.
    """
    cred = TenantCredential(
        tenant_id=tenant_id,
        provider_id=provider_id,
        encrypted_key=encrypt("sk-de-mentira-1234"),
        key_hint="1234",
    )
    db.add(cred)
    await db.flush()
    return cred


async def _make_repo(
    db: AsyncSession, tenant_id: uuid.UUID, *, default_branch: str = "main"
) -> Repository:
    await _make_credential(db, tenant_id)
    installation_id = int(uuid.uuid4().int % 1_000_000_000)
    db.add(TenantInstallation(tenant_id=tenant_id, installation_id=installation_id))
    await db.flush()
    repo = Repository(
        tenant_id=tenant_id,
        installation_id=installation_id,
        github_id=int(uuid.uuid4().int % 1_000_000_000),
        full_name=f"acme/repo-{_un()}",
        default_branch=default_branch,
        private=True,
        is_enrolled=True,
    )
    db.add(repo)
    await db.flush()
    await db.commit()
    return repo


class _FakeWorkspace:
    """Sustituye a WorkspaceService: no clona ni ejecuta git."""

    def __init__(self, diff: list[dict] | None = None) -> None:
        self.pushed_branch: str | None = None
        self.pushed_with: tuple[str, str] = ("", "")
        self.diff = diff or []
        # Real: el `AgentSandbox` del job cuelga de aqui y se crea y se borra de
        # verdad durante estos tests.
        self.base = Path(tempfile.mkdtemp(prefix="vesper-test-ws-"))

    def workspace_dir(self, tenant_id: str, repo_id: str):
        return self.base / tenant_id / repo_id

    async def clone(self, tenant_id, repo_id, repo_full_name, branch, installation_token):
        return self.workspace_dir(tenant_id, repo_id)

    async def configure_git(self, workdir) -> None:
        return None

    async def create_branch(self, workdir, branch_name) -> None:
        return None

    async def commit_and_push(
        self, workdir, branch_name, message, repo_full_name="", installation_token=""
    ) -> str:
        self.pushed_branch = branch_name
        self.pushed_with = (repo_full_name, installation_token)
        return "abc123sha"

    async def capture_diff(self, workdir) -> list[dict]:
        # El diff lo inyecta cada test via el FakeOpencodeRunner.
        return self.diff


@pytest.fixture(autouse=True)
def _no_background_jobs(monkeypatch):
    """Evita que `POST /jobs` dispare el runner real durante los tests.

    Los tests que ejercitan el flujo llaman a `run_job` explicitamente.
    """
    scheduled: list[tuple] = []
    monkeypatch.setattr(
        services,
        "schedule_job_run",
        lambda job_id, tenant_id, **kw: scheduled.append((job_id, tenant_id)),
    )
    return scheduled


@pytest.fixture
def patched_github(monkeypatch):
    """Mockea token de instalacion y creacion de PR. Registra las llamadas."""
    calls: dict = {}

    async def _fake_token(installation_id, client=None):
        calls["installation_id"] = installation_id
        return "ghs_faketoken"

    async def _fake_pr(token, owner, repo, head, base, title, body):
        calls["pr"] = {
            "owner": owner,
            "repo": repo,
            "head": head,
            "base": base,
            "title": title,
        }
        return {"html_url": f"https://github.com/{owner}/{repo}/pull/1"}

    monkeypatch.setattr(services, "get_installation_token", _fake_token)
    monkeypatch.setattr(services, "create_pull_request", _fake_pr)
    return calls


# ------------------------------------------------------  Aislamiento del SSE
async def test_job_events_requires_auth(client: AsyncClient):
    """El stream SSE no puede ser publico: filtraria progreso de otros tenants."""
    r = await client.get(f"/api/v1/jobs/{uuid.uuid4()}/events")
    assert r.status_code == 401


async def test_job_events_rejects_other_tenant(client: AsyncClient, db_session: AsyncSession):
    a = await _register(client, "sse-a")
    b = await _register(client, "sse-b")
    repo = await _make_repo(db_session, a["tenant_id"])

    created = await client.post(
        "/api/v1/jobs",
        json={"repository_id": str(repo.id), "task_type": "docs"},
        headers={"Cookie": a["cookie"]},
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    r = await client.get(f"/api/v1/jobs/{job_id}/events", headers={"Cookie": b["cookie"]})
    assert r.status_code == 404


async def test_get_job_rejects_other_tenant(client: AsyncClient, db_session: AsyncSession):
    a = await _register(client, "get-a")
    b = await _register(client, "get-b")
    repo = await _make_repo(db_session, a["tenant_id"])

    created = await client.post(
        "/api/v1/jobs",
        json={"repository_id": str(repo.id), "task_type": "docs"},
        headers={"Cookie": a["cookie"]},
    )
    job_id = created.json()["id"]

    r = await client.get(f"/api/v1/jobs/{job_id}", headers={"Cookie": b["cookie"]})
    assert r.status_code == 404


async def test_create_job_rejects_repo_of_other_tenant(
    client: AsyncClient, db_session: AsyncSession
):
    a = await _register(client, "repo-a")
    b = await _register(client, "repo-b")
    repo_a = await _make_repo(db_session, a["tenant_id"])

    r = await client.post(
        "/api/v1/jobs",
        json={"repository_id": str(repo_a.id), "task_type": "docs"},
        headers={"Cookie": b["cookie"]},
    )
    assert r.status_code == 404


async def test_list_jobs_only_own_tenant(client: AsyncClient, db_session: AsyncSession):
    a = await _register(client, "list-a")
    b = await _register(client, "list-b")
    repo = await _make_repo(db_session, a["tenant_id"])

    await client.post(
        "/api/v1/jobs",
        json={"repository_id": str(repo.id), "task_type": "docs"},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.get("/api/v1/jobs", headers={"Cookie": b["cookie"]})
    assert r.status_code == 200
    assert r.json() == []


# -------------------------------------------------  Modelo configurado por tenant
async def test_create_job_uses_tenant_developer_model(db_session: AsyncSession):
    tenant = Tenant(name="Model WS", slug=f"model-{_un()}", developer_model="kimi-k3")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    svc = services.ReviewService(db_session)
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    assert job.model == "kimi-k3"


async def test_get_job_scoped_in_service(db_session: AsyncSession):
    """El scoping vive en services.py, no solo en el router (CLAUDE.md)."""
    tenant = Tenant(name="Scope WS", slug=f"scope-{_un()}")
    other = Tenant(name="Other WS", slug=f"other-{_un()}")
    db_session.add_all([tenant, other])
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    svc = services.ReviewService(db_session)
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.flush()

    assert await svc.get_job(job.id, tenant.id) is not None
    assert await svc.get_job(job.id, other.id) is None


# ---------------------------------------------------------------  run_job feliz
async def test_run_job_opens_pr_and_completes(db_session: AsyncSession, patched_github):
    tenant = Tenant(name="Run WS", slug=f"run-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id, default_branch="develop")

    diff = [{"file": "src/util.py", "patch": "@@ -1 +1 @@"}]
    ws = _FakeWorkspace(diff)
    svc = services.ReviewService(
        db_session,
        workspace_svc=ws,
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port, diff=diff)
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.quality)
    )
    await db_session.commit()

    await svc.run_job(job.id, tenant.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.completed
    assert job.pull_request_url == f"https://github.com/acme/{repo.full_name.split('/')[1]}/pull/1"
    assert job.commit_sha == "abc123sha"
    assert job.branch_name == ws.pushed_branch
    # El PR debe apuntar al default branch del repo, no a "main" hardcodeado.
    assert patched_github["pr"]["base"] == "develop"


async def test_run_job_needs_review_on_sensitive_path(db_session: AsyncSession, patched_github):
    tenant = Tenant(name="Sens WS", slug=f"sens-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    diff = [{"file": ".github/workflows/deploy.yml", "patch": "@@"}]
    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace(diff),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port, diff=diff)
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.security)
    )
    await db_session.commit()

    await svc.run_job(job.id, tenant.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.needs_review
    assert "pr" not in patched_github, "no debe abrirse PR con rutas sensibles sin aprobacion"


async def test_run_job_no_changes_completes(db_session: AsyncSession, patched_github):
    tenant = Tenant(name="Empty WS", slug=f"empty-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace([]),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port, diff=[])
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()

    await svc.run_job(job.id, tenant.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.completed
    assert job.pull_request_url is None
    assert "pr" not in patched_github


async def test_run_job_failure_records_error(db_session: AsyncSession, monkeypatch):
    tenant = Tenant(name="Fail WS", slug=f"fail-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    async def _boom(installation_id, client=None):
        raise RuntimeError("github down")

    monkeypatch.setattr(services, "get_installation_token", _boom)

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace(),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port)
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()

    await svc.run_job(job.id, tenant.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.failed
    assert "github down" in job.error_message["error"]


async def test_run_job_ignores_job_of_other_tenant(db_session: AsyncSession, patched_github):
    """run_job no debe tocar un job que no pertenece al tenant indicado."""
    tenant = Tenant(name="Iso WS", slug=f"iso-{_un()}")
    other = Tenant(name="Iso Other", slug=f"isoo-{_un()}")
    db_session.add_all([tenant, other])
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace([{"file": "a"}]),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port, diff=[{"file": "a"}])
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()

    await svc.run_job(job.id, other.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.queued
    assert "pr" not in patched_github


# ------------------------------------------------  Diff capturado con git real
async def test_capture_diff_reads_working_tree(tmp_path):
    """El diff sale de git, no del endpoint del runtime.

    `GET /session/{id}/diff` solo devuelve los cambios de un `messageID`
    concreto y sin el parametro contesta vacio: en la corrida real el agente
    edito el archivo y el job lo vio como "sin cambios". git es la fuente de
    verdad del workspace.
    """
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "calc.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")

    ws = services.WorkspaceService(base=str(tmp_path))
    await services._run_git(repo, "init", "-q")
    await services._run_git(repo, "config", "user.email", "t@t.local")
    await services._run_git(repo, "config", "user.name", "Test")
    await services._run_git(repo, "add", "-A")
    await services._run_git(repo, "commit", "-qm", "baseline")

    # El "agente" modifica un archivo y crea otro nuevo sin trackear.
    (repo / "src" / "calc.py").write_text(
        "def divide(a, b):\n    if b == 0:\n        raise ValueError('cero')\n    return a / b\n",
        encoding="utf-8",
    )
    (repo / "src" / "nuevo.py").write_text("VALOR = 1\n", encoding="utf-8")

    diff = await ws.capture_diff(repo)

    files = {d["file"] for d in diff}
    assert "src/calc.py" in files
    assert "src/nuevo.py" in files, "los archivos nuevos tambien cuentan"
    calc = next(d for d in diff if d["file"] == "src/calc.py")
    assert "+    if b == 0:" in calc["patch"]
    assert calc["additions"] >= 2


async def test_capture_diff_empty_when_no_changes(tmp_path):
    repo = tmp_path / "clean"
    repo.mkdir(parents=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    ws = services.WorkspaceService(base=str(tmp_path))
    await services._run_git(repo, "init", "-q")
    await services._run_git(repo, "config", "user.email", "t@t.local")
    await services._run_git(repo, "config", "user.name", "Test")
    await services._run_git(repo, "add", "-A")
    await services._run_git(repo, "commit", "-qm", "baseline")

    assert await ws.capture_diff(repo) == []


# -------------------------------------------------------  Secretos en el diff
SECRET_SAMPLES = [
    ("aws", "+AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'"),
    ("github", "+token = 'ghp_012345678901234567890123456789abcdEF'"),
    ("anthropic", "+key = 'sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH'"),
    ("private-key", "+-----BEGIN RSA PRIVATE KEY-----"),
    # Partido en dos para que el push protection de GitHub no lo tome por un token real.
    ("slack", "+SLACK = 'xoxb-" + "123456789012-1234567890123-abcdefghijklmnopqrstuvwx'"),
]


@pytest.mark.parametrize("label,line", SECRET_SAMPLES, ids=[s[0] for s in SECRET_SAMPLES])
def test_validate_diff_flags_secrets(label: str, line: str):
    warning = services.validate_diff([{"file": "src/app.py", "patch": f"@@\n{line}\n"}])
    assert warning, f"no detecto el secreto de tipo {label}"


def test_validate_diff_ignores_removed_lines():
    """Una linea ELIMINADA que contenia un secreto es justo lo que queremos."""
    patch = "@@\n-AWS_KEY = 'AKIAIOSFODNN7EXAMPLE'\n+AWS_KEY = os.environ['AWS_KEY']\n"
    assert services.validate_diff([{"file": "src/app.py", "patch": patch}]) == ""


def test_validate_diff_clean_patch_has_no_warning():
    patch = "@@\n+def suma(a: int, b: int) -> int:\n+    return a + b\n"
    assert services.validate_diff([{"file": "src/math.py", "patch": patch}]) == ""


def test_validate_diff_still_flags_sensitive_paths():
    warning = services.validate_diff(
        [{"file": ".github/workflows/deploy.yml", "patch": "@@\n+x\n"}]
    )
    assert "Sensitive path" in warning


async def test_run_job_with_secret_in_diff_needs_review(db_session: AsyncSession, patched_github):
    """Un diff con un secreto no puede acabar en un PR automatico."""
    tenant = Tenant(name="Sec WS", slug=f"sec-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    diff = [{"file": "src/config.py", "patch": "@@\n+KEY = 'AKIAIOSFODNN7EXAMPLE'\n"}]
    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace(diff),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port, diff=diff)
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.security)
    )
    await db_session.commit()
    await svc.run_job(job.id, tenant.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.needs_review
    assert "pr" not in patched_github


# -------------------------------------------------------------------  Abort
async def test_abort_cancels_running_job(db_session: AsyncSession, patched_github):
    """Abortar debe parar el agente de verdad y dejar el job en `failed`.

    Antes el endpoint devolvia 204 sin hacer nada: el agente seguia y acababa
    abriendo el PR igual.
    """
    tenant = Tenant(name="Abort WS", slug=f"abort-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    started = asyncio.Event()
    stopped: list[bool] = []

    class _HangingRunner(FakeOpencodeRunner):
        async def send_prompt(self, client, session_id, prompt, model="glm-5.2"):
            started.set()
            await asyncio.sleep(30)  # el agente "pensando"
            return {}

        async def stop(self):
            stopped.append(True)

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace([{"file": "a.py"}]),
        engine_factory=_engine_with(lambda w, p, e=None: _HangingRunner(w, p)),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()

    task = asyncio.create_task(svc.run_job(job.id, tenant.id))
    services.register_running_job(job.id, task)
    await asyncio.wait_for(started.wait(), timeout=5)

    assert await services.abort_job(job.id) is True
    await asyncio.sleep(0.1)

    await db_session.refresh(job)
    assert job.status == JobStatus.failed
    assert stopped, "abortar debe parar el proceso del agente"
    assert "pr" not in patched_github, "un job abortado no puede abrir PR"
    # Ya no esta en vuelo: un segundo abort no encuentra nada que cancelar.
    assert await services.abort_job(job.id) is False


async def test_abort_queda_guardado_aunque_el_job_corra_con_su_propia_sesion(
    _engine, db_session: AsyncSession, patched_github
):
    """`_run_job_standalone` (el camino del worker) solo hacia commit si `run_job`
    terminaba bien. Un abort es `CancelledError` (BaseException): la sesion se cerraba
    sin commit, "Job abortado" se perdia y el job seguia `running` para la API."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    tenant = Tenant(name="Abort2 WS", slug=f"abort2-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)
    job = await services.ReviewService(db_session).create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()

    started = asyncio.Event()

    class _HangingRunner(FakeOpencodeRunner):
        async def send_prompt(self, client, session_id, prompt, model="glm-5.2"):
            started.set()
            await asyncio.sleep(30)
            return {}

    task = asyncio.create_task(
        services._run_job_standalone(
            job.id,
            tenant.id,
            workspace_svc=_FakeWorkspace([{"file": "a.py"}]),
            engine_factory=_engine_with(lambda w, p, e=None: _HangingRunner(w, p)),
            session_factory=async_sessionmaker(_engine, expire_on_commit=False),
        )
    )
    services.register_running_job(job.id, task)
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await services.abort_job(job.id) is True
    with pytest.raises(asyncio.CancelledError):
        await task

    async with async_sessionmaker(_engine)() as other:
        row = (await other.execute(select(ReviewJob).where(ReviewJob.id == job.id))).scalar_one()
    assert row.status == JobStatus.failed
    assert row.error_message == {"error": "Job abortado"}


async def test_abort_unknown_job_returns_false():
    assert await services.abort_job(uuid.uuid4()) is False


async def test_abort_frees_the_port(db_session: AsyncSession, patched_github):
    """Un job abortado tiene que devolver su puerto al pool."""
    before = await opencode_engine.acquire_port()
    opencode_engine.release_port(before)

    tenant = Tenant(name="Port WS", slug=f"port-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    started = asyncio.Event()

    class _HangingRunner(FakeOpencodeRunner):
        async def send_prompt(self, client, session_id, prompt, model="glm-5.2"):
            started.set()
            await asyncio.sleep(30)
            return {}

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace([{"file": "a.py"}]),
        engine_factory=_engine_with(lambda w, p, e=None: _HangingRunner(w, p)),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()
    task = asyncio.create_task(svc.run_job(job.id, tenant.id))
    services.register_running_job(job.id, task)
    await asyncio.wait_for(started.wait(), timeout=5)
    await services.abort_job(job.id)
    await asyncio.sleep(0.1)

    after = await opencode_engine.acquire_port()
    opencode_engine.release_port(after)
    assert after == before, "el puerto del job abortado quedo ocupado"


# ------------------------------------------------------------------  Puertos
async def test_port_pool_gives_distinct_ports():
    p1 = await opencode_engine.acquire_port()
    p2 = await opencode_engine.acquire_port()
    try:
        assert p1 != p2
    finally:
        opencode_engine.release_port(p1)
        opencode_engine.release_port(p2)


async def test_port_pool_reuses_released_port():
    p1 = await opencode_engine.acquire_port()
    opencode_engine.release_port(p1)
    p2 = await opencode_engine.acquire_port()
    try:
        assert p1 == p2
    finally:
        opencode_engine.release_port(p2)


# -------------------------------------------------------------------  Eventos
async def test_events_are_not_lost_between_polls():
    job_id = str(uuid.uuid4())
    await services.push_event(job_id, "progress", {"message": "one"})
    assert [e["data"]["message"] for e in await services.get_events(job_id, 0)] == ["one"]

    await services.push_event(job_id, "progress", {"message": "two"})
    # Leer con offset=1 debe devolver el segundo evento, no perderlo.
    assert [e["data"]["message"] for e in await services.get_events(job_id, 1)] == ["two"]

    await services.clear_events(job_id)
    assert await services.get_events(job_id, 0) == []


async def test_event_bus_uses_redis_when_configured(monkeypatch):
    """Con REDIS_URL los eventos van a una lista de Redis, no a memoria.

    Es lo que permite que el job corra en un worker y el SSE se sirva desde
    otro; con el bus en memoria el progreso solo se veia en un proceso.
    """
    calls: list[tuple] = []

    class _FakeRedis:
        async def rpush(self, key, value):
            calls.append(("rpush", key, value))

        async def expire(self, key, ttl):
            calls.append(("expire", key, ttl))

        async def lrange(self, key, start, end):
            return [v for (op, k, v) in calls if op == "rpush" and k == key][start:]

        async def delete(self, key):
            calls.append(("delete", key, None))

    async def _fake_get_redis():
        return _FakeRedis()

    monkeypatch.setattr(services, "_get_redis", _fake_get_redis)
    job_id = str(uuid.uuid4())

    await services.push_event(job_id, "progress", {"message": "via redis"})
    events = await services.get_events(job_id, 0)

    assert [e["data"]["message"] for e in events] == ["via redis"]
    assert any(op == "rpush" for op, _, _ in calls)
    # Los eventos son efimeros: la clave debe caducar.
    assert any(op == "expire" for op, _, _ in calls)
    # Y no debe haber tocado el dict en memoria.
    assert services._JOB_EVENTS.get(job_id) is None


async def test_event_bus_degrades_to_memory_when_redis_is_down(monkeypatch):
    """Si Redis no responde, la API sigue: se cae a memoria y se avisa."""
    monkeypatch.setattr(services.settings, "redis_url", "redis://127.0.0.1:6399", raising=False)
    services.reset_event_bus()
    try:
        job_id = str(uuid.uuid4())
        await services.push_event(job_id, "progress", {"message": "fallback"})
        events = await services.get_events(job_id, 0)
        assert [e["data"]["message"] for e in events] == ["fallback"]
    finally:
        services.reset_event_bus()


async def test_run_job_emits_terminal_event(db_session: AsyncSession, patched_github):
    tenant = Tenant(name="Ev WS", slug=f"ev-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace([{"file": "src/a.py"}]),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(
                workdir, port, diff=[{"file": "src/a.py"}]
            )
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()
    await svc.run_job(job.id, tenant.id)

    events = await services.get_events(str(job.id), 0)
    assert events, "run_job debe emitir eventos de progreso"
    assert events[-1]["event"] in services.TERMINAL_EVENTS
    await services.clear_events(str(job.id))


# ---------------------------------------------  create_job con repo inexistente
async def test_create_job_unknown_repo_raises(db_session: AsyncSession):
    tenant = Tenant(name="NF WS", slug=f"nf-{_un()}")
    db_session.add(tenant)
    await db_session.flush()

    svc = services.ReviewService(db_session)
    with pytest.raises(NotFoundError):
        await svc.create_job(
            tenant, JobCreateRequest(repository_id=uuid.uuid4(), task_type=TaskType.docs)
        )


async def test_job_persisted_before_background_task(client: AsyncClient, db_session: AsyncSession):
    """El endpoint debe dejar el job visible para una sesion nueva.

    Si el job solo se `flush`ea, la tarea de fondo (que abre su propia sesion)
    no lo encuentra y el job se queda en `queued` para siempre.
    """
    a = await _register(client, "persist")
    repo = await _make_repo(db_session, a["tenant_id"])

    created = await client.post(
        "/api/v1/jobs",
        json={"repository_id": str(repo.id), "task_type": "docs"},
        headers={"Cookie": a["cookie"]},
    )
    assert created.status_code == 201
    job_id = uuid.UUID(created.json()["id"])

    found = (
        await db_session.execute(select(ReviewJob).where(ReviewJob.id == job_id))
    ).scalar_one_or_none()
    assert found is not None


# ------------------------------------------  Credenciales fuera del workspace
async def _local_origin(tmp_path) -> tuple:
    """Crea un repo bare local que hace de `origin`, con una rama `develop`."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    await services._run_git(origin, "init", "-q", "--bare", "-b", "develop")

    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "app.py").write_text("x = 1\n", encoding="utf-8")
    await services._run_git(seed, "init", "-q", "-b", "develop")
    await services._run_git(seed, "config", "user.email", "t@t.local")
    await services._run_git(seed, "config", "user.name", "Test")
    await services._run_git(seed, "add", "-A")
    await services._run_git(seed, "commit", "-qm", "baseline")
    await services._run_git(seed, "push", "-q", str(origin), "develop")
    return origin, seed


async def test_clone_no_deja_el_token_en_git_config(tmp_path, monkeypatch):
    """El installation token no puede quedar escrito en el workspace.

    Clonar con el token incrustado en la URL —`x-access-token:TOKEN@github.com`—
    deja esa URL en `.git/config`, y ese archivo queda legible durante todo el
    job para el agente y para cualquier script del repo del tenant que corra en
    el sandbox.
    """
    origin, _ = await _local_origin(tmp_path)
    token = "ghs_tokensupersecreto"
    monkeypatch.setattr(services, "_authenticated_remote", lambda full, tok: str(origin))

    ws = services.WorkspaceService(base=str(tmp_path / "ws"))
    workdir = await ws.clone("tenant-1", "repo-1", "acme/repo", "develop", token)

    config = (workdir / ".git" / "config").read_text(encoding="utf-8")
    assert token not in config, "el token no puede persistir en el workspace"
    assert "https://github.com/acme/repo.git" in config


async def test_commit_and_push_usa_el_remote_autenticado_explicito(tmp_path, monkeypatch):
    """Con el `origin` sin credenciales, el push debe llevarlas como argumento."""
    origin, _ = await _local_origin(tmp_path)
    monkeypatch.setattr(services, "_authenticated_remote", lambda full, tok: str(origin))

    ws = services.WorkspaceService(base=str(tmp_path / "ws"))
    workdir = await ws.clone("tenant-1", "repo-1", "acme/repo", "develop", "ghs_secreto")
    await ws.configure_git(workdir)
    await ws.create_branch(workdir, "vesper/quality-abc123")
    (workdir / "app.py").write_text("x = 2\n", encoding="utf-8")

    sha = await ws.commit_and_push(
        workdir, "vesper/quality-abc123", "vesper: cambio", "acme/repo", "ghs_secreto"
    )

    assert len(sha) == 40
    _, ramas, _ = await services._run_git(origin, "branch", "--list")
    assert "vesper/quality-abc123" in ramas


def test_redact_tapa_el_token():
    crudo = "push a https://x:ghs_abc@github.com fallo"  # pragma: allowlist secret
    assert services._redact(crudo, "ghs_abc") == "push a https://x:***@github.com fallo"
    assert services._redact("sin token", "") == "sin token"


async def test_push_fallido_no_filtra_el_token(tmp_path, monkeypatch):
    """El error de un push fallido acaba en `error_message` del job y en la UI.

    git suele redactar el userinfo de la URL por su cuenta, pero eso depende de
    la version y del transporte: `_redact` lo garantiza pase lo que pase.
    """
    origin, _ = await _local_origin(tmp_path)
    monkeypatch.setattr(services, "_authenticated_remote", lambda full, tok: str(origin))

    ws = services.WorkspaceService(base=str(tmp_path / "ws"))
    workdir = await ws.clone("tenant-1", "repo-1", "acme/repo", "develop", "ghs_secreto")
    await ws.configure_git(workdir)
    (workdir / "app.py").write_text("x = 3\n", encoding="utf-8")

    token = "ghs_estonopuedeaparecer"
    monkeypatch.setattr(
        services, "_authenticated_remote", lambda full, tok: f"https://x:{token}@127.0.0.1:1/x.git"
    )
    with pytest.raises(RuntimeError) as exc:
        await ws.commit_and_push(workdir, "rama", "msg", "acme/repo", token)

    assert token not in str(exc.value)


# -------------------------------------------------------  Rama base del job
async def test_create_job_usa_la_rama_por_defecto_del_repo(db_session: AsyncSession):
    """Sin `ref` explicito manda el default branch del repo, no "main".

    Con "main" literal, en un repo con `develop`/`master` el clone fallaba con
    `Remote branch main not found`.
    """
    tenant = Tenant(name="Ref WS", slug=f"ref-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id, default_branch="develop")

    svc = services.ReviewService(db_session)
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    assert job.ref == "develop"

    explicito = await svc.create_job(
        tenant,
        JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs, ref="feature/x"),
    )
    assert explicito.ref == "feature/x"


async def test_run_job_pasa_el_token_al_push(db_session: AsyncSession, patched_github):
    tenant = Tenant(name="Push WS", slug=f"push-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    diff = [{"file": "src/util.py", "patch": "@@ -1 +1 @@"}]
    ws = _FakeWorkspace(diff)
    svc = services.ReviewService(
        db_session,
        workspace_svc=ws,
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port, diff=diff)
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.quality)
    )
    await db_session.commit()
    await svc.run_job(job.id, tenant.id)

    assert ws.pushed_with == (repo.full_name, "ghs_faketoken")


async def test_error_vacio_registra_al_menos_el_tipo(db_session: AsyncSession, monkeypatch):
    """Una excepcion sin mensaje no puede dejar el job sin explicacion.

    `NotImplementedError` —lo que lanza `create_subprocess_exec` bajo el
    SelectorEventLoop que `uvicorn --reload` instala en Windows— tiene `str()`
    vacio, y el job quedaba en `failed` con `{"error": ""}`.
    """
    tenant = Tenant(name="Mudo WS", slug=f"mudo-{_un()}")
    db_session.add(tenant)
    await db_session.flush()
    repo = await _make_repo(db_session, tenant.id)

    async def _boom(installation_id, client=None):
        raise NotImplementedError

    monkeypatch.setattr(services, "get_installation_token", _boom)

    svc = services.ReviewService(
        db_session,
        workspace_svc=_FakeWorkspace(),
        engine_factory=_engine_with(
            lambda workdir, port, env=None: FakeOpencodeRunner(workdir, port)
        ),
    )
    job = await svc.create_job(
        tenant, JobCreateRequest(repository_id=repo.id, task_type=TaskType.docs)
    )
    await db_session.commit()

    await svc.run_job(job.id, tenant.id)
    await db_session.refresh(job)

    assert job.status == JobStatus.failed
    assert job.error_message["error"].startswith("NotImplementedError")


async def test_clone_excluye_artefactos_efimeros(tmp_path, monkeypatch):
    """Los `.pyc` que genera el propio agente no pueden acabar en el PR.

    El primer PR real salio con dos `__pycache__/*.pyc`: el language server del
    agente compilo el proyecto y `git add -A` se los llevo. Muchos repos no
    tienen `.gitignore`, asi que la exclusion la pone el clon.
    """
    origin, _ = await _local_origin(tmp_path)
    monkeypatch.setattr(services, "_authenticated_remote", lambda full, tok: str(origin))

    ws = services.WorkspaceService(base=str(tmp_path / "ws"))
    workdir = await ws.clone("t", "r", "acme/repo", "develop", "ghs_x")

    # El "agente" toca un archivo de verdad y de paso deja bytecode.
    (workdir / "app.py").write_text("x = 2\n", encoding="utf-8")
    (workdir / "__pycache__").mkdir()
    (workdir / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"\x00basura")
    (workdir / "node_modules").mkdir()
    (workdir / "node_modules" / "dep.js").write_text("//\n", encoding="utf-8")

    ficheros = {d["file"] for d in await ws.capture_diff(workdir)}

    assert "app.py" in ficheros
    assert not any(f.startswith("__pycache__") for f in ficheros), ficheros
    assert not any(f.startswith("node_modules") for f in ficheros), ficheros

    # Y tampoco se cuelan por el `git add -A` del commit.
    await ws.configure_git(workdir)
    await ws.commit_and_push(workdir, "vesper/x", "vesper: cambio", "acme/repo", "ghs_x")
    _, listado, _ = await services._run_git(workdir, "show", "--name-only", "--format=", "HEAD")
    assert listado.split() == ["app.py"]


async def test_exclude_no_pisa_el_contenido_previo(tmp_path, monkeypatch):
    origin, _ = await _local_origin(tmp_path)
    monkeypatch.setattr(services, "_authenticated_remote", lambda full, tok: str(origin))

    ws = services.WorkspaceService(base=str(tmp_path / "ws"))
    workdir = await ws.clone("t", "r", "acme/repo", "develop", "ghs_x")
    exclude = workdir / ".git" / "info" / "exclude"
    exclude.write_text("# cabecera de git\nmi-patron-propio\n", encoding="utf-8")

    services.WorkspaceService._ignore_ephemeral(workdir)

    contenido = exclude.read_text(encoding="utf-8")
    assert "mi-patron-propio" in contenido
    assert "__pycache__/" in contenido


async def test_clone_reutiliza_un_workspace_sucio(tmp_path, monkeypatch):
    """Un segundo job sobre el mismo repo no puede morir por el clon anterior.

    `shutil.rmtree(..., ignore_errors=True)` fallaba a medias en Windows —los
    objetos de `.git` son de solo lectura— y el clone siguiente moria con
    "destination path already exists and is not an empty directory".
    """
    origin, _ = await _local_origin(tmp_path)
    monkeypatch.setattr(services, "_authenticated_remote", lambda full, tok: str(origin))

    ws = services.WorkspaceService(base=str(tmp_path / "ws"))
    primero = await ws.clone("t", "r", "acme/repo", "develop", "ghs_x")
    (primero / "residuo.txt").write_text("de la corrida anterior\n", encoding="utf-8")

    segundo = await ws.clone("t", "r", "acme/repo", "develop", "ghs_x")

    assert segundo == primero
    assert not (segundo / "residuo.txt").exists(), "el workspace debe quedar limpio"
    assert (segundo / "app.py").exists()


async def test_la_actividad_del_agente_llega_a_la_ui_sin_rafagas(monkeypatch):
    """El agente lanza herramientas a rafagas: la UI recibe la primera al momento y
    la ULTIMA al cerrar la ventana. Quedarse solo con la primera dejaba «Leyendo
    a.py» en pantalla los 20 min que tardaba la suite lanzada justo despues."""
    from src.agents.engine import Activity

    sent: list[tuple] = []

    async def fake_push(job_id, kind, data):
        sent.append((kind, data))

    monkeypatch.setattr(services, "push_event", fake_push)
    monkeypatch.setattr(services, "ACTIVITY_THROTTLE_SECONDS", 0.2)
    publish = services._activity_publisher(uuid.uuid4())
    await publish(Activity("read", "a.py"))
    await publish(Activity("read", "b.py"))
    await publish(Activity("bash"))
    assert sent == [("activity", {"tool": "read", "path": "a.py"})]

    await asyncio.sleep(0.4)
    assert sent[-1] == ("activity", {"tool": "bash", "path": None})
    assert len(sent) == 2
