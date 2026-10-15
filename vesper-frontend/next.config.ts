import type { NextConfig } from "next";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
const sseUrl = process.env.NEXT_PUBLIC_SSE_URL ?? "";

// CSP pragmática para una PWA Next.js: bloquea orígenes externos por defecto y
// solo abre lo que la app necesita (API REST via fetch, SSE de progreso del
// agente, el CSS-in-JS inline que Next inyecta, y los scripts inline del
// App Router streaming). TODO F8: endurecer con CSP basada en nonce
// (middleware.ts + next.config con `headers` dinámico) para eliminar
// 'unsafe-inline' de script-src.
const isDev = process.env.NODE_ENV !== "production";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiUrl} ${sseUrl}`.trim(),
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  // Empaqueta un servidor Node mínimo autocontenido (.next/standalone) para
  // el Dockerfile de producción.
  output: "standalone",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Strict-Transport-Security", value: "max-age=15552000; includeSubDomains" },
        ],
      },
    ];
  },
};

export default nextConfig;
