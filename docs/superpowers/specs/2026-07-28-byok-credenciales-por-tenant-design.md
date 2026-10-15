# BYOK — Credenciales de IA por tenant — Diseño

> **Proyecto:** Vesper — SaaS multi-tenant que vigila los repositorios GitHub de
> cada inquilino y propone Pull Requests autónomos usando `opencode` como
> runtime de agente.
>
> **Este doc:** cada tenant trae sus propias credenciales de IA (*bring your own
> key*) y elige entre cualquier proveedor que soporte el runtime, no solo la
> pasarela Zen. Las credenciales se inyectan por job en un directorio de datos
> aislado, y toda la resolución pasa por un único punto para que el futuro
> modelo de plataforma —key propia con cuotas por tenant— sea un cambio
> localizado y no una reescritura.
>
> **Proceso:** `brainstorming → spec → writing-plans → implementación → review`.
> Este archivo es el **spec**.

---

## 1. Por qué

F4 se cerró con un PR real del bot, pero funcionaba **por accidente**: el
backend arranca `opencode serve` heredando su entorno, y opencode leía las
credenciales personales del desarrollador en `~/.local/share/opencode/auth.json`.

De ahí salen tres problemas:

1. **En producción no hay nadie logueado.** El runtime corre en un contenedor
   por job; ese archivo no existe y ningún job se autenticaría.
2. **No hay noción de "de quién es el gasto".** Todos los tenants consumirían la
   cuenta de quien levantó el proceso.
3. **El estado del runtime está compartido.** Las sesiones de todos los jobs —de
   todos los tenants— van al mismo `opencode.db` (44 MB en la máquina de
   desarrollo al escribir esto), junto al uso personal del desarrollador.

`Settings.opencode_zen_key` existe en `config.py` desde F1 y **no se lee en
ningún sitio**: es un ajuste muerto.

## 2. Decisiones tomadas

| Decisión | Elegido | Motivo |
| --- | --- | --- |
| Propiedad de la key | **Cada tenant la suya** | Modelo de negocio futuro, no presente. Hoy proyecto open source. |
| Tenant sin key | **Fallback opt-in del operador** | Instancia personal: cómodo. Instancia compartida: nadie regala su saldo por accidente. |
| Directorio de datos del runtime | **Uno por job, efímero** | Cierra la decisión pendiente "persistencia de opencode: queremos efímero". |
| Catálogo de proveedores | **models.dev cacheado** | Misma fuente que usa opencode: nunca ofrecemos algo que el runtime no sepa ejecutar. 174 proveedores sin lista que mantener. |
| Transporte de la credencial | **`auth.json` del job** | Ver §4. |

## 3. Modelo de datos

Tabla nueva `tenant_credentials`:

| Columna | Tipo | Nota |
| --- | --- | --- |
| `id` | UUID | `UUIDMixin` |
| `tenant_id` | UUID FK | `TenantMixin` |
| `provider_id` | `String(64)` | id de models.dev: `openai`, `anthropic`, `google`, `deepseek`, `minimax`, `moonshotai`, `opencode-go`… |
| `encrypted_key` | `Text` | Fernet |
| `label` | `String(80)` nullable | Nombre que le pone el tenant ("cuenta del equipo") |
| `key_hint` | `String(8)` | Últimos 4 caracteres, para que el usuario reconozca cuál es |
| `last_used_at` | `DateTime` nullable | Lo escribe el job |
| timestamps | | `TimestampMixin` |

**`UNIQUE (tenant_id, provider_id)`** — por tenant, nunca global. Un UNIQUE
global sobre `provider_id` impediría que dos tenants usaran OpenAI, y la lección
de F3 fue justo esa: la unicidad de identificadores externos es *por tenant*.

### Cifrado

Fernet (`cryptography`, se declara explícita en `requirements.txt` en vez de
depender de la transitiva de `python-jose[cryptography]`).

Clave en `CREDENTIALS_ENCRYPTION_KEY`. Mismo patrón de arranque que
`JWT_SECRET`: si `ENVIRONMENT=production` y falta o sigue en el valor de
desarrollo, **el arranque aborta**. Sin esa clave las credenciales guardadas son
irrecuperables; se documenta como el secreto que hay que respaldar.

