"""Tareas del banco de evals: un encargo y como se comprueba que salio bien.

Cada comprobacion mira el resultado (el diff, la suite del fixture), no lo que el
agente dice que hizo.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "repo-basico"


@dataclass(frozen=True)
class EvalTask:
    name: str
    prompt: str
    check: Callable[[Path, str], bool]  # (workdir, git diff) -> aprobado


def suite_passes(workdir: Path, *tests: str) -> bool:
    # Ejecuta codigo que el modelo acaba de escribir: el banco solo se lanza a
    # mano, sobre el fixture, nunca en CI ni contra repos de tenants.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
        cwd=workdir,
        capture_output=True,
        timeout=120,
    )
    return result.returncode == 0


def _docstring_ok(workdir: Path, diff: str) -> bool:
    texto = (workdir / "texto.py").read_text(encoding="utf-8")
    return '"""' in texto and suite_passes(workdir, "test_texto.py")


TASKS = [
    EvalTask(
        name="bug-suma",
        prompt="Los tests de calc.py fallan. Encuentra el bug y arréglalo sin tocar los tests.",
        check=lambda workdir, diff: "test_calc.py" not in diff and suite_passes(workdir),
    ),
    EvalTask(
        name="docstrings",
        prompt="Añade docstrings a las funciones de texto.py. No cambies su comportamiento.",
        check=_docstring_ok,
    ),
    EvalTask(
        name="nada-que-hacer",
        prompt=(
            "Revisa texto.py y test_texto.py. Si son correctos, no cambies nada: "
            "no hace falta mejorar nada que ya funcione."
        ),
        check=lambda workdir, diff: diff.strip() == "",
    ),
]
