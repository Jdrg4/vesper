export const APP_NAME = "Vesper";

// URL pública del backend proxied via app/api/*. Se valida con Zod en
// `src/lib/env.ts` al arranque (next dev aborta si falta).
export const BACKEND_PUBLIC_URL = process.env.NEXT_PUBLIC_API_URL;

// URL interna del backend para server-side fetch (route handlers / RSC).
// En Coolify: nombre del servicio backend dentro del compose.
export const BACKEND_INTERNAL_URL =
  process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
