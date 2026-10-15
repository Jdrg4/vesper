"""F6a — OpencodeEngine: turno + escucha SSE + corte por inactividad.

El runner falso reproduce la forma real de los eventos de opencode 1.19.0
(ver tests/test_f6a_engine.py). No arranca ningun proceso.
"""

import asyncio
import contextlib

import httpx
import pytest

from src.agents import opencode_engine
from src.agents.engine import Activity
from src.agents.opencode_engine import OpencodeEngine
from src.agents.runner import FakeOpencodeRunner

SID = "fake-session-id"


def _tool(status, tool="edit", file=None, call="c1"):
    state = {"status": status, "input": {"filePath": file} if file else {}}
    part = {"type": "tool", "tool": tool, "callID": call, "state": state, "sessionID": SID}
    return {"type": "message.part.updated", "properties": {"sessionID": SID, "part": part}}


def _step(inp, out, cost):
    part = {"type": "step-finish", "tokens": {"input": inp, "output": out}, "cost": cost}
    return {"type": "message.part.updated", "properties": {"sessionID": SID, "part": part}}


DELTA = {"type": "message.part.delta", "properties": {"sessionID": SID, "delta": "x"}}
HEARTBEAT = {"type": "server.heartbeat", "properties": {}}


class ScriptedRunner(FakeOpencodeRunner):
    """`script`: lista de (segundos de espera, evento). El turno dura `turn` s."""

    def __init__(self, workdir, port, env=None, *, script=(), turn=0.0, fail=None, close=False):
        super().__init__(workdir, port)
        self.script = list(script)
        self.turn = turn
        self.fail = fail
        self.close = close  # el SSE se corta tras el guion y no vuelve
        self.stops = 0
        self.streams = 0

    async def stop(self):
        self.stops += 1

    async def send_prompt(self, client, session_id, prompt, model="m"):
        await asyncio.sleep(self.turn)
        if self.fail:
            raise self.fail
        return {"info": {}, "parts": []}

    async def stream_events(self, client):
        self.streams += 1
        if self.close and self.streams > 1:
            return
        # Como opencode real: lo primero que llega al suscribirse.
        yield {"type": "server.connected", "properties": {}}
        for delay, ev in self.script:
            await asyncio.sleep(delay)
            yield ev
        if not self.close:
            await asyncio.Event().wait()


def _engine(tmp_path, runner, idle=0.3):
    return OpencodeEngine(
        tmp_path, "job-1", runner_factory=lambda *a, **k: runner, idle_timeout=idle, poll=0.02
    )


async def _collect(engine, tmp_path):
    seen: list[Activity] = []

    async def on_activity(a):
        seen.append(a)

    try:
        result = await engine.run(
            tmp_path / "repo", "p", "deepseek/x", {"deepseek": "k"}, on_activity
        )
    finally:
        await engine.stop()
    return result, seen


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "repo").mkdir()
    return tmp_path / "repo"


async def test_un_turno_normal_suma_tokens_y_avisa_actividad(tmp_path, repo):
    script = [
        (0, _tool("running", file=str(repo / "app.py"))),
        (0, _step(10, 2, 0.5)),
        (0, _step(5, 1, 0.25)),
    ]
    runner = ScriptedRunner(str(repo), 0, script=script, turn=0.1)
    result, seen = await _collect(_engine(tmp_path, runner), tmp_path)
    assert seen == [Activity("edit", "app.py")]
    assert (result.tokens_input, result.tokens_output, result.cost) == (15, 3, 0.75)


async def test_sin_senales_de_vida_corta_por_inactividad(tmp_path, repo):
    runner = ScriptedRunner(str(repo), 0, turn=60)
    with pytest.raises(RuntimeError, match="no dio señales de vida"):
        await asyncio.wait_for(_collect(_engine(tmp_path, runner), tmp_path), 5)


async def test_el_heartbeat_no_mantiene_vivo_al_agente(tmp_path, repo):
    runner = ScriptedRunner(str(repo), 0, script=[(0.1, HEARTBEAT)] * 100, turn=60)
    with pytest.raises(RuntimeError, match="no dio señales de vida"):
        await asyncio.wait_for(_collect(_engine(tmp_path, runner), tmp_path), 5)


async def test_un_agente_que_escribe_no_se_corta(tmp_path, repo):
    runner = ScriptedRunner(str(repo), 0, script=[(0.1, DELTA)] * 12, turn=1.0)
    await asyncio.wait_for(_collect(_engine(tmp_path, runner), tmp_path), 5)


async def test_una_herramienta_larga_no_cuenta_como_inactividad(tmp_path, repo):
    """Una suite de 12 min dentro de `bash` no emite nada hasta terminar."""
    script = [(0, _tool("running", tool="bash")), (0.8, _tool("completed", tool="bash"))]
    runner = ScriptedRunner(str(repo), 0, script=script, turn=0.9)
    await asyncio.wait_for(_collect(_engine(tmp_path, runner), tmp_path), 5)


