---
paths:
  - "vesper-frontend/src/**"
  - "vesper-frontend/e2e/**"
  - "vesper-frontend/middleware*"
  - "vesper-frontend/package.json"
  - "vesper-frontend/pnpm-workspace.yaml"
---

# Frontend: patrones, Playwright y entorno

## Frontend — patrones clave

**Next.js 16 async:** `cookies()` y `headers()` son async y deben awaitearse.
La ruta `app/api/[...path]` es un proxy server-side genérico hacia el backend
que reenvía cookies en ambos sentidos.

**Protección de rutas:** `src/middleware.ts` redirige a `/login?next=` si no hay
cookie `access_token` en `/dashboard`, `/repositories` o `/jobs`, y de
`/login|/register` a `/dashboard` si ya hay sesión. Comprueba **presencia**, no
validez: la validez la decide el backend en cada request.

**Refresh automático:** interceptor de axios en `src/lib/api.ts` captura 401 →
llama `/api/auth/refresh` → reintenta. Deduplica: varios 401 concurrentes
disparan un único refresh. No duplicar la lógica.

**No te tragues los errores.** Un `.catch(() => {})` en una página convierte un
401 en "no hay datos" y hace parecer vacío un workspace que no lo está.

**React Query v5:** staleTime corto para datos que mutan rápido (jobs), 1
retry, sin refetch on window focus.

**SSE para progreso del agente:** suscripción `EventSource` dedicada al
`review_job_id` activo. No usar axios (no soporta streaming).

**Estado UI:** Zustand en `src/stores/`. No mezclar con React Query.

**Validación:** Zod en `src/schemas/`. Las env se validan en `src/lib/env.ts`;
si falta una, la app no arranca.

**PWA:** `public/manifest.webmanifest` + meta tags en `layout.tsx`. `<html>`
lleva `suppressHydrationWarning` porque next-themes reescribe `className` y
`color-scheme` antes de hidratar.


## Trampas conocidas de este tema

- **`getByRole("button", {name})` de Playwright casa por substring.** Con los
  textos de `/repositories`, un `name: "Vigilar"` casa también con **"Dejar de
  vigilar"** y desenrola el repo en vez de crear la regla. Usar `exact: true`.
- **El backend debe estar en el puerto que dice `NEXT_PUBLIC_API_URL`** del
  `.env.local`. Si lo cambias, levanta el backend ahí en vez de tocar el código.


## Deuda conocida de este tema

- **Sin specs E2E de Playwright** (`e2e-ci` corre en vacío).
