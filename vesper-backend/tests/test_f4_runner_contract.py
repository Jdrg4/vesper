"""Contrato HTTP real de `opencode serve` (verificado contra opencode 1.18.7).

Estos tests fijan la forma exacta de request/response que expone el runtime.
Se escribieron tras ejecutar `opencode serve` de verdad y descubrir que el
runner asumia una API que no existe: la sesion llegaba en `info.id`, el modelo
se mandaba como string y las partes sin `type`. Con `FakeOpencodeRunner` todo
pasaba y en produccion habria fallado el primer job.

No se levanta ningun proceso: se usa `httpx.MockTransport`.
"""

import httpx
import pytest

from src.agents.runner import OpencodeRunner

BASE = "http://127.0.0.1:14096"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ------------------------------------------------------------------  Sesion
async def test_create_session_reads_id_from_root():
    """`POST /session` devuelve el id en la RAIZ, no en `info.id`."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        # Respuesta real de opencode 1.18.7 (recortada).
        return httpx.Response(
            200,
            json={
                "id": "ses_0551fb7beffejtN7p3dJbUvyhW",
                "slug": "misty-engine",
                "projectID": "c996ba91",
                "directory": "/tmp/ws",
                "version": "1.18.7",
            },
        )

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with _client(handler) as client:
        session_id = await runner.create_session(client)

    assert session_id == "ses_0551fb7beffejtN7p3dJbUvyhW"
    assert captured["url"] == f"{BASE}/session"


# ------------------------------------------------------------------  Prompt
async def test_send_prompt_uses_provider_model_object_and_typed_parts():
    """`model` es un objeto {providerID, modelID} y las partes llevan `type`."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"info": {"id": "msg_1"}, "parts": []})

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with _client(handler) as client:
        await runner.send_prompt(client, "ses_abc", "revisa el repo", "glm-5.2")

    assert captured["url"] == f"{BASE}/session/ses_abc/message"
    body = captured["body"]
    # El schema exige providerID y modelID; un string plano lo rechaza.
    assert body["model"] == {"providerID": "opencode-go", "modelID": "glm-5.2"}
    # TextPartInput requiere `type` ademas de `text`.
    assert body["parts"] == [{"type": "text", "text": "revisa el repo"}]


async def test_send_prompt_accepts_explicit_provider():
    """Un modelo `provider/modelo` permite usar otro proveedor que el default."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with _client(handler) as client:
        await runner.send_prompt(client, "ses_abc", "hola", "deepseek/deepseek-v4-pro")

    assert captured["body"]["model"] == {
        "providerID": "deepseek",
        "modelID": "deepseek-v4-pro",
    }


# --------------------------------------------------------------------  Diff
async def test_get_diff_returns_snapshot_file_diffs():
    """`GET /session/{id}/diff` devuelve una lista de SnapshotFileDiff."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BASE}/session/ses_abc/diff"
        return httpx.Response(
            200,
            json=[
                {
                    "file": "src/calc.py",
                    "patch": "@@ -1 +1 @@\n+x = 1\n",
                    "additions": 1,
                    "deletions": 0,
                    "status": "modified",
                }
            ],
        )

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with _client(handler) as client:
        diff = await runner.get_diff(client, "ses_abc")

    assert diff[0]["file"] == "src/calc.py"


# ------------------------------------------------------------------  Health
async def test_wait_ready_polls_global_health():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert str(request.url) == f"{BASE}/global/health"
        if calls["n"] < 2:
            raise httpx.ConnectError("aun arrancando")
        return httpx.Response(200, json={"healthy": True, "version": "1.18.7"})

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with _client(handler) as client:
        await runner.wait_ready(timeout=10, client=client)

    assert calls["n"] >= 2, "debe reintentar hasta que el server responda"


async def test_wait_ready_times_out():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nunca arranca")

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with _client(handler) as client:
        with pytest.raises(TimeoutError):
            await runner.wait_ready(timeout=2, client=client)


# --------------------------------------------------------------------  stop()
async def test_stop_is_safe_when_process_already_exited():
    """`stop()` corre en el `finally` de run_job: no puede lanzar.

    Si el proceso ya murio, `kill()` lanza ProcessLookupError y esa excepcion
    tapaba el error real del job.
    """

    class _DeadProcess:
        returncode = 0

        def terminate(self):
            raise ProcessLookupError()

        def kill(self):
            raise ProcessLookupError()

        async def wait(self):
            return 0

    runner = OpencodeRunner("/tmp/ws", 14096)
    runner.process = _DeadProcess()
    await runner.stop()  # no debe lanzar


async def test_stop_without_process_is_noop():
    runner = OpencodeRunner("/tmp/ws", 14096)
    await runner.stop()


# -------------------------------------------------  Password del server
def test_each_runner_gets_its_own_password():
    """Un password distinto por job: el de un job no sirve contra otro."""
    a = OpencodeRunner("/tmp/a", 14096)
    b = OpencodeRunner("/tmp/b", 14097)
    assert a.server_password and b.server_password
    assert a.server_password != b.server_password
    assert len(a.server_password) >= 32


