# AGENTS.md

Guía para agentes de código (Codex, opencode, Cursor…) que trabajen sobre **este** repo.
La guía completa es [CLAUDE.md](CLAUDE.md) y el detalle por módulo está en
[.claude/rules/](.claude/rules/): **léelos antes de tocar nada.**

> No confundir: el agente que Vesper ejecuta sobre los repos de sus tenants **no** lee este
> archivo; este guía el desarrollo de Vesper mismo.

## Reglas que no se negocian

- **Aislamiento multi-tenant**: toda query de dominio pasa por
  `tenant_scoped_query(model, tenant_id)` (`src/core/tenancy.py`); nada de `db.get(Model, id)`
  directo. Cada dominio lleva tests de aislamiento (dato en tenant A, acceso desde B → falla).
- **La lógica vive en `services.py`**, nunca en el router.
- **El navegador nunca ve una API key**; el backend nunca es público.
- **El agente nunca ejecuta código del repo de un tenant fuera de su sandbox por job.**
- **Secretos solo en env vars / `.env` local**; nunca en git.
- **Nunca validar ni escribir contra producción.** Solo `vesper_dev` / `vesper_test` locales.
- Si agregas un `src/<dominio>/models.py`, impórtalo en `alembic/env.py`.

## Loop de verificación

```bash
# Backend (vesper-backend/)
pytest && ruff check . && ruff format --check .
# Frontend (vesper-frontend/)
pnpm exec tsc --noEmit && pnpm lint && pnpm test:run && pnpm build
```
