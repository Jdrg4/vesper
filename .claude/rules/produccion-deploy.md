---
paths:
  - "docker-compose.deploy.yml"
  - "**/Dockerfile"
  - ".github/**"
  - "vesper-backend/src/main.py"
---

# Producción: despliegue

El despliegue de referencia (F9) es **un solo compose**, `docker-compose.deploy.yml`
(backend + worker + frontend + Postgres + Redis), pensado para un PaaS self-hosted tipo
**Coolify** detrás de un proxy (Traefik) y, si el servidor está tras CGNAT, de **Cloudflare
Tunnel**. Las variables están en `.env.deploy.example`.

### 🔑 Credenciales: NUNCA en el repo

Accesos al servidor, tokens de la API del PaaS, llaves SSH y uuids viven fuera del repo.
Jamás copiar sus valores a un archivo commiteado, a un `.env` versionado ni a un mensaje.

### Trampas de deploy

- **Crear la app en el PaaS NO crea el webhook de auto-deploy.** Verificar con
  `gh api repos/<owner>/<repo>/hooks --jq '.[] | {id, url: .config.url, active}'`.
- **Compose único = deploy conjunto.** Un push redeploya todo (~2 min de corte).
- **Validar el deploy contra lo que SIRVE el sitio**, no contra el estado que reporta el
  PaaS. `curl --compressed` (sin `--compressed` puede dar falso negativo con respuestas
  comprimidas).
- **Volumen de Postgres: `/var/lib/postgresql/data`, NO `/data`** (queda unhealthy).
- **Ningún servicio publica `ports:`** — solo `expose` interno. Solo el frontend es público
  vía Traefik (`docker_compose_domains` en Coolify, no `fqdn`).
- **`NEXT_PUBLIC_*` se incrusta en el bundle**: cambiar el dominio del API exige rebuild.
- **SSH intermitente del servidor contra GitHub:** un `Permission denied` esporádico con
  llave válida → relanzar el deploy, no rotar llaves.
- **CI y deploy corren en paralelo.** El deploy no espera a que los tests pasen.
