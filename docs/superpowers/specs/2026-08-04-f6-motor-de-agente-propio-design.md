# F6 — Motor de agente propio

**Fecha:** 2026-08-04
**Estado:** diseño aprobado, pendiente de plan de implementación
**Sustituye a:** el runtime `opencode` de [F4](2026-07-28-f4-agent-runner-design.md)

---

## 1. Por qué cambiamos de rumbo

Hasta hoy Vesper no tenía agente: tenía un *cliente* de `opencode serve`. El
backend clonaba el repo, levantaba un proceso ajeno, le mandaba un prompt por
HTTP y recogía el diff resultante. Todo el valor diferencial vivía alrededor
—multi-tenancy, triggers, PRs con installation token, validación anti-secretos—
y el comportamiento del agente, que es lo único que el usuario percibe, era de
otro.

A partir de ahora **Vesper es el agente**: bucle propio de tool-calling contra
la API del proveedor, con sus propias herramientas sobre el workspace clonado.
El objetivo declarado es una herramienta de desarrollo profesional en web —del
orden de Claude Code o Codex— que itera de forma autónoma sobre los repos del
tenant respetando las convenciones que cada repo declara.

Esto no es un refactor: es la pieza central del producto, y hasta ahora estaba
subcontratada.

### Qué se retira

| Se borra | Motivo |
| --- | --- |
| `src/agents/runner.py` | Era el cliente HTTP de `opencode serve`. |
| `src/agents/sandbox.py` | El `auth.json` y los `XDG_*` existían para opencode. |
| `acquire_port` / `release_port` / `_PORTS_IN_USE` | El pool 14096+ era de opencode. |
| `settings.opencode_bin`, `settings.opencode_port_pool_start` | Sin binario que resolver. |
| `split_model` | Se traslada a `llm/providers.py::parse_model`, sin default `opencode-go`. |

Las trampas documentadas en `CLAUDE.md` sobre el árbol de procesos de opencode,
`XDG_DATA_HOME`, `--pure` y el pool de puertos dejan de aplicar y salen del
documento al cerrar F6a.

### Qué se conserva intacto

Clonado con installation token, `configure_git`, `create_branch`,
`capture_diff`, `EPHEMERAL_PATTERNS`, `validate_diff` (rutas sensibles +
patrones de secreto), `commit_and_push`, `create_pull_request`, los cuatro
triggers de F5 con su debounce y su anti-bucle, `reap_stale_jobs`, las cuotas
de `PLAN_QUOTAS`, el bus de eventos con su cursor sobre lista de Redis, y el
BYOK completo: `resolve_credentials` sigue siendo **el punto único** por el que
se decide con qué credenciales corre un job.

La diferencia es dónde se usa la key: antes se escribía en un `auth.json` para
que la leyera otro proceso; ahora la usa nuestro cliente HTTP y **nunca toca el
disco**.

---

## 2. Alcance: tres sub-fases

F6 completa es demasiado para una sola spec y para un solo plan. Se parte en
tres entregas, cada una cerrable y verificable por separado:

| Sub-fase | Qué entrega | Cierre |
| --- | --- | --- |
| **F6a — Núcleo** | Cliente de proveedores, bucle de tool-calling, herramientas de archivo, contexto y presupuesto, transcript y eventos, evals. | Un job real vuelve a abrir un PR, ya sin opencode. |
| **F6b — Entorno de desarrollo** | Contenedor por job, herramienta `bash`, instalación de dependencias, servicios auxiliares, ejecución de tests/lint/E2E, artefactos. | El PR incluye la evidencia de que los tests del repo pasan. |
| **F6c — Convenciones y skills** | Descubrimiento y uso de las reglas del repo, biblioteca de skills de Vesper, prompts por tarea configurables. | El PR "suena" al repo: sigue su estilo, sus comandos y sus normas. |

**Este documento detalla F6a a nivel implementable** y deja F6b y F6c a nivel
de diseño acordado, suficiente para no pintarnos en una esquina pero sin fijar
detalles que dependen de lo que aprendamos en F6a.

---

## 3. F6a — Núcleo del agente

### 3.1 Estructura

