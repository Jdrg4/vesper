from src.core.config import Settings

SECRETOS = {
    "database_url": "postgresql://u:clave-bd-secreta@db/v",  # pragma: allowlist secret
    "jwt_secret": "jwt-secreto-de-al-menos-32-caracteres!!",  # pragma: allowlist secret
    "credentials_encryption_key": "clave-de-cifrado-secreta",  # pragma: allowlist secret
    "opencode_zen_key": "zen-key-secreta",  # pragma: allowlist secret
    "github_app_private_key": "clave-privada-de-la-app-secreta",  # pragma: allowlist secret
    "github_app_client_secret": "client-secret-secreto",  # pragma: allowlist secret
    "github_webhook_secret": "webhook-secret-secreto",  # pragma: allowlist secret
}


def test_el_repr_de_settings_no_vuelca_secretos():
    """Pydantic incluye todos los campos en `repr`, y cualquier traza o log que
    imprima `settings` (un AttributeError sobre el objeto, sin ir mas lejos)
    volcaba la clave privada de la GitHub App y el resto de secretos."""
    texto = repr(Settings(_env_file=None, **SECRETOS)) + str(Settings(_env_file=None, **SECRETOS))

    for campo, valor in SECRETOS.items():
        assert valor not in texto, f"{campo} aparece en el repr"
