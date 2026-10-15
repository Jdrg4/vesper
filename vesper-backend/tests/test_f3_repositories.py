"""Tests de F3 — GitHub App e enrollment de repos.

Nunca se golpea la API real de GitHub: `github_client` se monkeypatchea.
"""

import uuid

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import ForbiddenError, ValidationDomainError
from src.repositories import services
from src.repositories.models import Repository, TenantInstallation
from src.repositories.schemas import CallbackRequest
from src.tenants.models import Tenant

# Referencia a la implementacion real, capturada antes de cualquier monkeypatch.
_REAL_VERIFY = services.verify_installation_ownership

# Cabecera de un PEM de mentira, para los tests de la clave privada de la App.
_CABECERA_PEM = "-----BEGIN RSA PRIVATE KEY-----"  # pragma: allowlist secret


def _un() -> str:
    return uuid.uuid4().hex[:8]


async def _register(client: AsyncClient, prefix: str) -> dict:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{prefix}-{_un()}@example.com",
            "password": "changeme123",
            "full_name": prefix,
            "tenant_name": f"{prefix} WS",
            "tenant_slug": f"{prefix}-{_un()}",
        },
    )
    assert r.status_code == 201, r.text
    return {
        "cookie": f"access_token={r.cookies['access_token']}",
        "tenant_id": uuid.UUID(r.json()["tenant"]["id"]),
    }


async def _make_tenant(db: AsyncSession, prefix: str) -> Tenant:
    tenant = Tenant(name=f"{prefix} WS", slug=f"{prefix}-{_un()}")
    db.add(tenant)
    await db.flush()
    return tenant


@pytest.fixture
def patched_github(monkeypatch):
    """Devuelve un token fijo y una lista de repos configurable."""
    state = {"repos": []}

    async def _fake_token(installation_id, client=None):
        return "ghs_faketoken"

    async def _fake_list(token, client=None):
        return state["repos"]

    monkeypatch.setattr(services, "get_installation_token", _fake_token)
    monkeypatch.setattr(services, "list_installation_repos", _fake_list)
    return state


def _gh_repo(full_name: str, github_id: int, **kw) -> dict:
    return {
        "id": github_id,
        "full_name": full_name,
        "default_branch": kw.get("default_branch", "main"),
        "private": kw.get("private", True),
    }


@pytest.fixture(autouse=True)
def github_app_configured(monkeypatch):
    """La App tiene credenciales OAuth: sin ellas el callback falla cerrado."""
    monkeypatch.setattr(settings, "github_app_client_id", "Iv1.testclientid", raising=False)
    monkeypatch.setattr(settings, "github_app_client_secret", "testsecret", raising=False)


@pytest.fixture(autouse=True)
def skip_ownership_check(monkeypatch):
    """Por defecto la verificacion de propiedad pasa.

    Los tests que la ejercitan piden `owns_installation`, que restaura la
    implementacion real y mockea solo las dos llamadas HTTP a GitHub.
    """

    async def _noop(data):
        return None

    monkeypatch.setattr(services, "verify_installation_ownership", _noop)


@pytest.fixture
def owns_installation(monkeypatch):
    """Simula el intercambio OAuth. Devuelve el set de instalaciones del usuario."""
    owned = {"ids": set()}

    async def _exchange(code, client=None):
        if code == "bad-code":
            raise ValidationDomainError("Codigo OAuth invalido")
        return "gho_usertoken"

    async def _list_user_installations(user_token, client=None):
        return [{"id": i} for i in owned["ids"]]

    monkeypatch.setattr(services, "exchange_oauth_code", _exchange)
    monkeypatch.setattr(services, "list_user_installations", _list_user_installations)
    monkeypatch.setattr(services, "verify_installation_ownership", _REAL_VERIFY)
    return owned


def _callback(installation_id: int, code: str = "good-code") -> CallbackRequest:
    return CallbackRequest(installation_id=installation_id, code=code)


