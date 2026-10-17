# F6b — Contenedor por job y PRs verificados

> Sigue a [F6a](2026-10-15-f6a-interfaz-de-motor-design.md). Sustituye el §4 de la spec del
> [2026-08-04](2026-08-04-f6-motor-de-agente-propio-design.md) donde la contradiga.

## 1. Por qué

Hoy el agente ejecuta sus comandos en el mismo servidor que el backend: puede leer otros
workspaces y el disco, y el PR sale **plausible, no verificado**. F6b mete cada job en un
contenedor propio, corre la suite del repo antes y después, y decide con eso si abre el PR.

## 2. Decisiones

| Decisión | Elegido | Por qué |
| --- | --- | --- |
| Dónde corren los contenedores | **Un anfitrión Docker aparte** al que el worker habla por la API de Docker (`DOCKER_HOST`, TLS mutuo) | Docker-in-Docker exige `--privileged`, que según la documentación oficial *«provides full access to the host environment»*: en el anfitrión de producción, un escape tomaría todas las apps. Sysbox evitaría el privilegio pero obliga a instalar un runtime en ese anfitrión. |
| Motor | `DockerOpencodeEngine`, otro `AgentEngine` | La interfaz de F6a: el flujo del job no cambia. |
| Por defecto | `AGENT_ENGINE=opencode` (proceso local, como hoy) | Quien autoaloje Vesper para sus propios repos no necesita Docker. |
| Token de GitHub | **Nunca entra al contenedor** | Clonar, commit, push y PR siguen en el worker. Con el token dentro, un prompt malicioso podría empujar a cualquier repo de la instalación. |
| Credencial del modelo | Entra al contenedor (`auth.json`) | Es la del propio tenant; el agente la necesita. |

### Escenarios de despliegue

| Quién | `AGENT_ENGINE` | `DOCKER_HOST` |
| --- | --- | --- |
| Autoalojado, solo repos propios | `opencode` (defecto) o `docker` | — / socket local |
| Instancia abierta a terceros | `docker` | **máquina aparte**, nunca el anfitrión del backend |

El README dirá en claro que con `opencode` el agente ejecuta comandos sobre el servidor:
aceptable para revisar repos propios, no para abrir el registro.

## 3. Ciclo de un job

1. El worker clona en su workspace (como hoy) con el token de instalación.
2. Crea el contenedor del job desde la imagen `vesper-agent` con límites y la red de jobs, y
   le sube el repo como tar (`put_archive`), con `.git` incluido y el remote **sin
   credenciales** (ya es así desde F4).
3. Escribe el `auth.json` del tenant en el directorio de datos de opencode del contenedor.
4. **Suite de referencia**: ejecuta los comandos de test detectados (§5) y guarda resultado.
5. Arranca `opencode serve` dentro del contenedor (password por job) y lo expone en un
   puerto efímero del anfitrión; el worker se conecta como hoy (sesión, SSE, vigilante de
   inactividad: todo lo de F6a se reutiliza).
6. **Suite posterior** con los mismos comandos.
7. Extrae el cambio con `git add -A && git diff --cached --binary` (respetando
   `EPHEMERAL_PATTERNS`) y el worker lo aplica a su clon con `git apply`. Desde ahí:
   `validate_diff`, commit, push y PR, sin cambios.
8. `stop()` destruye el contenedor y su volumen de trabajo; la caché del tenant se conserva.

## 4. Verificación

`EngineResult` gana `checks: Verification | None` (`None` = motor sin verificación, p. ej.
el local). `Verification` = comandos, exit code antes y después, y la cola del log
(4 KB, redactada con `SECRET_PATTERNS`).

| Antes | Después | Resultado |
| --- | --- | --- |
| ✅ | ✅ | PR con la evidencia en el cuerpo |
| ✅ | ❌ | `needs_review`, sin PR; el log en el job |
| ❌ | cualquiera | PR, avisando de que la suite ya fallaba |
| sin comandos | — | PR marcado «sin verificar» |

El prompt del agente añade: «corre los tests del repo antes de terminar».

## 5. Detección de comandos de test

Por convención, en este orden, y solo lo que exista:

| Señal | Instalar | Test |
| --- | --- | --- |
| `pnpm-lock.yaml` / `package-lock.json` / `yarn.lock` con script `test` | `pnpm i --frozen-lockfile` / `npm ci` / `yarn --frozen-lockfile` | `<gestor> test` |
| `pyproject.toml` o `requirements*.txt` + tests pytest | `pip install -e .` / `-r requirements.txt` | `python -m pytest -q` |
| `Makefile` con objetivo `test` | — | `make test` |

Timeout por comando: 15 min. Más allá, cuenta como ❌ con el motivo.

## 6. Anfitrión de jobs

- **Imagen `vesper-agent`**: Python 3.12, Node 22 + pnpm, git, make, `opencode-ai@1.19.0`,
  navegadores de Playwright. Se construye en CI y se publica en GHCR con versión.