```
src/agents/
├── catalog.py          (existente, ampliado — ver 3.7)
├── credentials.py      (existente, sin cambios de contrato)
├── models.py           (existente: TenantCredential)
├── router.py           (existente: BYOK)
├── schemas.py          (existente)
├── services.py         (existente)
├── llm/
│   ├── types.py        Message, ToolCall, ToolResult, Usage, ModelSpec
│   ├── providers.py    parse_model, base_url y spec por proveedor
│   └── client.py       ChatProvider (protocolo) + OpenAICompatibleProvider + ScriptedProvider
└── engine/
    ├── loop.py         AgentEngine: el bucle
    ├── prompts.py      prompt de sistema y de tarea
    ├── context.py      mapa del repo, ventana y compactación
    ├── budget.py       contadores, coste y circuit breaker
    ├── transcript.py   persistencia de pasos + emisión de eventos
    └── tools/
        ├── __init__.py registro y despacho
        ├── jail.py     resolución segura de rutas
        ├── files.py    read_file, write_file, edit_file, list_dir
        ├── search.py   glob, grep
        └── control.py  finish
```

`review_jobs/services.py` deja de conocer al runtime: pasa de orquestar
`OpencodeRunner` a llamar a `AgentEngine.run(task)`. Todo lo demás del flujo
(clone → branch → agente → diff → validación → PR) se queda como está.

### 3.2 Contrato del motor

```python
@dataclass(frozen=True)
class AgentTask:
    job_id: uuid.UUID
    tenant_id: uuid.UUID
    workdir: Path            # clon del repo, ya en la rama de trabajo
    repo_full_name: str
    ref: str
    model: str               # "proveedor/modelo"
    instruction: str         # plantilla del task_type o prompt libre del usuario

@dataclass
class AgentResult:
    summary: str             # lo que el modelo declaró al terminar
    stop_reason: StopReason  # finished | max_iterations | loop_detected | idle
                             # | provider_error | aborted
    usage: Usage             # tokens in/out, coste estimado
    steps: int
```

`AgentEngine` no sabe nada de git, de GitHub ni de PRs. Recibe un directorio y
una instrucción, deja el working tree modificado y devuelve un resumen. Esa
frontera es lo que permite testear el motor sin red y sin repositorio real.

### 3.3 Capa de proveedores

Un único cliente contra el formato OpenAI (`POST {base_url}/chat/completions`
con `tools`, `tool_choice: "auto"` y `stream: false` en F6a), que cubre Kimi,
GLM, Qwen, DeepSeek, OpenAI, Groq, Mistral, OpenRouter y la propia pasarela
Zen. Los proveedores que se desvían del formato —Anthropic es el caso
evidente— entran como implementaciones adicionales del mismo protocolo; F6a no
las incluye, solo deja el punto de extensión.

```python
class ChatProvider(Protocol):
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        model_id: str,
    ) -> Completion: ...
```

**Resolución de la base URL.** El `api` de cada proveedor sale de models.dev,
que ya es nuestra fuente de verdad. Se admite override por variable de entorno
para proveedores que models.dev no documente bien, y la key sale siempre de
`resolve_credentials`. Si el tenant tiene credenciales de varios proveedores,
manda el prefijo del modelo elegido (`kimi/kimi-k3` usa la credencial de
`kimi`); si no tiene credencial para ese proveedor, el job falla con un
mensaje accionable antes de clonar nada.

**Reintentos.** Backoff exponencial con jitter en 429 y 5xx (5 intentos,
tope de 60 s), sin reintento en 400/401/403 —esos no mejoran repitiendo—.
Un 401 se traduce a "tu API key de <proveedor> fue rechazada", nunca al cuerpo
crudo de la respuesta, que en algunos proveedores incluye fragmentos de la key.

**`ScriptedProvider`** devuelve una secuencia de respuestas pregrabada. Es lo
que permite testear el bucle entero —incluidas las ramas de error— sin tocar
la red, igual que `FakeOpencodeRunner` hacía en F4.

### 3.4 Herramientas

| Tool | Firma | Notas |
| --- | --- | --- |
| `read_file` | `path, offset?, limit?` | Devuelve numerado. Trunca por tamaño y avisa de la truncación. |
| `write_file` | `path, content` | Crea o reemplaza. Exige `read_file` previo si el archivo existe. |
| `edit_file` | `path, old_string, new_string, replace_all?` | Reemplazo **exacto**. Error si no casa o si es ambiguo. |
| `list_dir` | `path` | Respeta `.gitignore`. |
| `glob` | `pattern` | Ordenado por fecha de modificación. |
| `grep` | `pattern, path?, glob?, mode?` | `ripgrep` si está disponible, fallback en Python. |
| `finish` | `summary` | El modelo declara el trabajo terminado. |

La edición es por **búsqueda y reemplazo exacto**, no por reescritura del
archivo completo. Con archivos grandes, reescribir entero quema el contexto y
además provoca pérdidas silenciosas de código; el reemplazo exacto falla de
forma detectable y permite devolverle al modelo un error útil.

