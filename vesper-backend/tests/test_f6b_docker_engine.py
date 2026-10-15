"""F6b: DockerOpencodeEngine con un cliente de Docker falso (sin Docker, sin opencode)."""

import asyncio
import io
import json
import shutil
import subprocess
import tarfile
from types import SimpleNamespace

import pytest
from docker.errors import DockerException, ImageNotFound

from src.agents import docker_engine
from src.agents.docker_engine import ContainerRunner, DockerOpencodeEngine, _runtime_host
from src.agents.engine import EngineResult
from src.review_jobs.constants import EPHEMERAL_PATTERNS

# Se arma por concatenación: un literal así lo rechazaría el hook de detect-secrets.
FAKE_TOKEN = "ghs_" + "FAKEINSTALLATIONTOKEN0123456789abcd"
AWS_KEY = "AKIA" + "IOSFODNN7EXAMPLE"


# ------------------------------------------------------------  Doble de Docker
class FakeContainer:
    def __init__(self, client):
        self.client = client
        self.ports = {"4096/tcp": [{"HostIp": "0.0.0.0", "HostPort": "32768"}]}
        self.archives: list[tuple[str, bytes]] = []
        self.execs: list[tuple[list, dict]] = []
        self.removed = 0

    def reload(self):
        pass

    def put_archive(self, path, data):
        self.archives.append((path, data))
        return True

    def exec_run(self, cmd, **kw):
        self.execs.append((cmd, kw))
        line = " ".join(cmd)
        for needle, answer in self.client.rules:
            if needle in line:
                return answer() if callable(answer) else answer
        return (0, (b"", b""))

    def remove(self, force=False):
        assert force is True
        self.removed += 1


class FakeClient:
    def __init__(self):
        self.rules: list[tuple[str, object]] = []
        self.run_calls: list[dict] = []
        self.container: FakeContainer | None = None
        self.closed = False
        self.containers = SimpleNamespace(run=self._run, list=self._list)

    def _run(self, **kw):
        self.run_calls.append(kw)
        self.container = FakeContainer(self)
        return self.container

    def _list(self, **kw):
        return [self.container] if self.container else []

    def close(self):
        self.closed = True


@pytest.fixture
def client():
    return FakeClient()


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    # Semáforo nuevo por test y sin esperar a un opencode que no existe.
    monkeypatch.setattr(docker_engine, "_SLOTS", asyncio.Semaphore(2))

    async def ready(self, *a, **kw):
        pass

    monkeypatch.setattr(ContainerRunner, "wait_ready", ready)

    async def drive(self, runner, workdir, prompt, model, on_activity):
        return EngineResult(tokens_input=7)

    monkeypatch.setattr(DockerOpencodeEngine, "_drive", drive)
    monkeypatch.delenv("DOCKER_HOST", raising=False)


def _engine(tmp_path, client, tenant="t1", job="j1"):
    return DockerOpencodeEngine(
        tmp_path / "base", job, tenant_id=tenant, client_factory=lambda: client
    )


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
    )


def _repo(path, files=None):
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    for name, content in (files or {"a.txt": "hola\n"}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(content if isinstance(content, bytes) else content.encode())
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "base")
    return path


async def _run(engine, workdir):
    async def noop(_a):
        pass

    return await engine.run(workdir, "arregla", "p/m", {"openai": "sk-test"}, noop)


def _members(data: bytes) -> dict[str, tuple[tarfile.TarInfo, bytes]]:
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        return {
            m.name.removeprefix("./"): (m, tar.extractfile(m).read() if m.isfile() else b"")
            for m in tar.getmembers()
        }


# ------------------------------------------------------------  Contenedor
async def test_contenedor_sin_privilegios_y_acotado(tmp_path, client):
    wd = _repo(tmp_path / "wd")
    await _run(_engine(tmp_path, client), wd)
    kw = client.run_calls[0]
    assert "privileged" not in kw
    assert kw["cap_drop"] == ["ALL"]
    assert kw["security_opt"] == ["no-new-privileges"]
    assert kw["user"] == "agent"
    assert kw["pids_limit"] == 512
    assert kw["nano_cpus"] == 2_000_000_000
    assert kw["mem_limit"] == "4g"
    assert kw["network"] == "vesper-jobs"
    assert kw["command"] == ["sleep", "infinity"]
    assert kw["ports"] == {"4096/tcp": None}
    assert kw["labels"] == {"vesper.job": "j1", "vesper.tenant": "t1"}
    assert kw["detach"] is True


