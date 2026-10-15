import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { middleware } from "./middleware";

const ORIGIN = "http://localhost:3000";

function makeRequest(path: string, accessToken?: string): NextRequest {
  const headers = new Headers();
  if (accessToken) {
    headers.set("cookie", `access_token=${accessToken}`);
  }
  return new NextRequest(new URL(path, ORIGIN), { headers });
}

describe("middleware", () => {
  describe("rutas privadas sin cookie de sesion", () => {
    it.each(["/jobs", "/dashboard", "/repositories", "/settings"])(
      "redirige %s a /login con ?next=",
      (path) => {
        const res = middleware(makeRequest(path));

        expect(res.status).toBe(307);
        expect(res.headers.get("location")).toBe(
          `${ORIGIN}/login?next=${encodeURIComponent(path)}`,
        );
      },
    );

    it("preserva subrutas, no solo el prefijo exacto", () => {
      const res = middleware(makeRequest("/jobs/123"));

      expect(res.headers.get("location")).toBe(`${ORIGIN}/login?next=%2Fjobs%2F123`);
    });
  });

  describe("rutas privadas con cookie de sesion", () => {
    it.each(["/jobs", "/dashboard", "/repositories", "/settings"])("deja pasar %s", (path) => {
      const res = middleware(makeRequest(path, "some-token"));

      expect(res.headers.get("location")).toBeNull();
    });
  });

  describe("rutas de auth con cookie de sesion", () => {
    it.each(["/login", "/register"])("redirige %s a /dashboard", (path) => {
      const res = middleware(makeRequest(path, "some-token"));

      expect(res.status).toBe(307);
      expect(res.headers.get("location")).toBe(`${ORIGIN}/dashboard`);
    });
  });

  describe("rutas de auth sin cookie de sesion", () => {
    it.each(["/login", "/register"])("deja pasar %s", (path) => {
      const res = middleware(makeRequest(path));

      expect(res.headers.get("location")).toBeNull();
    });
  });

  describe("rutas no listadas", () => {
    it("deja pasar sin cookie", () => {
      const res = middleware(makeRequest("/"));

      expect(res.headers.get("location")).toBeNull();
    });

    it("deja pasar con cookie", () => {
      const res = middleware(makeRequest("/", "some-token"));

      expect(res.headers.get("location")).toBeNull();
    });
  });
});
