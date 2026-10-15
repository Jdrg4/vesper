"""Opencode runtime — spawn `opencode serve` por job, fake para tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import shutil
from collections.abc import AsyncIterator

import httpx

from src.core.config import settings

OPENCODE_BASE_PORT = 14096
OPENCODE_HOST = "127.0.0.1"

# Proveedor por defecto en la pasarela Zen. Los modelos que ofrecemos al tenant
# (glm-5.2, minimax-m3, kimi-k3, ...) viven todos bajo este providerID; se
# comprobó contra `GET /config/providers` de opencode 1.18.7.
DEFAULT_PROVIDER_ID = "opencode-go"


def resolve_opencode_bin() -> str:
    """Ruta ejecutable del binario `opencode`.

    Dos motivos para no pasar `"opencode"` a `create_subprocess_exec`:
    - `OPENCODE_BIN` estaba documentado pero no se leia en ningun sitio.
    - En Windows el `opencode` del PATH de npm es un script sin extension;
      `CreateProcess` no lo resuelve y falla con `FileNotFoundError`. `which`
      devuelve el `.cmd`/`.exe`, que si es ejecutable.
    """
    configured = settings.opencode_bin.strip()
    if configured:
        return configured
    found = shutil.which("opencode")
    if found:
        return found
    # Sin resolver: dejar que falle al spawnear, con el nombre a la vista.
    return "opencode"


# Lo unico del entorno del backend que hereda el runtime del agente: lo justo para
# que el proceso arranque y resuelva binarios, temporales y proxy. Todo lo demas
# (DATABASE_URL, JWT_SECRET, CREDENTIALS_ENCRYPTION_KEY, la clave de la GitHub
# App...) quedaria al alcance de un prompt malicioso del repo del tenant.
AGENT_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "HOME",
    "USERPROFILE",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "COMSPEC",
    "WINDIR",
    "TEMP",
    "TMP",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "XDG_CACHE_HOME",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "NODE_EXTRA_CA_CERTS",
)


def agent_base_env() -> dict[str, str]:
    """Entorno minimo del runtime: lista blanca, nunca una copia de `os.environ`."""
    return {k: os.environ[k] for k in AGENT_ENV_ALLOWLIST if k in os.environ}


def split_model(model: str) -> dict[str, str]:
    """Convierte el modelo del tenant al objeto que espera el runtime.

    Acepta `"glm-5.2"` (usa el proveedor por defecto) o `"deepseek/deepseek-v4-pro"`
    para fijar otro proveedor explícitamente.
    """
    provider_id, _, model_id = model.partition("/")
    if not model_id:
        return {"providerID": DEFAULT_PROVIDER_ID, "modelID": provider_id}
    return {"providerID": provider_id, "modelID": model_id}


class OpencodeRunner:
    """Runner real: spawn `opencode serve` como proceso hijo.

    La comunicación es HTTP hacia localhost:<port>. Cada job tiene su propio
    proceso y puerto del pool 14096+.
    """

    def __init__(
        self, workdir: str, port: int, env_overrides: dict[str, str] | None = None
    ) -> None:
        self.workdir = workdir
        self.port = port
        # Redirigen al runtime a un directorio de datos propio del job (ver
        # `AgentSandbox`): sus credenciales y su base de sesiones, no las de
        # quien levanto el backend.
        self.env_overrides = env_overrides or {}
        self.process: asyncio.subprocess.Process | None = None
        self._base_url = f"http://{OPENCODE_HOST}:{port}"
        # Password unico por job. Sin el, `opencode serve` queda abierto y
        # `GET /config/providers` devuelve las API keys en claro a cualquiera
        # que alcance el puerto — incluido el codigo del repo del tenant, que
        # se ejecuta en el mismo sandbox. Ademas evita que un job hable con la
        # sesion de otro tenant.
        self.server_password = secrets.token_urlsafe(32)

    @property
    def auth(self) -> tuple[str, str]:
        """Credenciales Basic que exige el runtime (el usuario da igual)."""
        return ("opencode", self.server_password)

    async def start(self) -> None:
        env = {
            **agent_base_env(),
            "OPENCODE_SERVER_PASSWORD": self.server_password,
            **self.env_overrides,
        }
        extra: dict = {}
        if os.name != "nt":
            # Grupo de procesos propio: es lo que permite matar de una vez al
            # servidor y a todo lo que cuelgue de el (ver `stop`).
            extra["start_new_session"] = True
        self.process = await asyncio.create_subprocess_exec(
            resolve_opencode_bin(),
            "serve",
            # Sin `--pure`, el runtime carga los plugins y skills globales del
            # operador. En un job de un tenant no pintan nada.
            "--pure",
            "--port",
            str(self.port),
            "--hostname",
            OPENCODE_HOST,
            cwd=self.workdir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **extra,
        )

    async def stop(self) -> None:
        """Para el runtime y TODO lo que haya lanzado. Nunca lanza.

        Corre en el `finally` de `run_job`, asi que una excepcion aqui taparia
        el error real del job (`kill()` lanza `ProcessLookupError` si el
        proceso ya murio por su cuenta).

        Hay que matar el arbol entero, no solo al padre: `opencode` arranca
        language servers (pyright, gopls...) dentro del workspace y sobreviven
        a la muerte del servidor. Cada job dejaba un pyright vivo que ademas
        mantenia abierto el directorio, y el siguiente job sobre ese repo moria
        al intentar limpiarlo.
        """
        if self.process is None or self.process.returncode is not None:
            return
        await self._kill_tree()
        try:
            self.process.terminate()
            await asyncio.wait_for(self.process.wait(), timeout=10)
        except (ProcessLookupError, TimeoutError, OSError):
            with contextlib.suppress(ProcessLookupError, OSError):
                self.process.kill()

    async def _kill_tree(self) -> None:
        """Mata a los descendientes del runtime. Best-effort, nunca lanza."""
        if self.process is None:
            return
        pid = self.process.pid
        if os.name == "nt":
            # `taskkill /T` recorre el arbol; siempre por PID concreto.
            with contextlib.suppress(Exception):
                proc = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.wait(), timeout=10)
            return
        import signal

        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(pid), signal.SIGTERM)

    async def wait_ready(
        self, timeout: float = 30, client: httpx.AsyncClient | None = None
    ) -> None:
        """Espera hasta que opencode serve responda en /global/health."""
        deadline = asyncio.get_event_loop().time() + timeout

        async def _poll(c: httpx.AsyncClient) -> bool:
            while asyncio.get_event_loop().time() < deadline:
                try:
                    r = await c.get(f"{self._base_url}/global/health", timeout=3, auth=self.auth)
                    if r.status_code == 200:
                        return True
                except Exception:
                    pass
                await asyncio.sleep(1)
            return False

        if client is not None:
            ready = await _poll(client)
        else:
            async with httpx.AsyncClient(auth=self.auth) as c:
                ready = await _poll(c)
        if not ready:
            raise TimeoutError(f"opencode serve no arrancó en {timeout}s en puerto {self.port}")

    async def create_session(self, client: httpx.AsyncClient) -> str:
        r = await client.post(f"{self._base_url}/session", json={})
        r.raise_for_status()
        # El id viene en la RAIZ del objeto Session. Antes se leia `info.id`,
        # que no existe en la API real y hacia fallar todo job con KeyError.
        return r.json()["id"]

    async def send_prompt(
        self, client: httpx.AsyncClient, session_id: str, prompt: str, model: str = "glm-5.2"
    ) -> dict:
        r = await client.post(
            f"{self._base_url}/session/{session_id}/message",
            json={
                # `model` es un objeto {providerID, modelID}, ambos obligatorios;
                # un string plano lo rechaza el schema del runtime.
                "model": split_model(model),
                # `TextPartInput` exige `type` ademas de `text`.
                "parts": [{"type": "text", "text": prompt}],
            },
            timeout=600,
        )
        r.raise_for_status()
        return r.json()

    async def get_diff(self, client: httpx.AsyncClient, session_id: str) -> list[dict]:
        r = await client.get(f"{self._base_url}/session/{session_id}/diff")
        r.raise_for_status()
        return r.json()

    async def stream_events(self, client: httpx.AsyncClient) -> AsyncIterator[dict]:
        async with client.stream("GET", f"{self._base_url}/event") as response:
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    try:
                        yield json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue


class FakeOpencodeRunner(OpencodeRunner):
    """Runner falso para tests: no spawna proceso opencode.

    Configurable con un diff pre-grabado y eventos SSE pre-definidos.
    """

    def __init__(
        self,
        workdir: str = "/tmp/workspace/fake",
        port: int = 9999,
        diff: list[dict] | None = None,
        events: list[dict] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> None:
        super().__init__(workdir, port, env_overrides)
        self.diff = diff or []
        self.events = events or []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def wait_ready(self, timeout: float = 30) -> None:
        pass

    async def create_session(self, client: httpx.AsyncClient) -> str:
        return "fake-session-id"

    async def send_prompt(
        self, client: httpx.AsyncClient, session_id: str, prompt: str, model: str = "glm-5.2"
    ) -> dict:
        return {"info": {"id": "fake-msg"}, "parts": []}

    async def get_diff(self, client: httpx.AsyncClient, session_id: str) -> list[dict]:
        return self.diff

    async def stream_events(self, client: httpx.AsyncClient) -> AsyncIterator[dict]:
        for ev in self.events:
            yield ev
