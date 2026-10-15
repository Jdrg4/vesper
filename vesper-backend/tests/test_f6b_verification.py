"""F6b: detección de comandos de test y veredicto de verificación (módulo puro)."""

import json

import pytest

from src.agents.verification import (
    SuiteRun,
    TestCommand,
    Verdict,
    Verification,
    detect_test_commands,
    tail_redacted,
    verdict,
)


def _pkg(repo, scripts=None):
    (repo / "package.json").write_text(json.dumps({"scripts": scripts or {}}))


@pytest.mark.parametrize(
    ("lock", "install", "test"),
    [
        ("pnpm-lock.yaml", "pnpm install --frozen-lockfile", "pnpm test"),
        ("yarn.lock", "yarn install --frozen-lockfile", "yarn test"),
        (None, "npm ci", "npm test"),
    ],
)
def test_node_elige_gestor_por_lockfile(tmp_path, lock, install, test):
    _pkg(tmp_path, {"test": "vitest run"})
    if lock:
        (tmp_path / lock).write_text("")
    assert detect_test_commands(tmp_path) == [TestCommand(install, test)]


def test_package_json_sin_script_test_no_da_nada(tmp_path):
    _pkg(tmp_path, {"build": "tsc"})
    assert detect_test_commands(tmp_path) == []


def test_python_con_pyproject_y_carpeta_tests(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    assert detect_test_commands(tmp_path) == [
        TestCommand("pip install -e .", "python -m pytest -q")
    ]


def test_python_con_requirements_y_test_en_raiz(tmp_path):
    (tmp_path / "requirements.txt").write_text("pytest\n")
    (tmp_path / "test_algo.py").write_text("")
    assert detect_test_commands(tmp_path) == [
        TestCommand("pip install -r requirements.txt", "python -m pytest -q")
    ]


def test_python_con_pyproject_tool_pytest_sin_carpeta(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    assert len(detect_test_commands(tmp_path)) == 1


def test_pyproject_sin_tests_no_da_nada(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_test_commands(tmp_path) == []


def test_makefile_con_target_test(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tcc x.c\ntest:\n\t./run\n")
    assert detect_test_commands(tmp_path) == [TestCommand(None, "make test")]


def test_makefile_sin_target_test(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tcc x.c\n")
    assert detect_test_commands(tmp_path) == []


def test_varias_senales_en_orden(tmp_path):
    _pkg(tmp_path, {"test": "x"})
    (tmp_path / "requirements.txt").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / "Makefile").write_text("test:\n\ttrue\n")
    assert [c.test for c in detect_test_commands(tmp_path)] == [
        "npm test",
        "python -m pytest -q",
        "make test",
    ]


def test_ninguna_senal(tmp_path):
    assert detect_test_commands(tmp_path) == []


def _v(before, after):
    cmds = [TestCommand(None, "make test")]
    return Verification(cmds, SuiteRun(before), SuiteRun(after))


def test_veredicto_verified():
    assert verdict(_v(0, 0)) is Verdict.verified


def test_veredicto_broke():
    assert verdict(_v(0, 1)) is Verdict.broke


@pytest.mark.parametrize("after", [0, 1])
def test_veredicto_already_red(after):
    assert verdict(_v(1, after)) is Verdict.already_red


def test_veredicto_unverified_sin_motor_o_sin_comandos():
    assert verdict(None) is Verdict.unverified
    assert verdict(Verification([], SuiteRun(None), SuiteRun(None))) is Verdict.unverified


def test_tail_redacted_quita_secreto_y_trunca_por_el_final():
    texto = "inicio " + "x" * 5000 + " " + "AKIA" + "ABCDEFGHIJKLMNOP" + " fin"
    out = tail_redacted(texto)
    assert "AKIA" not in out
    assert len(out) <= 4096
    assert out.endswith("fin")
    assert "inicio" not in out
