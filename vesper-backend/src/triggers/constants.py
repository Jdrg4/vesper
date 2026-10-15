"""Constantes del dominio `triggers`."""

# Presets que ofrece la UI. La expresion cruda sigue disponible como
# "personalizado": pedirle una expresion cron a un usuario es una trampa.
CRON_PRESETS: dict[str, str] = {
    "hourly": "0 * * * *",
    "daily": "0 3 * * *",  # 03:00 UTC
    "weekly": "0 3 * * 1",  # lunes 03:00 UTC
}

# Techo de reglas por repo: son cinco tareas y hay un UNIQUE por (repo, tarea).
MAX_RULES_PER_REPO = 5
