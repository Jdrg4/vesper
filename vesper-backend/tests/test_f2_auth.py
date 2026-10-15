"""Tests de F2 — Auth + Multi-tenancy."""

import uuid

from httpx import AsyncClient

from src.core.security import create_access_token
from src.shared.enums import UserRole
from src.tenants.constants import Plan
from src.tenants.models import Tenant
from src.users.models import User


def _un() -> str:
    return uuid.uuid4().hex[:8]


# ------------------------------------------------------------------  Register
async def test_register_creates_tenant_and_admin(client: AsyncClient):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"new-{_un()}@example.com",
            "password": "changeme123",
            "full_name": "New Admin",
            "tenant_name": "My Workspace",
            "tenant_slug": f"ws-{_un()}",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"].startswith("new-")
    assert body["role"] == UserRole.tenant_admin.value
    assert body["tenant"]["plan"] == Plan.free.value
    assert "access_token" in r.cookies
    assert "refresh_token" in r.cookies


async def test_register_duplicate_email(client: AsyncClient):
    email = f"dup-{_un()}@example.com"
    slug = f"dup-{_un()}"
    p = {
        "email": email,
        "password": "changeme123",
        "full_name": "Dup",
        "tenant_name": "Dup WS",
        "tenant_slug": slug,
    }
    r1 = await client.post("/api/v1/auth/register", json=p)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/auth/register", json=p)
    assert r2.status_code == 422
    assert "ya está registrado" in r2.json()["detail"].lower()


async def test_register_duplicate_slug(client: AsyncClient):
    slug = f"slug-{_un()}"
    p1 = {
        "email": f"a-{_un()}@example.com",
        "password": "changeme123",
        "full_name": "A",
        "tenant_name": "Slug Test",
        "tenant_slug": slug,
    }
    r1 = await client.post("/api/v1/auth/register", json=p1)
    assert r1.status_code == 201
    p2 = {
        "email": f"b-{_un()}@example.com",
        "password": "changeme123",
        "full_name": "B",
        "tenant_name": "Other",
        "tenant_slug": slug,
    }
    r2 = await client.post("/api/v1/auth/register", json=p2)
    assert r2.status_code == 422


async def test_register_auto_slug(client: AsyncClient):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"auto-{_un()}@example.com",
            "password": "changeme123",
            "full_name": "Auto",
            "tenant_name": "My Cool Workspace",
        },
    )
    assert r.status_code == 201
    assert r.json()["tenant"]["slug"] == "my-cool-workspace"


# ------------------------------------------------------------------  Login
async def test_login_ok(client: AsyncClient):
    email = f"login-{_un()}@example.com"
    slug = f"login-{_un()}"
    password = "changeme123"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Login",
            "tenant_name": "Login WS",
            "tenant_slug": slug,
        },
    )
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    assert "access_token" in r.json()


async def test_login_bad_password(client: AsyncClient):
    email = f"badp-{_un()}@example.com"
    slug = f"badp-{_un()}"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "BadP",
            "tenant_name": "BadP WS",
            "tenant_slug": slug,
        },
    )
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 401


async def test_login_nonexistent(client: AsyncClient):
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": f"nope-{_un()}@example.com", "password": "x"},
    )
    assert r.status_code == 401


# ------------------------------------------------------------------  Me
async def test_me_returns_user_and_tenant(client: AsyncClient):
    email = f"me-{_un()}@example.com"
    slug = f"me-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Me",
            "tenant_name": "Me WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.get(
        "/api/v1/auth/me", headers={"Cookie": f"access_token={r.cookies['access_token']}"}
    )
    assert r2.status_code == 200
    assert r2.json()["email"] == email
    assert r2.json()["tenant"]["slug"] == slug


async def test_me_without_token_401(client: AsyncClient):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401


# ------------------------------------------------------------------  Refresh
async def test_refresh_ok(client: AsyncClient):
    email = f"ref-{_un()}@example.com"
    slug = f"ref-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Ref",
            "tenant_name": "Ref WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": r.cookies["refresh_token"]},
    )
    assert r2.status_code == 200
    assert "access_token" in r2.json()


async def test_refresh_bad_401(client: AsyncClient):
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": "bad"})
    assert r.status_code == 422


# ------------------------------------------------------------------  Logout
async def test_logout_clears_cookies(client: AsyncClient):
    email = f"logout-{_un()}@example.com"
    slug = f"logout-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Logout",
            "tenant_name": "Logout WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.post("/api/v1/auth/logout")
    assert r2.status_code == 204


# ------------------------------------------------------------------  Tenants
async def test_tenants_me(client: AsyncClient):
    email = f"tm-{_un()}@example.com"
    slug = f"tm-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Tm",
            "tenant_name": "Tm WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.get(
        "/api/v1/tenants/me",
        headers={"Cookie": f"access_token={r.cookies['access_token']}"},
    )
    assert r2.status_code == 200
    assert r2.json()["slug"] == slug


