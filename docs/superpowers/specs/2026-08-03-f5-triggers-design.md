# F5 — Triggers — Diseño

> **Proyecto:** Vesper — SaaS multi-tenant que vigila los repositorios GitHub de
> cada inquilino y propone Pull Requests autónomos usando `opencode` como
> runtime de agente.
>
> **Este doc:** los cuatro disparadores que convierten a Vesper en un vigilante
> continuo en vez de un botón — **cron**, **webhook de GitHub**, **manual** y
> **prompt libre** — más la cola de trabajos que los sostiene.
>
> **Proceso:** `brainstorming → spec → writing-plans → implementación → review`.
> Este archivo es el **spec**.

---

## 1. Por qué

F4 cerró con un PR real abierto por el bot, pero el único camino para llegar a
él es que un humano pulse un botón. La promesa del producto —"vigila tus repos y
te abre PRs"— no se cumple hasta que el disparo es automático.

El enum `JobTrigger` ya declara los cuatro valores desde F4
(`src/review_jobs/constants.py`), y `GITHUB_WEBHOOK_SECRET` lleva en
`config.py` desde F1 sin que nadie lo lea. Están el hueco y el nombre; falta
todo lo demás.

Estado real al abrir la fase:

| Trigger | Hoy |
| --- | --- |
| `manual` | ✅ `POST /api/v1/jobs`, con `trigger` hardcodeado a `manual`. |
| `prompt` | ⬜ El enum existe, pero `JobCreateRequest` no acepta texto libre: el prompt lo genera `_build_prompt` desde el `task_type`. |
| `cron` | ⬜ Nada. No hay dónde guardar una cadencia. |
| `webhook` | ⬜ Nada: ni endpoint, ni verificación de firma. |

Y un problema estructural que F5 no puede ignorar: hoy los jobs corren con
`asyncio.create_task` **dentro del proceso de la API** (`schedule_job_run`). Con
un disparo manual cada vez es aceptable; con cron y webhook llegan ráfagas, y
cada job spawnea un `opencode serve` con su clon del repo. Un push a un repo
con cinco reglas activas levantaría cinco runtimes dentro del proceso que
atiende las peticiones HTTP.

## 2. Decisiones tomadas

| Decisión | Elegido | Motivo |
| --- | --- | --- |
| Ejecución | **Arq + worker separado**, sobre el Redis que ya existe | Los triggers solo encolan. Separa el agente de la API y da un sitio donde limitar la concurrencia. |
| Sin `REDIS_URL` | **Degrada al `asyncio.create_task` de hoy** | Igual que el bus de eventos. Dev local y los 70 tests siguen sin necesitar Redis. |
| Configuración de vigilancia | **Tabla `watch_rules`** (repo × task_type) | Permite "security cada noche, deps los lunes" desde el día uno, y es la unidad natural de las cuotas por plan. |
| Evaluación del cron | **`next_run_at` en la tabla + tick de Arq cada minuto** | El estado del scheduler vive en Postgres: observable con un `SELECT`, idempotente y sobrevive a reinicios. |
| Eventos de GitHub | **Solo `push` a la rama por defecto** | `pull_request` es materia de F7 (reviewer); diseñarlo aquí sería diseñarlo dos veces. |
| Ráfagas | **Debounce por (repo, task_type)** | Diez pushes seguidos = un job. Con BYOK, cada job redundante es dinero del tenant. |
| Prompt libre | **Preámbulo común + cuerpo** | El texto del usuario sustituye al cuerpo de la tarea; el andamiaje se comparte con las 5 plantillas. |
| Cuotas | **`MAX_JOBS_PER_DAY` y `MAX_CONCURRENT_JOBS` por plan** | Cierra los dos `TODO` ya escritos en el código. Una regla cron mal puesta no puede vaciar la API key del tenant. |

### Alternativas descartadas para el cron

- **`cron_jobs` de Arq.** Declara los crons en código, en el arranque del
  worker. Las reglas las crean los tenants en runtime: no encaja.
- **APScheduler con jobstore en Postgres.** Funciona, pero pone un segundo
  scheduler junto a Arq, con su propia persistencia y sus propios modos de
  fallo. Dos relojes en un sistema es uno de más.

## 3. Componentes

```
src/triggers/       WatchRule: models, schemas, router (CRUD), services, constants
src/webhooks/       router POST /api/v1/webhooks/github, verificación HMAC, despacho
src/core/queue.py   Arq: pool compartido, `enqueue`, fallback in-process
worker.py           WorkerSettings: `run_review_job` + `tick_scheduler` (cada 60 s)
```

`review_jobs/services.py` ya son 736 líneas y hace tres trabajos (bus de
eventos, workspace, orquestación). El despacho vive fuera en vez de engordarlo
más; `review_jobs` conserva la ejecución del job y pasa a exponer un
`enqueue_review_job(job_id, tenant_id)` como única puerta de entrada.

