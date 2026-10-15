# Credenciales de prueba (local)

Seed idempotente contra la BD local `vesper_dev` (Postgres en `localhost:55432`, ver
`.claude/rules/bd-local.md`). Correrlo dos veces no falla ni duplica: si el tenant/usuario
ya existe, lo detecta por `slug`/`email` y lo salta.

## Cómo sembrar

```bash
cd vesper-backend
export PYTHONPATH=.            # PowerShell: $env:PYTHONPATH="."
python scripts/seed_test_users.py
```

El script **aborta si `DATABASE_URL` no es local** (guard anti-prod: exige
`localhost`/`127.0.0.1` en la connection string; por defecto `src/core/config.py` ya apunta
a `vesper_dev`).

## Credenciales

| Rol | Email | Password | Tenant |
| --- | --- | --- | --- |
| tenant_admin | `admin@vesper.example` | `changeme123` | `vesper-demo` |
| user | `demo@vesper.example` | `changeme123` | `vesper-demo` |

Ambos usuarios pertenecen al mismo tenant (`vesper-demo`, plan `free`). El admin tiene rol
`tenant_admin`; el `user` tiene rol `user` — útil para probar `<RoleGuard>` y los distintos
permisos en la UI. **Solo para desarrollo local.**
