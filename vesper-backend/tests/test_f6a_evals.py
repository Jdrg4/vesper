"""F6a — el banco de evals juzga bien.

Un eval roto que da por bueno lo que no lo es es peor que no tener evals: estos
tests comprueban cada comprobacion con un motor que acierta y otro que falla.
El banco real (con modelo y saldo) se lanza a mano: `python -m evals.run`.
"""

import pytest

from evals.run import run_task
from evals.tasks import TASKS
from src.agents.engine import FakeEngine

FIXED_CALC = """def suma(a, b):
    return a + b


def resta(a, b):
    return a - b
"""

DOCUMENTED = '''def saluda(nombre):
    """Devuelve un saludo para `nombre`."""
    return f"Hola, {nombre}"
'''


def _task(name):
    return next(t for t in TASKS if t.name == name)


async def _run(name, engine):
    return await run_task(_task(name), "fake/model", {}, lambda _job_id: engine)


async def test_bug_suma_aprueba_el_arreglo():
    row = await _run("bug-suma", FakeEngine(files={"calc.py": FIXED_CALC}))
    assert row.passed, row.detail


async def test_bug_suma_suspende_si_no_se_toca_nada():
    row = await _run("bug-suma", FakeEngine())
    assert not row.passed


async def test_docstrings_aprueba_con_docstring_y_suite_verde():
    row = await _run("docstrings", FakeEngine(files={"texto.py": DOCUMENTED}))
    assert row.passed, row.detail


async def test_docstrings_suspende_si_rompe_el_modulo():
    row = await _run("docstrings", FakeEngine(files={"texto.py": '"""Doc."""\n'}))
    assert not row.passed


async def test_nada_que_hacer_aprueba_sin_cambios():
    row = await _run("nada-que-hacer", FakeEngine())
    assert row.passed, row.detail


async def test_nada_que_hacer_suspende_si_toca_algo():
    row = await _run("nada-que-hacer", FakeEngine(files={"texto.py": DOCUMENTED}))
    assert not row.passed


async def test_un_motor_que_falla_suspende_y_dice_por_que():
    row = await _run("bug-suma", FakeEngine(error="El modelo no respondio: 402"))
    assert not row.passed
    assert "402" in row.detail


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.name)
def test_cada_tarea_tiene_prompt(task):
    assert task.prompt.strip()


async def test_un_motor_que_revienta_con_otra_excepcion_no_tumba_el_banco():
    class Exploding(FakeEngine):
        async def run(self, *args, **kwargs):
            raise ValueError("500 crudo")

    row = await _run("bug-suma", Exploding())
    assert not row.passed
    assert "500 crudo" in row.detail
