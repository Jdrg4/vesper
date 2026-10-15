import { describe, expect, it } from "vitest";

import { safeNextPath } from "./safe-next";

const ORIGIN = "http://localhost:3000";

describe("safeNextPath", () => {
  it.each([
    ["/repositories", "/repositories"],
    ["/jobs?estado=running#ultimo", "/jobs?estado=running#ultimo"],
  ])("conserva una ruta interna: %s", (next, esperado) => {
    expect(safeNextPath(next, ORIGIN)).toBe(esperado);
  });

  // El navegador normaliza la URL antes de navegar: `\` pasa a `/` y se eliminan
  // tabuladores y saltos de linea. Un `startsWith("/")` sobre el texto crudo no lo ve.
  it.each([
    "//evil.com",
    "/\\evil.com",
    "\\\\evil.com",
    "/\t/evil.com",
    "/\n/evil.com",
    // Los segmentos `.`/`..` se normalizan y dejan el path en `//evil.com`.
    "/.//evil.com",
    "/..//evil.com",
    "/a/..//evil.com",
    "https://evil.com",
    "javascript:alert(1)",
    "evil.com",
  ])("manda al dashboard cualquier cosa que salga del origen: %j", (next) => {
    expect(safeNextPath(next, ORIGIN)).toBe("/dashboard");
  });

  it("sin next, al dashboard", () => {
    expect(safeNextPath(null, ORIGIN)).toBe("/dashboard");
  });
});