### `src/core/queue.py`

```python
async def enqueue(fn_name: str, *args, defer_seconds: int = 0) -> None:
    """Encola en Arq. Sin REDIS_URL, cae al asyncio.create_task de siempre."""
```

Un único punto de decisión, igual que `resolve_credentials` en BYOK: cuando
haga falta cambiar de backend de cola, se cambia aquí y en ningún otro sitio.

### `worker.py`

Proceso aparte (`arq src.worker.WorkerSettings`). Dos funciones registradas:

- `run_review_job(ctx, job_id, tenant_id)` → llama a `_run_job_standalone`, que
  ya abre su propia sesión de BD. Sin reintentos automáticos: reintentar un job
  del agente es volver a gastar tokens del tenant, y el resultado no es
  determinista. Un fallo se queda en `failed` y el tenant decide.
- `tick_scheduler(ctx)` → cron de Arq cada minuto (Arq garantiza con un lock en
  Redis que solo lo ejecuta un worker).

**Abort entre workers.** Se cierra el `TODO(F5)` de `services.py:207`: canal
pub/sub `vesper:job-abort`, cada worker se suscribe al arrancar y cancela la
task local si el `job_id` es suyo. `POST /jobs/{id}/abort` publica en el canal
además de intentar el abort local. Sin Redis se comporta como hoy.

## 4. Modelo `watch_rules` (migración 0006)

```
watch_rules
  id             uuid   PK
  tenant_id      uuid   FK → tenants        (TenantMixin)
  repository_id  uuid   FK → repositories   ON DELETE CASCADE
  task_type      enum   security|quality|deps|perf|docs
  cron           text?  expresión cron en UTC; null = sin cadencia
  on_push        bool   default false
  ref            text?  null = default_branch del repo
  enabled        bool   default true
  next_run_at    timestamptz?  calculado; null si cron es null o enabled es false
  last_run_at    timestamptz?
  created_at / updated_at                    (TimestampMixin)

  UNIQUE (repository_id, task_type)
  INDEX  (enabled, next_run_at)
```

- **`UNIQUE (repository_id, task_type)`**: una regla por tarea y repo. Dos
  cadencias para la misma tarea es una ambigüedad que nadie necesita.
- **`repository_id` no lleva `UNIQUE` global** por el mismo motivo que
  `repositories.github_id`: dos tenants pueden tener el mismo repo enrolado.
- **`cron` en UTC, siempre.** La UI lo dice explícitamente. Guardar zonas
  horarias por regla es complejidad que F5 no necesita.
- Una regla con `cron = null` y `on_push = true` es válida: solo reacciona a
  pushes. Una con ambos nulos/false es válida pero inerte, y la UI la muestra
  atenuada.
- `next_run_at` lo calcula el service con `croniter` (dependencia nueva) al
  crear o modificar la regla, y tras cada disparo.

`src/triggers/models.py` debe importarse en `alembic/env.py` o el
`--autogenerate` sale vacío en silencio.

## 5. El cron

`tick_scheduler`, cada 60 segundos:

1. `SELECT * FROM watch_rules WHERE enabled AND cron IS NOT NULL AND next_run_at <= now()`
   — **sin filtro de tenant a propósito**: es el único proceso del sistema que
   trabaja sobre todos los tenants, y por eso vive en un service propio
   (`triggers.services.due_rules`) y no pasa por `tenant_scoped_query`. Todo lo
   que hace después con cada regla sí va scopeado por el `tenant_id` de la fila.
2. Para cada regla: comprobar cuota → crear el `ReviewJob` (`trigger=cron`) →
   encolar.
3. `next_run_at = croniter(cron, now).get_next()`, `last_run_at = now()`,
   **en la misma transacción que la creación del job**. Si el commit falla, ni
   hay job ni avanza el reloj.

**Deriva y ticks perdidos.** `next_run_at` se recalcula desde `now()`, no desde
el `next_run_at` anterior. Si el worker estuvo caído seis horas, al volver
dispara **una** vez y sigue; no reproduce las seis ejecuciones perdidas. Es lo
que quiere un vigilante de repos: interesa el estado actual del repo, no la
historia.

## 6. El webhook

`POST /api/v1/webhooks/github` — **sin JWT**: lo autentica la firma. Es el único
endpoint público del backend además de auth, así que el orden de las defensas
importa.

1. **Sin `GITHUB_WEBHOOK_SECRET` configurado → 503, nunca 200.** Falla cerrado,
   igual que `verify_installation_ownership` en F3. Un despliegue mal
   configurado no acepta eventos.
2. **Firma.** `X-Hub-Signature-256` sobre el **body crudo** (leído antes de
   parsear el JSON), comparada con `hmac.compare_digest`. Sin firma o inválida →
   401.
