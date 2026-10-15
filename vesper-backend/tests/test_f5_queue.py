"""Tests de la cola de F5.

Ninguno necesita Redis: se ejercita el camino degradado, que es justo el que
mantiene vivos el dev local y el resto de la suite.
"""

import uuid

import pytest

from src.core import queue


@pytest.fixture(autouse=True)
def _reset():
    queue.reset_queue()
    yield
    queue.reset_queue()


async def test_sin_redis_ejecuta_in_process(monkeypatch):
    """Sin REDIS_URL la cola no falla: cae al camino de siempre."""
    monkeypatch.setattr(queue.settings, "redis_url", "", raising=False)
    llamadas = []
    monkeypatch.setitem(queue.LOCAL_FALLBACKS, "demo_fn", lambda *a: llamadas.append(a))

    resultado = await queue.enqueue("demo_fn", "arg1", "arg2")

    assert resultado is None
    assert llamadas == [("arg1", "arg2")]


async def test_funcion_desconocida_sin_redis_es_error(monkeypatch):
    """Un nombre sin fallback registrado no puede fallar en silencio."""
    monkeypatch.setattr(queue.settings, "redis_url", "", raising=False)

    with pytest.raises(KeyError):
        await queue.enqueue("no_existe")


async def test_enqueue_review_job_sin_redis_corre_in_process(monkeypatch):
    """El fallback registrado por review_jobs es el schedule_job_run de siempre."""
    from src.review_jobs import services as rj

    monkeypatch.setattr(queue.settings, "redis_url", "", raising=False)
    vistos = []
    monkeypatch.setattr(rj, "schedule_job_run", lambda *a, **k: vistos.append(a))

    jid, tid = uuid.uuid4(), uuid.uuid4()
    await rj.enqueue_review_job(jid, tid)

    assert vistos == [(jid, tid)]


async def test_publish_abort_sin_redis_no_revienta(monkeypatch):
    """Sin Redis el abort sigue siendo local; publicar es un no-op silencioso."""
    from src.review_jobs import services as rj

    monkeypatch.setattr(rj.settings, "redis_url", "", raising=False)
    rj.reset_event_bus()
    await rj.publish_abort(uuid.uuid4())  # no debe lanzar


async def test_worker_registra_run_review_job():
    """El nombre registrado debe casar con el que usa `enqueue`."""
    from src.review_jobs.services import QUEUE_FN_RUN_JOB
    from src.worker import WorkerSettings

    nombres = {f.__name__ for f in WorkerSettings.functions}
    assert QUEUE_FN_RUN_JOB in nombres


def test_worker_redis_settings_es_un_atributo_que_arq_sabe_leer():
    """Arq lee `WorkerSettings.redis_settings.host` como atributo. Con un
    `staticmethod` el worker de produccion moria al arrancar en bucle
    (`'staticmethod' object has no attribute 'host'`) y nada vigilaba los repos."""
    from arq.connections import RedisSettings

    from src.worker import WorkerSettings

    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
