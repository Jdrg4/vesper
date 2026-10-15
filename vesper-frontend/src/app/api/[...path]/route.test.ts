import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET, POST, PUT } from "./route";

const ORIGIN = "http://localhost:3000";

function makeRequest(path: string, body: unknown = {}, method = "POST"): NextRequest {
  return new NextRequest(new URL(path, ORIGIN), {
    method,
    headers: { "content-type": "application/json", cookie: "access_token=abc" },
    body: JSON.stringify(body),
  });
}

function mockBackend(status: number, body: string, headers: Record<string, string> = {}) {
  const spy = vi.fn(async () => new Response(status === 204 ? null : body, { status, headers }));
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("proxy /api/[...path]", () => {
  it("reenvia la peticion al backend reescribiendo /api -> /api/v1", async () => {
    const fetchSpy = mockBackend(200, '{"ok":true}');

    await POST(makeRequest("/api/auth/login", { email: "a@b.c" }));

    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/auth/login");
    expect((init.headers as Headers).get("Cookie")).toBe("access_token=abc");
  });

  it("reenvia un webhook de GitHub intacto: mismos bytes y cabeceras de firma", async () => {
    // GitHub firma los bytes EXACTOS del cuerpo. Re-serializar el JSON cambia los
    // bytes (espacios, orden) y descartar las cabeceras deja al backend sin firma:
    // todo webhook entrando por el dominio publico se rechazaba.
    const fetchSpy = mockBackend(200, '{"handled":true}');
    const raw = '{"ref": "refs/heads/main",  "after": "abc"}';
    const request = new NextRequest(new URL("/api/webhooks/github", ORIGIN), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-hub-signature-256": "sha256=deadbeef",
        "x-github-event": "push",
        "x-github-delivery": "d-1",
      },
      body: raw,
    });

    await POST(request);

    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/webhooks/github");
    expect(new TextDecoder().decode(init.body as ArrayBuffer)).toBe(raw);
    const headers = init.headers as Headers;
    expect(headers.get("X-Hub-Signature-256")).toBe("sha256=deadbeef");
    expect(headers.get("X-GitHub-Event")).toBe("push");
    expect(headers.get("X-GitHub-Delivery")).toBe("d-1");
  });

  it("no revienta con un 204 del backend", async () => {
    // 204 es "null body status": construir una Response con cuerpo — aunque sea
    // "" — lanza un TypeError. El logout responde 204, asi que sin esto cada
    // cierre de sesion devolvia un 500 del proxy.
    mockBackend(204, "");

    const res = await POST(makeRequest("/api/auth/logout"));

    expect(res.status).toBe(204);
    expect(await res.text()).toBe("");
  });

  it("propaga las cookies Set-Cookie del backend al navegador", async () => {
    mockBackend(200, '{"ok":true}', { "set-cookie": "access_token=nuevo; HttpOnly; Path=/" });

    const res = await POST(makeRequest("/api/auth/login"));

    expect(res.headers.get("set-cookie")).toContain("access_token=nuevo");
  });

  it("conserva el status de error del backend", async () => {
    mockBackend(401, '{"detail":"no autorizado"}');

    const res = await POST(makeRequest("/api/auth/me"));

    expect(res.status).toBe(401);
    expect(await res.text()).toContain("no autorizado");
  });

  it("soporta PUT (usado por /settings para guardar credenciales BYOK)", async () => {
    const fetchSpy = mockBackend(201, '{"id":"1","provider_id":"openai"}');

    const res = await PUT(
      makeRequest("/api/agents/credentials", { provider_id: "openai", api_key: "sk-x" }, "PUT"),
    );

    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/v1/agents/credentials");
    expect(init.method).toBe("PUT");
    expect(res.status).toBe(201);
  });

  it("pasa un SSE en vivo, sin esperar a que el backend cierre el stream", async () => {
    // Con `res.text()` el navegador no veia nada hasta que el backend cerraba,
    // minutos despues: la actividad del agente llegaba toda junta al final.
    let push!: (chunk: string) => void;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        push = (chunk) => controller.enqueue(new TextEncoder().encode(chunk));
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } })),
    );

    const res = await GET(new NextRequest(new URL("/api/jobs/j1/events", ORIGIN)));
    expect(res.headers.get("content-type")).toBe("text/event-stream");
    const reader = res.body!.getReader();
    push('data: {"event":"activity"}\n\n');
    const { value } = await reader.read();
    expect(new TextDecoder().decode(value)).toContain('"activity"');
  });
});