3. **Tenant.** `payload.installation.id` → `TenantInstallation.installation_id`
   (UNIQUE global) → ese es el tenant. **Ningún otro campo del payload decide
   tenencia**: el resto del cuerpo lo controla quien lo firmó. El repositorio se
   busca ya con `tenant_scoped_query(Repository, tenant_id)` por `github_id`.
   Instalación desconocida → 202 y log; no es un error del emisor.
4. **Filtros anti-bucle**, en este orden:
   - evento ≠ `push` → 202, ignorado (`pull_request` se loguea con una nota
     apuntando a F7);
   - `ref` ≠ `refs/heads/<default_branch>` → ignorado;
   - la rama empieza por `vesper/` (`BRANCH_PREFIX`) → ignorado;
   - `sender.type == "Bot"` y el login corresponde a la propia App → ignorado.

   Sin el tercero y el cuarto, cada PR del bot dispara un push que dispara otro
   job que abre otro PR. El bucle se paga en tokens del tenant.
5. **Repo no enrolado** (`is_enrolled = false`) → ignorado. La App tiene permiso
   sobre los 42 repos de la cuenta de pruebas; solo se toca lo enrolado.
6. **Debounce.** Para cada regla con `on_push`: si ya existe un job
   `queued` o `running` para ese `(repository_id, task_type)`, no se encola otro.
7. Crear job (`trigger=webhook`) y encolar.

El handler **siempre responde rápido** (201/202) y hace el trabajo en la cola:
GitHub reintenta si tarda más de 10 s.

## 7. Prompt libre y manual

`JobCreateRequest` gana dos campos:

```python
prompt: str | None = Field(default=None, max_length=4000)
ref: str | None = None          # ya existía
```

Con `prompt` presente el job nace con `trigger=prompt`; sin él, `manual`. El
`task_type` sigue siendo obligatorio: con prompt libre queda como etiqueta para
filtrar en la UI (`quality` es el default razonable en la pantalla).

`_build_prompt` se parte en dos:

```
[preámbulo común — compartido por las 5 plantillas y el prompt libre]
Repo: acme/api  ·  Rama: main
Aplica los cambios directamente en el working tree.
No hagas commit, push ni abras un PR: de eso se encarga Vesper.

[cuerpo]
plantilla del task_type  |  texto libre del usuario
```

Hoy los cinco prompts son frases sueltas sin ese andamiaje: el agente no sabe en
qué rama está ni que no debe commitear. Que funcionara en F4 fue suerte del
modelo.

## 8. Cuotas

Cierra los `TODO` de `review_jobs/constants.py:94` y `tenants/constants.py`.

```python
# src/tenants/constants.py
PLAN_QUOTAS = {
    Plan.free:       {"max_jobs_per_day": 10,   "max_concurrent_jobs": 1},
    Plan.pro:        {"max_jobs_per_day": 200,  "max_concurrent_jobs": 3},
    Plan.enterprise: {"max_jobs_per_day": None, "max_concurrent_jobs": 10},
}
```

`None` es "sin límite". Un `0` centinela se lee como "cero jobs permitidos" y es
justo el fallo que no quieres descubrir en producción.

```python
```

Se comprueban en `ReviewService.create_job`, **el punto único por donde pasan
los cuatro triggers**:

- jobs del día (`created_at >= today UTC`) ≥ `max_jobs_per_day` → `QuotaExceededError` → **429**;
- jobs en `running` ≥ `max_concurrent_jobs` → el job se crea igualmente en
  `queued` y se encola con `defer_seconds=60`. La cola es para esperar, no para
  rechazar.

Un trigger automático (cron/webhook) que topa la cuota diaria no devuelve error
a nadie: se registra en el log y no se crea el job.

## 9. API

| Método | Path | Auth | Descripción |
| --- | --- | --- | --- |
| GET | `/api/v1/repositories/{repo_id}/watch-rules` | JWT | Reglas del repo |
| POST | `/api/v1/repositories/{repo_id}/watch-rules` | JWT | Crear regla |
| PATCH | `/api/v1/watch-rules/{id}` | JWT | Editar (cadencia, on_push, enabled) |
| DELETE | `/api/v1/watch-rules/{id}` | JWT | Borrar |
| POST | `/api/v1/webhooks/github` | **firma HMAC** | Eventos de GitHub |
| POST | `/api/v1/jobs` | JWT | Ya existía; ahora acepta `prompt` |

## 10. Frontend

- **Detalle del repositorio:** tabla de reglas (tarea · cadencia · en push ·
  activa), con selector de presets —diario a las 03:00 UTC, semanal los lunes,
  solo en push, personalizado— en vez de pedir una expresión cron a pelo. La
  expresión cruda queda accesible en "personalizado".