async def test_cache_de_paquetes_es_por_tenant(tmp_path):
    wd = _repo(tmp_path / "wd")
    volumes = []
    for tenant in ("tenant-a", "tenant-b"):
        c = FakeClient()
        await _run(_engine(tmp_path, c, tenant=tenant, job=f"j-{tenant}"), wd)
        volumes.append(c.run_calls[0]["volumes"])
    assert volumes[0] == {"vesper-cache-tenant-a": {"bind": "/home/agent/.cache", "mode": "rw"}}
    assert list(volumes[1]) == ["vesper-cache-tenant-b"]


async def test_sube_repo_y_credenciales_como_agent(tmp_path, client):
    wd = _repo(tmp_path / "wd", {"src/x.py": "print(1)\n"})
    await _run(_engine(tmp_path, client), wd)
    (p1, repo_tar), (p2, auth_tar) = client.container.archives
    assert (p1, p2) == ("/workspace", "/home/agent")
    repo = _members(repo_tar)
    assert "src/x.py" in repo and any(n.startswith(".git/") for n in repo)
    assert {m.uid for m, _ in repo.values()} == {1000}
    assert {m.gid for m, _ in repo.values()} == {1000}
    auth = _members(auth_tar)
    meta, body = auth[".local/share/opencode/auth.json"]
    assert json.loads(body) == {"openai": {"type": "api", "key": "sk-test"}}
    assert meta.uid == 1000 and meta.mode == 0o600


async def test_token_de_github_nunca_entra_al_contenedor(tmp_path, client):
    wd = _repo(tmp_path / "wd")
    # Peor caso: un clon que SÍ guardara credenciales en su config.
    _git(wd, "remote", "add", "origin", f"https://x-access-token:{FAKE_TOKEN}@github.com/o/r.git")
    _git(wd, "config", "http.extraheader", f"AUTHORIZATION: basic {FAKE_TOKEN}")
    await _run(_engine(tmp_path, client), wd)

    c = client.container
    for _path, data in c.archives:
        assert FAKE_TOKEN.encode() not in data
        for _m, body in _members(data).values():
            assert FAKE_TOKEN.encode() not in body
    assert FAKE_TOKEN not in json.dumps(client.run_calls, default=str)
    assert FAKE_TOKEN not in json.dumps(c.execs, default=str)
    config = _members(c.archives[0][1])[".git/config"][1].decode()
    assert "github.com/o/r.git" in config  # el remote sigue, sin credenciales
    assert "extraheader" not in config


async def test_opencode_arranca_con_el_mismo_password_que_el_runner(tmp_path, client):
    wd = _repo(tmp_path / "wd")
    runner = await _engine(tmp_path, client)._provision(wd, {"openai": "k"})
    serve = next(kw for cmd, kw in client.container.execs if "serve" in cmd)
    assert serve["environment"]["OPENCODE_SERVER_PASSWORD"] == runner.server_password
    assert serve["user"] == "agent" and serve["detach"] is True
    assert runner.auth == ("opencode", runner.server_password)
    assert runner.port == 32768
    await runner.start()  # no-op: el proceso vive en el contenedor
    await runner.stop()


async def test_efimeros_se_excluyen_antes_de_que_trabaje_el_agente(tmp_path, client):
    wd = _repo(tmp_path / "wd")
    await _run(_engine(tmp_path, client), wd)
    first = " ".join(client.container.execs[0][0])
    assert ".git/info/exclude" in first
    assert all(p in first for p in EPHEMERAL_PATTERNS)


@pytest.mark.parametrize(
    ("docker_host", "expected"),
    [
        ("tcp://10.0.0.5:2376", "10.0.0.5"),
        ("https://dock.example:2376", "dock.example"),
        ("unix:///var/run/docker.sock", "127.0.0.1"),
        ("npipe:////./pipe/docker_engine", "127.0.0.1"),
        ("", "127.0.0.1"),
    ],
)
def test_host_del_runner_sale_de_docker_host(monkeypatch, docker_host, expected):
    monkeypatch.setenv("DOCKER_HOST", docker_host)
    assert _runtime_host() == expected


# ------------------------------------------------------------  Suites
def _node_repo(tmp_path):
    return _repo(
        tmp_path / "wd",
        {"package.json": json.dumps({"scripts": {"test": "vitest"}}), "pnpm-lock.yaml": ""},
    )