- **Por contenedor**: sin `--privileged`, `cap_drop: ALL` salvo lo mínimo, usuario no root,
  `pids_limit`, CPU y memoria (`AGENT_JOB_CPUS=2`, `AGENT_JOB_MEMORY=4g`), disco con
  `--storage-opt` si el driver lo permite.
- **Red**: una red Docker de jobs con salida a internet. En el anfitrión, reglas
  `DOCKER-USER` que **bloquean** RFC1918 y `100.64.0.0/10` (Tailscale) desde esa red. Sin
  ellas, un job alcanza las bases de datos de la LAN.
- **Caché por tenant**: volumen `vesper-cache-<tenant>` para pnpm/pip. Nunca compartido entre
  tenants (envenenamiento de dependencias).
- **Concurrencia**: `AGENT_MAX_JOBS` por anfitrión; si no hay hueco, el job espera en la cola.
- `deploy/jobs-host/` en el repo: script de preparación (Docker, reglas de red, certificados
  TLS) para replicarlo. Lo específico de nuestra infraestructura va en `CLAUDE.local.md`.

## 7. Errores

| Caso | Resultado |
| --- | --- |
| Anfitrión de jobs inalcanzable | `failed`, «No se pudo arrancar el entorno del job» |
| Imagen no disponible | `failed` con el motivo; nunca se cae al motor local en silencio |
| `git apply` falla | `failed`; el parche queda en el log |
| Suite que no termina | ❌ por timeout, con el motivo |
| Abort | `stop()` mata el contenedor (como en F6a) |

## 8. Fuera de F6b

- Servicios auxiliares (Postgres por job, `docker-compose.yml` del repo): F6b.2.
- Reintentos automáticos cuando el agente rompe la suite.
- VM efímera por job (Firecracker/gVisor).

## 9. Tests

| Área | Casos |
| --- | --- |
| Detección | cada señal de §5; varias a la vez; ninguna |
| Veredicto | las 4 filas de §4 |
| Motor | ciclo completo con un cliente Docker falso; abort; anfitrión caído |
| Diff | parche con binario y con archivo borrado se aplica igual en el worker |
| Redacción | un secreto en el log de tests no llega al job |
| Integración | job de CI con Docker real: imagen, contenedor, suite, parche |

## 10. Criterios de cierre

1. Un job real en producción, con `AGENT_ENGINE=docker` contra la VM de jobs, abre un PR con
   la evidencia de la suite en el cuerpo.
2. Un job cuyo cambio rompe la suite termina en `needs_review` sin PR.
3. Desde un contenedor de job, la LAN y Tailscale son inalcanzables (comprobado).
4. Con `AGENT_ENGINE=opencode` todo sigue como en F6a.
5. Loop completo en verde y job de CI con Docker real en verde.

## 11. Estado de la implementación (2026-10-17)

Cada tarea se implementó con TDD y pasó revisión independiente más revisión final de rama.

| # | Tarea | Estado |
| --- | --- | --- |
| 1 | `src/agents/verification.py`: detección de comandos de test (§5), `Verification`, veredicto (§4), `tail_redacted` | ✅ revisada |
| 2 | `OpencodeEngine` partido en `_provision` (arrancar el runtime) y `_drive` (sesión, SSE, vigilante); `OpencodeRunner(..., host=)` | ✅ revisada |
| 3 | `EngineResult.checks`; el veredicto decide PR o `needs_review`; sección «Verificación» en el cuerpo del PR; la instrucción «corre los tests» solo con `AGENT_ENGINE=docker` | ✅ revisada |
| 4 | `src/agents/docker_engine.py` (`DockerOpencodeEngine`) | ✅ auditada en seguridad y corregida (limpieza de `.git/logs`, exclusión de `.git/FETCH_HEAD`/`.git/logs`/`.git/hooks`, `git diff HEAD` con archivos borrados, `--no-verify` en commit) |
| 5 | `deploy/agent-image/Dockerfile`, `deploy/jobs-host/setup.sh` y su README | ✅ revisada y verificada en Docker real en CI |
| 6 | `AGENT_ENGINE` elige el motor; variables en el compose; aviso de aislamiento en los README; la UI muestra `error_message.suite_log` en `needs_review` (verificada a 1280 px y 390 px); decisión de `run_tests` al ejecutar el job | ✅ revisada |
| 7 | Test de integración y workflow de CI con Docker real (`docker-engine-ci.yml`: ejecuta `setup.sh` dos veces, comprueba reglas `DOCKER-USER`/`INPUT`/ICC y corre `test_docker_engine_real.py` por TCP 2376 + TLS) | ✅ en verde en CI |
| 8 | Cierre: documentación y revisión final de rama listas; pendiente aprovisionar el anfitrión de jobs en producción y correr el job real (§10.1–10.3) | 🔨 pendiente anfitrión de producción |

### Deuda menor anotada

- `before.exit_code is None` con comandos se pinta ❌ sin aviso.
- `setup.sh`: el SAN del certificado no se regenera si cambian las IPs; reinicia `dockerd` en
  cada ejecución; `netfilter-persistent save` guarda también las cadenas de Docker; sin reglas
  IPv6; con el backend nftables de Docker 29+ `DOCKER-USER` no existe y el script aborta.
