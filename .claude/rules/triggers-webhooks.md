---
paths:
  - "vesper-backend/src/triggers/**"
  - "vesper-backend/src/webhooks/**"
  - "vesper-backend/src/worker.py"
  - "vesper-backend/src/core/queue.py"
  - "vesper-backend/tests/test_f5_*"
  - "vesper-frontend/src/components/watch-rules.tsx"
  - "vesper-frontend/src/schemas/watch-rules*"
---

# Triggers, cron, webhooks y cuotas


## Redis y cron (de «Servicios y puertos»)

**Redis** hace de cola de jobs (**Arq**, desde F5) y de **bus de eventos** del
progreso del agente hacia la UI. Sin `REDIS_URL` ambas cosas degradan a memoria
del proceso: la API funciona y los jobs corren con `asyncio.create_task`, pero
con más de un worker uvicorn el stream SSE solo ve los jobs de *su* proceso.
Es degradación esperada, no un bug.

**Sin Redis el cron no corre**: el tick del scheduler vive en el worker de Arq
(`arq src.worker.WorkerSettings`), que sí lo necesita. En dev es aceptable
—el disparo manual, el prompt y el webhook siguen funcionando—; en producción
significa que nada se dispara solo.


## Trampas conocidas de este tema

- **El cron no recupera ticks perdidos.** `next_run_at` se recalcula desde
  `now()`, no desde el `next_run_at` anterior: si el worker estuvo caído seis
  horas, al volver dispara **una** vez y sigue. Es deliberado —a un vigilante de
  repos le interesa el estado actual, no la historia—, pero explica por qué el
  número de ejecuciones no cuadra tras una caída.
- **El debounce es por `(repo, task_type)`, no por contenido.** Un push que
  arregla justo lo que el job en vuelo está mirando no lo cancela ni lo
  reencola: el PR saldrá contra el commit que se clonó.
- **Un job colgado en `running` bloquea su `(repo, task_type)`.** Si el proceso
  muere (reinicio, crash), el debounce deja de encolar esa pareja y el repo
  queda sin vigilar **en silencio**. Lo recoge `reap_stale_jobs`, que corre en
  cada tick del scheduler y marca `failed` lo que lleve más de
  `STALE_JOB_SECONDS` (1 h) corriendo. Sin worker levantado, nadie lo recoge:
  en validación local hay que llamarlo a mano.


## Deuda conocida de este tema

- **El webhook entra por el proxy del frontend** (`/api/webhooks/github`), la única
  vía pública: el backend no se expone. El proxy reenvía el cuerpo **byte a byte** y
  las cabeceras `X-Hub-Signature-256`/`X-GitHub-Event`/`X-GitHub-Delivery`; si alguien
  vuelve a parsear o re-serializar el cuerpo, la firma deja de validar y todo push
  se rechaza con 401.
- **`WorkerSettings.redis_settings` es un atributo, no un método**: Arq lo lee como
  `redis_settings.host`. Como `staticmethod`, el worker moría al arrancar en
  producción. En local no se ve porque sin Redis no se lanza el worker.
- **Las cuotas cuentan jobs, no gasto.** `PLAN_QUOTAS` limita jobs/día y
  concurrencia; un job caro y uno barato valen igual. Con BYOK el coste lo paga
  el tenant, pero eso no protege de un prompt que queme su saldo.