async def test_start_sets_server_password_env(monkeypatch):
    """`opencode serve` sin OPENCODE_SERVER_PASSWORD queda abierto, y
    `/config/providers` devuelve las API keys en claro a quien alcance el
    puerto — incluido el codigo del repo del tenant que corre en el sandbox."""
    captured = {}

    async def _fake_exec(*args, **kwargs):
        captured["env"] = kwargs.get("env")

        class _P:
            returncode = None

        return _P()

    from src.agents import runner as runner_mod

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", _fake_exec)
    r = OpencodeRunner("/tmp/ws", 14096)
    await r.start()

    assert captured["env"]["OPENCODE_SERVER_PASSWORD"] == r.server_password
    # Lo minimo para que el proceso arranque si se conserva.
    assert "PATH" in captured["env"] or "Path" in captured["env"]


async def test_start_no_hereda_los_secretos_del_backend(monkeypatch):
    """El agente ejecuta comandos y scripts del repo del tenant: todo lo que haya
    en su entorno es legible por un prompt malicioso (`env`, `/proc/<pid>/environ`).
    Con `os.environ` entero se llevaba la clave que descifra las credenciales de
    TODOS los tenants, la URL de la BD y la clave privada de la GitHub App."""
    captured = {}

    async def _fake_exec(*args, **kwargs):
        captured["env"] = kwargs.get("env")

        class _P:
            returncode = None

        return _P()

    from src.agents import runner as runner_mod

    for name in (
        "CREDENTIALS_ENCRYPTION_KEY",
        "DATABASE_URL",
        "JWT_SECRET",
        "GITHUB_APP_PRIVATE_KEY",
        "OPENCODE_ZEN_KEY",
    ):
        monkeypatch.setenv(name, "secreto-del-backend")
    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", _fake_exec)
    r = OpencodeRunner("/tmp/ws", 14096, {"XDG_DATA_HOME": "/tmp/job/data"})
    await r.start()

    assert "secreto-del-backend" not in captured["env"].values()
    assert captured["env"]["XDG_DATA_HOME"] == "/tmp/job/data"


async def test_requests_authenticate_with_basic_auth():
    """El runtime exige Basic auth cuando el password esta puesto."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "ses_x"})

    runner = OpencodeRunner("/tmp/ws", 14096)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), auth=runner.auth
    ) as client:
        await runner.create_session(client)

    assert seen["auth"], "las requests deben ir autenticadas"
    assert seen["auth"].startswith("Basic ")


# ------------------------------------------------------  Binario en Windows
def test_resolve_opencode_bin_prefers_setting(monkeypatch):
    from src.agents import runner as runner_mod

    monkeypatch.setattr(runner_mod.settings, "opencode_bin", r"C:\custom\opencode.exe")
    assert runner_mod.resolve_opencode_bin() == r"C:\custom\opencode.exe"


def test_resolve_opencode_bin_falls_back_to_which(monkeypatch):
    """En Windows el `opencode` del PATH de npm es un script sin extension y
    `create_subprocess_exec` no lo resuelve; `which` devuelve el ejecutable."""
    from src.agents import runner as runner_mod

    monkeypatch.setattr(runner_mod.settings, "opencode_bin", "")
    monkeypatch.setattr(runner_mod.shutil, "which", lambda _n: r"C:\npm\opencode.cmd")
    assert runner_mod.resolve_opencode_bin() == r"C:\npm\opencode.cmd"


# ------------------------------------------  Apagado: matar el arbol, no al padre
async def test_stop_mata_el_arbol_antes_de_terminar_el_padre():
    """`opencode` deja vivos sus language servers si solo matas al padre.

    Ademas, en Windows `which("opencode")` devuelve el `.cmd` de npm, asi que
    el hijo directo es el envoltorio: `terminate()` lo mataba y el servidor
    real seguia corriendo. Un job dejo ~30 procesos vivos, y uno de ellos
    mantenia abierto el workspace, tumbando el siguiente job del mismo repo.
    """
    from src.agents.runner import OpencodeRunner

    orden: list[str] = []

    class _Proc:
        pid = 4242
        returncode = None

        def terminate(self):
            orden.append("terminate")

        async def wait(self):
            self.returncode = 0

    runner = OpencodeRunner("/tmp/ws", 14096)
    runner.process = _Proc()

    async def _fake_kill_tree():
        orden.append("kill_tree")

    runner._kill_tree = _fake_kill_tree
    await runner.stop()

    assert orden == ["kill_tree", "terminate"]


async def test_stop_no_hace_nada_si_el_proceso_ya_murio():
    """`stop()` corre en el `finally` de `run_job`: si lanza, tapa el error real."""
    from src.agents.runner import OpencodeRunner

    llamadas: list[str] = []

    class _Muerto:
        pid = 1
        returncode = 0

        def terminate(self):
            llamadas.append("terminate")

    runner = OpencodeRunner("/tmp/ws", 14096)
    runner.process = _Muerto()

    await runner.stop()

    assert llamadas == []


async def test_kill_tree_no_lanza_con_un_pid_inexistente():
    from src.agents.runner import OpencodeRunner

    class _Fantasma:
        pid = 999_999
        returncode = None

    runner = OpencodeRunner("/tmp/ws", 14096)
    runner.process = _Fantasma()

    await runner._kill_tree()  # no debe lanzar
