/**
 * Destino tras el login a partir del `?next=` que pone el middleware.
 *
 * Se resuelve con el mismo parser que usa el navegador y se exige el mismo origen:
 * validar el texto crudo con `startsWith("/")` deja pasar `/\evil.com` o `/\t/evil.com`,
 * que el navegador normaliza a `//evil.com` (open redirect).
 *
 * Se valida el valor DEVUELTO, no solo la entrada: normalizar `/.//evil.com` deja
 * el path en `//evil.com`, que el router resuelve como otro dominio.
 */
export function safeNextPath(next: string | null, origin: string): string {
  if (next?.startsWith("/")) {
    try {
      const url = new URL(next, origin);
      const path = url.pathname + url.search + url.hash;
      if (url.origin === origin && new URL(path, origin).origin === origin) {
        return path;
      }
    } catch {
      // URL imposible de parsear: se ignora.
    }
  }
  return "/dashboard";
}
