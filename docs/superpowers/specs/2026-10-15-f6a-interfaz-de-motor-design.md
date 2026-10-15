# F6a — Interfaz de motor, corte por inactividad y evals

> Sustituye la parte de **motor propio** de la spec del 2026-08-04
> ([motor de agente propio](2026-08-04-f6-motor-de-agente-propio-design.md)). Lo que esa
> spec decía del entorno de desarrollo (su §4, ahora F6b) y de los evals (§3.12) sigue
> vigente salvo donde este documento lo cambie.

## 1. Por qué

Vesper no va a escribir su propio bucle de tool-calling. La calidad de un agente de código
sale de modelo + harness + verificación, y el harness es el producto entero de otros
equipos (`opencode`, `pi`, DeepSeek Harness). Lo que Vesper aporta está alrededor: elegir
el harness con datos, verificar el PR en un entorno real y aislar a cada tenant.

F6 se parte en:

| Sub-fase | Qué | Necesita Docker |
| --- | --- | --- |
| **F6a** (esta spec) | Interfaz de motor con `opencode` detrás, corte por inactividad, progreso visible, banco de evals | No |
| **F6b** | Contenedor por job: el agente instala, corre la suite y Playwright; el PR sale verificado | Sí |
| **F6c** | Segundo motor (`pi` primero), elegido o descartado con la tabla de evals | No |

## 2. Situación de partida

- `ReviewService._run_job` conoce todos los detalles de `opencode`: pool de puertos,
  `AgentSandbox`, cliente httpx con password por job, sesión, `send_prompt`.
- `send_prompt` es **una sola llamada bloqueante** de hasta 2 h
  (`AGENT_TURN_TIMEOUT_SECONDS`). Mientras dura, el backend no sabe nada del agente.
- `OpencodeRunner.stream_events` existe (SSE `GET /event`) pero **nadie lo consume**. La
  UI muestra «Agent reviewing...» todo el turno: no se distingue un agente que trabaja de
  uno colgado.

## 3. Interfaz de motor

Archivo nuevo `src/agents/engine.py`:

```python
@dataclass
class EngineResult:
    tokens_input: int | None = None
    tokens_output: int | None = None

class AgentEngine(Protocol):
    async def run(
        self,
        workdir: Path,
        prompt: str,
        model: str,                       # "proveedor/modelo"
        credentials: dict[str, str],      # las de resolve_credentials del tenant
        on_activity: Callable[[Activity], Awaitable[None]],
    ) -> EngineResult: ...
    async def stop(self) -> None: ...
```

- `Activity` = `{tool, path}`; `path` relativa al workdir u opcional.
- **El motor no toca git ni GitHub.** Clonar, capturar el diff, `validate_diff`, commit,
  push y PR siguen en `services.py`, iguales para todos los motores. Así la seguridad del
  flujo (`validate_diff`, `EPHEMERAL_PATTERNS`, token fuera de `.git/config`) no depende
  del harness.
- **El motor lanza `RuntimeError` con un mensaje legible** si el modelo falla
  (`info.error`), si se corta por inactividad o por techo. `services.py` ya convierte eso
  en `failed` + `error_message`.
- `stop()` es idempotente y mata todo lo que el motor arrancó (árbol de procesos, puerto,
  directorio del sandbox). El `finally` de `_run_job` la llama siempre; el aborto manual
  (`CancelledError`) sigue funcionando igual.

`OpencodeEngine` (en `src/agents/opencode_engine.py`) envuelve lo existente:
`acquire_port`/`release_port`, `AgentSandbox`, `OpencodeRunner`, el password por job y la
sesión. `runner.py` y `sandbox.py` no cambian de comportamiento; solo dejan de ser
importados desde `services.py`.

Selección: `settings.agent_engine: Literal["opencode"] = "opencode"` (`AGENT_ENGINE`).
Una por instancia; por tenant no tiene sentido hasta que los evals lo justifiquen.

Tests: `FakeOpencodeRunner` se sustituye por `FakeEngine` (escribe archivos en el
workdir, emite actividades programadas, puede quedarse colgado o fallar). El parámetro
`runner_class` de `ReviewService` pasa a `engine_factory`.

## 4. Corte por inactividad

Dentro de `OpencodeEngine.run`, dos tareas concurrentes:

1. el turno (`send_prompt`), como hoy;
2. un consumidor de `stream_events` que, por cada evento de **la sesión del job**,
   reinicia el reloj de inactividad y traduce el evento a `Activity`.

| Reloj | Default | Variable | Al saltar |
| --- | --- | --- | --- |
| Inactividad | 10 min | `AGENT_IDLE_TIMEOUT_SECONDS` | `RuntimeError("El agente no dio señales de vida en 10 min …")` |
| Techo del turno | 6 h | `AGENT_TURN_TIMEOUT_SECONDS` | el mensaje actual de «no terminó en N min» |
| `job_timeout` del worker | 6 h 15 min | — | Arq cancela |
| `STALE_JOB_SECONDS` | 7 h | — | `reap_stale_jobs` lo marca `failed` |

El techo deja de ser el corte normal y queda como red de seguridad. El test de orden de
relojes que ya existe se amplía: `idle < turno < job_timeout < stale`.

