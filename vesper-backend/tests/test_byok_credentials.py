"""Tests de BYOK — credenciales de IA por tenant, catalogo y sandbox.

Ninguno sale a la red: models.dev se monkeypatchea y no se spawnea opencode.
"""

import json
import uuid
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import catalog, credentials
from src.agents.models import TenantCredential
from src.agents.sandbox import AgentSandbox
from src.core.config import settings
from src.core.crypto import CredentialDecryptError, decrypt, encrypt, key_hint
from src.core.exceptions import NotFoundError, ValidationDomainError
from src.tenants.models import Tenant

KEY_A = "sk-tenant-a-secretisima-0001"
KEY_B = "sk-tenant-b-secretisima-0002"


def _un() -> str:
    return uuid.uuid4().hex[:8]


async def _make_tenant(db: AsyncSession, prefix: str) -> Tenant:
    tenant = Tenant(name=f"{prefix} WS", slug=f"{prefix}-{_un()}")
    db.add(tenant)
    await db.flush()
    return tenant


async def _register(client: AsyncClient, prefix: str) -> dict:
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{prefix}-{_un()}@example.com",
            "password": "changeme123",  # pragma: allowlist secret
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


@pytest.fixture(autouse=True)
def catalogo_falso(monkeypatch):
    """Catalogo fijo: los tests no salen a models.dev."""
    catalog.reset_catalog_cache()
    falso = {
        "opencode-go": {"name": "OpenCode Zen", "models": [{"id": "glm-5.2", "name": "GLM 5.2"}]},
        "openai": {"name": "OpenAI", "models": [{"id": "gpt-5", "name": "GPT-5"}]},
        "anthropic": {
            "name": "Anthropic",
            "models": [{"id": "claude-opus-5", "name": "Claude Opus 5"}],
        },
    }

    async def _get_catalog(client=None):
        return falso

    monkeypatch.setattr(catalog, "get_catalog", _get_catalog)
    yield falso
    catalog.reset_catalog_cache()


@pytest.fixture(autouse=True)
def sin_fallback(monkeypatch):
    """Por defecto el fallback de instancia esta apagado, como en produccion."""
    monkeypatch.setattr(settings, "allow_instance_key_fallback", False, raising=False)
    monkeypatch.setattr(settings, "opencode_zen_key", "", raising=False)


# ---------------------------------------------------------------  Cifrado
def test_la_key_no_se_guarda_en_claro():
    cifrada = encrypt(KEY_A)
    assert KEY_A not in cifrada
    assert decrypt(cifrada) == KEY_A


def test_dos_cifrados_de_la_misma_key_son_distintos():
    """Fernet lleva IV: dos filas con la misma key no se delatan entre si."""
    assert encrypt(KEY_A) != encrypt(KEY_A)


def test_descifrar_con_otra_clave_maestra_da_error_de_dominio(monkeypatch):
    """Cambiar CREDENTIALS_ENCRYPTION_KEY no puede reventar con una traza."""
    cifrada = encrypt(KEY_A)
    monkeypatch.setattr(settings, "credentials_encryption_key", "otra-clave-distinta-larga")
    with pytest.raises(CredentialDecryptError):
        decrypt(cifrada)


def test_key_hint_son_los_ultimos_cuatro():
    assert key_hint("sk-abcdefgh1234") == "1234"
    assert key_hint("ab") == "?"


# -----------------------------------------------------------------  CRUD
async def test_guardar_y_recuperar_credencial(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "cred")
    cred = await credentials.upsert_credential(db_session, tenant.id, "openai", KEY_A, "principal")

    assert cred.provider_id == "openai"
    assert cred.key_hint == KEY_A[-4:]
    assert KEY_A not in cred.encrypted_key
    assert await credentials.resolve_credentials(db_session, tenant.id) == {"openai": KEY_A}


async def test_guardar_dos_veces_reemplaza_no_duplica(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "dup")
    await credentials.upsert_credential(db_session, tenant.id, "openai", KEY_A)
    await credentials.upsert_credential(db_session, tenant.id, "openai", KEY_B)

    creds = await credentials.list_credentials(db_session, tenant.id)
    assert len(creds) == 1
    assert await credentials.resolve_credentials(db_session, tenant.id) == {"openai": KEY_B}