async def test_suites_antes_y_despues_del_agente(tmp_path, client):
    wd = _node_repo(tmp_path)
    order = []
    runs = iter([(0, (b"ok antes", b"")), (1, (b"fallo despues", b""))])

    def test_cmd():
        order.append("test")
        return next(runs)

    async def drive(self, runner, workdir, prompt, model, on_activity):
        order.append("agente")
        return EngineResult()

    client.rules = [("pnpm install", lambda: order.append("install") or (0, (b"", b"")))]
    client.rules.append(("pnpm test", test_cmd))
    engine = _engine(tmp_path, client)
    engine._drive = lambda *a, **k: drive(engine, *a, **k)
    result = await _run(engine, wd)

    assert order == ["install", "test", "agente", "install", "test"]
    checks = result.checks
    assert checks.before.exit_code == 0 and "ok antes" in checks.before.log_tail
    assert checks.after.exit_code == 1 and "fallo despues" in checks.after.log_tail
    suite = [c for c, kw in client.container.execs if "pnpm test" in " ".join(c)][0]
    assert suite[:2] == ["bash", "-lc"] and suite[2].startswith("timeout 900 bash -lc ")
    kw = [kw for c, kw in client.container.execs if "pnpm test" in " ".join(c)][0]
    assert kw["workdir"] == "/workspace" and kw["user"] == "agent"


async def test_timeout_124_marca_timed_out(tmp_path, client):
    wd = _node_repo(tmp_path)
    client.rules = [("pnpm test", (124, (b"colgado", b"")))]
    result = await _run(_engine(tmp_path, client), wd)
    assert result.checks.before.timed_out and result.checks.before.exit_code == 124
    assert result.checks.after.timed_out


async def test_install_roto_no_corre_el_test(tmp_path, client):
    wd = _node_repo(tmp_path)
    client.rules = [("pnpm install", (1, (b"", b"ERR_PNPM")))]
    result = await _run(_engine(tmp_path, client), wd)
    assert result.checks.before.exit_code == 1 and "ERR_PNPM" in result.checks.before.log_tail
    assert not any("pnpm test" in " ".join(c) for c, _ in client.container.execs)


async def test_sin_comandos_exit_code_none(tmp_path, client):
    result = await _run(_engine(tmp_path, client), _repo(tmp_path / "wd"))
    assert result.checks.commands == []
    assert result.checks.before.exit_code is None and result.checks.after.exit_code is None


async def test_la_salida_de_la_suite_se_redacta(tmp_path, client):
    wd = _node_repo(tmp_path)
    client.rules = [("pnpm test", (1, (f"key={AWS_KEY} falló".encode(), b"")))]
    result = await _run(_engine(tmp_path, client), wd)
    tail = result.checks.before.log_tail
    assert AWS_KEY not in tail and "[REDACTED]" in tail


