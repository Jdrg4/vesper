"""Motor con un contenedor sin privilegios por job (F6b, spec §2, §3, §6, §7).

El repo del tenant y todo lo que el agente ejecute corren DENTRO del contenedor, en un host
de Docker aparte del backend. El worker solo sube el repo (sin credenciales de GitHub), lee
el parche que el agente produjo y lo aplica sobre su clon; clonar, `validate_diff`, commit y
PR siguen en `services.py`, iguales para cualquier motor.

El SDK de Docker es síncrono: cada llamada va por `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import posixpath
import re
import secrets
import shlex
import tarfile
import time
from pathlib import Path
from urllib.parse import urlparse

import docker
import requests
import structlog
from docker.errors import DockerException

from src.agents.engine import ActivityCallback, EngineResult
from src.agents.opencode_engine import OpencodeEngine
from src.agents.runner import OPENCODE_HOST, OpencodeRunner
from src.agents.verification import (
    SuiteRun,
    TestCommand,
    Verification,
    detect_test_commands,
    tail_redacted,
)
from src.core.config import settings
from src.review_jobs.constants import EPHEMERAL_PATTERNS

logger = structlog.get_logger(__name__)

# uid/gid de `agent` en la imagen: los archivos subidos tienen que ser suyos.
AGENT_UID = 1000
OPENCODE_PORT = "4096/tcp"
WORKSPACE = "/workspace"
START_ERROR = "No se pudo arrancar el entorno del job"
# `timeout` de coreutils sale con 124 cuando corta el comando.
TIMEOUT_EXIT = 124

# Tope de jobs simultáneos en el host de Docker. Módulo y no instancia: es un recurso
# compartido por todos los jobs del proceso (cada motor es de un solo job).
_SLOTS = asyncio.Semaphore(settings.agent_max_jobs)

# Credenciales dentro de la config de git (usuario:clave dentro de la URL del remote, o un
# `http.extraheader`): jamás deben cruzar al contenedor, donde corre código del tenant.
_URL_USERINFO = re.compile(r"(\w+://)[^/@\s]+@")
_AUTH_LINE = re.compile(r"extraheader|authorization", re.I)


def _runtime_host() -> str:
    """Host donde se publican los puertos del contenedor: el del `DOCKER_HOST` remoto."""
    parsed = urlparse(os.environ.get("DOCKER_HOST", ""))
    if parsed.scheme in ("tcp", "http", "https") and parsed.hostname:
        return parsed.hostname
    return OPENCODE_HOST  # socket unix o sin definir: Docker local


def _scrub_git_config(raw: bytes) -> bytes:
    lines = [ln for ln in raw.decode("utf-8", "replace").splitlines() if not _AUTH_LINE.search(ln)]
    return _URL_USERINFO.sub(r"\1", "\n".join(lines) + "\n").encode()


def _owned(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = AGENT_UID
    info.uname = info.gname = "agent"
    return info


def _repo_tar(workdir: Path) -> bytes:
    """El clon entero (con `.git`, para poder sacar el diff) como tar de `agent`."""
    buf = io.BytesIO()
    config = workdir / ".git" / "config"

    def keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        # La config va aparte, ya sin credenciales (ver `_scrub_git_config`).
        if posixpath.normpath(info.name) == ".git/config":
            return None
        return _owned(info)

    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(workdir, arcname=".", filter=keep)
        if config.is_file():
            data = _scrub_git_config(config.read_bytes())
            info = _owned(tarfile.TarInfo(".git/config"))
            info.size, info.mode = len(data), 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _auth_tar(credentials: dict[str, str]) -> bytes:
    """`~/.local/share/opencode/auth.json` con las keys del tenant (misma forma que
    `AgentSandbox.setup`). Entra como archivo y no como env var: el entorno lo heredan
    todos los procesos que el agente lance."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        # Dirs explícitos: los que crea el tar solos quedarían de root e inescribibles.
        for d in (".local", ".local/share", ".local/share/opencode"):
            info = _owned(tarfile.TarInfo(d))
            info.type, info.mode = tarfile.DIRTYPE, 0o700
            tar.addfile(info)
        data = json.dumps(
            {provider: {"type": "api", "key": key} for provider, key in credentials.items()}
        ).encode()
        info = _owned(tarfile.TarInfo(".local/share/opencode/auth.json"))
        info.size, info.mode = len(data), 0o600
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _text(output) -> bytes:
    """`exec_run(demux=True)` devuelve `(stdout, stderr)`, con `None` si un canal vino vacío."""
    if isinstance(output, tuple):
        return b"".join(part or b"" for part in output)
    return output or b""


