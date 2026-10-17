"""F6b — test de integración de `DockerOpencodeEngine` contra un Docker real.

Se salta automáticamente si no hay un daemon de Docker accesible o si no está
construida la imagen `vesper-agent:1`. En CI lo corre `.github/workflows/docker-engine-ci.yml`
después de ejecutar `deploy/jobs-host/setup.sh`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import docker
import pytest
from docker.errors import DockerException, NotFound

from evals.tasks import FIXTURE
from src.agents.docker_engine import DockerOpencodeEngine
from src.agents.engine import Activity, EngineResult
from src.core.config import settings
from src.review_jobs.services import WorkspaceService

FAKE_TOKEN = "ghs_" + "INTEGRATIONTESTTOKEN0123456789abcdef"


@pytest.fixture(autouse=True)
def _override_get_db():
    """Este test no usa Postgres: anula el fixture autouse de `tests/conftest.py`."""
    yield


def _require_docker() -> docker.DockerClient:
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(settings.agent_image)
        return client
    except Exception as exc:
        if os.environ.get("VESPER_REQUIRE_DOCKER") == "1":
            pytest.fail(f"Docker obligatorio en CI pero no disponible: {exc}")
        pytest.skip(f"Docker o la imagen {settings.agent_image} no están disponibles: {exc}")


def _ensure_network(client: docker.DockerClient) -> None:
    try:
        client.networks.get(settings.agent_docker_network)
    except NotFound:
        client.networks.create(settings.agent_docker_network, driver="bridge")


def _git(workdir: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@vesper.local", *args],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.docker
async def test_docker_engine_real_ciclo_completo(tmp_path: Path) -> None:
    client = _require_docker()
    _ensure_network(client)

    workdir = tmp_path / "repo"
    shutil.copytree(FIXTURE, workdir)
    _git(workdir, "init", "-q")
    _git(workdir, "add", "-A")
    _git(workdir, "commit", "-q", "-m", "fixture inicial con bug en suma")
    # Simula un clon autenticado con x-access-token en remote y reflogs para comprobar
    # contra un contenedor real que nada de eso cruza a `/workspace/.git`.
    _git(
        workdir,
        "remote",
        "add",
        "origin",
        f"https://x-access-token:{FAKE_TOKEN}@github.com/acme/repo-basico.git",
    )
    logs_dir = workdir / ".git" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "HEAD").write_text(
        f"0000 1111 test <t@v> 1 +0000\tclone: from https://x-access-token:{FAKE_TOKEN}@github.com/acme/repo-basico.git\n",
        encoding="utf-8",
    )

    job_id = f"it-{uuid.uuid4().hex[:10]}"
    engine = DockerOpencodeEngine(tmp_path, job_id, tenant_id="tenant-it")

    async def fake_drive(runner, _workdir, _prompt, _model, _on_activity) -> EngineResult:
        # `_provision` ya arrancó `opencode serve` en el contenedor y `runner.wait_ready()`
        # comprobó por HTTP que responde en el puerto efímero publicado.
        assert runner.port > 0

        code, uid_out = await engine._exec("id -u && id -un")
        assert code == 0
        assert uid_out.decode().split() == ["1000", "agent"]

        # El token de instalación de GitHub jamás puede aparecer dentro del contenedor.
        leak_code, leak_out = await engine._exec(f"grep -rn {FAKE_TOKEN} /workspace/.git || true")
        assert leak_code == 0
        assert leak_out.decode().strip() == ""

        # Sustituye al LLM: corrige el bug de `suma` dentro del contenedor como `agent`.
        fix_code, fix_out = await engine._exec(
            'python -c "'
            "from pathlib import Path; "
            "p = Path('calc.py'); "
            "p.write_text(p.read_text().replace('return a - b', 'return a + b', 1))"
            '"'
        )
        assert fix_code == 0, fix_out.decode("utf-8", "replace")
        return EngineResult(tokens_input=12, tokens_output=6)

    engine._drive = fake_drive  # type: ignore[method-assign]

    async def noop(_: Activity) -> None:
        return None

    try:
        result = await engine.run(
            workdir,
            "Arregla suma en calc.py",
            "deepseek/deepseek-chat",
            {"deepseek": "sk-test-integration"},
            noop,
        )
    finally:
        await engine.stop()

    assert result.checks is not None
    assert len(result.checks.commands) == 1
    assert result.checks.before.exit_code != 0, result.checks.before.log_tail
    assert result.checks.after.exit_code == 0, result.checks.after.log_tail

    # El parche volvió del contenedor y se aplicó en el clon del worker:
    assert "return a + b" in (workdir / "calc.py").read_text(encoding="utf-8")
    diffs = await WorkspaceService(tmp_path).capture_diff(workdir)
    assert len(diffs) == 1
    assert diffs[0]["file"] == "calc.py"
    assert "return a + b" in diffs[0]["patch"]

    # `_teardown` eliminó el contenedor:
    remaining = client.containers.list(all=True, filters={"label": f"vesper.job={job_id}"})
    assert remaining == []
    try:
        vol = client.volumes.get("vesper-cache-tenant-it")
        vol.remove(force=True)
    except DockerException:
        pass
    client.close()
