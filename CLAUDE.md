# CLAUDE.md

Guía para trabajar en **Vesper** con Claude Code (o cualquier agente de código). Léela antes
de tocar nada: aquí están la arquitectura, los comandos, el invariante de seguridad y las
trampas que ya costaron tiempo. El detalle de cada módulo vive en `.claude/rules/` y se carga
solo al leer archivos de su ruta.

> Si tienes preferencias personales para este repo, ponlas en un `CLAUDE.local.md` en la raíz
> (está en `.gitignore`; Claude Code lo carga junto a este archivo).

## Qué es

**Plataforma multi-tenant que vigila continuamente los repositorios GitHub de cada inquilino
y propone Pull Requests autónomos** (seguridad, code quality, deps, performance, docs).
Interfaz móvil por **PWA**.

> *Claude Code multi-tenant, autoservicio, que te abre PRs.*

Monorepo con dos paquetes independientes:

- `vesper-backend/` — API FastAPI async (monolito modular), Python 3.12, PostgreSQL. **Privado:
  nunca expuesto a internet.**
- `vesper-frontend/` — Next.js 16 (App Router), pnpm. **La única app pública.**

Conceptos:

- **Tenant** = un equipo/desarrollador. Crea cuenta, instala la **GitHub App** en sus repos,
  configura `developer_model` + `reviewer_model` (BYOK: trae su propia key), recibe PRs del bot.
- **Agent loop** (hoy): el backend spawnea `opencode serve` por job, con `cwd` =
  workspace clonado del repo del tenant (shallow clone + token de instalación). Crea sesión,
  envía prompt, captura diff, valida, commitea en rama nueva y abre PR. SSE hacia la UI.
- **Multi-agente reviewer** (F7): un segundo modelo revisa el PR recién creado.
- **4 triggers** (F5): cron + webhook de GitHub + disparo manual + prompt libre desde la UI.

> ### 🔄 F6: harness intercambiable y PRs verificados (replanteada el 2026-10-15)
> Vesper **no** construye su propio bucle de agente: usa un harness maduro (`opencode`
> hoy) detrás de una interfaz de motor, para poder probar otros (`pi`, DeepSeek Harness) y
> elegir con evals, no a ojo. El esfuerzo de F6 va a lo que ningún harness resuelve: un
> **entorno de desarrollo containerizado por job** —donde el agente instala dependencias,
> levanta la BD, corre la suite y Playwright— para que el PR salga verificado y cada tenant
> quede aislado. La spec del 2026-08-04
> ([motor propio](docs/superpowers/specs/2026-08-04-f6-motor-de-agente-propio-design.md))
> queda superada en lo del bucle propio; sus partes de contenedor y evals siguen vigentes.

**Estado por fase (F1-F9)**: `.claude/rules/roadmap-fases.md`. Hoy: F1-F5 y F9 (despliegue)
cerradas; **F6 en curso**; F7 reviewer y F8 PWA pendientes. Las decisiones de diseño de cada fase
viven en [docs/superpowers/specs/](docs/superpowers/specs/): al tocar la lógica de una fase,
leer su spec antes de cambiarla.

### Servicios y puertos

| Servicio | Stack | Puerto | Dev local | Producción |
| --- | --- | --- | --- | --- |
| backend | Python 3.12 / FastAPI | 8000 | `uvicorn` nativo | Docker (`docker-compose.deploy.yml`) |
| frontend | Next.js 16 / pnpm | 3000 | `pnpm dev` (Turbopack) | Docker |
| `postgres` | PostgreSQL 16+ | 55432 | Postgres local | Contenedor del compose |
| `redis` | Redis | 6379 | Opcional (degrada con gracia) | Contenedor del compose |
| `worker` (cola + cron) | Arq | — | `arq src.worker.WorkerSettings` | Mismo contenedor, otro `command` |
| `opencode` (runtime agente) | binario opencode | 14096+ (pool dinámico) | Primer harness (F6 lo pone tras una interfaz) | Sandbox por job |

**Desarrollo local sin Docker**, salvo el sandbox del agent runner.

## Comandos

### Backend (`cd vesper-backend`)
```bash
python3.12 -m venv .venv            # Windows: py -3.12 -m venv .venv
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000

pytest                                                   # toda la suite (199 tests, ~100 s)
pytest tests/test_f4_review_jobs.py                      # un archivo
pytest tests/test_f4_review_jobs.py::test_abort_cancels_running_job   # un test
pytest --cov=src --cov-report=term
ruff check . && ruff format --check .                    # lint + formato (limpio: no ensuciar)
ruff check --fix . && ruff format .                      # auto-fix antes de commit

alembic upgrade head                                     # 0004 = unique por tenant, 0006 = watch_rules
alembic revision --autogenerate -m "descripcion"         # revisar SIEMPRE el script generado
alembic check                                            # drift modelos ↔ revisiones
```

