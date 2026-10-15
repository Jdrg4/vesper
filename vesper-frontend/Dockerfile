# Dockerfile de PRODUCCION del frontend (Next.js 16). El frontend es la unica
# app publica via Traefik en Coolify (ver docker-compose.deploy.yml).
# Usa `output: "standalone"` (next.config.ts) para empaquetar un servidor Node
# minimo autocontenido sin arrastrar node_modules completo.

# --- Builder: pnpm install + next build ---
FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@11.1.2 --activate

COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
# NEXT_PUBLIC_* son build-time (se incrustan en el bundle): si cambia el
# dominio del API, hay que rebuild. Arg en build para no commitearlas.
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SSE_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_SSE_URL=$NEXT_PUBLIC_SSE_URL

RUN pnpm install --frozen-lockfile

COPY . .

RUN pnpm build

# --- Runner: standalone server ---
FROM node:22-alpine

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Copia el standalone output + static + public (ver Next docs de `output: standalone`).
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
