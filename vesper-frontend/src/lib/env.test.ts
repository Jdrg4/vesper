import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  vi.resetModules();
  process.env = { ...ORIGINAL_ENV };
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("env", () => {
  it("aborta el arranque si falta NEXT_PUBLIC_API_URL", async () => {
    delete process.env.NEXT_PUBLIC_API_URL;
    process.env.NEXT_PUBLIC_SSE_URL = "http://localhost:8000/sse";

    await expect(import("./env")).rejects.toThrow();
  });

  it("aborta el arranque si falta NEXT_PUBLIC_SSE_URL", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
    delete process.env.NEXT_PUBLIC_SSE_URL;

    await expect(import("./env")).rejects.toThrow();
  });

  it("aborta si NEXT_PUBLIC_API_URL no es una URL valida", async () => {
    process.env.NEXT_PUBLIC_API_URL = "no-es-una-url";
    process.env.NEXT_PUBLIC_SSE_URL = "http://localhost:8000/sse";

    await expect(import("./env")).rejects.toThrow();
  });

  it("parsea y expone las env vars cuando son validas", async () => {
    process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";
    process.env.NEXT_PUBLIC_SSE_URL = "http://localhost:8000/sse";

    const { env } = await import("./env");

    expect(env).toEqual({
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
      NEXT_PUBLIC_SSE_URL: "http://localhost:8000/sse",
    });
  });
});
