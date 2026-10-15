import { type NextRequest, NextResponse } from "next/server";

// Rutas que exigen sesion. Sin esto, un visitante sin cookie llegaba a
// /dashboard, /repositories, /jobs o /settings y veia la UI vacia: el backend
// respondia 401, la pagina se tragaba el error y mostraba "No hay jobs" como
// si el workspace estuviera vacio.
const PRIVATE_PREFIXES = ["/dashboard", "/repositories", "/jobs", "/settings"];

// Rutas de entrada: con sesion activa no tiene sentido volver a ellas.
const AUTH_PREFIXES = ["/login", "/register"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  // Presencia de cookie, no validez: el token se valida server-side en el
  // backend en cada request. Esto solo evita pintar pantallas privadas vacias.
  const hasSession = Boolean(request.cookies.get("access_token")?.value);

  if (!hasSession && PRIVATE_PREFIXES.some((p) => pathname.startsWith(p))) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }

  if (hasSession && AUTH_PREFIXES.some((p) => pathname.startsWith(p))) {
    const url = request.nextUrl.clone();
    url.pathname = "/dashboard";
    url.search = "";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  // Excluye el proxy /api, los assets de Next y los ficheros de la PWA.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|manifest.webmanifest|icons).*)"],
};
