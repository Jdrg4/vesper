# F3 — GitHub App Integration — Diseño

> **Fase 3:** conectar la GitHub App del SaaS a los tenants. Cada tenant
> instala la App en su cuenta, el backend almacena el `installation_id` y puede
> listar los repos autorizados. El tenant selecciona cuáles vigilar (enroll).

## 1. Alcance F3

- Modelos: `TenantInstallation`, `Repository`
- OAuth flow: redirect a GitHub → callback → guardar installation
- Listar repos de la instalación vía API de GitHub (token de instalación)
- Enroll/unenroll repos (toggle `is_enrolled`)
- GitHub client: JWT app → exchange por installation token → llamadas API
- Tests con mocks httpx (sin hitting GitHub real)
- Frontend: página para conectar GitHub, ver repos, toggle enrollment

**Out of scope:** webhooks (F5), auto-scan (F4), auto PR opening (F4).

## 2. Modelos

### TenantInstallation
`tenant_id` FK → tenants.id ON DELETE CASCADE, UNIQUE
`installation_id` int (GitHub, NO sensible)
`installed_at` → app user/org name
`created_at`

### Repository (dato de tenant)
`tenant_id` FK
`installation_id` FK → TenantInstallation
`github_id` int UNIQUE global
`full_name` str (owner/repo)
`default_branch` str
`private` bool
`is_enrolled` bool default false
`enrolled_at` nullable

## 3. API

| Método | Path | Auth | Descripción |
|---|---|---|---|
| GET | `/repositories/install-url` | access | URL de instalación de la GitHub App |
| POST | `/repositories/callback` | access | Procesa installation_id tras callback |
| GET | `/repositories/installation` | access | Estado de la instalación del tenant |
| POST | `/repositories/sync` | `tenant_admin` | Sinc lista de repos desde GitHub |
| GET | `/repositories` | access | Lista repos del tenant (filtro enrolled opcional) |
| PATCH | `/repositories/{id}/enroll` | `tenant_admin` | Toggle enrollment |

## 4. GitHub Client

`src/repositories/github_client.py`:
- `create_jwt(app_id, private_key)` → JWT para autenticar como App
- `get_installation_token(jwt, installation_id)` → token 1h
- `list_repositories(token)` → lista de repos
- `get_repository(token, owner, repo)` → detalle de un repo

Tests: mock httpx con respuestas pre-grabadas.

## 5. Frontend

Página `/repositories`:
- Si no hay instalación: botón "Conectar GitHub"
- Si hay instalación: tabla de repos con toggle de enrollment
- Botón "Sync" (solo admin)

## 6. Migración

`0002_f3_repositories`:
- tabla `tenant_installations`
- tabla `repositories`