async def test_dos_tenants_pueden_usar_el_mismo_proveedor(db_session: AsyncSession):
    """El UNIQUE es (tenant_id, provider_id), nunca global.

    Con un UNIQUE global sobre `provider_id`, el segundo tenant que quisiera
    usar OpenAI se estrellaria. Es la misma leccion que dejo el sync de repos.
    """
    a = await _make_tenant(db_session, "same-a")
    b = await _make_tenant(db_session, "same-b")

    await credentials.upsert_credential(db_session, a.id, "openai", KEY_A)
    await credentials.upsert_credential(db_session, b.id, "openai", KEY_B)

    assert await credentials.resolve_credentials(db_session, a.id) == {"openai": KEY_A}
    assert await credentials.resolve_credentials(db_session, b.id) == {"openai": KEY_B}


async def test_proveedor_desconocido_se_rechaza(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "unknown")
    with pytest.raises(ValidationDomainError):
        await credentials.upsert_credential(db_session, tenant.id, "no-existe", KEY_A)


async def test_key_vacia_se_rechaza(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "empty")
    with pytest.raises(ValidationDomainError):
        await credentials.upsert_credential(db_session, tenant.id, "openai", "   ")


async def test_borrar_credencial(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "del")
    await credentials.upsert_credential(db_session, tenant.id, "openai", KEY_A)
    await credentials.delete_credential(db_session, tenant.id, "openai")

    assert await credentials.list_credentials(db_session, tenant.id) == []


async def test_borrar_credencial_inexistente(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "del2")
    with pytest.raises(NotFoundError):
        await credentials.delete_credential(db_session, tenant.id, "openai")


# ------------------------------------------------  Aislamiento multi-tenant
async def test_un_tenant_no_ve_las_credenciales_de_otro(db_session: AsyncSession):
    a = await _make_tenant(db_session, "iso-a")
    b = await _make_tenant(db_session, "iso-b")
    await credentials.upsert_credential(db_session, a.id, "openai", KEY_A)

    assert await credentials.list_credentials(db_session, b.id) == []


async def test_resolve_de_un_tenant_nunca_devuelve_la_key_de_otro(db_session: AsyncSession):
    a = await _make_tenant(db_session, "res-a")
    b = await _make_tenant(db_session, "res-b")
    await credentials.upsert_credential(db_session, a.id, "openai", KEY_A)
    await credentials.upsert_credential(db_session, b.id, "anthropic", KEY_B)

    resueltas_a = await credentials.resolve_credentials(db_session, a.id)
    assert KEY_B not in resueltas_a.values()
    assert set(resueltas_a) == {"openai"}


async def test_un_tenant_no_borra_la_credencial_de_otro(db_session: AsyncSession):
    a = await _make_tenant(db_session, "delx-a")
    b = await _make_tenant(db_session, "delx-b")
    await credentials.upsert_credential(db_session, a.id, "openai", KEY_A)

    with pytest.raises(NotFoundError):
        await credentials.delete_credential(db_session, b.id, "openai")
    assert len(await credentials.list_credentials(db_session, a.id)) == 1


# -----------------------------------------------------------  Fallback
async def test_sin_credenciales_y_sin_fallback_error_accionable(db_session: AsyncSession):
    tenant = await _make_tenant(db_session, "nofb")
    with pytest.raises(ValidationDomainError) as exc:
        await credentials.resolve_credentials(db_session, tenant.id)
    assert "Ajustes" in str(exc.value)


async def test_fallback_apagado_aunque_haya_key_de_instancia(db_session: AsyncSession, monkeypatch):
    """Tener la key en el entorno no basta: hay que encender el interruptor.

    En una instancia compartida, el operador no puede acabar pagando el consumo
    de desconocidos por descuido.
    """
    monkeypatch.setattr(settings, "opencode_zen_key", "sk-de-la-instancia")
    monkeypatch.setattr(settings, "allow_instance_key_fallback", False)
    tenant = await _make_tenant(db_session, "fb-off")

    with pytest.raises(ValidationDomainError):
        await credentials.resolve_credentials(db_session, tenant.id)


async def test_fallback_encendido_usa_la_key_de_instancia(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "opencode_zen_key", "sk-de-la-instancia")
    monkeypatch.setattr(settings, "allow_instance_key_fallback", True)
    tenant = await _make_tenant(db_session, "fb-on")

    assert await credentials.resolve_credentials(db_session, tenant.id) == {
        "opencode-go": "sk-de-la-instancia"
    }


