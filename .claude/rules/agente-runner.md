---
paths:
  - "vesper-backend/src/agents/**"
  - "vesper-backend/src/review_jobs/**"
  - "vesper-backend/tests/test_f4_*"
  - "vesper-backend/tests/test_byok*"
---

# Agent runner (opencode): seguridad, procesos y deuda


## Tareas de fondo (de «Backend — patrones clave»)

**Tareas de fondo:** una tarea lanzada desde un endpoint **no puede usar la
sesión de la request** — se cierra al enviar la respuesta. Usar
`schedule_job_run`, que abre sesión propia vía `_run_job_standalone`, y guardar
referencia fuerte de la task (`asyncio.create_task` solo guarda una débil y el
GC puede matar el job a mitad de camino).

**Seguridad del agent runner:**
- `validate_diff` (en `review_jobs/services.py`) manda el job a `needs_review`
  —sin abrir PR— si el diff toca `SENSITIVE_PATHS` o si **añade** algo que casa
  con `SECRET_PATTERNS`. Solo se miran las líneas añadidas: que el agente borre
  un secreto es justo lo que se le pide. El valor detectado nunca se loguea.
- El `installation_id` del callback de GitHub **se verifica contra GitHub**
  (`verify_installation_ownership`): se canjea el `code` OAuth y se comprueba
  que la instalación aparece en `GET /user/installations` de ese usuario. Falla
  cerrado.

- **El runtime NO hereda el entorno del backend**: recibe una lista blanca
  (`AGENT_ENV_ALLOWLIST` en `runner.py`). Con `os.environ` entero, un `env` dentro
  del agente mostraba `CREDENTIALS_ENCRYPTION_KEY`, `DATABASE_URL`, `JWT_SECRET` y la
  clave de la GitHub App: un prompt malicioso en el repo del tenant se llevaba las
  credenciales de todos. Si `opencode` necesita otra variable, se añade a la lista;
  nunca se vuelve a copiar el entorno.
- **Requiere `opencode-ai` 1.x** (verificado con 1.19.0), fijado con `OPENCODE_BIN`.
  `@opencode/cli` 2.x quitó `--pure` y cambió la API: `opencode serve --pure` imprime
  la ayuda y sale, y el job falla con un timeout de arranque que no dice por qué.
- **`opencode serve` usa un pool de puertos (14096+), uno por job.** Matarlos
  por PID concreto al cierre; nunca genérico.
- **`opencode` usa `~/.local/share/opencode/` salvo que le redirijas
  `XDG_DATA_HOME`.** Ahí están las credenciales personales de quien levantó el
  proceso y una base de sesiones compartida (llegó a 44 MB con jobs de varios
  tenants mezclados). Cada job recibe su directorio efímero vía `AgentSandbox`;
  `XDG_CACHE_HOME` **sí** se comparte, porque solo guarda paquetes descargados.
  Comprobación rápida: `XDG_DATA_HOME=<tmp> opencode providers list` debe
  reportar *0 credentials*.
- **`opencode` deja un árbol de procesos, no un proceso.** Arranca language
  servers (pyright, gopls…) dentro del workspace, y en Windows el `opencode`
  del PATH de npm es un `.cmd`, así que el hijo directo es el envoltorio:
  `terminate()` mataba el envoltorio y dejaba vivo el servidor real. Un job
  llegó a dejar ~30 procesos, y uno de ellos mantenía abierto el directorio, de
  modo que el **siguiente job sobre ese repo moría al limpiarlo**. `stop()`
  mata el árbol entero (`taskkill /T` en Windows, `killpg` en POSIX).
- **`shutil.rmtree(..., ignore_errors=True)` no borra un clon de git en
  Windows.** Los objetos de `.git` son de solo lectura: falla a medias y en
  silencio, y el `git clone` siguiente muere con "destination path already
  exists". `_wipe` quita el flag y reintenta.
- **`git add -A` se lleva lo que genera el propio agente.** El primer PR real
  salió con dos `.pyc` que compiló el language server. Los patrones de
  `EPHEMERAL_PATTERNS` se escriben en `.git/info/exclude` del clon (local, no
  se commitea) para que ni el diff ni el commit los vean.
- (F4+) **Auth con Zen requiere `Authorization: Bearer $OPENCODE_ZEN_KEY`.** Si
  hay 401 sistemático, verificar la suscripción en `opencode.ai/auth`, no rotar
  en código.


## Deuda conocida de este tema

- **El installation token sigue apareciendo en la línea de comandos del push.**
  Ya no se persiste en `.git/config` del workspace (el remote guardado va sin
  credenciales), pero durante el `git push` es visible en la lista de procesos
  de la máquina. Con sandbox por job es aceptable; sin él, no.

- **`error_message` va tal cual a la UI del tenant, con rutas del servidor
  dentro.** Un fallo de git enseña `<workspaces>/<tenant>/<repo>`. No
  es fuga entre tenants —esos ids ya son suyos— pero expone la disposición del
  disco del servidor. Habría que separar el detalle técnico (log) del mensaje
  que ve el usuario.
- **`opencode serve` sin `OPENCODE_SERVER_PASSWORD` queda abierto** y
  `GET /config/providers` devuelve las API keys en claro. Ya se arranca con un
  password aleatorio por job, pero **esto refuerza que el sandbox por job es
  obligatorio**: el código del repo del tenant corre junto al runtime.

- **Sin aislamiento de sistema de archivos por job** (lo resuelve F6b): el agente
  puede leer otros workspaces y el disco del servidor. Los secretos del backend ya no
  están a su alcance (lista blanca de entorno), pero las credenciales del propio job
  y los clones de otros tenants sí, hasta que cada job corra en su contenedor.

- **Persistencia de opencode por job:** queremos efímero. Definir si hace falta
  volumen efímero o `--no-state`.
- **Cuotas / throttle por tenant contra Zen.** Ninguna protección todavía.