La rotación de la clave maestra queda fuera de alcance. Se anota como deuda.

### Lo que la API nunca devuelve

`CredentialRead` expone `provider_id`, `label`, `key_hint`, `last_used_at` y
fechas. **Nunca** `encrypted_key` ni la key en claro. No hay endpoint de lectura
de la credencial: se escribe y se sustituye, no se consulta.

## 4. Resolución de credenciales — el punto único

```python
# src/agents/credentials.py
async def resolve_credentials(db, tenant) -> dict[str, str]:
    """provider_id -> api key, listo para el auth.json del job."""
```

Orden:

1. Credenciales del tenant (scoped con `tenant_scoped_query`).
2. Si no tiene ninguna **y** el operador activó `ALLOW_INSTANCE_KEY_FALLBACK`,
   la key de instancia (`OPENCODE_ZEN_KEY` → proveedor `opencode-go`).
3. Si no, `ValidationDomainError` con un mensaje que le diga al tenant qué le
   falta y dónde configurarlo.

**Todo el sistema pasa por aquí.** El día del modelo de plataforma, la
comprobación de cuota por plan y la key propia entran en esta función y en
ningún otro sitio. Es la razón de que exista como módulo separado y no como un
método de `ReviewService`.

## 5. Inyección en el runtime

### Por qué `auth.json` y no variables de entorno

models.dev declara por proveedor las env vars que lee (`OPENAI_API_KEY`,
`GEMINI_API_KEY`, `MINIMAX_API_KEY`…), y opencode las respeta. Aun así se
descarta: **el entorno lo heredan todos los procesos hijos**, incluidos los
language servers que abre el agente y cualquier script del repositorio del
tenant que se ejecute en el sandbox. Una key en el entorno es legible en
`/proc/<pid>/environ`. El `auth.json` es un archivo bajo nuestro control, con
permisos restringidos, que no se propaga solo.

Tampoco se usa `opencode.json` con `provider.options.apiKey`: mezclaría
credenciales con configuración, y la configuración es lo que querríamos poder
versionar más adelante.

### `AgentSandbox`

Módulo nuevo `src/agents/sandbox.py`. Por job:

```
<workspace_root>/.runtime/<job_id>/
├── data/opencode/auth.json     # solo los proveedores de ESTE tenant, modo 600
└── config/                     # vacío: sin plugins ni skills del operador
```

- Arranca opencode con `XDG_DATA_HOME` y `XDG_CONFIG_HOME` apuntando ahí, y con
  `--pure` para no cargar plugins externos.
- **`XDG_CACHE_HOME` se queda compartido.** Ahí viven los paquetes que opencode
  descarga (pyright y compañía); no contienen secretos y aislarlos obligaría a
  volver a bajarlos en cada job.
- El directorio se borra en el `finally` de `run_job`, con el mismo `_wipe`
  endurecido que se escribió al cerrar F4 (`ignore_errors=True` no borra un clon
  de git en Windows).

Verificado antes de escribir este spec: con `XDG_DATA_HOME` propio,
`opencode providers list` reporta *0 credentials* en vez de las del
desarrollador. El aislamiento funciona.

Efecto colateral buscado: se acaba el `opencode.db` compartido.

## 6. Catálogo de proveedores

Módulo nuevo `src/agents/catalog.py`.

- Descarga `https://models.dev/api.json` (3,2 MB, 174 proveedores).
- Cachea 24 h: Redis si hay `REDIS_URL`, memoria del proceso si no —la misma
  degradación con gracia que el bus de eventos.
- **Recorta antes de servir**: `{provider_id: {name, models: [{id, name}]}}`.
  Los 3 MB no cruzan al navegador.
- Si models.dev no responde, se sirve la última copia. Si nunca se pudo
  descargar, se sirve una semilla mínima incrustada para que la UI no aparezca
  vacía.

Endpoint `GET /api/v1/agents/providers`, autenticado y scoped: marca qué
proveedores tiene ya configurados el tenant.

## 7. Modelos por tenant

`developer_model` y `reviewer_model` pasan a formato `proveedor/modelo`.
`split_model` (en `runner.py`) ya lo entiende: sin barra asume `opencode-go`.

