"""Servicios del dominio review_jobs.

WorkspaceService: clona repos del tenant, maneja branches locales.
ReviewService: orquesta el flujo: clone → branch → opencode → git commit/push → PR.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.credentials import mark_used, resolve_credentials
from src.agents.engine import Activity, AgentEngine
from src.agents.opencode_engine import OpencodeEngine
from src.agents.runner import split_model
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.exceptions import NotFoundError, QuotaExceededError, ValidationDomainError
from src.core.files import wipe
from src.core.queue import LOCAL_FALLBACKS, enqueue
from src.core.tenancy import tenant_scoped_query
from src.repositories.github_client import (
    create_pull_request,
    get_installation_token,
)
from src.repositories.models import Repository, TenantInstallation
from src.review_jobs.constants import (
    BRANCH_PREFIX,
    DIFF_CONTENT_KEYS,
    EPHEMERAL_PATTERNS,
    SECRET_PATTERNS,
    SENSITIVE_PATHS,
    JobStatus,
    JobTrigger,
)
from src.review_jobs.models import ReviewJob
from src.review_jobs.schemas import JobCreateRequest
from src.tenants.constants import PLAN_QUOTAS

if TYPE_CHECKING:
    from src.tenants.models import Tenant

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------  Eventos
# Bus de progreso del agente hacia la UI.
#
# Con `REDIS_URL` los eventos van a una LISTA de Redis por job. Se usa lista y
# no pub/sub a proposito: el stream SSE relee con un cursor (`offset`), y en
# pub/sub un evento emitido antes de que el navegador se suscriba se pierde
# para siempre. `LRANGE key offset -1` reproduce la semantica exacta y ademas
# permite que el job corra en un worker y el SSE se sirva desde otro.
#
# Sin `REDIS_URL` degrada a memoria del proceso: la API sigue funcionando, pero
# con mas de un worker uvicorn el stream solo ve los jobs de SU proceso. Es la
# degradacion documentada en CLAUDE.md, no un bug.
_JOB_EVENTS: dict[str, list[dict]] = {}

# Eventos que cierran el stream: despues de uno de estos no llega nada mas.
TERMINAL_EVENTS = frozenset({"completed", "error", "needs_review"})

_EVENT_KEY_PREFIX = "vesper:job-events:"
# Los eventos son efimeros: el estado real del job vive en Postgres.
_EVENT_TTL_SECONDS = 3600

_redis_client = None
_redis_unavailable = False


def _events_key(job_id: str | uuid.UUID) -> str:
    return f"{_EVENT_KEY_PREFIX}{job_id}"


async def _get_redis():
    """Cliente Redis compartido, o None si no hay o no responde."""
    global _redis_client, _redis_unavailable
    if not settings.redis_url or _redis_unavailable:
        return None
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _redis_client = client
        except Exception as exc:
            # Degradar, nunca tumbar la API por el bus de progreso.
            _redis_unavailable = True
            logger.warning("event_bus_redis_unavailable", error=str(exc))
            return None
    return _redis_client


def reset_event_bus() -> None:
    """Limpia estado del bus (usado por los tests)."""
    global _redis_client, _redis_unavailable
    _redis_client = None
    _redis_unavailable = False
    _JOB_EVENTS.clear()


async def push_event(job_id: str | uuid.UUID, event: str, data: dict | None = None) -> None:
    payload = {"event": event, "data": data}
    redis = await _get_redis()
    if redis is None:
        _JOB_EVENTS.setdefault(str(job_id), []).append(payload)
        return
    key = _events_key(job_id)
    await redis.rpush(key, json.dumps(payload))
    await redis.expire(key, _EVENT_TTL_SECONDS)


async def get_events(job_id: str | uuid.UUID, offset: int = 0) -> list[dict]:
    """Eventos a partir de `offset`. NO destructivo.

    Leer no puede vaciar la cola: el stream lleva su propio cursor, y con un
    `pop` se perdia todo evento posterior al primer poll.
    """
    redis = await _get_redis()
    if redis is None:
        return _JOB_EVENTS.get(str(job_id), [])[offset:]
    raw = await redis.lrange(_events_key(job_id), offset, -1)
    return [json.loads(item) for item in raw]


async def clear_events(job_id: str | uuid.UUID) -> None:
    redis = await _get_redis()
    if redis is None:
        _JOB_EVENTS.pop(str(job_id), None)
        return
    await redis.delete(_events_key(job_id))


# ------------------------------------------------------------------  Motor
# Cuanto espera la UI entre dos avisos de actividad del mismo job: el agente
# lanza herramientas a rafagas y el bus no necesita cada una.
ACTIVITY_THROTTLE_SECONDS = 3.0

EngineFactory = Callable[[str], AgentEngine]


def default_engine_factory(workspace_base: Path) -> EngineFactory:
    return lambda job_id: OpencodeEngine(workspace_base, job_id)


# ------------------------------------------------------------  Tareas de fondo
# Referencia fuerte a las tareas en vuelo: `asyncio.create_task` solo mantiene
# una referencia debil y el GC puede matar el job a mitad de camino.
_BACKGROUND_TASKS: set[asyncio.Task] = set()


async def _run_job_standalone(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    workspace_svc: WorkspaceService | None = None,
    engine_factory: EngineFactory | None = None,
    session_factory=None,
) -> None:
    """Corre un job con su PROPIA sesion de BD.

    La sesion de la request se cierra al enviar la respuesta; reutilizarla aqui
    dejaba al job operando sobre una `AsyncSession` ya cerrada.
    """
    factory = session_factory or AsyncSessionLocal
    async with factory() as session:
        svc = ReviewService(session, workspace_svc=workspace_svc, engine_factory=engine_factory)
        try:
            await svc.run_job(job_id, tenant_id)
            await session.commit()
        except asyncio.CancelledError:
            # Abortado: `run_job` ya dejo el job en `failed` / "Job abortado" con un
            # flush. CancelledError no es Exception: sin este commit la sesion se
            # cerraba descartandolo y el job seguia `running` para siempre.
            await session.commit()
            raise
        except Exception:
            await session.rollback()
            logger.exception("review_job_task_crashed", job_id=str(job_id))


def schedule_job_run(job_id: uuid.UUID, tenant_id: uuid.UUID, **kwargs) -> asyncio.Task:
    task = asyncio.create_task(_run_job_standalone(job_id, tenant_id, **kwargs))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    register_running_job(job_id, task)
    return task


# Nombre con el que el worker de Arq registra la funcion. El fallback in-process
# es el `schedule_job_run` de siempre, resuelto por atributo del modulo para que
# los tests puedan sustituirlo.
QUEUE_FN_RUN_JOB = "run_review_job"
LOCAL_FALLBACKS[QUEUE_FN_RUN_JOB] = lambda *args: schedule_job_run(*args)


async def enqueue_review_job(
    job_id: uuid.UUID, tenant_id: uuid.UUID, *, defer_seconds: int = 0
) -> None:
    """Manda el job a la cola. Sin Redis lo corre este mismo proceso."""
    await enqueue(QUEUE_FN_RUN_JOB, job_id, tenant_id, defer_seconds=defer_seconds)


# Jobs en vuelo, para poder abortarlos. Solo alcanza a los de ESTE proceso; con
# la cola, el job casi nunca corre donde se recibio el HTTP, asi que el abort
# viaja ademas por `ABORT_CHANNEL`.
_RUNNING_JOBS: dict[str, asyncio.Task] = {}

# Canal pub/sub por el que la API pide a los workers que cancelen un job.
ABORT_CHANNEL = "vesper:job-abort"


def register_running_job(job_id: uuid.UUID | str, task: asyncio.Task) -> None:
    key = str(job_id)
    _RUNNING_JOBS[key] = task
    task.add_done_callback(lambda _t: _RUNNING_JOBS.pop(key, None))


async def abort_job(job_id: uuid.UUID | str) -> bool:
    """Cancela el job en vuelo. Devuelve False si no habia ninguno corriendo.

    La cancelacion desata `CancelledError` dentro de `run_job`, que en su
    `finally` para el proceso `opencode` y libera el puerto.
    """
    task = _RUNNING_JOBS.get(str(job_id))
    if task is None or task.done():
        return False
    task.cancel()
    return True


# Un job cuyo proceso murio (reinicio del worker, crash, OOM) se queda
# `running` para siempre, y el debounce de F5 deja de encolar esa pareja
# (repo, tarea) — el repo deja de vigilarse en silencio. Se recogen por
# antiguedad y no "todos los running al arrancar", que con varios workers
# matarian los jobs vivos de los demas.
STALE_JOB_SECONDS = 7 * 60 * 60  # por encima del job_timeout del worker, o recogeria jobs vivos


async def reap_stale_jobs(db: AsyncSession, older_than: int = STALE_JOB_SECONDS) -> int:
    """Marca como `failed` los jobs colgados. Devuelve cuantos recogio."""
    from datetime import timedelta

    limite = datetime.now(UTC) - timedelta(seconds=older_than)
    q = select(ReviewJob).where(
        ReviewJob.status == JobStatus.running,
        ReviewJob.started_at.is_not(None),
        ReviewJob.started_at < limite,
    )
    colgados = list((await db.execute(q)).scalars().all())
    for job in colgados:
        job.status = JobStatus.failed
        job.completed_at = datetime.now(UTC)
        job.error_message = {"error": "El job quedo colgado y fue recogido por el scheduler"}
        logger.warning("review_job_reaped", job_id=str(job.id), tenant_id=str(job.tenant_id))
    return len(colgados)


async def publish_abort(job_id: uuid.UUID | str) -> None:
    """Anuncia el abort a todos los workers. Sin Redis es un no-op."""
    redis = await _get_redis()
    if redis is None:
        return
    await redis.publish(ABORT_CHANNEL, str(job_id))


async def listen_aborts() -> None:
    """Cancela los jobs locales anunciados en el canal. Lo arranca el worker."""
    redis = await _get_redis()
    if redis is None:
        return
    pubsub = redis.pubsub()
    await pubsub.subscribe(ABORT_CHANNEL)
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        job_id = message["data"]
        if await abort_job(job_id):
            logger.info("review_job_aborted_remote", job_id=job_id)


async def _run_git(workdir: Path, *args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (proc.returncode or 0, stdout.decode(), stderr.decode())


def _authenticated_remote(repo_full_name: str, installation_token: str) -> str:
    return f"https://x-access-token:{installation_token}@github.com/{repo_full_name}.git"


def _clean_remote(repo_full_name: str) -> str:
    return f"https://github.com/{repo_full_name}.git"


def _redact(text: str, secret: str) -> str:
    """Quita el token de la salida de git antes de que llegue a un log o a la UI.

    git incluye la URL del remote en varios mensajes de error, y esa URL lleva
    el installation token incrustado.
    """
    return text.replace(secret, "***") if secret else text


class WorkspaceService:
    def __init__(self, base: str | None = None) -> None:
        self.base = Path(base if base is not None else settings.workspace_root)

    def workspace_dir(self, tenant_id: str, repo_id: str) -> Path:
        return self.base / tenant_id / repo_id

    async def clone(
        self,
        tenant_id: str,
        repo_id: str,
        repo_full_name: str,
        branch: str,
        installation_token: str,
    ) -> Path:
        workdir = self.workspace_dir(tenant_id, repo_id)
        await wipe(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        rc, _, stderr = await _run_git(
            workdir.parent,
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            _authenticated_remote(repo_full_name, installation_token),
            str(workdir),
        )
        if rc != 0:
            raise RuntimeError(f"git clone failed: {_redact(stderr, installation_token)}")

        # `git clone` deja la URL con el token dentro de `.git/config`, y ese
        # archivo queda legible durante todo el job para el agente y para
        # cualquier script del repo del tenant que se ejecute en el sandbox.
        # El push vuelve a pasar el remote autenticado como argumento.
        await _run_git(workdir, "remote", "set-url", "origin", _clean_remote(repo_full_name))
        self._ignore_ephemeral(workdir)
        return workdir

    @staticmethod
    def _ignore_ephemeral(workdir: Path) -> None:
        """Excluye del commit lo que genera el propio agente al trabajar.

        En la primera corrida real, el language server que abre el agente
        compiló el proyecto y el PR salió con dos `.pyc` dentro. `git add -A`
        no distingue: se lleva todo lo que no esté ignorado, y muchos repos no
        tienen `.gitignore`.

        Va en `.git/info/exclude` y no en un `.gitignore`: ese archivo es local
        al clon y no aparece en el diff, así que no le metemos al tenant un
        cambio que no ha pedido.
        """
        exclude = workdir / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        previo = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        exclude.write_text(
            previo.rstrip("\n") + "\n" + "\n".join(EPHEMERAL_PATTERNS) + "\n",
            encoding="utf-8",
        )

    async def create_branch(self, workdir: Path, branch_name: str) -> None:
        rc, _, stderr = await _run_git(workdir, "checkout", "-b", branch_name)
        if rc != 0:
            raise RuntimeError(f"git checkout -b failed: {stderr}")

    async def commit_and_push(
        self,
        workdir: Path,
        branch_name: str,
        message: str,
        repo_full_name: str = "",
        installation_token: str = "",
    ) -> str:
        rc, _, _ = await _run_git(workdir, "add", "-A")
        if rc != 0:
            raise RuntimeError("git add failed")

        # verificar si hay cambios
        rc, stdout, _ = await _run_git(workdir, "status", "--porcelain")
        if rc != 0 or not stdout.strip():
            raise RuntimeError("no changes to commit")

        rc, _, stderr = await _run_git(
            workdir,
            "commit",
            "-m",
            message,
        )
        if rc != 0:
            raise RuntimeError(f"git commit failed: {stderr}")

        # El remote guardado no lleva credenciales (ver `clone`): el token se
        # pasa solo en este comando.
        target = (
            _authenticated_remote(repo_full_name, installation_token)
            if repo_full_name and installation_token
            else "origin"
        )
        rc, stdout, stderr = await _run_git(
            workdir,
            "push",
            target,
            f"HEAD:refs/heads/{branch_name}",
        )
        if rc != 0:
            raise RuntimeError(f"git push failed: {_redact(stderr, installation_token)}")

        # `_run_git` devuelve (returncode, stdout, stderr): leer el SHA de la
        # primera posicion daba un int y reventaba con AttributeError justo
        # despues de un push correcto, antes de llegar a abrir el PR.
        _, sha_out, _ = await _run_git(workdir, "rev-parse", "HEAD")
        return sha_out.strip()

    async def configure_git(self, workdir: Path) -> None:
        await _run_git(workdir, "config", "user.email", "vesper@networkia.local")
        await _run_git(workdir, "config", "user.name", "Vesper Bot")

    async def capture_diff(self, workdir: Path) -> list[dict]:
        """Cambios del workspace, en la forma `SnapshotFileDiff` del runtime.

        git es la fuente de verdad, no `GET /session/{id}/diff`: ese endpoint
        devuelve solo lo que produjo un `messageID` concreto y sin el parametro
        contesta vacio, asi que el job veia "sin cambios" aunque el agente
        hubiera editado archivos. Ademas asi se capturan los cambios que el
        agente haga por cualquier via (comandos, varios mensajes).
        """
        # `-N` (intent-to-add) hace que los archivos nuevos aparezcan en
        # `git diff` sin llegar a stagear su contenido.
        await _run_git(workdir, "add", "-A", "-N")

        rc, numstat, _ = await _run_git(workdir, "diff", "--numstat")
        if rc != 0 or not numstat.strip():
            return []

        diffs: list[dict] = []
        for line in numstat.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            additions, deletions, path = parts
            _, patch, _err = await _run_git(workdir, "diff", "--", path)
            diffs.append(
                {
                    "file": path,
                    "patch": patch,
                    "additions": int(additions) if additions.isdigit() else 0,
                    "deletions": int(deletions) if deletions.isdigit() else 0,
                    "status": "modified",
                }
            )
        return diffs


# El agente no sabe donde esta ni que hara Vesper despues con su trabajo. Este
# preambulo lo comparten las cinco plantillas y el prompt libre; en F4 no
# existia y que el primer PR saliera limpio fue suerte del modelo.
_PROMPT_PREAMBLE = (
    "Repositorio: `{repo_name}` · Rama: `{ref}`\n"
    "Aplica los cambios directamente en el working tree.\n"
    "No hagas commit, push ni abras un pull request: de eso se encarga Vesper.\n\n"
)

_TASK_BODIES = {
    "security": (
        "Review the repository for security vulnerabilities. "
        "Check for exposed secrets, unsafe dependencies, SQL injection, XSS, "
        "insecure auth, missing input validation. Apply concrete fixes."
    ),
    "quality": (
        "Review the repository for code quality: dead code, duplication, "
        "complex functions, inconsistent patterns, missing types. Apply refactors."
    ),
    "deps": (
        "Review the repository dependencies. Check for outdated packages, "
        "security advisories, deprecated APIs. Update to latest safe versions."
    ),
    "perf": (
        "Review the repository for performance: N+1 queries, unnecessary "
        "re-renders, large payloads, missing indexes. Apply optimizations."
    ),
    "docs": (
        "Review the repository docs coverage. Add missing docstrings, "
        "improve README, add usage examples for public functions."
    ),
}

_DEFAULT_BODY = "Review the repository and propose improvements."


def build_prompt(task_type: str, repo_name: str, ref: str, custom: str | None = None) -> str:
    """Preambulo comun + cuerpo (plantilla del task_type, o texto del usuario).

    Un `custom` en blanco cae a la plantilla: un textarea vacio no puede dejar
    al agente sin instrucciones.
    """
    limpio = custom.strip() if custom else ""
    body = limpio or _TASK_BODIES.get(task_type, _DEFAULT_BODY)
    return _PROMPT_PREAMBLE.format(repo_name=repo_name, ref=ref) + body


_COMPILED_SECRET_PATTERNS = tuple(
    (label, re.compile(pattern)) for label, pattern in SECRET_PATTERNS
)


def _added_lines(entry: dict) -> list[str]:
    """Lineas que el diff AÑADE. Ignora contexto, cabeceras y eliminaciones."""
    for key in DIFF_CONTENT_KEYS:
        body = entry.get(key)
        if isinstance(body, str) and body:
            return [
                line[1:]
                for line in body.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
    return []


def validate_diff(diffs: list[dict]) -> str:
    """Devuelve un warning si el diff no puede auto-mergearse.

    Dos motivos: toca una ruta sensible, o introduce algo que parece un
    secreto. En ambos casos el job termina en `needs_review` y no se abre PR.
    """
    warnings: list[str] = []
    for d in diffs:
        path = _diff_path(d)
        for sensitive in SENSITIVE_PATHS:
            if sensitive in path:
                warnings.append(f"Sensitive path modified: {path}")
        for line in _added_lines(d):
            for label, pattern in _COMPILED_SECRET_PATTERNS:
                if pattern.search(line):
                    # Nunca loguear ni propagar el valor: iria al historial del
                    # job y a la UI del tenant.
                    warnings.append(f"Possible {label} added in {path}")
                    break
    return "; ".join(warnings) if warnings else ""


def _diff_path(entry: dict) -> str:
    """Ruta del archivo dentro de un `SnapshotFileDiff`.

    El runtime la devuelve en `file`; se acepta `path` como alias porque era lo
    que asumia el codigo antes de contrastarlo con opencode real (con `path`,
    la deteccion de rutas sensibles no se disparaba nunca).
    """
    return entry.get("file") or entry.get("path") or "?"


def _pr_body(task_type: str, model: str, summary: str) -> str:
    """Cuerpo del PR. Quien lo revisa necesita saber que lo escribio una maquina."""
    return (
        f"Revisión automática de **Vesper** (`{task_type}`).\n\n"
        f"{summary}\n\n"
        "---\n"
        f"Generado por un agente con el modelo `{model}`. "
        "Revisa el diff antes de mergear."
    )


def _diff_summary(diffs: list[dict]) -> str:
    if not diffs:
        return "No changes proposed."
    paths = [_diff_path(d) for d in diffs[:10]]
    return f"{len(diffs)} files changed: {', '.join(paths)}"


def _activity_publisher(job_id: uuid.UUID):
    """Reenvia al SSE lo que hace el agente, como mucho una vez cada
    `ACTIVITY_THROTTLE_SECONDS`."""
    last_sent = -ACTIVITY_THROTTLE_SECONDS

    async def publish(activity: Activity) -> None:
        nonlocal last_sent
        now = time.monotonic()
        if now - last_sent < ACTIVITY_THROTTLE_SECONDS:
            return
        last_sent = now
        await push_event(job_id, "activity", {"tool": activity.tool, "path": activity.path})

    return publish


class ReviewService:
    def __init__(
        self,
        db: AsyncSession,
        workspace_svc: WorkspaceService | None = None,
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self.db = db
        self.workspace_svc = workspace_svc or WorkspaceService()
        self.engine_factory = engine_factory or default_engine_factory(self.workspace_svc.base)

    async def _repo_scoped(self, repo_id: uuid.UUID, tenant_id: uuid.UUID) -> Repository | None:
        q = tenant_scoped_query(Repository, tenant_id).where(Repository.id == repo_id)
        return (await self.db.execute(q)).scalar_one_or_none()

    async def _jobs_today(self, tenant_id: uuid.UUID) -> int:
        """Jobs creados hoy (UTC) por el tenant."""
        inicio = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        q = (
            select(func.count())
            .select_from(ReviewJob)
            .where(ReviewJob.tenant_id == tenant_id, ReviewJob.created_at >= inicio)
        )
        return (await self.db.execute(q)).scalar_one()

    async def _jobs_running(self, tenant_id: uuid.UUID) -> int:
        q = (
            select(func.count())
            .select_from(ReviewJob)
            .where(ReviewJob.tenant_id == tenant_id, ReviewJob.status == JobStatus.running)
        )
        return (await self.db.execute(q)).scalar_one()

    async def defer_seconds_for(self, tenant: Tenant) -> int:
        """0 si hay hueco; 60 si el tenant esta al tope de concurrencia.

        Topar la concurrencia no rechaza el job: lo retrasa. La cola existe
        justamente para esperar.
        """
        tope = PLAN_QUOTAS[tenant.plan]["max_concurrent_jobs"]
        return 60 if await self._jobs_running(tenant.id) >= tope else 0

    async def _check_daily_quota(self, tenant: Tenant) -> None:
        tope = PLAN_QUOTAS[tenant.plan]["max_jobs_per_day"]
        if tope is None:
            return
        usados = await self._jobs_today(tenant.id)
        if usados >= tope:
            logger.warning(
                "quota_exceeded",
                tenant_id=str(tenant.id),
                plan=tenant.plan.value,
                usados=usados,
                tope=tope,
            )
            raise QuotaExceededError(f"Limite de {tope} jobs diarios alcanzado")

    async def create_job(self, tenant: Tenant, data: JobCreateRequest) -> ReviewJob:
        repo = await self._repo_scoped(data.repository_id, tenant.id)
        if repo is None:
            raise NotFoundError("Repository not found")

        await self._check_daily_quota(tenant)

        # La rama del repo manda sobre el default del schema.
        ref = data.ref or repo.default_branch
        job = ReviewJob(
            tenant_id=tenant.id,
            repository_id=data.repository_id,
            task_type=data.task_type,
            status=JobStatus.queued,
            # Un prompt libre es lo que distingue al trigger `prompt` del
            # `manual`: el resto del flujo es identico.
            trigger=JobTrigger.prompt if data.prompt else JobTrigger.manual,
            ref=ref,
            # El modelo lo elige el tenant en su configuracion; hardcodearlo
            # dejaba a `developer_model` sin ningun efecto.
            model=tenant.developer_model,
            prompt=build_prompt(data.task_type.value, repo.full_name, ref, data.prompt),
        )
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job

    async def _get_installation_token(self, repo: Repository) -> str:
        q = tenant_scoped_query(TenantInstallation, repo.tenant_id).where(
            TenantInstallation.installation_id == repo.installation_id
        )
        inst = (await self.db.execute(q)).scalar_one_or_none()
        if inst is None:
            raise ValidationDomainError("No GitHub App installation found")
        return await get_installation_token(inst.installation_id)

    async def run_job(self, job_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        job = await self.get_job(job_id, tenant_id)
        if job is None:
            logger.warning("review_job_not_found", job_id=str(job_id), tenant_id=str(tenant_id))
            return

        repo = await self._repo_scoped(job.repository_id, tenant_id)
        if repo is None:
            job.status = JobStatus.failed
            job.error_message = {"error": "repository not found"}
            await self.db.flush()
            return

        job.status = JobStatus.running
        job.started_at = datetime.now(UTC)
        # Commit, no flush: este job corre en una tarea de fondo con su propia
        # sesion, y hasta que no commitee nadie mas ve el cambio. Con un flush,
        # la UI mostraba "queued" durante toda la ejecucion —varios minutos— y
        # solo saltaba al estado final de golpe.
        await self.db.commit()

        engine: AgentEngine | None = None

        try:
            # Las credenciales del tenant primero: si no las tiene, no tiene
            # sentido clonar nada ni pedir un token de GitHub.
            credentials = await resolve_credentials(self.db, tenant_id)

            token = await self._get_installation_token(repo)
            workdir = await self.workspace_svc.clone(
                str(job.tenant_id), str(repo.id), repo.full_name, job.ref, token
            )
            await self.workspace_svc.configure_git(workdir)

            branch = f"{BRANCH_PREFIX}/{job.task_type.value}-{str(job_id)[:8]}"
            await self.workspace_svc.create_branch(workdir, branch)

            await push_event(job_id, "progress", {"message": "Starting agent..."})

            prompt = job.prompt or build_prompt(job.task_type.value, repo.full_name, job.ref)
            # `create_job` siempre puebla `prompt`; el fallback cubre jobs viejos,
            # que se escribieron cuando la columna admitia NULL.

            await push_event(job_id, "progress", {"message": "Agent reviewing..."})
            engine = self.engine_factory(str(job_id))
            await engine.run(workdir, prompt, job.model, credentials, _activity_publisher(job_id))
            await mark_used(self.db, tenant_id, split_model(job.model)["providerID"])

            # El diff se lee del workspace con git, no de `GET /session/:id/diff`
            # (ver `WorkspaceService.capture_diff`).
            diff = await self.workspace_svc.capture_diff(workdir)
            summary = _diff_summary(diff)
            warning = validate_diff(diff)

            if not diff:
                job.status = JobStatus.completed
                job.diff_summary = "No changes proposed."
                job.completed_at = datetime.now(UTC)
                await self.db.flush()
                await push_event(job_id, "completed", {"summary": job.diff_summary})
                return

            if warning:
                job.status = JobStatus.needs_review
                job.diff_summary = f"{summary} WARNING: {warning}"
                job.completed_at = datetime.now(UTC)
                await self.db.flush()
                await push_event(job_id, "needs_review", {"warning": warning})
                return

            await push_event(job_id, "progress", {"message": "Committing and pushing..."})
            commit_msg = f"vesper: {job.task_type.value} improvements ({str(job_id)[:8]})"
            sha = await self.workspace_svc.commit_and_push(
                workdir, branch, commit_msg, repo.full_name, token
            )

            owner, repo_name = repo.full_name.split("/")
            pr = await create_pull_request(
                token,
                owner,
                repo_name,
                branch,
                # base = default branch real del repo; "main" hardcodeado abria
                # PRs invalidos en repos con master/develop/trunk.
                repo.default_branch,
                f"[Vesper] {job.task_type.value}: improvements for {repo_name}",
                _pr_body(job.task_type.value, job.model, summary),
            )

            job.status = JobStatus.completed
            job.branch_name = branch
            job.commit_sha = sha
            job.pull_request_url = pr.get("html_url")
            job.diff_summary = summary
            job.completed_at = datetime.now(UTC)
            await self.db.flush()
            await push_event(job_id, "completed", {"pull_request_url": job.pull_request_url})
            logger.info(
                "review_job_completed",
                job_id=str(job_id),
                tenant_id=str(tenant_id),
                pull_request_url=job.pull_request_url,
            )

        except asyncio.CancelledError:
            # `CancelledError` hereda de BaseException: sin esta rama, un job
            # abortado quedaba para siempre en `running`. El `finally` de abajo
            # mata el proceso opencode y libera el puerto.
            job.status = JobStatus.failed
            job.error_message = {"error": "Job abortado"}
            job.completed_at = datetime.now(UTC)
            await self.db.flush()
            await push_event(job_id, "error", {"error": "Job abortado"})
            logger.info("review_job_aborted", job_id=str(job_id), tenant_id=str(tenant_id))
            raise

        except Exception as exc:
            # `str(exc)` puede ser cadena vacia — `NotImplementedError` es el
            # caso tipico — y entonces el job quedaba como `failed` sin ninguna
            # pista de por que. El tipo siempre dice algo.
            detail = str(exc) or repr(exc)
            message = f"{type(exc).__name__}: {detail}"
            job.status = JobStatus.failed
            job.error_message = {"error": message}
            job.completed_at = datetime.now(UTC)
            await self.db.flush()
            await push_event(job_id, "error", {"error": message})
            logger.warning(
                "review_job_failed",
                job_id=str(job_id),
                tenant_id=str(tenant_id),
                error=message,
                exc_type=type(exc).__name__,
            )

        finally:
            if engine is not None:
                await engine.stop()

    async def trigger_job(self, tenant: Tenant, data: JobCreateRequest) -> ReviewJob:
        job = await self.create_job(tenant, data)
        # Commit explicito (excepcion justificada a la regla de CLAUDE.md): la
        # tarea de fondo abre su propia sesion y no veria un job solo flusheado.
        await self.db.commit()
        await enqueue_review_job(
            job.id, tenant.id, defer_seconds=await self.defer_seconds_for(tenant)
        )
        logger.info(
            "review_job_queued",
            job_id=str(job.id),
            tenant_id=str(tenant.id),
            repository_id=str(job.repository_id),
            task_type=job.task_type.value,
            model=job.model,
        )
        return job

    async def list_jobs(self, tenant_id: uuid.UUID) -> list[ReviewJob]:
        q = tenant_scoped_query(ReviewJob, tenant_id).order_by(ReviewJob.created_at.desc())
        return list((await self.db.execute(q)).scalars().all())

    async def get_job(self, job_id: uuid.UUID, tenant_id: uuid.UUID) -> ReviewJob | None:
        q = tenant_scoped_query(ReviewJob, tenant_id).where(ReviewJob.id == job_id)
        return (await self.db.execute(q)).scalar_one_or_none()
