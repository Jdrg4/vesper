import { type NextRequest, NextResponse } from "next/server";

// Proxy genérico: todas las llamadas a /api/* se reenvían al backend con cookies.
// El cliente Axios envía `withCredentials: true` contra /api/*, y Next reenvía
// las cookies httpOnly al backend (auth/register, login, refresh, etc.).
// El backend setea cookies httpOnly en la respuesta; el proxy las reenvía.
//
// Solo se usa para endpoints que setean cookies (auth). Para llamadas que
// requieren el access_token en Authorization, el proxy lo reenvía desde
// la cookie o header automáticamente (el backend soporta ambos).

const BACKEND_URL = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

export async function GET(request: NextRequest) {
  return proxy(request);
}

export async function POST(request: NextRequest) {
  return proxy(request);
}

export async function PUT(request: NextRequest) {
  return proxy(request);
}

export async function PATCH(request: NextRequest) {
  return proxy(request);
}

export async function DELETE(request: NextRequest) {
  return proxy(request);
}

async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname.replace("/api", "/api/v1");
  const url = `${BACKEND_URL}${path}${request.nextUrl.search}`;

  const headers = new Headers();
  headers.set("Content-Type", "application/json");

  // Reenviar cookies del navegador al backend (httpOnly)
  const cookie = request.headers.get("cookie") ?? "";
  if (cookie) headers.set("Cookie", cookie);

  const body = ["GET", "HEAD"].includes(request.method)
    ? undefined
    : JSON.stringify(await request.json().catch(() => ({})));

  const res = await fetch(url, {
    method: request.method,
    headers,
    body,
  });

  const resBody = await res.text();

  // 204/205/304 son "null body status": el constructor de Response lanza si les
  // pasas un cuerpo, aunque sea "". El logout del backend responde 204, asi que
  // sin esto CADA cierre de sesion acababa en un 500 del proxy.
  const nullBody = [204, 205, 304].includes(res.status);

  const nextResponse = new NextResponse(nullBody ? null : resBody, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });

  // Reenviar Set-Cookie headers del backend al navegador
  res.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") {
      nextResponse.headers.append("Set-Cookie", value);
    }
  });

  return nextResponse;
}