Los tests necesitan **Postgres real** en `localhost:55432`, base `vesper_test`, usuario/clave
`vesper/vesper` (override con `TEST_DATABASE_URL`). El fixture recrea el esquema completo en
cada test, y el autouse `_override_get_db` es lo que redirige la app a la base de tests.
BD local y seed de usuarios: `.claude/rules/bd-local.md` y
[docs/test-users.md](docs/test-users.md).

### Frontend (`cd vesper-frontend`)
```bash
pnpm install
pnpm dev
pnpm build
pnpm lint
pnpm exec tsc --noEmit    # typecheck — lo corre la CI
pnpm test:run             # Vitest
npx playwright install chromium   # una vez por máquina
pnpm e2e                  # Playwright, con backend + frontend corriendo
```
El frontend necesita `.env.local` (copiar de `.env.example`); sin él la validación Zod de
`src/lib/env.ts` impide arrancar.

### Levantar el entorno completo (el orden importa)
```bash
# 1. Backend — SIN --reload si vas a ejecutar review jobs de verdad en Windows (ver Trampas)
cd vesper-backend && uvicorn src.main:app --port 8000
# 2. Worker de Arq (cola + cron), otra terminal
arq src.worker.WorkerSettings
# 3. Frontend, otra terminal
cd vesper-frontend && pnpm dev
```

## Arquitectura

```
PWA móvil (Next.js) — única app pública
  │
  ├─→ middleware.ts        protege /dashboard, /repositories, /jobs
  ├─→ Next.js API Routes (/api/[...path])   proxy server-side, cookies httpOnly
  │      │
  │      └─→ Backend API (/api/v1/...)   JWT, PRIVADO (nunca público)
  │             │
  │             ├─→ PostgreSQL (SQLAlchemy async, multi-tenant vía tenant_id)
  │             ├─→ Redis (cola de jobs + bus de eventos de progreso)
  │             ├─→ GitHub App (installation tokens per repo del tenant)
  │             │
  │             └─→ Agent runner (F4; F6 lo pone tras una interfaz de motor):
  │                   acquire_port() → `opencode serve --port <pool 14096+>`
  │                   cwd = <workspaces>/<tenant>/<repo>/
  │                   wait_ready() → POST /session → message → GET /diff
  │                   validate_diff() → commit + push + PR
  │
  └─→ SSE de progreso (backend → frontend)    un stream por review_job
```

**Regla de oro:** el navegador NUNCA ve una API key. Toda llamada a un proveedor de modelos
sale del backend (o del runtime que spawnea el backend). Toda escritura a GitHub sale con
installation token del tenant, no con PAT del usuario.

### Backend

Monolito modular: cada dominio es un paquete bajo `src/<modulo>/` con `models.py`,
`schemas.py`, `router.py`, `services.py`, `constants.py`. La lógica de negocio vive en
`services.py`, **NUNCA en el router**: el router valida input, llama al service y mapea la
respuesta.

| Módulo | Fase | Responsabilidad |
| --- | --- | --- |
| `auth` | F2 ✅ | Registro de tenant/usuario, login, JWT (access + refresh), roles. |
| `tenants` | F2 ✅ | Alta de tenant, plan, cuotas, configuración de modelos default. |
| `users` | F2 ✅ | Perfil, miembros del tenant, estado activo. |
| `repositories` | F3 ✅ | GitHub App, verificación OAuth de la instalación, enrollment. |
| `review_jobs` | F4 ✅ | Cola, estado y orquestación del runner. Cuotas por plan en `create_job`, el punto único por el que pasan los 4 triggers. |
| `triggers` | F5 ✅ | `watch_rules` (repo × tarea), scheduler cron y CRUD de reglas. |
| `webhooks` | F5 ✅ | `POST /api/v1/webhooks/github`: firma HMAC, filtros anti-bucle y despacho. |
| `agents` | ✅ / F6 ⬜ | **BYOK**: credenciales de IA por tenant, catálogo de proveedores y sandbox del runtime. |
| `reviews` | F7 ⬜ | Pasada de revisión con el segundo modelo. |

