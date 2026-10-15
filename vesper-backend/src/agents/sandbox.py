"""Directorio de datos efimero del runtime, uno por job.

Sin esto, `opencode serve` hereda el entorno del backend y usa el
`~/.local/share/opencode/` de quien levanto el proceso: sus credenciales
personales y una base de sesiones compartida por todos los tenants. En
produccion ese directorio directamente no existe y ningun job se autenticaria.

Cada job recibe su propio `XDG_DATA_HOME` con un `auth.json` que contiene
**solo los proveedores de su tenant**, y su propio `XDG_CONFIG_HOME` vacio para
que no se le cuelen plugins ni skills del operador.

`XDG_CACHE_HOME` se deja compartido a proposito: ahi viven los paquetes que
opencode descarga (language servers y demas), no hay secretos, y aislarlo
obligaria a volver a bajarlos en cada job.
"""

from __future__ import annotations

import contextlib
import json
import stat
from pathlib import Path

import structlog

from src.core.files import wipe

logger = structlog.get_logger(__name__)


class AgentSandbox:
    """Entorno aislado de un job. Crear con `setup`, destruir con `cleanup`."""

    def __init__(self, root: Path, job_id: str) -> None:
        self.base = Path(root) / ".runtime" / str(job_id)
        self.data_dir = self.base / "data"
        self.config_dir = self.base / "config"

    @property
    def auth_file(self) -> Path:
        return self.data_dir / "opencode" / "auth.json"

    def setup(self, credentials: dict[str, str]) -> None:
        """Escribe el `auth.json` del job con las credenciales del tenant."""
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        payload = {provider: {"type": "api", "key": key} for provider, key in credentials.items()}
        self.auth_file.write_text(json.dumps(payload), encoding="utf-8")
        # Solo el dueño. En Windows no hay permisos POSIX y esto es un no-op
        # efectivo; el aislamiento real ahi lo da el sandbox por job.
        with contextlib.suppress(OSError):
            self.auth_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        logger.info("agent_sandbox_ready", providers=sorted(payload))

    def env(self) -> dict[str, str]:
        """Variables que redirigen a opencode a este directorio.

        Las credenciales NO viajan como env vars: el entorno lo heredan todos
        los procesos hijos —language servers incluidos, y cualquier script del
        repo del tenant que el agente ejecute— y quedarian legibles en
        `/proc/<pid>/environ`.
        """
        return {
            "XDG_DATA_HOME": str(self.data_dir),
            "XDG_CONFIG_HOME": str(self.config_dir),
        }

    async def cleanup(self) -> None:
        """Borra el directorio. Nunca lanza: corre en el `finally` del job."""
        try:
            await wipe(self.base)
        except OSError as exc:
            # Un sandbox sin borrar es un problema —deja una key en disco— pero
            # no justifica tapar el resultado del job.
            logger.warning("agent_sandbox_cleanup_failed", path=str(self.base), error=str(exc))