async def test_un_modelo_inexistente_dice_por_que(tmp_path, repo):
    """Con un modelo desconocido opencode responde 500 generico; el motivo solo
    llega por `session.error`."""
    err = {
        "type": "session.error",
        "properties": {
            "sessionID": SID,
            "error": {"name": "UnknownError", "data": {"message": "Model not found: deepseek/x"}},
        },
    }
    request = httpx.Request("POST", "http://x/session/s/message")
    fail = httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request)
    )
    runner = ScriptedRunner(str(repo), 0, script=[(0, err)], turn=0.1, fail=fail)
    with pytest.raises(RuntimeError, match="Model not found: deepseek/x"):
        await _collect(_engine(tmp_path, runner), tmp_path)


async def test_stop_es_idempotente_y_libera_el_puerto(tmp_path, repo):
    runner = ScriptedRunner(str(repo), 0, turn=0)
    engine = _engine(tmp_path, runner)
    await _collect(engine, tmp_path)  # ya llama a stop
    await engine.stop()
    assert runner.stops == 1
    assert not opencode_engine._PORTS_IN_USE
    assert not (tmp_path / ".runtime" / "job-1").exists()


async def test_stop_durante_el_turno_lo_corta(tmp_path, repo):
    runner = ScriptedRunner(str(repo), 0, script=[(0.05, DELTA)] * 100, turn=60)
    engine = _engine(tmp_path, runner, idle=10)

    async def noop(_):
        return None

    task = asyncio.create_task(engine.run(repo, "p", "deepseek/x", {}, noop))
    await asyncio.sleep(0.2)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await engine.stop()
    assert runner.stops == 1
    assert not opencode_engine._PORTS_IN_USE


async def test_el_motivo_del_500_se_espera_aunque_llegue_despues(tmp_path, repo):
    """Con opencode real el 500 vuelve antes de que el SSE entregue `session.error`:
    cortar la escucha en cuanto acaba el turno perdia el motivo."""
    err = {
        "type": "session.error",
        "properties": {
            "sessionID": SID,
            "error": {"name": "UnknownError", "data": {"message": "Model not found: deepseek/x"}},
        },
    }
    request = httpx.Request("POST", "http://x/session/s/message")
    fail = httpx.HTTPStatusError(
        "500", request=request, response=httpx.Response(500, request=request)
    )
    runner = ScriptedRunner(str(repo), 0, script=[(0.3, err)], turn=0.05, fail=fail)
    with pytest.raises(RuntimeError, match="Model not found: deepseek/x"):
        await _collect(_engine(tmp_path, runner), tmp_path)


async def test_si_publicar_la_actividad_falla_el_job_sigue(tmp_path, repo):
    """Un corte de Redis al publicar la actividad (cosmetica) tumbaba el listener y,
    al acabar, el job fallaba aunque el agente hubiera terminado bien."""
    script = [(0, _tool("running", file=str(repo / "a.py"))), (0, _step(1, 1, 0.1))]
    runner = ScriptedRunner(str(repo), 0, script=script, turn=0.3)
    engine = _engine(tmp_path, runner)

    async def broken(_):
        raise ConnectionError("redis caido")

    try:
        result = await engine.run(repo, "p", "deepseek/x", {}, broken)
    finally:
        await engine.stop()
    assert result.tokens_input == 1


async def test_si_el_sse_se_corta_con_una_herramienta_en_marcha_el_corte_sigue_vivo(tmp_path, repo):
    """El `completed` de la herramienta se pierde con el SSE: sin limpiar `busy` el
    reloj quedaba pausado para siempre y el job llegaba al techo de 6 h."""
    script = [(0, _tool("running", tool="bash"))]
    runner = ScriptedRunner(str(repo), 0, script=script, turn=60, close=True)
    with pytest.raises(RuntimeError, match="no dio señales de vida"):
        await asyncio.wait_for(_collect(_engine(tmp_path, runner), tmp_path), 5)


async def test_un_error_inmediato_no_se_pierde_por_suscribirse_tarde(tmp_path, repo):
    """El turno no empieza hasta que el SSE esta conectado: si el modelo falla al
    instante, su `session.error` ya tiene quien lo escuche."""
    order: list[str] = []

    class Ordered(ScriptedRunner):
        async def send_prompt(self, client, session_id, prompt, model="m"):
            order.append("turn")
            return await super().send_prompt(client, session_id, prompt, model)

        async def stream_events(self, client):
            async for ev in super().stream_events(client):
                order.append(ev["type"])
                yield ev

    runner = Ordered(str(repo), 0, turn=0)
    await _collect(_engine(tmp_path, runner), tmp_path)
    assert order[:2] == ["server.connected", "turn"]
