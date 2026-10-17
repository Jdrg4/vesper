"""F6b: qué tests correr en un repo y qué veredicto sale de compararlos antes/después.

Módulo puro (sin Docker ni BD): el motor con contenedor lo alimenta y `services.py` lo lee.
"""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from src.review_jobs.constants import SECRET_PATTERNS

_SECRETS = tuple(re.compile(p) for _, p in SECRET_PATTERNS)


@dataclass(frozen=True)
class TestCommand:
    __test__ = False  # pytest no debe recogerla como clase de tests

    install: str | None  # p. ej. "pnpm install --frozen-lockfile"
    test: str  # p. ej. "pnpm test"


@dataclass
class SuiteRun:
    exit_code: int | None  # None = no hubo comandos
    log_tail: str = ""  # ya redactado y truncado a 4096
    timed_out: bool = False


@dataclass
class Verification:
    commands: list[TestCommand]
    before: SuiteRun
    after: SuiteRun


class Verdict(StrEnum):
    verified = "verified"  # ✅ → ✅
    broke = "broke"  # ✅ → ❌
    already_red = "already_red"  # ❌ → *
    unverified = "unverified"  # sin comandos o motor sin verificación


def _node(repo: Path) -> TestCommand | None:
    try:
        scripts = json.loads((repo / "package.json").read_text(encoding="utf-8")).get("scripts")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(scripts, dict) or "test" not in scripts:
        return None
    if (repo / "pnpm-lock.yaml").exists():
        return TestCommand("pnpm install --frozen-lockfile", "pnpm test")
    if (repo / "yarn.lock").exists():
        return TestCommand("yarn install --frozen-lockfile", "yarn test")
    return TestCommand("npm ci", "npm test")


def _python(repo: Path) -> TestCommand | None:
    pyproject = repo / "pyproject.toml"
    req_files = sorted(repo.glob("requirements*.txt"))
    if not (pyproject.exists() or req_files):
        return None
    try:
        pyproject_text = (
            pyproject.read_text(encoding="utf-8", errors="replace") if pyproject.exists() else ""
        )
    except OSError:
        pyproject_text = ""
    has_tests = (
        (repo / "tests").is_dir() or any(repo.glob("test_*.py")) or "[tool.pytest" in pyproject_text
    )
    if not has_tests:
        return None
    if pyproject.exists():
        return TestCommand("pip install -e .", "python -m pytest -q")
    req = "requirements.txt" if (repo / "requirements.txt").exists() else req_files[0].name
    return TestCommand(f"pip install -r {req}", "python -m pytest -q")


def _make(repo: Path) -> TestCommand | None:
    try:
        text = (repo / "Makefile").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return TestCommand(None, "make test") if re.search(r"^test:", text, re.M) else None


def detect_test_commands(repo: Path) -> list[TestCommand]:
    """Comandos de test del repo, en orden node, python, make (spec §5)."""
    found = (_node(repo), _python(repo), _make(repo))
    return [c for c in found if c]


def verdict(v: Verification | None) -> Verdict:
    if v is None or not v.commands or v.before.exit_code is None:
        return Verdict.unverified
    if v.before.exit_code != 0:
        return Verdict.already_red
    return Verdict.verified if v.after.exit_code == 0 else Verdict.broke


def tail_redacted(text: str, limit: int = 4096) -> str:
    """Redacta primero y trunca después: así un secreto cortado por el límite no se cuela."""
    for pattern in _SECRETS:
        text = pattern.sub("[REDACTED]", text)
    return text[-limit:]