# ------------------------------------------------------------  Parche
def _agent_patch(tmp_path):
    """Un repo 'dentro del contenedor' que el agente edita; devuelve (host_repo, parche)."""
    files = {"a.txt": "hola\n", "borrar.txt": "adios\n", "bin.dat": b"\x00\x01\x02\xff"}
    host = _repo(tmp_path / "wd", files)
    box = tmp_path / "box"
    shutil.copytree(host, box)
    (box / "a.txt").write_text("hola mundo\n")
    (box / "borrar.txt").unlink()
    (box / "nuevo.bin").write_bytes(bytes(range(256)))
    (box / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    _git(box, "add", "-A")
    return host, _git(box, "diff", "--cached", "--binary").stdout


async def test_parche_se_aplica_en_el_clon_del_worker(tmp_path, client):
    host, patch = _agent_patch(tmp_path)
    client.rules = [("git diff --cached --binary", (0, (patch, b"")))]
    await _run(_engine(tmp_path, client), host)

    assert (host / "a.txt").read_text() == "hola mundo\n"
    assert not (host / "borrar.txt").exists()
    assert (host / "nuevo.bin").read_bytes() == bytes(range(256))
    assert (host / "bin.dat").read_bytes() == b"\xff\xfe\x00\x01"
    staged = _git(host, "diff", "--cached", "--name-status").stdout.decode()
    assert "D\tborrar.txt" in staged and "A\tnuevo.bin" in staged and "M\ta.txt" in staged


async def test_parche_vacio_no_toca_nada(tmp_path, client):
    host = _repo(tmp_path / "wd")
    await _run(_engine(tmp_path, client), host)
    assert _git(host, "status", "--porcelain").stdout == b""


async def test_parche_que_no_aplica_da_error_legible(tmp_path, client):
    host = _repo(tmp_path / "wd")
    client.rules = [("git diff --cached --binary", (0, (b"esto no es un parche\n", b"")))]
    with pytest.raises(RuntimeError, match="No se pudo aplicar el cambio del agente"):
        await _run(_engine(tmp_path, client), host)


async def test_parche_no_puede_escribir_en_git(tmp_path, client):
    host = _repo(tmp_path / "wd")
    evil = (
        b"diff --git a/.git/hooks/pre-commit b/.git/hooks/pre-commit\n"
        b"new file mode 100755\n--- /dev/null\n+++ b/.git/hooks/pre-commit\n@@ -0,0 +1 @@\n+x\n"
    )
    client.rules = [("git diff --cached --binary", (0, (evil, b"")))]
    with pytest.raises(RuntimeError, match="No se pudo aplicar"):
        await _run(_engine(tmp_path, client), host)
    assert not (host / ".git" / "hooks" / "pre-commit").exists()


# ------------------------------------------------------------  Limpieza y errores
async def test_teardown_borra_el_contenedor_en_exito(tmp_path, client):
    engine = _engine(tmp_path, client)
    await _run(engine, _repo(tmp_path / "wd"))
    await engine.stop()
    assert client.container.removed == 1 and client.closed
    assert docker_engine._SLOTS._value == 2


async def test_teardown_borra_el_contenedor_si_el_job_falla(tmp_path, client, monkeypatch):
    async def boom(self, *a, **k):
        raise RuntimeError("el modelo no respondio")

    monkeypatch.setattr(DockerOpencodeEngine, "_drive", boom)
    engine = _engine(tmp_path, client)
    with pytest.raises(RuntimeError, match="modelo"):
        await _run(engine, _repo(tmp_path / "wd"))
    await engine.stop()
    assert client.container.removed == 1
    assert docker_engine._SLOTS._value == 2


async def test_teardown_borra_el_contenedor_si_cancelan_el_job(tmp_path, client, monkeypatch):
    started = asyncio.Event()

    async def hang(self, *a, **k):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(DockerOpencodeEngine, "_drive", hang)
    engine = _engine(tmp_path, client)
    task = asyncio.create_task(_run(engine, _repo(tmp_path / "wd")))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await engine.stop()
    assert client.container.removed == 1
    assert docker_engine._SLOTS._value == 2


async def test_cancelado_antes_de_guardar_el_contenedor_se_busca_por_etiqueta(tmp_path, client):
    engine = _engine(tmp_path, client)
    engine._docker = client
    client.container = FakeContainer(client)  # `containers.run` terminó en su hilo, tarde
    engine._acquired = True
    await docker_engine._SLOTS.acquire()
    await engine.stop()
    assert client.container.removed == 1
    assert docker_engine._SLOTS._value == 2


async def test_semaforo_se_libera_una_sola_vez(tmp_path, client):
    engine = _engine(tmp_path, client)
    await _run(engine, _repo(tmp_path / "wd"))
    assert docker_engine._SLOTS._value == 1
    await engine.stop()
    await engine.stop()
    assert docker_engine._SLOTS._value == 2  # no 3


async def test_stop_sin_provision_no_libera_un_hueco_ajeno(tmp_path, client):
    await _engine(tmp_path, client).stop()
    assert docker_engine._SLOTS._value == 2


async def test_si_provision_falla_a_medias_stop_libera_y_limpia(tmp_path, client):
    client.containers.run = lambda **kw: (_ for _ in ()).throw(ImageNotFound("vesper-agent:1"))
    engine = _engine(tmp_path, client)
    with pytest.raises(RuntimeError, match="No se pudo arrancar el entorno del job"):
        await _run(engine, _repo(tmp_path / "wd"))
    await engine.stop()
    assert docker_engine._SLOTS._value == 2


async def test_docker_caido_da_mensaje_legible_y_sin_fallback(tmp_path):
    def down():
        raise DockerException("Error while fetching server API version: Connection refused")

    engine = DockerOpencodeEngine(tmp_path / "b", "j", tenant_id="t", client_factory=down)
    with pytest.raises(RuntimeError, match="No se pudo arrancar el entorno del job: Error while"):
        await _run(engine, _repo(tmp_path / "wd"))
    await engine.stop()
    assert docker_engine._SLOTS._value == 2


async def test_tope_de_jobs_simultaneos(tmp_path, monkeypatch):
    monkeypatch.setattr(docker_engine, "_SLOTS", asyncio.Semaphore(1))
    wd = _repo(tmp_path / "wd")
    first, second = (
        _engine(tmp_path, FakeClient(), job="a"),
        _engine(tmp_path, FakeClient(), job="b"),
    )
    await first._provision(wd, {})
    waiting = asyncio.create_task(second._provision(wd, {}))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    await first.stop()
    await asyncio.wait_for(waiting, 2)
    await second.stop()
