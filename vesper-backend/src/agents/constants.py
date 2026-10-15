"""Constantes del dominio `agents`."""

# Pool de puertos para `opencode serve`. Uno por job concurrently.
# Ver `CLAUDE.md` -> Trampas: matarlos por PID concreto al cierre.
OPENCODE_SERVE_HOST = "127.0.0.1"

# Tiempo maximo de un job antes de abortarlo (segundos).
JOB_TIMEOUT_SECONDS = 30 * 60  # 30 min por defecto; configurable por tenant en F6.

# TODO(F4): ajustar timeout por `task_type` (security puede tardar mas).
