# Producción: despliegue

El despliegue de referencia (F9) es **un solo compose**, `docker-compose.deploy.yml`
(backend + worker + frontend + Postgres + Redis), pensado para un PaaS self-hosted tipo
**Coolify** detrás de un proxy (Traefik) y, si el servidor está tras CGNAT, de **Cloudflare
Tunnel**. Las variables están en `.env.deploy.example`.

### 🔑 Credenciales: NUNCA en el repo

Accesos al servidor, tokens de la API del PaaS, llaves SSH y uuids viven fuera del repo.
Jamás copiar sus valores a un archivo commiteado, a un `.env` versionado ni a un mensaje.

### Primer despliegue: la cuenta antes que el dominio

El compose arranca con `REGISTRATION_ENABLED=false`: solo se permite **la primera cuenta**.
Créala **antes** de publicar el dominio (desde dentro del contenedor del backend, contra
`http://localhost:8000/api/v1/auth/register`), o el primero que llegue a `/register` se queda
con la instancia. Hasta que cada job corra en su propio contenedor, no abras el registro a
terceros: el agente de un tenant podría leer del disco los clones de otro.

### Trampas de deploy

- **Que Coolify diga `finished` no significa que todo esté arriba.** El primer despliegue
  acabó `finished` con el worker en bucle de reinicios. Mirar el estado de cada contenedor
  (`docker ps`) y los logs del worker: debe verse `tick_scheduler` cada minuto.
- **El worker no tiene healthcheck**, así que Coolify muestra la app como `running:unknown`.
  Es normal; lo que importa son sus logs.

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