**Qué cuenta como actividad**: cualquier evento cuyo `sessionID` sea el del job
(partes de mensaje, llamadas a herramienta, cambios de estado). Eventos de otras sesiones
o sin sesión no reinician el reloj. Si el SSE se cae, se reconecta una vez; si vuelve a
caer, el reloj sigue corriendo y acaba cortando (falla cerrado: sin señales = colgado).

**Verificación previa obligatoria (primera tarea del plan):** comprobar con `opencode`
1.19.0 real que `GET /event` emite eventos de la sesión **durante** el turno, y con qué
forma (`type`, dónde va `sessionID`, cómo se ve una llamada a herramienta). Si no los
emite, este apartado se rediseña antes de escribir código.

## 5. Progreso visible

`on_activity` publica en el bus existente un evento SSE nuevo `activity`
(`{tool, path}`):

- **Throttle**: como mucho uno cada 3 s por job; el reloj de inactividad se reinicia con
  todos, el reenvío solo con los que pasan el throttle.
- **Sin texto libre**: solo el nombre de la herramienta y la ruta relativa al workspace
  (`None` si cae fuera). Ni texto del modelo ni argumentos de búsqueda, así que no hay nada
  que redactar. Las rutas nunca son las del servidor.
- **No se persiste** en base de datos: es progreso en vivo. La tabla de pasos de la spec
  vieja queda fuera.
- El proxy de Next pasa los `text/event-stream` sin bufferizar.

Frontend: `job-thread` muestra la última actividad («Editando `src/app.py`») debajo del
estado mientras el job está `running`. Sin actividad recibida, se queda como hoy.

## 6. Banco de evals

`vesper-backend/evals/`:

```
evals/
  run.py               # python -m evals.run --model deepseek/deepseek-v4-flash
  tasks.py             # las tareas: prompt + comprobación
  fixtures/repo-basico/  # repo Python mínimo con su suite pytest
```

- Corre el motor **directamente** sobre una copia temporal del fixture: sin GitHub, sin
  base de datos, sin API. Las credenciales salen de variables de entorno del que lo lanza.
- **3 tareas** para empezar, cada una con su comprobación:
  1. arreglar un bug con test que falla → la suite del fixture pasa;
  2. añadir docstrings a un módulo → el patrón aparece y la suite sigue verde;
  3. no tocar nada cuando no hay nada que hacer → diff vacío.
- Salida: tabla Markdown (tarea · modelo · motor · ✅/❌ · segundos · tokens) en stdout y
  en `evals/results/<fecha>.md` (ignorado por git).
- **Gasta saldo de la key**: nunca corre en CI ni en `pytest`. Se lanza a mano.
- La lógica de comprobación sí tiene tests (con `FakeEngine`), para que un eval roto no
  pase por bueno.

## 7. Fuera de F6a

- El contenedor por job (F6b). **Decisión tomada**: los contenedores de los jobs corren en
  un servicio Docker aislado dentro del compose (rootless o Sysbox), al que el worker habla
  por red. **Nunca** el socket de Docker del host. Abrir el registro al público exigirá
  pasar a una VM dedicada a jobs.
- El adaptador de `pi` (F6c).
- Tabla `agent_steps`, coste por job, prompts editables por tenant.

## 8. Errores y casos límite

| Caso | Resultado |
| --- | --- |
| Agente colgado (sin eventos) | `failed`, «no dio señales de vida en 10 min» |
| Agente activo más de 6 h | `failed`, mensaje del techo |
| Modelo sin saldo / key inválida | `failed`, «El modelo no respondió: …» (como hoy) |
| Usuario pulsa «Detener» | `failed`, «Job abortado»; `stop()` limpia (como hoy) |
| SSE de `opencode` cae dos veces | el reloj sigue y corta a los 10 min |
| `AGENT_ENGINE` con valor desconocido | la app no arranca (validación de settings) |

## 9. Tests (TDD)

| Área | Casos |
| --- | --- |
| Interfaz | `_run_job` completo con `FakeEngine` → PR (los tests actuales, migrados) |
| Inactividad | motor sin actividad corta en el idle (con reloj corto en test); con actividad constante no corta |
| Filtro de sesión | eventos de otra sesión no reinician el reloj |
| Actividad | throttle; redacción de secretos; rutas relativas |
| Relojes | `idle < turno < job_timeout < stale` |
| `stop()` | idempotente; se llama en éxito, error y abort |
| Evals | cada comprobación con un `FakeEngine` que acierta y otro que falla |
| Frontend | `job-thread` pinta la última actividad |

## 10. Criterios de cierre

1. Un job real en producción abre un PR pasando por `OpencodeEngine`.
2. `services.py` no importa `OpencodeRunner` ni `AgentSandbox` (solo `split_model`).
3. El corte por inactividad está cubierto por test y verificado con el `opencode` real
   (la primera tarea del plan).
4. El hilo del job muestra actividad en vivo en producción.
5. `python -m evals.run` saca la tabla de las 3 tareas con un modelo real.
6. Loop completo en verde: `pytest`, `ruff`, `pnpm test:run`, `tsc`, `lint`, `build`.
