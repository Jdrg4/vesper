#!/bin/sh
# Entrypoint de produccion del backend: espera Postgres -> migra -> arranca uvicorn.
# F1: no hay seeds todavia (no hay auth ni tenant data). Se agregan en F2.
#
# Falla ruidoso a proposito: si `alembic upgrade head` falla, el contenedor
# NO debe arrancar uvicorn con un esquema inconsistente.
set -e

MAX_ATTEMPTS=30  # ~60s con 2s de espera entre intentos
ATTEMPT=0

echo "==> Esperando a Postgres..."
until python -c "
import sys
import psycopg
from src.core.config import settings

url = settings.database_url.replace('+asyncpg', '').replace('+psycopg', '')
try:
    psycopg.connect(url, connect_timeout=3).close()
except Exception as exc:
    print(f'  (aun no listo: {exc})', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
    ATTEMPT=$((ATTEMPT + 1))
    if [ "$ATTEMPT" -ge "$MAX_ATTEMPTS" ]; then
        echo "==> ERROR: Postgres no respondio tras ${MAX_ATTEMPTS} intentos (~60s). Abortando." >&2
        exit 1
    fi
    echo "==> Postgres no listo aun (intento ${ATTEMPT}/${MAX_ATTEMPTS}), reintentando en 2s..."
    sleep 2
done
echo "==> Postgres listo."

echo "==> Aplicando migraciones (alembic upgrade head)..."
if ! alembic upgrade head; then
    echo "==> ERROR: alembic upgrade head fallo. Abortando arranque (esquema inconsistente)." >&2
    exit 1
fi
echo "==> Migraciones OK."

# F2: sembrado idempotente de tenant admin de produccion va aqui.

echo "==> Arrancando uvicorn..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