Cuando una tool falla, el error vuelve al modelo como resultado de la llamada
—con el contexto necesario para corregir— en vez de romper el job. Un
`edit_file` que no casa devuelve las líneas reales alrededor de la zona
buscada. Los fallos cuentan para el circuit breaker.

`finish` existe para no tener que adivinar cuándo ha terminado el modelo: sin
una señal explícita, la alternativa es cortar cuando deja de pedir tools, que
es exactamente lo que hace un modelo que se ha perdido.

### 3.5 Jaula de rutas (invariante de seguridad)

Toda ruta que llegue de una tool pasa por `jail.resolve(workdir, path)`:

1. Se resuelve contra el workdir (nunca se aceptan rutas absolutas).
2. Se resuelven symlinks y se comprueba que el resultado **sigue dentro** del
   workdir.
3. Se rechaza `.git/` para cualquier escritura. Un agente que puede escribir
   en `.git/hooks/pre-commit` ejecuta código nuestro en el `commit` que hace
   Vesper a continuación, y un agente que puede escribir en `.git/config`
   redirige el push.

Sin este control, un modelo confundido —o un prompt hostil dentro del propio
repo del tenant— puede leer o escribir cualquier archivo del servidor. En F6b
el contenedor añade una segunda barrera, pero **la jaula no depende de él**:
tiene que aguantar sola.

### 3.6 Contexto

**Prompt de sistema**: quién es (ingeniero senior trabajando dentro de un
repositorio concreto), qué no debe hacer (ni commit, ni push, ni PR — de eso se
encarga Vesper; nada de secretos; cambios mínimos y coherentes con el estilo
existente), el mapa del repo y las convenciones que el repo declare.

**Mapa del repo**: `git ls-files` —que ya respeta `.gitignore`— agrupado por
directorio y recortado a un número de entradas razonable, más el stack
detectado (`pyproject.toml`, `package.json`, `go.mod`…). Nunca se vuelca el
contenido de los archivos: el agente los pide con sus herramientas. Un volcado
gasta el contexto en lo que no se necesita y deja sin sitio a lo que sí.

**Convenciones**: en F6a se cargan, si existen, `AGENTS.md`, `CLAUDE.md` y
`CONTRIBUTING.md` de la raíz. F6c convierte esto en un subsistema con
descubrimiento completo y biblioteca de skills.

**Compactación**: cuando la conversación supera el 70 % del contexto del modelo
(el límite sale de models.dev), los intercambios antiguos se resumen con el
propio modelo y se sustituyen por ese resumen, conservando el prompt de sistema
y los últimos intercambios íntegros. Los resultados de tool voluminosos se
truncan antes de entrar en el historial.

### 3.7 Ampliación del catálogo

`catalog._trim` hoy tira precios y endpoints, porque el selector de la UI no
los necesita. El motor sí: necesita `api` (base URL), `limit.context` para la
compactación y `cost` para calcular el gasto. Se separan dos vistas sobre la
misma copia cacheada:

- `get_catalog()` — lo que ya devuelve, recortado, para el frontend.
- `get_model_spec(provider_id, model_id) -> ModelSpec | None` — base URL,
  ventana de contexto y precios, para uso interno.

La semilla de emergencia se amplía con esos campos para los cuatro proveedores
que ya cubre.

### 3.8 Presupuesto y circuit breaker

Decisión de producto: **no hay cuota de tokens ni de tiempo**. Quien usa esto
paga su propia key y quiere que el agente termine el trabajo, no que se rinda a
mitad.

Lo que sí hay es un freno de emergencia, que no existe para racionar sino para
que un fallo no deje un job girando toda la noche contra la API de pago del
tenant:

| Corte | Default | Configurable |
| --- | --- | --- |
| Tool calls idénticas consecutivas | 5 (aviso al modelo en la 3.ª) | sí |
| Sin cambios en el workspace ni `finish` | 20 min | sí |
| Iteraciones | 200 | sí, `None` lo desactiva |
| Tokens | sin límite | sí, opcional por si el operador lo quiere |

Los cuatro se registran como `stop_reason` distintos, para que la UI pueda
decir *por qué* paró y no solo que paró. El aborto manual que ya existe sigue
funcionando: cancela la tarea y el `finally` limpia.

**Coste**: se acumula `usage` de cada respuesta y se multiplica por el precio
de models.dev. Se guarda en el job y se muestra en la UI. Con BYOK el tenant
paga cada token; enseñarle lo que le costó cada PR es información que hoy nadie
le da.

### 3.9 Transcript y eventos

Tabla nueva `agent_steps` (migración `0007`):

