---
paths:
  - "vesper-backend/src/agents/**"
  - "vesper-backend/src/core/crypto.py"
  - "vesper-backend/src/tenants/**"
  - "vesper-backend/tests/test_byok*"
  - "vesper-frontend/src/schemas/credentials.ts"
  - "vesper-frontend/src/app/settings/**"
---

# Modelos y credenciales — BYOK

## Modelos y credenciales — BYOK

**Cada tenant trae su propia API key** (*bring your own key*) y puede usar
**cualquier proveedor del catálogo de models.dev**: OpenAI, Anthropic, Gemini,
DeepSeek, MiniMax, Kimi, xAI, Groq, Mistral, OpenRouter, la pasarela Zen… 174
en total. No mantenemos ninguna lista: models.dev es la misma fuente que usa
opencode, así que nunca ofrecemos un modelo que el runtime no sepa ejecutar
(`src/agents/catalog.py`, cacheado 24 h, con semilla si el servicio no
responde).
Los modelos `status: "deprecated"` se filtran: `opencode` los oculta y un job con
uno moría con «Model not found» (`deepseek-v4-flash`, renombrado a `deepseek-flash`).

**Los modelos van en formato `proveedor/modelo`** (`opencode-go/glm-5.2`,
`openai/gpt-5`). Sin el prefijo, `split_model` asume `opencode-go`. Defaults en
`src/tenants/constants.py`. El job **usa el modelo configurado por el tenant**.

**`resolve_credentials`** (`src/agents/credentials.py`) es el **punto único**
donde se decide con qué credenciales corre un job: primero las del tenant, y si
no tiene y el operador activó `ALLOW_INSTANCE_KEY_FALLBACK`, la key de la
instancia. Cuando llegue el modelo de plataforma con cuotas por plan, el cambio
entra **ahí y en ningún otro sitio**.

- Las keys se guardan **cifradas** con Fernet (`src/core/crypto.py`); la clave
  maestra es `CREDENTIALS_ENCRYPTION_KEY` y nunca vive en la BD. Perderla
  equivale a perder todas las credenciales.
- La API **nunca** devuelve una key: solo proveedor, etiqueta y los últimos 4
  caracteres. No hay endpoint de lectura.
- **Nunca** incrustes ninguna key en el bundle del frontend.
- No se verifica la key contra el proveedor al guardarla: con 174 proveedores
  no hay forma uniforme de hacerlo. El primer job da el error.

Diseño completo en
[docs/superpowers/specs/2026-07-28-byok-credenciales-por-tenant-design.md](docs/superpowers/specs/2026-07-28-byok-credenciales-por-tenant-design.md).
