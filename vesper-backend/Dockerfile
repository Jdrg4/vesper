# Dockerfile de PRODUCCION del backend (FastAPI). Usado por Coolify via
# docker-compose.deploy.yml (build_pack=dockercompose). El backend NUNCA es
# publico (ver docker-compose.deploy.yml): solo `expose`, jamas `ports`.
#
# --- Builder: instala dependencias con headers de compilacion ---
# asyncpg / psycopg[binary] / passlib[argon2] suelen traer wheels
# precompilados, pero si pip cae a compilar desde sdist necesita gcc + libpq-dev.
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Runner: imagen final sin herramientas de compilacion ---
FROM python:3.12-slim

WORKDIR /app

RUN groupadd --system --gid 1001 vesper \
    && useradd --system --uid 1001 --gid vesper --no-create-home vesper

COPY --from=builder /root/.local /usr/local

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY scripts/ ./scripts/
COPY docker-entrypoint.sh .

RUN chmod +x docker-entrypoint.sh \
    && chown -R vesper:vesper /app

USER vesper

EXPOSE 8000

# Liveness basico para Coolify/Docker: no toca BD (GET /health).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
