"""F6a — contrato del motor y parser de eventos de opencode.

Los eventos son copias (recortadas) de los que emitio `opencode` 1.19.0 real con
deepseek-v4-pro el 2026-10-15.
"""

from pathlib import Path

import pytest

from src.agents.engine import Activity, FakeEngine, event_session, tool_activity

WORKDIR = Path("C:/ws/tenant/repo") if Path("C:/").exists() else Path("/ws/tenant/repo")


def _tool(status: str, tool: str = "edit", file: str | None = None) -> dict:
    state: dict = {"status": status, "input": {}}
    if file is not None:
        state["input"]["filePath"] = file
    return {
        "type": "message.part.updated",
        "properties": {
            "sessionID": "ses_1",
            "part": {"type": "tool", "tool": tool, "callID": "call_1", "state": state},
        },
    }


def test_la_sesion_se_lee_de_properties():
    assert (
        event_session({"type": "session.status", "properties": {"sessionID": "ses_1"}}) == "ses_1"
    )


def test_la_sesion_se_lee_de_la_parte_si_no_esta_arriba():
    ev = {"type": "message.part.updated", "properties": {"part": {"sessionID": "ses_2"}}}
    assert event_session(ev) == "ses_2"


def test_el_heartbeat_no_es_de_ninguna_sesion():
    assert event_session({"type": "server.heartbeat", "properties": {}}) is None


def test_una_herramienta_en_marcha_da_su_ruta_relativa():
    ev = _tool("running", file=str(WORKDIR / "src" / "app.py"))
    assert tool_activity(ev, WORKDIR) == Activity("edit", "src/app.py")


def test_una_ruta_fuera_del_workspace_no_se_reenvia():
    outside = WORKDIR.parent / "otro-repo" / "secreto.py"
    assert tool_activity(_tool("running", file=str(outside)), WORKDIR) == Activity("edit", None)


def test_una_herramienta_sin_archivo_da_solo_su_nombre():
    assert tool_activity(_tool("running", tool="glob"), WORKDIR) == Activity("glob", None)


@pytest.mark.parametrize("status", ["pending", "completed", "error"])
def test_solo_cuenta_la_herramienta_en_marcha(status):
    assert tool_activity(_tool(status, file=str(WORKDIR / "a.py")), WORKDIR) is None


def test_lo_que_no_es_herramienta_no_es_actividad():
    ev = {"type": "message.part.delta", "properties": {"sessionID": "ses_1", "delta": "Let"}}
    assert tool_activity(ev, WORKDIR) is None


async def test_fake_engine_escribe_archivos_y_avisa(tmp_path):
    seen: list[Activity] = []

    async def on_activity(a: Activity) -> None:
        seen.append(a)

    engine = FakeEngine(files={"a.py": "x = 1\n"}, activities=[Activity("edit", "a.py")])
    await engine.run(tmp_path, "p", "deepseek/x", {}, on_activity)
    assert (tmp_path / "a.py").read_text() == "x = 1\n"
    assert seen == [Activity("edit", "a.py")]


async def test_fake_engine_puede_fallar(tmp_path):
    async def noop(_):
        return None

    with pytest.raises(RuntimeError, match="boom"):
        await FakeEngine(error="boom").run(tmp_path, "p", "m", {}, noop)
