"""Contrato entre el flujo del job y el harness que hace el trabajo (F6a).

`ReviewService` clona, crea la rama, valida el diff y abre el PR; el motor solo
trabaja sobre el workdir. Asi la seguridad del flujo no depende del harness y
probar otro (`pi`, DeepSeek Harness) es escribir otro motor, no tocar el job.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from src.agents.verification import Verification


@dataclass(frozen=True)
class Activity:
    """Lo que el agente esta haciendo. Va a la UI: nunca texto libre del modelo
    ni rutas del servidor, solo la herramienta y la ruta relativa al repo."""

    tool: str
    path: str | None = None


@dataclass
class EngineResult:
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0
    # Veredicto antes/después de la suite; None = el motor no verifica (opencode local).
    checks: Verification | None = None


ActivityCallback = Callable[[Activity], Awaitable[None]]


class AgentEngine(Protocol):
    async def run(
        self,
        workdir: Path,
        prompt: str,
        model: str,
        credentials: dict[str, str],
        on_activity: ActivityCallback,
    ) -> EngineResult:
        """Trabaja sobre `workdir`. Lanza `RuntimeError` con un mensaje legible
        si el modelo falla o el agente se cuelga."""
        ...

    async def stop(self) -> None:
        """Mata todo lo que arranco. Idempotente; se llama siempre."""
        ...


# ------------------------------------------------------------  Eventos opencode


def event_session(ev: dict) -> str | None:
    """Sesion a la que pertenece un evento SSE de opencode, o None.

    Los eventos globales (`server.heartbeat`, `plugin.added`...) no llevan
    sesion: siguen llegando con el agente colgado, asi que no son actividad.
    """
    props = ev.get("properties") or {}
    return props.get("sessionID") or (props.get("part") or {}).get("sessionID")


def tool_activity(ev: dict, workdir: Path) -> Activity | None:
    """La herramienta que el agente acaba de poner en marcha, si la hay."""
    if ev.get("type") != "message.part.updated":
        return None
    part = (ev.get("properties") or {}).get("part") or {}
    state = part.get("state") or {}
    if part.get("type") != "tool" or state.get("status") != "running":
        return None
    file = (state.get("input") or {}).get("filePath")
    return Activity(part.get("tool") or "tool", _relative(file, workdir))


def _relative(file: str | None, workdir: Path) -> str | None:
    if not file:
        return None
    try:
        # Una ruta absoluta en `file` ignora `workdir` al unirlas: la proteccion es la misma.
        return (workdir / file).resolve().relative_to(workdir.resolve()).as_posix()
    except ValueError:
        # Fuera del workspace: la ruta absoluta enseñaria el disco del servidor.
        return None


# ------------------------------------------------------------  Motor falso


@dataclass
class FakeEngine:
    """Motor para tests: escribe `files`, avisa `activities`, falla o se cuelga."""

    files: dict[str, str] = field(default_factory=dict)
    activities: list[Activity] = field(default_factory=list)
    error: str | None = None
    hang: bool = False
    checks: Verification | None = None
    stopped: int = 0
    prompts: list[str] = field(default_factory=list)

    async def run(
        self,
        workdir: Path,
        prompt: str,
        model: str,
        credentials: dict[str, str],
        on_activity: ActivityCallback,
    ) -> EngineResult:
        self.prompts.append(prompt)
        for activity in self.activities:
            await on_activity(activity)
        if self.hang:
            await asyncio.Event().wait()
        if self.error:
            raise RuntimeError(self.error)
        for name, content in self.files.items():
            target = Path(workdir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return EngineResult(checks=self.checks)

    async def stop(self) -> None:
        self.stopped += 1
