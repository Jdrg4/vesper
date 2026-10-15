/**
 * Contraste WCAG de los tokens de color, leido del CSS real (`app/globals.css`).
 *
 * Parsea el archivo en vez de traer los hex copiados: una copia seguiria en verde
 * despues de cambiar un token, que es justo el fallo que este test existe para atrapar.
 *
 * Umbrales distintos a proposito:
 *   - 4.5:1  texto normal sobre su fondo (WCAG 1.4.3 AA).
 *   - 3:1    contorno de algo accionable: campo, boton outline, anillo de foco (WCAG 1.4.11).
 * Los divisores decorativos (`--border`) NO llevan umbral: exigirles 3:1 los vuelve rayas.
 *
 * Diagnostico de la paleta anterior (grises oklch de shadcn), medido el 2026-10-15:
 * borde de campo 1.26:1 y anillo de foco 2.59:1 en claro — por debajo de 3:1.
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const css = readFileSync(join(__dirname, "../app/globals.css"), "utf8");

const TEMAS: [string, string][] = [
  ["claro", ":root {"],
  ["oscuro", ".dark {"],
];

/** [primer plano, fondo, minimo, para que sirve] */
const PARES: [string, string, number, string][] = [
  ["--foreground", "--background", 4.5, "texto principal sobre el lienzo"],
  ["--foreground", "--card", 4.5, "texto principal sobre tarjeta"],
  ["--foreground", "--secondary", 4.5, "texto sobre la columna lateral"],
  ["--muted-foreground", "--card", 4.5, "texto secundario sobre tarjeta"],
  ["--muted-foreground", "--background", 4.5, "texto secundario sobre el lienzo"],
  ["--muted-foreground", "--secondary", 4.5, "texto secundario en la columna lateral"],
  ["--ink-3", "--card", 4.5, "texto terciario (metadatos)"],

  ["--primary-foreground", "--primary", 4.5, "texto del boton primario"],
  ["--primary", "--card", 4.5, "enlace / acento como texto"],

  // Estados de un job: el color dice si el agente termino, fallo o espera revision.
  ["--success", "--card", 4.5, "completado"],
  ["--warning", "--card", 4.5, "necesita revision"],
  ["--destructive", "--card", 4.5, "fallido"],
  ["--destructive-foreground", "--destructive", 4.5, "texto sobre fondo de error"],
  // Badges de estado: el texto va sobre su fondo suave, no sobre la tarjeta.
  ["--success", "--success-soft", 4.5, "badge completado"],
  ["--warning", "--warning-soft", 4.5, "badge revisar"],
  ["--destructive", "--destructive-soft", 4.5, "badge fallido y tarjeta de error"],
  ["--primary", "--primary-soft", 4.5, "badge trabajando"],
  ["--ink-2", "--muted", 4.5, "badge en cola"],

  ["--input", "--card", 3, "borde de campo sobre tarjeta"],
  ["--input", "--background", 3, "borde de campo sobre el lienzo"],
  ["--ring", "--background", 3, "anillo de foco"],
];

function tokensDe(selector: string): Record<string, string> {
  const inicio = css.indexOf(selector);
  if (inicio === -1) throw new Error(`No se encontro el selector ${selector}`);
  const abre = css.indexOf("{", inicio);
  const cierra = css.indexOf("\n}", abre);
  const tokens: Record<string, string> = {};
  for (const m of css.slice(abre, cierra).matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    tokens[m[1]] = m[2];
  }
  return tokens;
}

function luminancia(hex: string): number {
  const canal = (v: number) => {
    const c = v / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  const n = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16));
  return 0.2126 * canal(r) + 0.7152 * canal(g) + 0.0722 * canal(b);
}

function contraste(a: string, b: string): number {
  const [x, y] = [luminancia(a), luminancia(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe.each(TEMAS)("contraste AA — tema %s", (_tema, selector) => {
  const tokens = tokensDe(selector);

  it.each(PARES)("%s sobre %s >= %s:1 (%s)", (fg, bg, minimo) => {
    const a = tokens[fg];
    const b = tokens[bg];
    expect(a, `falta el token ${fg} en ${selector}`).toBeDefined();
    expect(b, `falta el token ${bg} en ${selector}`).toBeDefined();
    const ratio = contraste(a, b);
    expect(
      Number(ratio.toFixed(2)),
      `${fg} (${a}) sobre ${bg} (${b}) da ${ratio.toFixed(2)}:1`,
    ).toBeGreaterThanOrEqual(minimo);
  });
});
