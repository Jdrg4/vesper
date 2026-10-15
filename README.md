# Vesper

**Un agente que vigila tus repositorios de GitHub y te abre Pull Requests.** Seguridad, calidad
de código, dependencias, rendimiento y documentación: Vesper revisa tus repos de forma
continua y propone los cambios como PRs listos para revisar.

Multi-tenant y autoservicio: cada equipo conecta sus repos con una GitHub App, trae su propia
API key del proveedor de modelos (BYOK) y decide cuándo actuar el agente. La interfaz es una
PWA pensada para el móvil.

> **Estado:** en desarrollo activo, aún sin versión estable. Las fases F1-F5 (auth y
> multi-tenancy, GitHub App, runner del agente, triggers) están cerradas; F6 —el motor de
> agente propio— está en curso. No lo uses todavía en producción.

## Qué hace

- **Cuatro formas de disparar al agente**: programado (cron), por webhook de GitHub (`push`),
  manual desde la UI, o con un prompt libre.
- **Abre el PR él mismo**, con el token de instalación de la GitHub App: rama nueva, commit,
  push y PR, después de validar el diff (secretos, archivos generados).
- **Progreso en vivo** por SSE en la interfaz.
- **BYOK**: cada tenant guarda sus credenciales cifradas y elige modelo de desarrollo y de
  revisión.
- **Próximamente**: bucle de agente propio con entorno de desarrollo containerizado por job
  (instala dependencias, corre la suite y Playwright antes de abrir el PR) y un segundo
  modelo que revisa cada PR.

## Stack

- **Backend** (`vesper-backend/`): Python 3.12 · FastAPI · SQLAlchemy async · Alembic ·
  Pydantic v2 · PostgreSQL · Redis · Arq.
- **Frontend** (`vesper-frontend/`): Next.js 16 · Tailwind v4 · shadcn/ui · React Query ·
  Zustand · Zod · Vitest · Playwright.

## Arranque rápido (local)

Requisitos: Python 3.12, Node 22 con pnpm, PostgreSQL 16+ en el puerto 55432 (ver
[.claude/rules/bd-local.md](.claude/rules/bd-local.md)). Redis es opcional.

```bash
# Backend
cd vesper-backend
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export PYTHONPATH=.
alembic upgrade head
python scripts/seed_test_users.py
uvicorn src.main:app --reload --port 8000

# Worker (otra terminal): cola de jobs y cron
arq src.worker.WorkerSettings

# Frontend (otra terminal)
cd vesper-frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

Usuarios de prueba en [docs/test-users.md](docs/test-users.md). Para conectar repos reales
necesitas crear tu propia GitHub App: ver
[.claude/rules/github-app-entorno.md](.claude/rules/github-app-entorno.md).

## Contribuir

Lee [CLAUDE.md](CLAUDE.md): arquitectura, comandos, el invariante de aislamiento
multi-tenant y la lista de comprobaciones antes de abrir un PR. Sirve igual si trabajas con
o sin un agente de código. Las decisiones de diseño por fase están en
[docs/superpowers/specs/](docs/superpowers/specs/).

## Licencia

Vesper se distribuye bajo la [Functional Source License 1.1 (FSL-1.1-ALv2)](LICENSE.md). Es
**source-available**, no open source en sentido estricto:

- ✅ Puedes usarlo, modificarlo y autoalojarlo, también dentro de tu empresa y para tus
  propios repos.
- ❌ No puedes ofrecerlo, ni una versión modificada, como producto o servicio que compita
  con Vesper.
- ⏳ Cada versión pasa automáticamente a **Apache 2.0** dos años después de publicarse.