# ------------------------------------------------------------  Instalacion
async def test_store_installation_once_per_tenant(db_session: AsyncSession, owns_installation):
    tenant = await _make_tenant(db_session, "inst")
    owns_installation["ids"] = {1001, 1002}
    await services.store_installation(db_session, tenant, _callback(1001))

    with pytest.raises(ValidationDomainError):
        await services.store_installation(db_session, tenant, _callback(1002))


async def test_installation_of_other_tenant_is_rejected(
    db_session: AsyncSession, owns_installation
):
    """Un tenant no puede reclamar la instalacion de otro.

    Si lo consiguiera, obtendria installation tokens sobre los repos ajenos y
    podria abrir PRs en ellos.
    """
    a = await _make_tenant(db_session, "own-a")
    b = await _make_tenant(db_session, "own-b")
    owns_installation["ids"] = {2001}
    await services.store_installation(db_session, a, _callback(2001))

    with pytest.raises(ValidationDomainError):
        await services.store_installation(db_session, b, _callback(2001))


# --------------------------------------------  Propiedad real de la instalacion
async def test_callback_rejects_installation_the_user_does_not_own(
    db_session: AsyncSession, owns_installation
):
    """El `installation_id` llega en el body y es adivinable (entero secuencial).

    Sin verificarlo contra GitHub, cualquiera podia reclamar la instalacion de
    otra cuenta aun no registrada y obtener installation tokens sobre SUS repos.
    """
    tenant = await _make_tenant(db_session, "notmine")
    owns_installation["ids"] = {999_111}  # el usuario tiene otra instalacion

    with pytest.raises(ForbiddenError):
        await services.store_installation(db_session, tenant, _callback(2500))

    assert await services.get_installation(db_session, tenant.id) is None


async def test_callback_accepts_installation_the_user_owns(
    db_session: AsyncSession, owns_installation
):
    tenant = await _make_tenant(db_session, "mine")
    owns_installation["ids"] = {2600, 999_111}

    inst = await services.store_installation(db_session, tenant, _callback(2600))
    assert inst.installation_id == 2600


async def test_callback_rejects_bad_oauth_code(db_session: AsyncSession, owns_installation):
    tenant = await _make_tenant(db_session, "badcode")
    owns_installation["ids"] = {2700}

    with pytest.raises(ValidationDomainError):
        await services.store_installation(db_session, tenant, _callback(2700, code="bad-code"))


async def test_callback_fails_closed_without_app_credentials(
    db_session: AsyncSession, owns_installation, monkeypatch
):
    """Sin credenciales OAuth no se puede verificar: hay que rechazar, no confiar."""
    monkeypatch.setattr(settings, "github_app_client_id", "", raising=False)
    monkeypatch.setattr(settings, "github_app_client_secret", "", raising=False)
    tenant = await _make_tenant(db_session, "nocreds")
    owns_installation["ids"] = {2800}

    with pytest.raises(ValidationDomainError):
        await services.store_installation(db_session, tenant, _callback(2800))


async def test_callback_requires_oauth_code_in_schema():
    """El `code` es obligatorio: sin el no hay forma de probar la propiedad."""
    with pytest.raises(ValidationError):
        CallbackRequest(installation_id=1)


async def test_get_installation_scoped(db_session: AsyncSession):
    a = await _make_tenant(db_session, "gi-a")
    b = await _make_tenant(db_session, "gi-b")
    await services.store_installation(db_session, a, _callback(3001))

    assert await services.get_installation(db_session, a.id) is not None
    assert await services.get_installation(db_session, b.id) is None


# ------------------------------------------------------------------  Sync
async def test_sync_creates_repositories(db_session: AsyncSession, patched_github):
    tenant = await _make_tenant(db_session, "sync")
    await services.store_installation(db_session, tenant, _callback(4001))
    patched_github["repos"] = [_gh_repo("acme/api", 501), _gh_repo("acme/web", 502)]

    repos = await services.sync_repositories(db_session, tenant)

    assert {r.full_name for r in repos} == {"acme/api", "acme/web"}
    assert all(r.tenant_id == tenant.id for r in repos)
    assert all(r.is_enrolled is False for r in repos)


