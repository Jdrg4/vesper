"""Cifrado simetrico de credenciales en reposo.

Las API keys de los tenants se guardan cifradas con Fernet (AES-128-CBC +
HMAC). La clave maestra vive en `CREDENTIALS_ENCRYPTION_KEY` y **nunca** en la
base de datos: quien se lleve un volcado de Postgres no se lleva las keys.

Perder la clave maestra equivale a perder todas las credenciales guardadas. Es
el secreto que hay que respaldar.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings
from src.core.exceptions import ValidationDomainError


class CredentialDecryptError(ValidationDomainError):
    """La credencial guardada no se puede descifrar con la clave actual.

    Pasa si `CREDENTIALS_ENCRYPTION_KEY` cambio. Es un error de dominio y no una
    traza de Fernet: al tenant hay que decirle que reconfigure sus credenciales.
    """


def _fernet() -> Fernet:
    """Deriva una clave Fernet valida de la env var.

    Se acepta cualquier cadena razonable en vez de exigir una clave Fernet
    literal: el operador de una instancia self-hosted no tiene por que saber que
    Fernet quiere 32 bytes en base64 urlsafe. SHA-256 normaliza la entrada.
    """
    raw = settings.credentials_encryption_key.encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise CredentialDecryptError(
            "No se pudo descifrar la credencial guardada. Si cambiaste "
            "CREDENTIALS_ENCRYPTION_KEY, hay que volver a introducirla."
        ) from exc


def key_hint(value: str) -> str:
    """Ultimos 4 caracteres, para que el usuario reconozca cual es la key."""
    return value[-4:] if len(value) >= 4 else "?"