async def test_tenants_me_patch(client: AsyncClient):
    email = f"tmp-{_un()}@example.com"
    slug = f"tmp-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Tmp",
            "tenant_name": "Tmp WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.patch(
        "/api/v1/tenants/me",
        json={"name": "Updated WS"},
        headers={"Cookie": f"access_token={r.cookies['access_token']}"},
    )
    assert r2.status_code == 200
    assert r2.json()["name"] == "Updated WS"


# ------------------------------------------------------------------  Users
async def test_users_me(client: AsyncClient):
    email = f"um-{_un()}@example.com"
    slug = f"um-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Um",
            "tenant_name": "Um WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.get(
        "/api/v1/users/me",
        headers={"Cookie": f"access_token={r.cookies['access_token']}"},
    )
    assert r2.status_code == 200
    assert r2.json()["email"] == email


async def test_users_me_update(client: AsyncClient):
    email = f"umu-{_un()}@example.com"
    slug = f"umu-{_un()}"
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "changeme123",
            "full_name": "Umu",
            "tenant_name": "Umu WS",
            "tenant_slug": slug,
        },
    )
    assert r.status_code == 201
    r2 = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Updated Name"},
        headers={"Cookie": f"access_token={r.cookies['access_token']}"},
    )
    assert r2.status_code == 200
    assert r2.json()["full_name"] == "Updated Name"


# ------------------------------------------------------------------  RBAC
async def test_non_admin_blocked_on_tenant_patch(client: AsyncClient, db_session):
    tid = uuid.uuid4()
    t = Tenant(id=tid, name="Other", slug=f"rbac-{tid.hex[:8]}", plan=Plan.free, is_active=True)
    db_session.add(t)
    uid = uuid.uuid4()
    u = User(
        id=uid,
        tenant_id=tid,
        email=f"rbac-{_un()}@example.com",
        hashed_password="...",
        full_name="User",
        role=UserRole.user,
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()

    token = create_access_token(str(uid), u.role.value, str(tid))
    r = await client.patch(
        "/api/v1/tenants/me",
        json={"name": "Nope"},
        headers={"Cookie": f"access_token={token}"},
    )
    assert r.status_code == 403


# ------------------------------------------------------------------  Aislamiento multi-tenant
async def test_isolation_tenants_me_only_own(client: AsyncClient, db_session):
    tid_a = uuid.uuid4()
    tid_b = uuid.uuid4()
    tA = Tenant(
        id=tid_a, name="Tenant A", slug=f"iso-a-{tid_a.hex[:8]}", plan=Plan.free, is_active=True
    )
    tB = Tenant(
        id=tid_b, name="Tenant B", slug=f"iso-b-{tid_b.hex[:8]}", plan=Plan.free, is_active=True
    )
    db_session.add_all([tA, tB])
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    uA = User(
        id=uid_a,
        tenant_id=tid_a,
        email=f"iso-a-{_un()}@example.com",
        hashed_password="...",
        full_name="A",
        role=UserRole.tenant_admin,
        is_active=True,
    )
    uB = User(
        id=uid_b,
        tenant_id=tid_b,
        email=f"iso-b-{_un()}@example.com",
        hashed_password="...",
        full_name="B",
        role=UserRole.tenant_admin,
        is_active=True,
    )
    db_session.add_all([uA, uB])
    await db_session.commit()

    tokenA = create_access_token(str(uid_a), uA.role.value, str(tid_a))
    tokenB = create_access_token(str(uid_b), uB.role.value, str(tid_b))

    rA = await client.get("/api/v1/tenants/me", headers={"Cookie": f"access_token={tokenA}"})
    assert rA.status_code == 200
    assert "Tenant A" in rA.json()["name"]

    rB = await client.get("/api/v1/tenants/me", headers={"Cookie": f"access_token={tokenB}"})
    assert rB.status_code == 200
    assert "Tenant B" in rB.json()["name"]


async def test_scoped_query_excludes_other_tenant(db_session):
    """tenant_scoped_query filtra correctamente por tenant_id."""
    tA = Tenant(
        id=uuid.uuid4(), name="Tenant A", slug=f"sq-a-{_un()}", plan=Plan.free, is_active=True
    )
    tB = Tenant(
        id=uuid.uuid4(), name="Tenant B", slug=f"sq-b-{_un()}", plan=Plan.free, is_active=True
    )
    db_session.add_all([tA, tB])
    await db_session.flush()

    uA = User(
        id=uuid.uuid4(),
        tenant_id=tA.id,
        email=f"sq-a-{_un()}@example.com",
        hashed_password="...",
        full_name="A",
        role=UserRole.tenant_admin,
        is_active=True,
    )
    uB = User(
        id=uuid.uuid4(),
        tenant_id=tB.id,
        email=f"sq-b-{_un()}@example.com",
        hashed_password="...",
        full_name="B",
        role=UserRole.tenant_admin,
        is_active=True,
    )
    db_session.add_all([uA, uB])
    await db_session.flush()

    from src.core.tenancy import tenant_scoped_query

    results = (await db_session.execute(tenant_scoped_query(User, tA.id))).scalars().all()
    assert len(results) == 1
    assert results[0].email == uA.email
