# F2 — Auth + Multi-tenancy CRUD — Diseño

> **Proyecto:** Vesper
> **Fase 2:** primer Feature end-to-end. Registro self-serve de tenant +
> primer `tenant_admin`, login JWT (access + refresh en cookie httpOnly),
> RBAC, scoping multi-tenant real, UI mínima (register / login / dashboard).
>
> Decisiones de brainstorming (2026-07-28):
> - Registro **self-serve público** (sin email confirm, sin invite code).
> - **Backend + frontend mínimo** (no full dashboard ni invitaciones).
> - Plan **solo `free`**, sin enforcement de cuotas.
> - User ↔ tenant **1:1** (sin switcher multi-tenant).
> - Tokens: **access 15 min + refresh 7 días**, cookies httpOnly; logout limpia
>   cookies (sin denylist Redis en F2 — refresh queda vivo hasta exp si roban
>   cookie; aceptable en F2, endurecer en F5).

---

## 1. Objetivo de usuario

1. Un desarrollador abre la PWA, se registra con email/password + nombre del
   workspace (tenant), y queda logueado como `tenant_admin` de ese tenant.
2. Puede cerrar sesión y volver a entrar.
3. Ve un dashboard mínimo con el nombre del tenant y su email/rol.
4. Un tenant **no puede** leer datos de otro (tests de aislamiento obligatorios).

---

## 2. Modelo de datos

### 2.1 `tenants` (referencia raíz — SIN `tenant_id`)

| Columna | Tipo | Notas |
| --- | --- | --- |
| `id` | UUID PK | `gen_random_uuid()` |
| `name` | String(120) | Nombre display |
| `slug` | String(80) UNIQUE | URL-safe, lowercase, `[a-z0-9-]+` |
| `plan` | Enum `plan` | Default `free` |
| `developer_model` | String(64) | Default `glm-5.2` |
| `reviewer_model` | String(64) | Default `minimax-m3` |
| `is_active` | Bool | Default true |
| `created_at` / `updated_at` | timestamptz | TimestampMixin |

### 2.2 `users` (dato de tenant — CON `tenant_id`)

| Columna | Tipo | Notas |
| --- | --- | --- |
| `id` | UUID PK | |
| `tenant_id` | UUID FK → `tenants.id` ON DELETE CASCADE, INDEX | TenantMixin |
| `email` | String(255) | UNIQUE compuesto `(tenant_id, email)` |
| `hashed_password` | String(255) | argon2 |
| `full_name` | String(255) | |
| `role` | Enum `user_role` | `tenant_admin` \| `user` |
| `is_active` | Bool | Default true |
| timestamps | | |

**Email global vs por tenant:** con User↔tenant 1:1, el email puede ser UNIQUE
global (un email = un usuario = un tenant). Más simple para login. Decisión F2:
**`email` UNIQUE global** (no solo por tenant). El `tenant_id` sigue en el
modelo para el scoping futuro y para FK; el UNIQUE compuesto no se necesita
mientras sea 1:1 estricto. Aun así: toda query de listado/miembros filtra por
`tenant_id`.

### 2.3 `TenantMixin` (materializado)

```python
tenant_id: Mapped[uuid.UUID] = mapped_column(
    PGUUID(as_uuid=True),
    ForeignKey("tenants.id", ondelete="CASCADE"),
    nullable=False,
    index=True,
)
```

`tenant_scoped_query(model, tenant_id)` deja de ser stub:
`select(model).where(model.tenant_id == tenant_id)`.

---

## 3. API (`/api/v1`)

### Auth

| Método | Path | Auth | Descripción |
| --- | --- | --- | --- |
| POST | `/auth/register` | no | Crea tenant + user `tenant_admin`. Body: `email`, `password`, `full_name`, `tenant_name`, `tenant_slug?` (auto desde name si falta). 201 + setea cookies. |
| POST | `/auth/login` | no | Body: `email`, `password`. 200 + setea cookies. |
| POST | `/auth/refresh` | cookie refresh | Rota access (+ refresh). 200. |
| POST | `/auth/logout` | no (idempotente) | Limpia cookies. 204. |
| GET | `/auth/me` | access | User actual + tenant embebido mínimo. |

### Tenants