| Columna | Tipo | Nota |
| --- | --- | --- |
| `id` | UUID | |
| `tenant_id` | UUID FK | invariante de aislamiento |
| `review_job_id` | UUID FK, index | `ON DELETE CASCADE` |
| `idx` | int | orden dentro del job |
| `kind` | enum | `assistant` · `tool_call` · `tool_result` · `error` · `summary` |
| `tool_name` | str? | |
| `payload` | JSON | truncado a 8 KB por paso |
| `tokens_input` / `tokens_output` | int? | solo en pasos `assistant` |
| `created_at` | timestamptz | |

Y en `review_jobs`: `tokens_input`, `tokens_output`, `cost_usd`, `iterations`,
`stop_reason`.

Eventos SSE nuevos sobre el bus existente: `assistant` (texto del modelo),
`tool_call` (nombre + argumentos resumidos), `tool_result` (ok/error +
resumen), `usage` (tokens y coste acumulados). Los terminales no cambian.

**Nada de secretos en el transcript.** Los resultados de tool pasan por el
mismo redactor de `SECRET_PATTERNS` antes de persistirse: el agente puede leer
un `.env` del repo del tenant, y ese contenido no puede acabar en nuestra base
de datos ni en la UI.

### 3.10 Frontend

Lo mínimo para que el progreso se entienda: la página del job pasa de una línea
de estado a un **hilo de pasos** —qué archivo leyó, qué editó, qué falló—
alimentado por los eventos nuevos, más el contador de tokens y coste. Sin esto,
el motor nuevo se percibe igual que el viejo: una barra que gira varios
minutos.

### 3.11 Tests (TDD, obligatorio)

| Área | Casos |
| --- | --- |
| Jaula | `../` fuera del workspace, ruta absoluta, symlink que escapa, escritura en `.git/` |
| `edit_file` | no casa, casa dos veces sin `replace_all`, casa una, `replace_all` |
| Bucle | tool call → resultado → `finish`; tool inválida; error de proveedor; 429 con reintento |
| Breaker | 5 llamadas idénticas cortan con `loop_detected`; inactividad corta con `idle` |
| Contexto | compactación al superar el umbral; mapa del repo respeta `.gitignore` |
| Coste | usage acumulado y precio aplicado |
| Aislamiento | `agent_steps` de tenant A no visibles desde tenant B |
| Extremo a extremo | job completo con `ScriptedProvider` y GitHub mockeado → PR |

### 3.12 Evals

Un harness propio en `vesper-backend/evals/`: tareas doradas sobre repos
fixture, cada una con su aserción (archivo tocado, patrón presente o ausente,
suite del fixture en verde). Se ejecuta contra un modelo real y produce una
tabla comparativa.

En F6a entran tres tareas. Crece en cada sub-fase. Sin esto, elegir entre Kimi,
GLM y Qwen es una discusión de opiniones; con esto, es una tabla. Es también el
único modo honesto de saber si un cambio en el prompt de sistema mejora o
empeora el agente.

### 3.13 Criterios de cierre de F6a

1. Un job real sobre `vesper-testbed` abre un PR usando el motor propio.
2. No queda ninguna referencia a opencode en el código del backend.
3. `pytest`, `ruff`, `pnpm test:run`, `pnpm exec tsc --noEmit` y `pnpm build` en
   verde; migración `0007` con ciclo `upgrade → downgrade → upgrade → check`.
4. Las tres tareas de eval pasan con el modelo elegido.
5. La UI del job muestra el hilo de pasos y el coste.

---

## 4. F6b — Entorno de desarrollo (diseño acordado)

No es un sandbox que contiene daños: es un **entorno de trabajo** donde el
agente puede hacer lo que hace un desarrollador. Instalar dependencias,
levantar la base de datos, arrancar los servidores, correr la suite, ejecutar
Playwright contra un navegador, trabajar en TDD.

- **Imagen base propia**: Python + Node/pnpm + git + navegadores de Playwright
  preinstalados. Se construye una vez y se versiona; bajarla en cada job se
  come varios minutos de cada revisión.
- **Bootstrap del workspace**: detección del stack y preparación del entorno
  antes de que el agente escriba nada, con **caché de dependencias por
  repositorio** en volumen. Sin caché, `pnpm install` se lleva el minuto útil.
- **Servicios auxiliares**: primero servicios comunes precableados en la red
  del job (Postgres y poco más); después, levantar el `docker-compose.yml` que
  el propio repo declare. Esto último exige Docker dentro del contenedor,
  aislado. **Nunca el socket del host**: montarlo equivale a dar root del
  servidor a cualquier repo que revisemos.
