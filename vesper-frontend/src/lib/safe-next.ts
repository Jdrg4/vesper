/**
 * Destino tras el login a partir del `?next=` que pone el middleware.
 *
 * Se resuelve con el mismo parser que usa el navegador y se exige el mismo origen:
 * validar el texto crudo con `startsWith("/")` deja pasar `/\evil.com` o `/\t/evil.com`,
 * que el navegador normaliza a `//evil.com` (open redirect).
 */
export function safeNextPath(next: string | null, origin: string): string {
  if (next) {
    try {
      const url = new URL(next, origin);
      if (url.origin === origin && next.startsWith("/")) {
        return url.pathname + url.search + url.hash;
      }
    } catch {
      // URL imposible de parsear: se ignora.
    }
  }
  return "/dashboard";
}
