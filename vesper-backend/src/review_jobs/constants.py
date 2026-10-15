"""Constantes del dominio `review_jobs`."""

from enum import StrEnum


class TaskType(StrEnum):
    """Tareas que cubre el agente. Las 5 que eligio el usuario."""

    security = "security"  # CVEs, secretos, OWASP
    quality = "quality"  # code quality / refactors
    deps = "deps"  # dependency updates
    perf = "perf"  # performance / queries
    docs = "docs"  # docs / coverage


class JobStatus(StrEnum):
    """Estado de un ReviewJob."""

    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    needs_review = "needs_review"  # diff toca rutas sensibles; approval manual


class JobTrigger(StrEnum):
    """Que disparo el job."""

    cron = "cron"
    webhook = "webhook"
    manual = "manual"
    prompt = "prompt"


# Rutas sensibles: si el diff las toca, el job se marca `needs_review` (no
# auto-merge). El tenant_admin aprueba manualmente desde la UI.
SENSITIVE_PATHS = (
    ".github/workflows/",
    "package.json",  # deps nuevas
    "requirements.txt",
    "pyproject.toml",
    ".env",
)

# Secretos que el agente NUNCA debe introducir en un PR. Si el diff añade una
# linea que casa con alguno, el job se marca `needs_review` y no se abre PR: un
# secreto commiteado queda en el historial de git aunque se borre despues.
# Solo se inspeccionan las lineas AÑADIDAS; que el agente BORRE un secreto es
# justo lo que se le pide.
SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("GitHub token", r"gh[pousr]_[A-Za-z0-9]{36,}"),
    ("Anthropic API key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("OpenAI API key", r"sk-(?!ant-)[A-Za-z0-9]{32,}"),
    ("Slack token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("private key block", r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----"),
    (
        "credential in connection string",
        r"(?:postgres|postgresql|mysql|mongodb)(?:\+\w+)?://[^\s:]+:[^\s@]+@",
    ),
    (
        "hardcoded credential",
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)\b"
        r"\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']",
    ),
)

# Claves donde el runtime de opencode puede devolver el cuerpo del diff.
DIFF_CONTENT_KEYS = ("patch", "diff", "content")

# Branch prefix de los PRs abiertos por el bot.
BRANCH_PREFIX = "vesper"

# Artefactos que aparecen en el workspace por el mero hecho de trabajar en el
# (bytecode, caches de linters, dependencias) y que no deben acabar en el PR.
# Se escriben en `.git/info/exclude` del clon, que es local y no se commitea.
# El primer PR real salio con dos `.pyc` dentro: el language server del agente
# compilo el proyecto y `git add -A` se los llevo.
EPHEMERAL_PATTERNS = (
    "__pycache__/",
    "*.py[cod]",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    "node_modules/",
    ".next/",
    ".turbo/",
    "*.log",
    ".DS_Store",
    ".opencode/",
)