- **Herramienta `bash`**: comando, timeout, cwd forzado al workspace, salida
  truncada. Con entorno de verdad, la allowlist de comandos deja de tener
  sentido —no se puede prever qué comando necesita cada repo— y el aislamiento
  lo da el contenedor.
- **Verificación antes del PR**: se ejecutan los comandos de test y lint del
  repo. Un cambio que rompe la suite no abre PR: reintenta o termina en
  `needs_review`. El cuerpo del PR incluye la evidencia de la ejecución. Esa
  es la diferencia entre un bot que genera ruido y uno que genera confianza.
- **Artefactos**: capturas y trazas de Playwright, logs de test, adjuntos al
  job.
- **Concurrencia**: un job pasa de "un proceso" a "un contenedor con base de
  datos y navegador". Los `max_concurrent_jobs` de `PLAN_QUOTAS` hay que
  fijarlos con la RAM del servidor delante, y el planificador debe rechazar o
  encolar cuando no haya sitio.

**Bloqueo conocido**: la máquina de desarrollo no tiene Docker instalado y WSL
no tiene ninguna distribución. F6a no lo necesita; F6b es Docker de principio a
fin. Hay que instalar Docker Desktop (WSL2) o desarrollar esa fase contra el
servidor de casa por SSH.

---

## 5. F6c — Convenciones y skills (diseño acordado)

- **Descubrimiento**: `AGENTS.md`, `CLAUDE.md`, `.claude/` (incluidas sus
  skills), `CONTRIBUTING.md`, `.editorconfig`, configuración de linters. El
  agente debe seguir las normas del repo sin que nadie se las copie a mano.
- **Biblioteca de skills de Vesper**: instrucciones curadas por nosotros,
  versionadas en el repo, activables por tenant, que se inyectan según el
  `task_type`.
- **Prompts por tarea configurables**: los cinco `_TASK_BODIES` de hoy están a
  fuego en el código; pasan a ser editables por el tenant, con los nuestros
  como valor por defecto.
- **Idea a evaluar (no comprometida)**: memoria por repositorio, alimentada por
  los PRs cerrados sin mergear y por los comentarios de review. Es la única
  ventaja que se acumula con el tiempo, pero exige diseñar cómo se distingue
  una lección real de un accidente.

---

## 6. Riesgos y decisiones

| Riesgo | Mitigación |
| --- | --- |
| **La fiabilidad del tool-calling de los modelos abiertos.** Alucinan rutas, se saltan el formato de edición, repiten llamadas. Es el riesgo número uno de toda la fase. | Edición exacta con error devuelto al modelo, breaker de bucles, y evals para medirlo en vez de opinarlo. |
| **Coste sin límite.** Es la política acordada, pero un bug nuestro puede quemar el saldo del tenant. | El breaker corta bucles e inactividad; el coste se muestra en vivo; el aborto manual ya existe. |
| **Ejecución de código ajeno en el servidor (F6b).** Un contenedor no es una VM. | Aceptable mientras los tenants sean conocidos. Abrir el registro público exige VM efímera (Firecracker/gVisor) o runners desechables. Queda escrito, no descubierto. |
| **Prompt injection desde el repo del tenant.** Un `README` puede contener instrucciones dirigidas al agente. | La jaula de rutas y `validate_diff` no dependen de lo que el modelo crea; ningún secreto de Vesper entra en el contexto del agente. |
| **Recursos del servidor casero.** | Concurrencia dimensionada con la RAM real, no con un número inventado. |

### Decisiones tomadas

- Ejecución de comandos: **sí**, con contenedor por job (F6b).
- Proveedores: **cliente OpenAI-compatible + adaptadores**, sin SDK por
  proveedor.
- Transición: **sustitución completa**, sin convivencia con opencode.
- Presupuesto: **sin cuotas**, con circuit breaker.
- Resultado: **siempre PR**, nunca push directo ni auto-merge.
- Modelo de arranque: key directa del proveedor. Recomendación **Kimi K3** por
  su comportamiento en cadenas largas de tool-calling, con GLM 5.2 como
  alternativa barata. La decisión final se toma con la tabla de evals.

### Abierto

- Qué proveedor se da de alta primero (bloquea la validación real de F6a, no su
  desarrollo).
- Docker en la máquina de desarrollo (bloquea F6b).
- Streaming de la respuesta del modelo: F6a no lo usa. Mejoraría la sensación
  de la UI y se decide cuando el hilo de pasos esté en pie.
- Renombrado de `opencode_zen_key` / `opencode_zen_base_url` a nombres
  neutros: Zen pasa a ser un proveedor más. Cambio de `.env`, sin producción
  todavía que romper.