- **Vista de jobs:** botón "Prompt libre" que abre un modal con textarea,
  selector de repo y de rama. Al enviar, la vista se suscribe al SSE del job
  como ya hace el disparo manual.
- **Badge de trigger** en la lista de jobs (cron / webhook / manual / prompt):
  hoy el campo se guarda y no se muestra.
- Zod para los schemas, React Query para las reglas (`staleTime` largo: cambian
  poco).

## 11. Tests

TDD: cada uno se escribe fallando antes de la implementación.

**Webhook (`src/webhooks/`)**
- firma inválida → 401; sin cabecera de firma → 401;
- `GITHUB_WEBHOOK_SECRET` vacío → 503;
- **aislamiento:** un evento de la instalación del tenant A no crea ni toca
  nada del tenant B, aunque el payload nombre un repo de B;
- instalación desconocida → 202 sin efectos;
- push a rama no-default → ignorado;
- push a rama `vesper/*` → ignorado (anti-bucle);
- repo no enrolado → ignorado;
- debounce: dos pushes seguidos → un solo job.

**Scheduler (`src/triggers/`)**
- `due_rules` devuelve solo reglas vencidas, habilitadas y con cron;
- el tick crea el job y avanza `next_run_at`;
- dos ticks seguidos no crean dos jobs;
- una regla deshabilitada no dispara;
- **aislamiento:** el CRUD de reglas del tenant B no ve ni modifica las de A.

**Cola**
- sin `REDIS_URL`, `enqueue` cae al camino in-process y el job corre igual;
- el abort publicado en el canal cancela el job en el worker que lo tiene.

**Cuotas**
- cuota diaria agotada → 429 en el disparo manual;
- cuota diaria agotada en cron → no se crea job y no se propaga excepción;
- concurrencia al límite → el job queda `queued` y se re-encola con retraso.

**Prompt**
- `prompt` presente → `trigger=prompt` y el cuerpo del prompt es el del usuario;
- el preámbulo aparece en los seis casos (5 plantillas + libre).

## 12. Variables de entorno

Ninguna nueva obligatoria. Cambian de estatus:

- `REDIS_URL` — de opcional a **requerido en producción**. En dev sigue siendo
  opcional por el fallback in-process.
- `GITHUB_WEBHOOK_SECRET` — deja de ser un ajuste muerto. Sin él, el endpoint
  de webhooks responde 503.

## 13. Riesgos asumidos

- **Un servicio más en el deploy.** El worker de Arq es un proceso aparte:
  F9 tendrá que añadirlo al `docker-compose.deploy.yml` con la misma imagen del
  backend y otro `command`. Se asume a cambio de no ejecutar agentes dentro del
  proceso que atiende HTTP.
- **La URL del webhook debe ser pública.** El servidor está tras CGNAT; el
  túnel de Cloudflare de F9 tiene que exponer `/api/v1/webhooks/github` sin
  exponer el resto del backend. Hasta F9, la validación local se hace con
  `gh webhook forward` o reenvío manual del payload firmado.
- **El cron no recupera ticks perdidos** (§5). Es deliberado, pero conviene
  decirlo en la UI: "última ejecución" y "próxima ejecución" visibles en la
  tabla de reglas.
- **El debounce es por `(repo, task_type)`, no por contenido.** Un push que
  arregla justo lo que el job en vuelo está mirando no cancela ni reencola nada:
  el PR saldrá contra el commit que se clonó. Aceptable; el PR dice contra qué
  SHA se generó.

## 14. Cambios durante la implementación

Dos cosas que el diseño no preveía y que salieron en la validación manual:

- **Jobs colgados.** El debounce de §6 introduce un fallo silencioso: un job que
  se queda en `running` porque su proceso murió bloquea su `(repo, task_type)`
  para siempre, y ese repo deja de vigilarse sin que nadie se entere. Se añadió
  `reap_stale_jobs`, que corre al principio de cada tick y marca `failed` lo que
  lleve más de una hora corriendo. Se recoge **por antigüedad** y no "todos los
  `running` al arrancar el worker", que con varios workers mataría los jobs
  vivos de los demás.
- **Regla duplicada = 409, no 500.** El `UNIQUE (repository_id, task_type)`
  llegaba al usuario como error del servidor. `create_rule` captura el
  `IntegrityError` y lanza un `ConflictError`.

## 15. Fuera de alcance

- Revisión de PRs ajenos y comentarios en el PR → **F7 (reviewer)**.
- Eventos `pull_request`, `issue_comment`, `check_run` → F7.
- Cancelar un job en vuelo cuando llega un push más nuevo del mismo repo.
- Cuotas de tokens o de coste (las cuotas de F5 cuentan **jobs**, no gasto).
- Reintentos automáticos de jobs fallidos.
