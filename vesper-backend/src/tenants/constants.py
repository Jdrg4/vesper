"""Constantes del dominio `tenants`."""

from enum import StrEnum


class Plan(StrEnum):
    """Planes del SaaS. Define cuotas y modelo premium/free."""

    free = "free"
    pro = "pro"
    enterprise = "enterprise"


# Defaults de modelos por tenant, en formato `proveedor/modelo`. El proveedor
# es obligatorio desde que el tenant puede traer credenciales de cualquier IA:
# sin el, "glm-5.2" solo tenia sentido asumiendo la pasarela Zen.
DEFAULT_DEVELOPER_MODEL = "opencode-go/glm-5.2"
DEFAULT_REVIEWER_MODEL = "opencode-go/minimax-m3"

# Cuotas por plan (F5). `None` es "sin limite": un 0 centinela se lee como
# "cero jobs permitidos", que es justo el fallo que no quieres descubrir en
# produccion. Cuentan JOBS, no gasto en tokens — el coste real lo paga el
# tenant, que trae su propia key (BYOK).
PLAN_QUOTAS: dict[Plan, dict[str, int | None]] = {
    Plan.free: {"max_jobs_per_day": 10, "max_concurrent_jobs": 1},
    Plan.pro: {"max_jobs_per_day": 200, "max_concurrent_jobs": 3},
    Plan.enterprise: {"max_jobs_per_day": None, "max_concurrent_jobs": 10},
}