class ContainerRunner(OpencodeRunner):
    """El proceso vive en el contenedor: aquí solo se habla HTTP con él.

    `start`/`stop` no hacen nada (el contenedor lo borra `_teardown`), pero se reusa el
    resto del runner, y con él `wait_ready`, `auth` y el cliente de sesiones.
    """

    def __init__(self, workdir: str, port: int, *, host: str, password: str) -> None:
        super().__init__(workdir, port, host=host)
        self.server_password = password  # el mismo que recibió `opencode serve` en el contenedor

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class DockerOpencodeEngine(OpencodeEngine):
    def __init__(
        self,
        workspace_base: Path,
        job_id: str,
        *,
        tenant_id: str,
        client_factory=docker.from_env,
        **kw,
    ) -> None:
        super().__init__(workspace_base, job_id, **kw)
        self.tenant_id = str(tenant_id)
        self._client_factory = client_factory
        self._docker = None
        self._container = None
        self._acquired = False

    # ------------------------------------------------------------  Ciclo del job
    async def run(
        self,
        workdir: Path,
        prompt: str,
        model: str,
        credentials: dict[str, str],
        on_activity: ActivityCallback,
    ) -> EngineResult:
        workdir = Path(workdir)
        runner = await self._provision(workdir, credentials)
        commands = await asyncio.to_thread(detect_test_commands, workdir)
        before = await self._suite(commands)
        if commands:
            await self._exclude_suite_artifacts()
        result = await self._drive(runner, workdir, prompt, model, on_activity)
        # El parche se toma ANTES de la suite posterior: así lo que esta genere
        # (builds, caches) no puede colarse en el diff del PR.
        patch = await self._extract_patch()
        after = await self._suite(commands)
        await self._apply_patch(workdir, patch)
        result.checks = Verification(commands, before, after)
        return result

    async def _provision(self, workdir: Path, credentials: dict[str, str]) -> OpencodeRunner:
        # Antes que nada: si algo falla de aquí en adelante `_teardown` lo libera una vez.
        await _SLOTS.acquire()
        self._acquired = True
        try:
            self._docker = await self._call(self._client_factory)
            password = secrets.token_urlsafe(32)
            self._container = await self._call(self._docker.containers.run, **self._run_kwargs())
            await self._call(
                self._container.put_archive, WORKSPACE, await asyncio.to_thread(_repo_tar, workdir)
            )
            await self._call(
                self._container.put_archive,
                "/home/agent",
                await asyncio.to_thread(_auth_tar, credentials),
            )
            # `git add -A` se lleva lo que genera el propio agente: que ni el diff lo vea.
            code, _ = await self._exec(
                "mkdir -p .git/info && printf '%s\\n' "
                + " ".join(shlex.quote(p) for p in EPHEMERAL_PATTERNS)
                + " >> .git/info/exclude"
            )
            if code != 0:
                raise RuntimeError(f"{START_ERROR}: no se pudo preparar el repo (exit {code})")
            await self._call(
                self._container.exec_run,
                ["opencode", "serve", "--pure", "--port", "4096", "--hostname", "0.0.0.0"],
                detach=True,
                environment={
                    "OPENCODE_SERVER_PASSWORD": password,
                    "XDG_DATA_HOME": "/home/agent/.local/share",
                    "XDG_CONFIG_HOME": "/home/agent/.config",
                },
                workdir=WORKSPACE,
                user="agent",
            )
            await self._call(self._container.reload)
            try:
                port = int(self._container.ports[OPENCODE_PORT][0]["HostPort"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise RuntimeError(f"{START_ERROR}: el contenedor no publicó el puerto") from exc
            self._runner = ContainerRunner(
                str(workdir), port, host=_runtime_host(), password=password
            )
            await self._runner.wait_ready()
            logger.info("agent_container_ready", job_id=self.job_id, tenant_id=self.tenant_id)
            return self._runner
        except TimeoutError as exc:
            raise RuntimeError(f"{START_ERROR}: opencode no respondió ({exc})") from exc

    def _run_kwargs(self) -> dict:
        return {
            "image": settings.agent_image,
            "command": ["sleep", "infinity"],  # tini (entrypoint de la imagen) es el PID 1
            "detach": True,
            "user": "agent",  # nunca root
            # El host de Docker es un host ajeno al backend, pero el contenedor se endurece
            # igual: sin capacidades, sin ganar privilegios (setuid) y sin `privileged`.
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "pids_limit": 512,  # contra fork bombs
            "nano_cpus": int(settings.agent_job_cpus * 1e9),
            "mem_limit": settings.agent_job_memory,
            "memswap_limit": settings.agent_job_memory,  # sin swap: el tope de RAM es real
            # Red `vesper-jobs`: sin DNS roto, sin alcance al anfitrión ni entre tenants.
            "network": settings.agent_docker_network,
            "ports": {OPENCODE_PORT: None},  # puerto efímero del host, lo lee `_provision`
            "labels": {"vesper.job": self.job_id, "vesper.tenant": self.tenant_id},
            # Caché de paquetes POR TENANT: compartirla entre tenants permitiría que uno
            # envenene las dependencias que instala otro.
            "volumes": {
                f"vesper-cache-{self.tenant_id}": {"bind": "/home/agent/.cache", "mode": "rw"}
            },
        }

    # ------------------------------------------------------------  Docker
    async def _call(self, fn, *args, **kw):
        """Llamada síncrona del SDK sin bloquear el loop; errores de Docker, legibles."""
        try:
            return await asyncio.to_thread(fn, *args, **kw)
        except (DockerException, requests.RequestException) as exc:
            raise RuntimeError(f"{START_ERROR}: {exc}") from exc

    async def _exec(self, cmd: str) -> tuple[int, bytes]:
        res = await self._call(
            self._container.exec_run,
            ["bash", "-lc", cmd],
            workdir=WORKSPACE,
            user="agent",
            demux=True,
        )
        code, output = res
        return (code if code is not None else 0), _text(output)

    # ------------------------------------------------------------  Suites
    async def _suite(self, commands: list[TestCommand]) -> SuiteRun:
        if not commands:
            return SuiteRun(exit_code=None)
        limit = settings.agent_suite_timeout_seconds
        exit_code, timed_out, logs = 0, False, []
        for command in commands:
            for cmd in (command.install, command.test):
                if not cmd:
                    continue
                started = time.monotonic()
                code, out = await self._exec(f"timeout {limit} bash -lc {shlex.quote(cmd)}")
                logs.append(out.decode("utf-8", "replace"))
                timed_out |= code == TIMEOUT_EXIT
                exit_code = exit_code or code
                logger.info(
                    "agent_suite_command",
                    job_id=self.job_id,
                    exit_code=code,
                    seconds=round(time.monotonic() - started),
                )
                if code != 0:
                    break  # install roto: correr el test detrás solo añade ruido
        # SIEMPRE por `tail_redacted`: la salida de la suite es código del tenant y
        # acaba en la UI y en el cuerpo del PR.
        return SuiteRun(exit_code, tail_redacted("\n".join(logs)), timed_out)

    async def _exclude_suite_artifacts(self) -> None:
        """Lo que el install/test previos dejaron sin trackear (`.egg-info`, `dist/`…) no es
        cambio del agente: se excluye antes de que trabaje."""
        # ponytail: nombres con comodines de glob (`[`, `*`) se tratarían como patrón.
        await self._exec(
            "git ls-files -z --others --exclude-standard"
            " | xargs -0 -r printf '/%s\\n' >> .git/info/exclude"
        )

    # ------------------------------------------------------------  Parche
    async def _extract_patch(self) -> bytes:
        code, out = await self._exec("git add -A && git diff --cached --binary")
        if code != 0:
            raise RuntimeError(f"No se pudo aplicar el cambio del agente: git diff salió {code}")
        return out

    async def _apply_patch(self, workdir: Path, patch: bytes) -> None:
        if not patch.strip():
            return  # el agente no cambió nada
        # `git apply` trata el parche como datos no confiables: rechaza rutas fuera del
        # árbol, escrituras a través de symlinks y cualquier cosa dentro de `.git/`.
        proc = await asyncio.create_subprocess_exec(
            "git",
            "apply",
            "--binary",
            "--index",
            "-",
            cwd=workdir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate(patch)
        if proc.returncode != 0:
            detail = err.decode("utf-8", "replace").strip()[:500]
            raise RuntimeError(f"No se pudo aplicar el cambio del agente: {detail}")

    # ------------------------------------------------------------  Limpieza
    async def _teardown(self) -> None:
        # try/finally anidados: el semáforo se libera pase lo que pase.
        try:
            await self._remove_container()
        finally:
            if self._acquired:
                self._acquired = False  # una sola vez, aunque `stop()` se llame de nuevo
                _SLOTS.release()

    async def _remove_container(self) -> None:
        """Best-effort: un fallo aquí no puede tapar el error real del job."""
        if self._docker is None:
            return
        try:
            containers = [self._container] if self._container is not None else []
            if not containers:
                # Cancelado mientras `containers.run` seguía en su hilo: lo encontramos
                # por la etiqueta.
                containers = await asyncio.to_thread(
                    self._docker.containers.list,
                    all=True,
                    filters={"label": f"vesper.job={self.job_id}"},
                )
            for container in containers:
                await asyncio.to_thread(container.remove, force=True)
        except Exception as exc:
            logger.warning("agent_container_remove_failed", job_id=self.job_id, error=str(exc))
        finally:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(self._docker.close)
