"""GitHub App API client.

Autentica como GitHub App via JWT (RS256), luego intercambia por
installation token (1h). Los tests mockean httpx; nunca se golpea la
API real de GitHub en CI.
"""

from __future__ import annotations

import time

import httpx
from jose import jwt

from src.core.config import settings
from src.core.exceptions import ValidationDomainError

GITHUB_API_URL = "https://api.github.com"
GITHUB_OAUTH_URL = "https://github.com"


async def exchange_oauth_code(code: str, client: httpx.AsyncClient | None = None) -> str:
    """Cambia el `code` del redirect de GitHub por un user access token.

    Es la unica forma de probar QUIEN esta instalando: el `installation_id` que
    llega en el callback es un entero adivinable y por si solo no acredita nada.
    """
    url = f"{GITHUB_OAUTH_URL}/login/oauth/access_token"
    payload = {
        "client_id": settings.github_app_client_id,
        "client_secret": settings.github_app_client_secret,
        "code": code,
    }
    headers = {"Accept": "application/json"}

    async def _post(c: httpx.AsyncClient) -> str:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        # GitHub devuelve 200 con {"error": ...} cuando el code es invalido o
        # ya fue usado; hay que mirar el cuerpo, no solo el status.
        token = data.get("access_token")
        if not token:
            raise ValidationDomainError(
                f"GitHub rechazo el codigo de instalacion: {data.get('error', 'sin detalle')}"
            )
        return token

    if client:
        return await _post(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _post(c)


async def list_user_installations(
    user_token: str, client: httpx.AsyncClient | None = None
) -> list[dict]:
    """Instalaciones de la App a las que accede el usuario del token (paginado)."""
    url = f"{GITHUB_API_URL}/user/installations"
    headers = {
        "Authorization": f"Bearer {user_token}",
        "Accept": "application/vnd.github+json",
    }
    per_page = 100
    installations: list[dict] = []

    async def _list(c: httpx.AsyncClient) -> list[dict]:
        page = 1
        while True:
            r = await c.get(url, headers=headers, params={"per_page": per_page, "page": page})
            r.raise_for_status()
            batch = r.json().get("installations", [])
            installations.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return installations

    if client:
        return await _list(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _list(c)


def _pem_bytes() -> bytes:
    return settings.github_app_private_key.encode() if settings.github_app_private_key else b""


def create_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, _pem_bytes(), algorithm="RS256")


async def get_installation_token(
    installation_id: int, client: httpx.AsyncClient | None = None
) -> str:
    jwt_token = create_app_jwt()
    url = f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
    }

    async def _post(c: httpx.AsyncClient) -> str:
        r = await c.post(url, headers=headers)
        r.raise_for_status()
        return r.json()["token"]

    if client:
        return await _post(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _post(c)


async def list_installation_repos(
    installation_token: str, client: httpx.AsyncClient | None = None
) -> list[dict]:
    """Lista todos los repos accesibles a la instalacion (paginados)."""
    url = f"{GITHUB_API_URL}/installation/repositories"
    headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github+json",
    }
    repos: list[dict] = []
    per_page = 100
    page = 1

    async def _list(c: httpx.AsyncClient) -> list[dict]:
        nonlocal repos, page
        while True:
            r = await c.get(url, headers=headers, params={"per_page": per_page, "page": page})
            r.raise_for_status()
            data = r.json()
            repos.extend(data.get("repositories", []))
            if len(data.get("repositories", [])) < per_page:
                break
            page += 1
        return repos

    if client:
        return await _list(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _list(c)


async def create_pull_request(
    installation_token: str,
    owner: str,
    repo: str,
    head: str,
    base: str,
    title: str,
    body: str,
    client: httpx.AsyncClient | None = None,
) -> dict:
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {installation_token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"title": title, "head": head, "base": base, "body": body}

    async def _post(c: httpx.AsyncClient) -> dict:
        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()

    if client:
        return await _post(client)
    async with httpx.AsyncClient(timeout=30) as c:
        return await _post(c)