Patrones transversales:
- **Async de punta a punta.** `get_db` inyecta `AsyncSession` con commit/rollback
  automático. `await db.flush()` para obtener IDs antes del commit. **La única excepción** al
  "no llames `db.commit()` en services" es `ReviewService.trigger_job`: la tarea de fondo abre
  su propia sesión y no vería un job solo flusheado.
- **Migraciones:** `alembic/env.py` debe importar **todos** los `models.py` o
  `--autogenerate` falla en silencio (el hook de `.claude/hooks/` lo recuerda). Revisar
  siempre el script generado.
- **Logging:** structlog con eventos key-value (`logger.info("review_started", job_id=jid,
  tenant_id=tid)`). **Sin f-strings** en los mensajes del logger.
- **Health checks:** `GET /health` (liveness, no toca BD) y `GET /health/ready` (`SELECT 1`,
  503 si la BD falla).

### 🔒 Multi-tenant — invariante de aislamiento

**Es un invariante de seguridad. No se relaja para que pase un test.** Todo PR que lo toque se
revisa con lupa.

- **Toda query de dominio** pasa por `tenant_scoped_query(model, tenant_id)`
  (`src/core/tenancy.py`). Prohibido `db.get(Model, id)` directo: hay que
  `db.execute(tenant_scoped_query(Model, tid).where(Model.id == id))`.
- **La unicidad de identificadores externos es POR TENANT**, no global: `repositories` usa
  `UNIQUE (tenant_id, github_id)`. Un UNIQUE global hacía que el sync de un tenant
  encontrara y mutara la fila de otro con acceso al mismo repo.
  (`tenant_installations.installation_id` **sí** es UNIQUE global a propósito: una
  instalación pertenece a una sola cuenta.)
- **Los endpoints de streaming también van autenticados y scoped.** `GET /jobs/{id}/events`
  exige `get_current_tenant`; `EventSource` no manda headers pero sí la cookie `access_token`.
- **Tests de aislamiento obligatorios** en cada dominio: dato en tenant A, leer/escribir
  desde tenant B → debe fallar o devolver vacío.
- **El agente nunca ejecuta código del repo del tenant fuera del sandbox por job.**

### Frontend

Patrones (Next 16 async, middleware, refresh, SSE, React Query, Zustand, Zod, PWA) y trampas
de Playwright: `.claude/rules/frontend.md`. Antes de crear un componente, revisar
`src/components/ui/`. Diseño limpio de panel de control; mirar siempre también a 390 px.

## Configuración

- **Variables de entorno y creación de la GitHub App** (manifest flow, claves, OAuth de
  instalación): `.claude/rules/github-app-entorno.md`.
- **Modelos y credenciales (BYOK)** (cifrado Fernet, `resolve_credentials`, formato
  `proveedor/modelo`): `.claude/rules/byok.md`.
- **Secretos** solo en env vars / `.env` local. Nunca en el repo (hay `detect-secrets` en
  pre-commit).
- **Nunca correr validaciones, seeds ni migraciones de prueba contra producción.** El seed
  aborta si `DATABASE_URL` no es local.
- **Despliegue** (compose único, Traefik, Cloudflare Tunnel): `.claude/rules/produccion-deploy.md`.

## 📚 Conocimiento por módulo: `.claude/rules/`

Se carga **solo cuando se lee un archivo de sus rutas** (frontmatter `paths:`). Si una tarea
toca un tema sin leer sus archivos —p. ej. diseñas antes de abrir código—, **lee la regla a
mano**: es ahí donde están las trampas.

| Regla | Qué contiene |
|---|---|
| `agente-runner.md` | Seguridad del runner, trampas de `opencode` (puertos, `XDG_*`, árbol de procesos, `rmtree`, `git add -A`) y su deuda. |
| `byok.md` | Credenciales de IA por tenant: catálogo models.dev, cifrado Fernet, `resolve_credentials`. |
| `github-app-entorno.md` | Variables de entorno, manifest flow de la GitHub App, OAuth de instalación. |
| `triggers-webhooks.md` | Cron sin ticks perdidos, debounce, jobs colgados (`reap_stale_jobs`), webhook público, cuotas. |
| `frontend.md` | Patrones Next 16/React Query/Zustand/Zod/PWA, trampas de Playwright y `.env.local`. |
| `bd-local.md` | Postgres local, `vesper_dev`/`vesper_test`, seed de usuarios de prueba. |
| `roadmap-fases.md` | Tabla de estado F1-F9 y qué sustituye F6. |
| `produccion-deploy.md` | Despliegue con compose único y sus trampas. |

### Avisos transversales (muerden fuera de su módulo)

