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


## Motor del agente (F6a)

- **`services.py` no conoce `opencode`**: pide un `AgentEngine` a `engine_factory`
  (`src/agents/engine.py`). `OpencodeEngine` (`opencode_engine.py`) junta pool de puertos,
  `AgentSandbox`, proceso, password y sesión. El motor no toca git ni GitHub: clonar,
  `validate_diff`, commit y PR siguen en `services.py`, iguales para cualquier motor.
- **Corte por inactividad**, no por reloj: cada evento SSE **de la sesión del job** reinicia
  un reloj de `AGENT_IDLE_TIMEOUT_SECONDS` (10 min). `server.heartbeat`, `plugin.added` y
  demás eventos globales no llevan sesión y **no cuentan**: siguen llegando con el agente
  colgado. Una herramienta en `pending`/`running` pausa el reloj (una suite larga dentro de
  `bash` no emite nada hasta acabar). El techo de 6 h queda de red de seguridad.
- **Forma de los eventos** (opencode 1.19.0): herramienta = `message.part.updated` con
  `part.type == "tool"`, `part.tool`, `part.state.status`, `part.state.input.filePath`
  **absoluta**; texto = `message.part.delta`; tokens y coste en `part.type == "step-finish"`.
  A la UI solo va `{tool, path relativa}`: nunca texto del modelo ni rutas del servidor.
- **Un modelo que el runtime no conoce da un 500 genérico** en `POST /message`; el motivo
  («Model not found: …») solo llega por el evento `session.error`, y el motor lo usa como
  mensaje del job (esperando hasta 5 s: el 500 vuelve **antes** que el evento). El caso
  real fue un modelo `deprecated` en models.dev, que `opencode` oculta; el catálogo de Vesper
  ya los filtra.
- **El SSE pasa por el proxy de Next sin bufferizar** (`text/event-stream`); con
  `res.text()` la UI no recibía nada hasta el final.
- **Banco de evals**: `python -m evals.run --model <proveedor/modelo>` con
  `VESPER_EVAL_CREDENTIALS="proveedor=key"`. Gasta saldo y ejecuta código que escribe el
  modelo sobre el fixture: solo a mano, nunca en CI.

## Contenedor por job y PRs verificados (F6b)

- **`AGENT_ENGINE` elige el motor** en `default_engine_factory` (`review_jobs/services.py`):
  `opencode` (por defecto, proceso local para desarrollo) o `docker` (`DockerOpencodeEngine` en
  `src/agents/docker_engine.py`). Nunca cae de `docker` a `opencode` en silencio: si el daemon
  Docker no responde, el job falla con un mensaje legible.
- **Un contenedor sin privilegios por job (`vesper-agent:1`)**, en un anfitrión Docker separado
  del backend (`DOCKER_HOST=tcp://<ip>:2376`, `DOCKER_TLS_VERIFY=1`, `DOCKER_CERT_PATH`):
  usuario `agent` (uid 1000), `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`,
  `pids_limit=512`, `nano_cpus` y `mem_limit`/`memswap_limit` de `settings`. Semáforo de proceso
  `_SLOTS` (`AGENT_MAX_JOBS`) liberado siempre en `_teardown`.
- **El token de instalación de GitHub jamás entra al contenedor**: `WorkspaceService.clone`
  limpia la URL de `origin` y borra `.git/logs`, y `_repo_tar` excluye `.git/config` cruda,
  `.git/FETCH_HEAD`, `.git/logs` y `.git/hooks`, inyectando una `.git/config` saneada sin
  credenciales ni `extraheader`/`insteadOf`/`helper` y con `dereference=False` (no sigue symlinks
  del clon hacia el host).
- **Caché de paquetes por tenant**: volumen `vesper-cache-<tenant_id>` montado en
  `/home/agent/.cache` (`tenant_id` obligatorio en `DockerOpencodeEngine`) para que un tenant no
  pueda envenenar la caché de otro.
- **Red `vesper-jobs` (`172.30.0.0/16`, bridge `vesper-jobs0`, `enable_icc=false`)**: creada por
  `deploy/jobs-host/setup.sh` con reglas `DOCKER-USER` (salida a internet permitida, bloqueo a
  RFC1918, CGNAT/Tailscale `100.64.0.0/10` y link-local/metadata `169.254.0.0/16`) e `INPUT`
  (los contenedores no alcanzan al propio anfitrión).
- **Verificación antes y después (`src/agents/verification.py`)**: `detect_test_commands`
  detecta Node (`pnpm`/`yarn`/`npm`), Python (`pyproject.toml`/`requirements*.txt` + `pytest`) y
  `Makefile` (`test:`). El motor corre la suite antes del agente, excluye artefactos nuevos de
  la suite base (`.git/info/exclude`), ejecuta `opencode`, extrae el parche **antes** de la
  segunda suite (`git add -A && git diff --cached --binary`), corre la suite después (timeout
  900 s por comando, salida por `tail_redacted`) y aplica el parche en el clon del worker con
  `git apply --binary --index -`. `WorkspaceService.commit_and_push` commitea con `--no-verify`
  para que ningún hook escrito por el parche se ejecute en el worker.
- **El veredicto decide el PR**: `verified` (✅→✅), `already_red` (❌→*) y `unverified` abren PR
  con sección `## Verificación`; `broke` (✅→❌) deja el job en `needs_review` sin PR y guarda
  `error_message.suite_log` (mostrado en la UI). La instrucción «Antes de terminar, corre los
  tests…» se añade al prompt **al ejecutar** el job (`run_job`), nunca al encolarlo, y solo si
  `AGENT_ENGINE=docker`.

## Deuda conocida de este tema

- **El installation token sigue apareciendo en la línea de comandos del push en el worker.**
  Ya no se persiste en `.git/config` ni en `.git/logs` y nunca viaja al contenedor de job, pero
  durante el `git push` es visible en la lista de procesos del worker.
- **`error_message` va tal cual a la UI del tenant, con rutas del servidor
  dentro.** Un fallo de git enseña `<workspaces>/<tenant>/<repo>`. No
  es fuga entre tenants —esos ids ya son suyos— pero expone la disposición del
  disco del servidor. Habría que separar el detalle técnico (log) del mensaje
  que ve el usuario.
- **Con `AGENT_ENGINE=opencode` (modo local de desarrollo) no hay aislamiento de sistema de
  archivos ni de red**: usar `AGENT_ENGINE=docker` en despliegues multi-tenant.
- **Cuotas / throttle por tenant contra Zen.** Ninguna protección todavía.
