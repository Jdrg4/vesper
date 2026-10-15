---
paths:
  - "docs/superpowers/**"
  - "vesper-backend/src/agents/**"
  - "vesper-backend/src/review_jobs/**"
  - "vesper-backend/src/reviews/**"
---

# Estado real por fase (roadmap)

### Estado real por fase

| Fase | Estado | Nota |
| --- | --- | --- |
| F1 Fundación/DevEx | ✅ | CI, pre-commit, `.claude/`, `.mcp.json`. |
| F2 Auth + multi-tenancy | ✅ | JWT, RBAC, `tenant_scoped_query`, seed de usuarios. |
| F3 GitHub App | ✅ **Verificado con una App real** | Instalación **con verificación OAuth de propiedad**, enrollment, sync (42 repos reales). |
| F4 Agent runner | ✅ **Cerrada punta a punta** | Job real completo: clone con installation token → `opencode serve` → modelo del tenant → diff por git → validación → push → **PR abierto por el bot**. `opencode` se queda como primer harness (F6 lo pone detrás de una interfaz). En producción: PRs reales con `deepseek-v4-pro`. |
| F5 Triggers | ✅ **Validada punta a punta** | Los 4 disparos + cola Arq con worker aparte. Verificado contra `vesper-testbed` con payloads firmados de verdad: webhook → job `trigger=webhook`, debounce, anti-bucle, cron que avanza `next_run_at` sin duplicar, prompt libre y UI de reglas. |
| **F6 Motor del agente** | 🔨 **Replanteada el 2026-10-15** | **Ya no se construye un motor propio.** Harness intercambiable detrás de una interfaz de motor (`opencode` primero, ya en producción); el esfuerzo va al **contenedor por job** que corre tests y Playwright (PRs verificados y aislamiento entre tenants) y a **evals** para comparar harnesses (`pi`, DeepSeek Harness) con datos. La spec del 2026-08-04 queda superada en lo del motor propio; pendiente la spec revisada. |
| F9 Deploy | ✅ **En producción desde el 2026-10-15** | Compose único (backend, worker, frontend, Postgres, Redis), auto-deploy por webhook verificado, registro cerrado salvo la primera cuenta. Detalle en `produccion-deploy.md`. |
| F7 Reviewer · F8 PWA | ⬜ | Después de F6. La interfaz ya se rediseñó (ver `vesper-frontend/DESIGN.md`). |

Detalle por fases en [docs/superpowers/specs/](docs/superpowers/specs/).
