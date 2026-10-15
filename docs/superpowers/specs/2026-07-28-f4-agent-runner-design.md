# F4 — Agent Runner — Diseño

> **Fase 4:** el backend orquesta `opencode serve` para revisar un repo del
> tenant, producir un diff, validarlo y abrir un PR en GitHub. SSE para
> progreso en vivo hacia la UI.

## 1. Componentes

### WorkspaceService
- `clone_repo(tenant_id, repo_full_name, branch, token)` → shallow clone en
  `/var/workspaces/<tenant>/<repo>/`
- Crear `.git-credentials` temporal o usar `GIT_ASKPASS` con el token

### OpencodeRunner (interface + 2 impls)
- `spawn(workdir, port, model)` → inicia `opencode serve --port N --cwd workdir`
- `create_session(client)` → POST /session
- `send_prompt(client, session_id, prompt)` → POST /session/:id/message
- `send_prompt_async(client, session_id, prompt)` → POST /session/:id/prompt_async
- `get_diff(client, session_id)` → GET /session/:id/diff
- `stop(port)` → kill process by PID
- `stream_events(client, session_id)` → SSE iterator desde /event

**FakeOpencodeRunner** (tests): devuelve diffs pre-grabados sin spawnear procesos.

### ReviewService (orquestador)
- `trigger_job(...)` → crea ReviewJob, lanza `run_job` en background (asyncio.create_task)
- `run_job(job_id)` → workspace → spawn opencode → session → prompt → SSE → diff → validate → commit → PR
- `validate_diff(diff)` → check secrets, sensitive paths, mark `needs_review` if risky
- `create_pr(...)` → GitHub API: create branch, commit, push, open PR

### SSE Endpoint
- `GET /api/v1/jobs/{id}/events` → SSE stream del progreso. Eventos: `progress`, `completed`, `error`.

## 2. Modelo ReviewJob (migración)

Tabla `review_jobs`:
- `tenant_id` FK (TenantMixin)
- `repository_id` FK → repositories
- `task_type` enum (security/quality/deps/perf/docs)
- `status` enum (queued/running/completed/failed/needs_review)
- `trigger` enum (manual — por ahora F4, F5 trae cron/webhook/prompt)
- `ref` str (branch name, default "main")
- `prompt` str | null
- `pull_request_url` str | null
- `branch_name` str | null
- `commit_sha` str | null
- `diff_summary` str | null
- `error_message` JSONB | null
- `started_at` timestamptz | null
- `completed_at` timestamptz | null

## 3. API

| Método | Path | Descripción |
|---|---|---|
| POST | `/jobs` | Crear job (body: repository_id, task_type, ref?) |
| GET | `/jobs` | Listar jobs del tenant |
| GET | `/jobs/{id}` | Detalle de un job |
| GET | `/jobs/{id}/events` | SSE de progreso |
| POST | `/jobs/{id}/abort` | Abortar job en vuelo |

## 4. Out of scope F4
- Scheduling (cron) — F5
- Webhooks — F5
- Reviewer pass (segundo modelo) — F7
- Prompt templates por task_type — se usa un prompt genérico "review this repo"

## 5. Tests
- `FakeOpencodeRunner` con diff pregrabados
- `ReviewService.run_job` test con mock github + mock opencode
- Test de validación de diff (secretos, paths sensibles)
- Sin procesos reales de `opencode` en pytest (marca `slow` si se usan)
