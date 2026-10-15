from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor de dev usado como default de `jwt_secret` para no romper la suite de
# tests ni el arranque local sin `.env`. Nunca debe llegar a produccion: ver
# `_forbid_dev_secret_in_production` (un runtime real que arranque sin la env
# `JWT_SECRET` fijada quedaria firmando/validando tokens con un secreto
# publico conocido en este repo, permitiendo forjar tokens de tenant_admin).
DEV_JWT_SECRET_DEFAULT = "change-me-in-env-min-32-characters-long!!"

# Igual que el anterior: default de desarrollo para no exigir configuracion al
# clonar el repo, prohibido en produccion. Con este valor conocido, cualquiera
# con un volcado de la BD descifraria las API keys de todos los tenants.
DEV_CREDENTIALS_KEY_DEFAULT = "change-me-credentials-encryption-key-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://vesper:vesper@localhost:55432/vesper_dev", repr=False
    )
    jwt_secret: str = Field(default=DEV_JWT_SECRET_DEFAULT, repr=False)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    environment: str = "development"
    # Registro abierto. Una instancia para uso propio lo cierra (`false`): hasta
    # que cada job corra en su contenedor, el agente de otro tenant podria leer
    # del disco los clones ajenos. La primera cuenta se permite siempre.
    registration_enabled: bool = True

    # Redis (cola de jobs + pub/sub progreso del agente). Vacio = degrada con
    # gracia (sin scheduling ni SSE en vivo). Ver `CLAUDE.md` -> Trampas.
    redis_url: str = ""

    # Allowlist de origenes para `CORSMiddleware` (CSV, p.ej.
    # "https://vesper.example.com"). Vacio = sin CORS abierto, correcto
    # mientras frontend/backend se sirvan desde el mismo origen.
    cors_origins: str = ""

    # Credenciales de IA de los tenants (BYOK). Ver `src/core/crypto.py`.
    credentials_encryption_key: str = Field(default=DEV_CREDENTIALS_KEY_DEFAULT, repr=False)

    # Key de la instancia, para tenants que no han configurado la suya. Solo se
    # usa si el operador enciende el fallback: en una instancia compartida,
    # regalar el saldo propio a desconocidos debe ser una decision consciente.
    opencode_zen_key: str = Field(default="", repr=False)
    opencode_zen_base_url: str = "https://opencode.ai/zen/go/v1"
    allow_instance_key_fallback: bool = False

    # Agent runtime (F4+).
    opencode_bin: str = ""
    opencode_port_pool_start: int = 14096
    # Raiz de los workspaces clonados, uno por (tenant, repo). El default es la
    # ruta del contenedor; en local se apunta a un directorio temporal, porque
    # `/var/...` no existe fuera de Linux.
    workspace_root: str = "/var/workspaces"

    # GitHub App (F3+).
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_private_key: str = Field(default="", repr=False)
    github_app_client_id: str = ""
    github_app_client_secret: str = Field(default="", repr=False)
    github_webhook_secret: str = Field(default="", repr=False)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("github_app_private_key")
    @classmethod
    def _normalize_pem(cls, v: str) -> str:
        """Acepta el PEM con saltos de linea escapados.

        La clave privada de la App es multilinea, y ni una env var de Coolify ni
        una linea de `.env` la aguantan tal cual. Se guarda con `\\n` escapados y
        se restaura aqui; sin esto `jwt.encode(..., RS256)` revienta con un PEM
        de una sola linea.
        """
        if not v:
            return v
        v = v.strip().strip('"').strip("'")
        return v.replace("\\n", "\n")

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET debe tener al menos 32 caracteres")
        return v

    @model_validator(mode="after")
    def _forbid_dev_secret_in_production(self) -> "Settings":
        if self.environment != "production":
            return self
        if self.jwt_secret == DEV_JWT_SECRET_DEFAULT:
            raise ValueError(
                "JWT_SECRET sigue en el valor por defecto de desarrollo con "
                "environment=production. Fija un JWT_SECRET real (>=32 "
                "caracteres) en el entorno de produccion."
            )
        if self.credentials_encryption_key == DEV_CREDENTIALS_KEY_DEFAULT:
            raise ValueError(
                "CREDENTIALS_ENCRYPTION_KEY sigue en el valor por defecto de "
                "desarrollo con environment=production. Con ese valor conocido, "
                "un volcado de la BD basta para descifrar las API keys de todos "
                "los tenants."
            )
        return self


settings = Settings()
