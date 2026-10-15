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

const GITHUB_WEBHOOK_HEADERS = ["X-Hub-Signature-256", "X-GitHub-Event", "X-GitHub-Delivery"];

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
  headers.set("Content-Type", request.headers.get("content-type") ?? "application/json");

  // Reenviar cookies del navegador al backend (httpOnly)
  const cookie = request.headers.get("cookie") ?? "";
  if (cookie) headers.set("Cookie", cookie);

  // Webhooks de GitHub: la firma HMAC va en cabecera y cubre los bytes exactos
  // del cuerpo. Por eso el cuerpo se reenvia tal cual, sin parsear ni re-serializar.
  for (const name of GITHUB_WEBHOOK_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const body = ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer();

  const res = await fetch(url, {
    method: request.method,
    headers,
    body,
    // Si el navegador se va (p. ej. cierra un SSE), la peticion al backend tambien.
    signal: request.signal,
  });

  // SSE (progreso del agente): se pasa el stream tal cual. Con `res.text()` el
  // navegador no recibia nada hasta que el backend cerraba, minutos despues.
  const contentType = res.headers.get("content-type") ?? "application/json";
  if (contentType.startsWith("text/event-stream")) {
    return new Response(res.body, {
      status: res.status,
      headers: { "Content-Type": contentType, "Cache-Control": "no-cache, no-transform" },
    });
  }

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
