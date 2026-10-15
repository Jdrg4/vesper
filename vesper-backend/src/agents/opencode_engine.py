"""`opencode serve` detras de la interfaz `AgentEngine` (F6a).

Junta lo que antes vivia repartido en `ReviewService._run_job`: pool de puertos,
`AgentSandbox`, el proceso y su password, y la sesion. Y anade lo que faltaba:
escuchar el SSE de opencode mientras dura el turno, para

- cortar cuando el agente deja de dar señales de vida (en vez de un reloj fijo),
- contar a la UI que esta haciendo,
- y saber por que fallo el modelo cuando el turno solo devuelve un 500.

Forma de los eventos medida con opencode 1.19.0: ver `engine.event_session`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

import httpx
import structlog

from src.agents.engine import ActivityCallback, EngineResult, event_session, tool_activity
from src.agents.runner import AGENT_TURN_TIMEOUT_SECONDS, OpencodeRunner
from src.agents.sandbox import AgentSandbox
from src.core.config import settings
from src.core.exceptions import ValidationDomainError

logger = structlog.get_logger(__name__)

# ------------------------------------------------------------  Pool de puertos
_PORT_LOCK = asyncio.Lock()
_PORTS_IN_USE: set[int] = set()
MAX_CONCURRENT_JOBS = 64


async def acquire_port() -> int:
    async with _PORT_LOCK:
        start = settings.opencode_port_pool_start
        for offset in range(MAX_CONCURRENT_JOBS):
            port = start + offset
            if port not in _PORTS_IN_USE:
                _PORTS_IN_USE.add(port)
                return port
    raise ValidationDomainError(
        f"Sin puertos libres para el agente (max {MAX_CONCURRENT_JOBS} jobs concurrentes)"
    )


def release_port(port: int) -> None:
    _PORTS_IN_USE.discard(port)


# ------------------------------------------------------------  Motor


class OpencodeEngine:
    def __init__(
        self,
        workspace_base: Path,
        job_id: str,
        *,
        runner_factory=OpencodeRunner,
        idle_timeout: float | None = None,
        poll: float = 1.0,
    ) -> None:
        self.workspace_base = Path(workspace_base)
        self.job_id = job_id
        self.runner_factory = runner_factory
        self.idle_timeout = idle_timeout or settings.agent_idle_timeout_seconds
        self.poll = poll
        self._port: int | None = None
        self._sandbox: AgentSandbox | None = None
        self._runner: OpencodeRunner | None = None
        self._client: httpx.AsyncClient | None = None
        self._tasks: list[asyncio.Task] = []
        self._stopped = False

    async def run(
        self,
        workdir: Path,
        prompt: str,
        model: str,
        credentials: dict[str, str],
        on_activity: ActivityCallback,
    ) -> EngineResult:
        workdir = Path(workdir)
        # Directorio de datos propio del job, con las credenciales de ESTE
        # tenant y nada mas. Ver `AgentSandbox`.
        self._sandbox = AgentSandbox(self.workspace_base, self.job_id)
        self._sandbox.setup(credentials)
        self._port = await acquire_port()
        self._runner = self.runner_factory(str(workdir), self._port, self._sandbox.env())
        await self._runner.start()
        # Sondea /global/health: el arranque de `opencode serve` no es instantaneo.
        await self._runner.wait_ready()
        # `auth`: el runtime arranca protegido con un password por job.
        self._client = httpx.AsyncClient(timeout=AGENT_TURN_TIMEOUT_SECONDS, auth=self._runner.auth)
        session_id = await self._runner.create_session(self._client)

        result = EngineResult()
        last_sign = time.monotonic()
        busy: set[str] = set()
        model_error: list[str] = []

        async def handle(ev: dict) -> None:
            nonlocal last_sign
            if event_session(ev) != session_id:
                # Heartbeats y eventos globales: llegan igual con el agente colgado.
                return
            last_sign = time.monotonic()
            props = ev.get("properties") or {}
            if ev.get("type") == "session.error":
                error = props.get("error") or {}
                model_error.append(
                    (error.get("data") or {}).get("message") or error.get("name") or str(error)
                )
                return
            part = props.get("part") or {}
            if part.get("type") == "tool":
                # Mientras una herramienta corre (una suite de tests larga) no
                # llega nada: no es inactividad.
                status = (part.get("state") or {}).get("status")
                call = part.get("callID") or ""
                if status in ("pending", "running"):
                    busy.add(call)
                else:
                    busy.discard(call)
            elif part.get("type") == "step-finish":
                tokens = part.get("tokens") or {}
                result.tokens_input += tokens.get("input") or 0
                result.tokens_output += tokens.get("output") or 0
                result.cost += part.get("cost") or 0.0
            activity = tool_activity(ev, workdir)
            if activity is not None:
                await on_activity(activity)

        async def listen() -> None:
            # Una reconexion si el SSE se cae; si vuelve a caer, el reloj de
            # inactividad sigue corriendo y acaba cortando (falla cerrado).
            for _attempt in range(2):
                with contextlib.suppress(httpx.HTTPError):
                    async for ev in self._runner.stream_events(self._client):
                        await handle(ev)

        listener = asyncio.create_task(listen())
        turn = asyncio.create_task(
            self._runner.send_prompt(self._client, session_id, prompt, model)
        )
        self._tasks = [listener, turn]

        while not turn.done():
            await asyncio.wait({turn}, timeout=self.poll)
            if turn.done():
                break
            if not busy and time.monotonic() - last_sign > self.idle_timeout:
                turn.cancel()
                minutes = max(1, round(self.idle_timeout / 60))
                logger.warning("agent_idle_timeout", job_id=self.job_id, minutes=minutes)
                raise RuntimeError(
                    f"El agente no dio señales de vida en {minutes} min y se detuvo. "
                    "Suele ser el proveedor del modelo que no responde; reintenta más tarde."
                )

        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await listener
        try:
            turn.result()
        except httpx.HTTPStatusError:
            # Con un modelo desconocido opencode responde un 500 generico; el
            # motivo real solo llega por `session.error`.
            if model_error:
                raise RuntimeError(f"El modelo no respondio: {model_error[0]}") from None
            raise
        if model_error:
            raise RuntimeError(f"El modelo no respondio: {model_error[0]}")
        return result

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(BaseException):
                await task
        if self._client is not None:
            await self._client.aclose()
        if self._runner is not None:
            await self._runner.stop()
        if self._port is not None:
            release_port(self._port)
        if self._sandbox is not None:
            await self._sandbox.cleanup()