async def test_la_credencial_del_tenant_gana_al_fallback(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "opencode_zen_key", "sk-de-la-instancia")
    monkeypatch.setattr(settings, "allow_instance_key_fallback", True)
    tenant = await _make_tenant(db_session, "fb-own")
    await credentials.upsert_credential(db_session, tenant.id, "openai", KEY_A)

    assert await credentials.resolve_credentials(db_session, tenant.id) == {"openai": KEY_A}


# --------------------------------------------------------------  Sandbox
def test_el_sandbox_escribe_solo_los_proveedores_del_tenant(tmp_path):
    sandbox = AgentSandbox(tmp_path, "job-1")
    sandbox.setup({"openai": KEY_A, "anthropic": KEY_B})

    guardado = json.loads(sandbox.auth_file.read_text(encoding="utf-8"))
    assert guardado == {
        "openai": {"type": "api", "key": KEY_A},
        "anthropic": {"type": "api", "key": KEY_B},
    }


def test_el_sandbox_redirige_el_directorio_de_datos(tmp_path):
    """Sin esto, opencode usa el `~/.local/share/opencode` del operador: sus
    credenciales personales y una base de sesiones comun a todos los tenants."""
    sandbox = AgentSandbox(tmp_path, "job-2")
    env = sandbox.env()

    assert env["XDG_DATA_HOME"] == str(sandbox.data_dir)
    assert env["XDG_CONFIG_HOME"] == str(sandbox.config_dir)
    # La cache se comparte a proposito: son paquetes descargados, no secretos.
    assert "XDG_CACHE_HOME" not in env


def test_las_credenciales_no_viajan_como_variables_de_entorno(tmp_path):
    """El entorno lo heredan todos los hijos, incluido el codigo del tenant."""
    sandbox = AgentSandbox(tmp_path, "job-3")
    sandbox.setup({"openai": KEY_A})

    assert KEY_A not in json.dumps(sandbox.env())


async def test_el_sandbox_se_borra(tmp_path):
    sandbox = AgentSandbox(tmp_path, "job-4")
    sandbox.setup({"openai": KEY_A})
    assert sandbox.auth_file.exists()

    await sandbox.cleanup()

    assert not sandbox.base.exists(), "la key no puede quedarse en disco"


async def test_cleanup_no_lanza_si_no_hay_nada(tmp_path):
    """Corre en el `finally` del job: si lanza, tapa el resultado real."""
    await AgentSandbox(tmp_path, "job-5").cleanup()


# --------------------------------------------------------------  Catalogo
async def test_el_catalogo_se_recorta():
    """models.dev son 3 MB con precios y limites; al navegador no le hacen falta."""
    crudo = {
        "openai": {
            "name": "OpenAI",
            "env": ["OPENAI_API_KEY"],
            "npm": "@ai-sdk/openai",
            "models": {
                "gpt-5": {"name": "GPT-5", "cost": {"input": 1.25}, "limit": {"context": 400000}}
            },
        },
        "vacio": {"name": "Sin modelos", "models": {}},
    }
    recortado = catalog._trim(crudo)

    assert recortado == {"openai": {"name": "OpenAI", "models": [{"id": "gpt-5", "name": "GPT-5"}]}}
    assert "vacio" not in recortado, "un proveedor sin modelos no sirve de nada"


async def test_el_catalogo_no_rompe_si_models_dev_no_responde(monkeypatch):
    catalog.reset_catalog_cache()
    monkeypatch.undo()  # quitar el catalogo falso: queremos el real con fallo

    async def _boom(request):
        raise httpx.ConnectError("sin red")

    transport = httpx.MockTransport(_boom)
    async with httpx.AsyncClient(transport=transport) as client:
        catalogo = await catalog.get_catalog(client)

    assert catalogo, "debe caer a la semilla, no quedarse vacio"
    assert "opencode-go" in catalogo
    catalog.reset_catalog_cache()


# -----------------------------------------------------------------  API
async def test_la_api_nunca_devuelve_la_key(client: AsyncClient):
    a = await _register(client, "api-key")

    creada = await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A, "label": "principal"},
        headers={"Cookie": a["cookie"]},
    )
    assert creada.status_code == 201, creada.text
    assert KEY_A not in creada.text

    listado = await client.get("/api/v1/agents/credentials", headers={"Cookie": a["cookie"]})
    assert listado.status_code == 200
    assert KEY_A not in listado.text
    assert listado.json()[0]["key_hint"] == KEY_A[-4:]


