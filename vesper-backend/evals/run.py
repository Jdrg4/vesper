"""Banco de evals de Vesper (F6a). GASTA SALDO de la key: solo a mano.

    VESPER_EVAL_CREDENTIALS="deepseek=sk-..." \\
        python -m evals.run --model deepseek/deepseek-v4-pro [--task bug-suma]

Corre el motor directamente sobre una copia del fixture (sin GitHub ni base de
datos) y saca una tabla: tarea · modelo · motor · resultado · segundos · tokens.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from evals.tasks import FIXTURE, TASKS, EvalTask
from src.agents.engine import Activity, AgentEngine, EngineResult
from src.agents.opencode_engine import OpencodeEngine

EngineFactory = Callable[[str], AgentEngine]


@dataclass
class Row:
    task: str
    model: str
    engine: str
    passed: bool
    seconds: float
    tokens: int
    detail: str = ""


def _git(workdir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=eval", "-c", "user.email=eval@vesper", *args],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


async def run_task(
    task: EvalTask,
    model: str,
    credentials: dict[str, str],
    engine_factory: EngineFactory,
) -> Row:
    base = Path(tempfile.mkdtemp(prefix="vesper-eval-"))
    workdir = base / "repo"
    shutil.copytree(FIXTURE, workdir)
    _git(workdir, "init", "-q")
    _git(workdir, "add", "-A")
    _git(workdir, "commit", "-q", "-m", "fixture")

    engine = engine_factory(f"eval-{uuid.uuid4().hex[:8]}")
    started = time.monotonic()
    result, detail = EngineResult(), ""

    async def ignore(_: Activity) -> None:
        return None

    try:
        result = await engine.run(workdir, task.prompt, model, credentials, ignore)
    except RuntimeError as exc:
        detail = str(exc)
    finally:
        await engine.stop()

    passed = False
    if not detail:
        _git(workdir, "add", "-A")
        diff = _git(workdir, "diff", "--cached")
        passed = task.check(workdir, diff)
        detail = "" if passed else "la comprobación no se cumplió"
    shutil.rmtree(base, ignore_errors=True)
    return Row(
        task=task.name,
        model=model,
        engine=type(engine).__name__,
        passed=passed,
        seconds=round(time.monotonic() - started, 1),
        tokens=result.tokens_input + result.tokens_output,
        detail=detail,
    )


def table(rows: list[Row]) -> str:
    lines = [
        "| Tarea | Modelo | Motor | Resultado | s | Tokens | Detalle |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        mark = "✅" if r.passed else "❌"
        cells = [r.task, r.model, r.engine, mark, str(r.seconds), str(r.tokens), r.detail]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _credentials() -> dict[str, str]:
    raw = os.environ.get("VESPER_EVAL_CREDENTIALS", "")
    pairs = (item.split("=", 1) for item in raw.split(",") if "=" in item)
    return {provider.strip(): key.strip() for provider, key in pairs}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True, help="proveedor/modelo")
    parser.add_argument("--task", action="append", help="solo estas tareas")
    args = parser.parse_args()

    credentials = _credentials()
    if not credentials:
        raise SystemExit('Falta VESPER_EVAL_CREDENTIALS="proveedor=key"')
    tasks = [t for t in TASKS if not args.task or t.name in args.task]
    root = Path(tempfile.mkdtemp(prefix="vesper-eval-runtime-"))
    rows = []
    for task in tasks:
        rows.append(
            await run_task(task, args.model, credentials, lambda jid: OpencodeEngine(root, jid))
        )
        print(table(rows[-1:]).splitlines()[-1], flush=True)

    report = table(rows)
    print("\n" + report)
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M")
    (out / f"{stamp}.md").write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