**Migración:** reescribe los valores existentes a `opencode-go/glm-5.2` y
`opencode-go/minimax-m3`. El `downgrade` quita el prefijo. Los defaults de
`tenants/constants.py` se actualizan al formato nuevo.

Al guardar la configuración se valida que el proveedor del modelo elegido tenga
credencial (o que el fallback esté activo y el proveedor sea `opencode-go`).

## 8. UI

Página nueva `/settings`, protegida por el middleware como el resto:

- **Credenciales** — lista de proveedores configurados con su etiqueta y los
  últimos 4 caracteres; añadir (selector de proveedor del catálogo + campo de
  key) y borrar. La key se envía una vez y no se vuelve a mostrar.
- **Modelos** — selectores de developer y reviewer alimentados por el catálogo,
  **filtrados a los proveedores con credencial**. Si el tenant no tiene ninguna,
  el bloque explica que primero hay que añadir una.

Solo `tenant_admin` escribe; el resto de roles ven la página en lectura.

## 9. Errores

| Situación | Comportamiento |
| --- | --- |
| Tenant sin credenciales y sin fallback | El job no llega a arrancar: `failed` con un mensaje accionable, no una traza. |
| Key inválida o sin saldo | El proveedor responde 401/402; el job falla con el mensaje del proveedor, **sin incluir la key**. |
| models.dev caído | Se sirve la caché. La UI nunca se queda en blanco por esto. |
| `CREDENTIALS_ENCRYPTION_KEY` cambiada | Las credenciales existentes dejan de descifrarse: el job falla pidiendo reconfigurarlas, no revienta con una traza de Fernet. |

Regla transversal, ya vigente en el runner: **el valor de una credencial nunca
se loguea ni se propaga a `error_message`**.

## 10. Tests

Obligatorios antes de implementar (TDD), con especial peso en aislamiento:

**Aislamiento multi-tenant**
- El tenant B no lee, no lista, no borra ni usa las credenciales de A.
- `resolve_credentials` de A nunca devuelve una key de B.
- El `auth.json` de un job contiene **solo** los proveedores de su tenant.

**Cifrado**
- Lo persistido en la columna no contiene la key en claro.
- Round-trip cifrar/descifrar.
- Ninguna respuesta de la API contiene la key.

**Sandbox**
- El directorio del job se crea con el `auth.json` esperado y **se borra al
  terminar**, también cuando el job falla.
- El runner recibe `XDG_DATA_HOME`/`XDG_CONFIG_HOME` propios y `--pure`.
- `XDG_CACHE_HOME` **no** se aísla.

**Fallback**
- Apagado y sin credenciales → error de dominio con mensaje accionable.
- Encendido → usa la key de instancia y el job arranca.
- Encendido pero el tenant tiene la suya → gana la del tenant.

**Catálogo**
- models.dev caído → se sirve la caché; sin caché → semilla; nunca excepción.
- La respuesta recortada no arrastra los 3 MB.

**Migración**
- `upgrade → downgrade → upgrade` limpio y `alembic check` sin drift.
- Los valores existentes quedan con el prefijo correcto.

## 11. Fuera de alcance

Cuotas y facturación; rotación de la clave maestra; credenciales por
repositorio; y **verificación de la key contra el proveedor al guardarla**.

Esta última se excluye a propósito: con 174 proveedores no hay una forma
uniforme de comprobar una credencial, y una verificación que funcione bien en
OpenAI y mienta en los demás es peor que no tenerla. El primer job da un error
claro. Un botón "Probar credencial" que gaste un token queda como mejora
posterior.

## 12. Deuda que este diseño reconoce

- **Rotación de `CREDENTIALS_ENCRYPTION_KEY`.** Hoy cambiarla inutiliza todas
  las credenciales guardadas. Una columna `key_version` permitiría rotar sin
  cortar; no se añade hasta que haga falta.
- **La key sigue apareciendo en el `auth.json` en disco** durante el job. Es el
  mínimo inevitable para que el runtime la use; refuerza que el sandbox por job
  es obligatorio, no opcional.
- **Sin límite de gasto por tenant.** Un tenant puede quemar su propia cuenta;
  es su key y su decisión, pero cuando exista el modelo de plataforma habrá que
  frenar antes.