async def test_credenciales_requieren_autenticacion(client: AsyncClient):
    r = await client.get("/api/v1/agents/credentials")
    assert r.status_code == 401


async def test_un_tenant_no_lista_las_credenciales_de_otro_por_api(client: AsyncClient):
    a = await _register(client, "apix-a")
    b = await _register(client, "apix-b")
    await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.get("/api/v1/agents/credentials", headers={"Cookie": b["cookie"]})
    assert r.status_code == 200
    assert r.json() == []


async def test_un_tenant_no_borra_por_api_la_credencial_de_otro(
    client: AsyncClient, db_session: AsyncSession
):
    a = await _register(client, "apid-a")
    b = await _register(client, "apid-b")
    await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.delete("/api/v1/agents/credentials/openai", headers={"Cookie": b["cookie"]})
    assert r.status_code == 404

    quedan = (
        (
            await db_session.execute(
                select(TenantCredential).where(TenantCredential.tenant_id == a["tenant_id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(quedan) == 1


async def test_los_proveedores_marcan_los_ya_configurados(client: AsyncClient):
    a = await _register(client, "prov")
    await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.get("/api/v1/agents/providers", headers={"Cookie": a["cookie"]})
    assert r.status_code == 200
    por_id = {p["id"]: p for p in r.json()}
    assert por_id["openai"]["configured"] is True
    assert por_id["anthropic"]["configured"] is False
    assert por_id["openai"]["models"] == [{"id": "gpt-5", "name": "GPT-5"}]


async def test_el_catalogo_de_proveedores_no_filtra_entre_tenants(client: AsyncClient):
    a = await _register(client, "provx-a")
    b = await _register(client, "provx-b")
    await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.get("/api/v1/agents/providers", headers={"Cookie": b["cookie"]})
    assert all(not p["configured"] for p in r.json())


# --------------------------------------------------------  Ruta del sandbox
def test_el_sandbox_vive_fuera_del_clon_del_repo(tmp_path):
    """`.runtime/` cuelga de la raiz de workspaces, no del repo clonado.

    Si viviera dentro, `git add -A` lo meteria en el PR del tenant — con la key
    dentro.
    """
    sandbox = AgentSandbox(tmp_path, "job-6")
    repo_clonado = Path(tmp_path) / "tenant-x" / "repo-y"

    assert repo_clonado not in sandbox.base.parents
    assert sandbox.base.parent.name == ".runtime"


# ----------------------------------------  Validacion del modelo del tenant
async def test_no_se_puede_elegir_un_modelo_sin_credencial(client: AsyncClient):
    """Elegir un modelo que no puedes pagar debe fallar AHORA, no dentro del job."""
    a = await _register(client, "mdl-a")

    r = await client.patch(
        "/api/v1/tenants/me",
        json={"developer_model": "openai/gpt-5"},
        headers={"Cookie": a["cookie"]},
    )
    # `ValidationDomainError` -> 422 en este proyecto, no 400.
    assert r.status_code == 422, r.text
    assert "openai" in r.text


async def test_no_se_puede_elegir_un_modelo_inexistente(client: AsyncClient):
    a = await _register(client, "mdl-b")
    await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.patch(
        "/api/v1/tenants/me",
        json={"developer_model": "openai/modelo-que-no-existe"},
        headers={"Cookie": a["cookie"]},
    )
    assert r.status_code == 422


async def test_con_credencial_el_modelo_se_guarda(client: AsyncClient):
    a = await _register(client, "mdl-c")
    await client.put(
        "/api/v1/agents/credentials",
        json={"provider_id": "openai", "api_key": KEY_A},
        headers={"Cookie": a["cookie"]},
    )

    r = await client.patch(
        "/api/v1/tenants/me",
        json={"developer_model": "openai/gpt-5"},
        headers={"Cookie": a["cookie"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["developer_model"] == "openai/gpt-5"


async def test_el_default_del_tenant_lleva_proveedor(client: AsyncClient):
    """`glm-5.2` a secas solo tenia sentido asumiendo Zen."""
    a = await _register(client, "mdl-d")
    r = await client.get("/api/v1/tenants/me", headers={"Cookie": a["cookie"]})
    assert r.json()["developer_model"] == "opencode-go/glm-5.2"
    assert r.json()["reviewer_model"] == "opencode-go/minimax-m3"
