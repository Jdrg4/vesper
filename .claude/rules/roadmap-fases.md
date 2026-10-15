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
| F4 Agent runner | ✅ **Cerrada punta a punta** · ⚠️ **la sustituye F6** | Job real completo: clone con installation token → `opencode serve` → glm-5.2 → diff por git → validación → push → **PR abierto por el bot** ([vesper-testbed#2](https://github.com/Jdrg4/vesper-testbed/pull/2)). El runtime opencode se retira en F6a; todo lo demás del flujo se conserva. |
| F5 Triggers | ✅ **Validada punta a punta** | Los 4 disparos + cola Arq con worker aparte. Verificado contra `vesper-testbed` con payloads firmados de verdad: webhook → job `trigger=webhook`, debounce, anti-bucle, cron que avanza `next_run_at` sin duplicar, prompt libre y UI de reglas. |
| **F6 Motor de agente propio** | 🔨 **En curso — spec aprobada** | Sustituye a opencode. **F6a** núcleo (cliente de proveedores, bucle de tool-calling, herramientas de archivo, contexto, evals) → **F6b** entorno de desarrollo containerizado (bash, tests, Playwright) → **F6c** convenciones y skills. |
| F7 Reviewer · F8 PWA · F9 Deploy | ⬜ | Después de F6. |

Detalle por fases en [docs/superpowers/specs/](docs/superpowers/specs/).
