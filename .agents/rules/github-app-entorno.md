# GitHub App y variables de entorno

## Variables de entorno

Cada servicio tiene su `.env.example`. Copiarlo a `.env` (backend) /
`.env.local` (frontend).

- `DATABASE_URL` — Postgres (default local `vesper_dev`).
- `JWT_SECRET` — mínimo 32 caracteres. El default de desarrollo aborta el
  arranque si `ENVIRONMENT=production`.
- `REDIS_URL` — cola + bus de eventos. Sin esto, la degradación de arriba.
- `OPENCODE_ZEN_KEY` / `OPENCODE_ZEN_BASE_URL` — pasarela Zen. Solo backend.
- `OPENCODE_BIN`, `OPENCODE_PORT_POOL_START` (14096) — runtime del agente.
- `WORKSPACE_ROOT` — raíz de los clones (default `/var/workspaces`, la ruta del
  contenedor). En Windows/macOS hay que apuntarlo a un directorio real.
- `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_PRIVATE_KEY`,
  `GITHUB_APP_CLIENT_ID`, `GITHUB_APP_CLIENT_SECRET` — **client id y secret son
  obligatorios**: sin ellos `verify_installation_ownership` rechaza toda
  instalación (falla cerrado).
- `GITHUB_WEBHOOK_SECRET` — valida webhooks firmados (F5).
- `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SSE_URL` — frontend.

### Crear la GitHub App

No se rellenan a mano las seis claves de arriba. Cada instalación de Vesper
necesita su propia App, y el *manifest flow* la crea con un clic:

```powershell
cd vesper-backend
.venv\Scripts\python.exe scripts\create_github_app.py --name "Vesper Bot"
```

Abre el navegador, tú pulsas **Create GitHub App**, y el script canjea el
`code` y escribe app id, slug, clave privada, client id, client secret y
webhook secret en el `.env` (que está gitignoreado). Nunca imprime secretos.
Acepta `--org` para crearla en una organización y `--frontend-url` para añadir
callbacks (por defecto `localhost:3100` y `localhost:3000`).

El manifest ya activa **"Request user authorization (OAuth) during
installation"**; sin eso el redirect no trae `code` y el callback no puede
verificar la propiedad de la instalación. Los permisos que pide son los
mínimos: `contents:write`, `pull_requests:write`, `metadata:read`.

> La clave privada se guarda en una línea, con los saltos escapados como `\n`
> y entre comillas; `config.py` la restaura. Ni una línea de `.env` ni una env
> var de Coolify admiten un PEM multilínea.


## Deuda conocida de este tema

- **El sync deja de vigilar lo que GitHub no devuelve** (repo borrado o fuera de la
  instalación). Si la instalación cambia *mientras* se pagina, el corte por offset
  puede saltarse un repo válido y des-enrolarlo (se reactiva a mano). Arreglo si
  molesta: comparar `len(repos)` con el `total_count` de GitHub y no des-enrolar si
  no cuadran.

- **La App de pruebas está instalada en los 42 repos de la cuenta.** Solo se
  toca lo que esté *enrolado*, pero la App tiene `contents:write` sobre todos.
  Conviene reducir la instalación a los repos que de verdad se vigilen.

- **Cifrado de installation tokens en reposo.** Hoy no se persisten (se piden a
  demanda), pero F5+ puede necesitar cachearlos.