| Método | Path | Auth | Descripción |
| --- | --- | --- | --- |
| GET | `/tenants/me` | access | Tenant del usuario actual. |
| PATCH | `/tenants/me` | `tenant_admin` | Update `name`, `developer_model`, `reviewer_model`. |

### Users

| Método | Path | Auth | Descripción |
| --- | --- | --- | --- |
| GET | `/users/me` | access | Perfil propio. |
| PATCH | `/users/me` | access | Update `full_name` (no email/password en F2). |

**Cookies (nombres):**
- `access_token` — httpOnly, SameSite=Lax, Path=/, Max-Age=900
- `refresh_token` — httpOnly, SameSite=Lax, Path=/api/v1/auth, Max-Age=604800

En dev (HTTP) sin `Secure`. En prod (`ENVIRONMENT=production`) con `Secure`.

El frontend Next proxy (`app/api/*`) reenvía cookies al backend y expone
Bearer solo server-side si hace falta. El cliente axios usa `withCredentials`
contra `/api/*` (proxy), nunca ve el JWT en JS.

**JWT payload access:** `{ sub, role, tenant_id, type: "access" }`
**JWT payload refresh:** `{ sub, tenant_id, type: "refresh" }`

---

## 4. Dependencies

- `get_current_user` — lee Bearer o cookie `access_token`, valida type=access,
  carga User activo.
- `get_current_tenant` — deriva del `user.tenant_id` (nunca del body/path).
- `RoleChecker(["tenant_admin"])` — 403 si rol no match.

---

## 5. Frontend mínimo

Rutas:
- `/` — si auth → redirect `/dashboard`; si no → landing con links login/register
- `/register` — form self-serve
- `/login` — form
- `/dashboard` — shell: saluda, muestra tenant name + plan + models + email/rol
- `/api/auth/*` — proxy server-side (login/register/refresh/logout/me)

Stack: react-hook-form + Zod, shadcn básicos (button, input, label, card),
sonner toasts. Sin invitaciones, sin lista de miembros, sin settings avanzados.

---

## 6. Tests (TDD obligatorio)

Backend:
1. `test_register_creates_tenant_and_admin`
2. `test_register_duplicate_email_422`
3. `test_login_ok_and_me`
4. `test_login_bad_password_401`
5. `test_refresh_ok`
6. `test_isolation_tenant_a_cannot_read_tenant_b_via_scoped_query` (unit del helper)
7. `test_tenants_me_returns_own_only` (crear 2 tenants, token A no ve B)
8. `test_role_checker_blocks_user_on_admin_endpoint` (cuando haya endpoint admin;
   en F2 `PATCH /tenants/me` con rol `user` → 403; seed un user no-admin vía
   factory interna de tests)

Frontend:
- Vitest: schema Zod de register/login; opcional smoke del form.
- E2E Playwright `e2e/f2-auth.spec.ts`: register → dashboard → logout → login
  (continue-on-error del workflow se puede quitar en F2 si el spec es estable).

---

## 7. Migración

Una sola revisión `0001_f2_tenants_users`:
- `CREATE EXTENSION IF NOT EXISTS pgcrypto` (para `gen_random_uuid`)
- tablas `tenants`, `users`
- enums `plan`, `user_role`
- indexes + FKs
- downgrade reversible + drop enums explícito (lección aprendida)

---

## 8. Seed local

`scripts/seed_test_users.py` real:
- tenant `vesper-demo` / slug `vesper-demo`
- admin `admin@vesper.local` / `changeme123` / role `tenant_admin`
- user `demo@vesper.local` / `changeme123` / role `user`
- guard anti-prod intacto
- documentar en `docs/test-users.md`

---

## 9. Out of scope F2

- Invitaciones / miembros extra desde UI
- Email verification / reset password
- Rate-limit login (F2b opcional; si sobra tiempo)
- Cuotas por plan
- GitHub App (F3)
- Agent runner (F4)
- Multi-tenant membership M:N

---

## 10. Criterios de done

1. Migración upgrade→downgrade→upgrade→check verde.
2. pytest verde con coverage de aislamiento.
3. ruff limpio.
4. Frontend tsc + eslint + build verdes.
5. Validación manual navegador: register → dashboard → logout → login.
6. `docs/test-users.md` actualizado.
7. Commit atómico F2 (con permiso).