- 🔴 **Perder `CREDENTIALS_ENCRYPTION_KEY` equivale a perder todas las credenciales de los
  tenants** (`byok.md`).
- **Sin worker de Arq nadie recoge jobs colgados ni corre el cron**: el repo queda sin
  vigilar en silencio (`triggers-webhooks.md`).
- **Un `.catch(() => {})` en el frontend convierte un 401 en "no hay datos"**: una pantalla
  vacía puede ser una sesión caducada (`frontend.md`).
- **`opencode` deja un árbol de procesos y retiene el directorio del clon**: matar por
  árbol/PID (`agente-runner.md`).
- **`git add -A` se lleva lo que genera el agente** (`.pyc`): usar `EPHEMERAL_PATTERNS`
  (`agente-runner.md`).
- **Sin client id/secret de la GitHub App, toda instalación se rechaza** (falla cerrado).
- **CI y deploy corren en paralelo**: validar contra lo que sirve el sitio.

## Trampas conocidas (leer antes de depurar)

- **`uvicorn` sin `--reload` sirve código viejo** → **500 fantasma** en endpoints ya
  arreglados. Ante un 500 raro, levantar otra instancia en otro puerto y comparar.
- **`uvicorn --reload` en Windows impide que el agent runner arranque.** Con reload, uvicorn
  instala `WindowsSelectorEventLoopPolicy`, que **no soporta subprocesos**: el primer
  `asyncio.create_subprocess_exec` —el `git clone`— lanza `NotImplementedError`, cuyo
  `str()` es **cadena vacía**. Síntoma: el job pasa a `failed` en menos de un segundo con
  `{"error": "NotImplementedError: ..."}`. En Linux no aplica.
- **Matar el reloader de uvicorn deja huérfano al hijo, que retiene el puerto.** Buscar al
  dueño real del puerto (`Get-NetTCPConnection -LocalPort <puerto> -State Listen` en Windows,
  `lsof -i :<puerto>` en Unix) y matar por PID.
- **`pnpm-workspace.yaml` con los placeholders de `allowBuilds` rompe TODO**: con los
  literales `set this to true or false`, cualquier `pnpm install` aborta con
  `ERR_PNPM_IGNORED_BUILDS`. Resolver cada entrada a `true`/`false`.
- **Los tests deben apuntar a `vesper_test`.** Sin el autouse `_override_get_db` la suite pega
  contra `vesper_dev` (`UndefinedTableError`, o peor, escribe en la BD de desarrollo).
- **Los filtros `paths` de los workflows no disparan en el primer push de una rama**: usar
  `gh workflow run "<nombre>"`.
- **Sin `REDIS_URL`, el bus de eventos degrada a memoria del proceso.** Esperado.

## Antes de abrir un PR

- **TDD**: test que falla, verlo fallar por la razón correcta, código mínimo, verlo pasar.
  Obligatorio en `services.py`, en el agent runner y en todo lo que toque el aislamiento.
- **El loop, entero y en verde:**

  | Check | Comando | Cuándo |
  | --- | --- | --- |
  | Backend tests | `pytest` | Siempre |
  | Backend lint/format | `ruff check . && ruff format --check .` | Siempre |
  | Frontend tests | `pnpm test:run` | Siempre |
  | Frontend typecheck + lint | `pnpm exec tsc --noEmit && pnpm lint` | Siempre |
  | Frontend build | `pnpm build` | Siempre |
  | Migraciones | `alembic upgrade head && alembic downgrade -1 && alembic upgrade head && alembic check` | Si tocaste `alembic/` o `**/models.py` |
  | E2E | `pnpm e2e` | Si tocaste flujos críticos |

- **Probar el flujo real**, no solo los tests: levantar backend + frontend, entrar con un
  usuario de [docs/test-users.md](docs/test-users.md) y recorrerlo. Lo que toca el runner o
  los triggers, con un job de verdad contra un repo de pruebas propio.
- **Si encuentras errores preexistentes** de tipos o lint en archivos ajenos, arréglalos
  también.
- Commits atómicos, en el formato de los existentes (`feat(f6): ...`, `fix: ...`, `docs: ...`).
- **CI** en `.github/workflows/` (`backend-ci`, `frontend-ci`, `migrations-ci`, `e2e-ci`);
  pre-commit con ruff y `detect-secrets`: `pip install pre-commit && pre-commit install`.

## Licencia

[FSL-1.1-ALv2](LICENSE.md): puedes usar, modificar y autoalojar Vesper para cualquier fin
salvo ofrecerlo como producto o servicio que compita con él; cada versión pasa a Apache 2.0
a los dos años.