async def test_sync_updates_existing_repo_without_duplicating(
    db_session: AsyncSession, patched_github
):
    tenant = await _make_tenant(db_session, "resync")
    await services.store_installation(db_session, tenant, _callback(4002))
    patched_github["repos"] = [_gh_repo("acme/api", 601, default_branch="main")]
    await services.sync_repositories(db_session, tenant)

    patched_github["repos"] = [_gh_repo("acme/api-renamed", 601, default_branch="develop")]
    await services.sync_repositories(db_session, tenant)

    rows = (
        (await db_session.execute(select(Repository).where(Repository.github_id == 601)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].full_name == "acme/api-renamed"
    assert rows[0].default_branch == "develop"


async def test_sync_preserves_enrollment(db_session: AsyncSession, patched_github):
    """Re-sincronizar no debe desactivar los repos que el tenant ya vigilaba."""
    tenant = await _make_tenant(db_session, "keep")
    await services.store_installation(db_session, tenant, _callback(4003))
    patched_github["repos"] = [_gh_repo("acme/api", 701)]
    await services.sync_repositories(db_session, tenant)
    await services.toggle_enrollment(
        db_session,
        tenant.id,
        (await db_session.execute(select(Repository).where(Repository.github_id == 701)))
        .scalar_one()
        .id,
        True,
    )

    await services.sync_repositories(db_session, tenant)

    repo = (
        await db_session.execute(select(Repository).where(Repository.github_id == 701))
    ).scalar_one()
    assert repo.is_enrolled is True


async def test_sync_without_installation_raises(db_session: AsyncSession, patched_github):
    tenant = await _make_tenant(db_session, "noinst")
    with pytest.raises(ValidationDomainError):
        await services.sync_repositories(db_session, tenant)


async def test_sync_does_not_touch_other_tenant_repo(db_session: AsyncSession, patched_github):
    """Dos tenants con acceso al MISMO repo de GitHub.

    Pasa cuando alguien instala la App en dos cuentas que comparten un repo (un
    contractor, una org y un fork). El sync del tenant B no puede adueñarse ni
    mutar la fila del tenant A.
    """
    a = await _make_tenant(db_session, "shared-a")
    b = await _make_tenant(db_session, "shared-b")
    await services.store_installation(db_session, a, _callback(5001))
    await services.store_installation(db_session, b, _callback(5002))

    patched_github["repos"] = [_gh_repo("acme/shared", 801, default_branch="main")]
    await services.sync_repositories(db_session, a)

    patched_github["repos"] = [_gh_repo("acme/shared", 801, default_branch="develop")]
    await services.sync_repositories(db_session, b)

    repo_a = (
        await db_session.execute(
            select(Repository).where(Repository.github_id == 801, Repository.tenant_id == a.id)
        )
    ).scalar_one_or_none()
    repo_b = (
        await db_session.execute(
            select(Repository).where(Repository.github_id == 801, Repository.tenant_id == b.id)
        )
    ).scalar_one_or_none()

    assert repo_a is not None, "el repo del tenant A no debe desaparecer"
    assert repo_b is not None, "el tenant B debe tener su propia fila"
    assert repo_a.id != repo_b.id
    assert repo_a.default_branch == "main", "el sync de B no debe mutar la fila de A"
    assert repo_b.default_branch == "develop"


# -------------------------------------------------------------  Enrollment
async def test_toggle_enrollment_scoped(db_session: AsyncSession, patched_github):
    a = await _make_tenant(db_session, "enr-a")
    b = await _make_tenant(db_session, "enr-b")
    await services.store_installation(db_session, a, _callback(6001))
    patched_github["repos"] = [_gh_repo("acme/api", 901)]
    await services.sync_repositories(db_session, a)
    repo = (
        await db_session.execute(select(Repository).where(Repository.github_id == 901))
    ).scalar_one()

    assert await services.toggle_enrollment(db_session, b.id, repo.id, True) is None
    assert await services.toggle_enrollment(db_session, a.id, repo.id, True) is not None


async def test_list_repositories_scoped(db_session: AsyncSession, patched_github):
    a = await _make_tenant(db_session, "lst-a")
    b = await _make_tenant(db_session, "lst-b")
    await services.store_installation(db_session, a, _callback(7001))
    patched_github["repos"] = [_gh_repo("acme/api", 1001), _gh_repo("acme/web", 1002)]
    await services.sync_repositories(db_session, a)

    assert len(await services.list_repositories(db_session, a.id)) == 2
    assert await services.list_repositories(db_session, b.id) == []


async def test_list_repositories_enrolled_filter(db_session: AsyncSession, patched_github):
    tenant = await _make_tenant(db_session, "flt")
    await services.store_installation(db_session, tenant, _callback(7002))
    patched_github["repos"] = [_gh_repo("acme/api", 1101), _gh_repo("acme/web", 1102)]
    await services.sync_repositories(db_session, tenant)
    repo = (
        await db_session.execute(select(Repository).where(Repository.github_id == 1101))
    ).scalar_one()
    await services.toggle_enrollment(db_session, tenant.id, repo.id, True)

    enrolled = await services.list_repositories(db_session, tenant.id, enrolled_only=True)
    assert [r.full_name for r in enrolled] == ["acme/api"]


# ------------------------------------------------------------------  API
async def test_repositories_endpoints_require_auth(client: AsyncClient):
    assert (await client.get("/api/v1/repositories")).status_code == 401
    assert (await client.post("/api/v1/repositories/sync")).status_code == 401
    assert (
        await client.post("/api/v1/repositories/callback", json={"installation_id": 1})
    ).status_code == 401


async def test_list_repos_endpoint_isolated(client: AsyncClient, db_session: AsyncSession):
    a = await _register(client, "api-a")
    b = await _register(client, "api-b")

    db_session.add(TenantInstallation(tenant_id=a["tenant_id"], installation_id=8001))
    await db_session.flush()
    db_session.add(
        Repository(
            tenant_id=a["tenant_id"],
            installation_id=8001,
            github_id=1201,
            full_name="acme/private",
            default_branch="main",
            private=True,
            is_enrolled=True,
        )
    )
    await db_session.commit()

    ra = await client.get("/api/v1/repositories", headers={"Cookie": a["cookie"]})
    rb = await client.get("/api/v1/repositories", headers={"Cookie": b["cookie"]})
    assert [r["full_name"] for r in ra.json()] == ["acme/private"]
    assert rb.json() == []


# ----------------------------------------------  Clave privada de la GitHub App
def test_private_key_acepta_saltos_escapados():
    """El PEM llega en una linea con `\n` escapados y hay que restaurarlo.

    Ni una linea de `.env` ni una env var de Coolify admiten una clave RSA
    multilinea. Si no se deshace el escape, `jwt.encode(..., RS256)` revienta y
    ninguna llamada a GitHub llega a hacerse.
    """
    from src.core.config import Settings

    # Tal cual queda en el `.env`: una sola linea, entre comillas y con los
    # saltos escapados.
    en_una_linea = r'"-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"'  # pragma: allowlist secret  # noqa: E501
    s = Settings(github_app_private_key=en_una_linea)

    assert "\\n" not in s.github_app_private_key, "los saltos deben quedar reales"
    assert s.github_app_private_key.splitlines()[0] == _CABECERA_PEM
    assert len(s.github_app_private_key.splitlines()) == 3


def test_private_key_respeta_un_pem_multilinea_real():
    from src.core.config import Settings

    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"  # pragma: allowlist secret  # noqa: E501
    assert Settings(github_app_private_key=pem).github_app_private_key == pem
