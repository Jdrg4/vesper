"""Crea la GitHub App de Vesper con el *manifest flow* y escribe el `.env`.

Cada instalacion de Vesper (la tuya, la de cualquiera que lo self-hostee)
necesita SU propia GitHub App. Hacerlo a mano son ~10 campos, generar una clave
privada, descargar el `.pem` y copiar el client secret antes de que GitHub lo
esconda: mucho sitio donde equivocarse.

El manifest flow lo reduce a un clic. Este script:

1. Levanta un servidor local efimero.
2. Abre el navegador con un formulario que ya lleva el manifest (permisos,
   eventos, callback URLs, OAuth en la instalacion...) y se autoenvia.
3. Tu pulsas "Create GitHub App" en github.com.
4. GitHub redirige aqui con un `code` de un solo uso.
5. El script lo canjea por app id, slug, clave privada RSA, client id, client
   secret y webhook secret, y los escribe en `.env` (que esta gitignoreado).

Los secretos NUNCA se imprimen en pantalla ni se loguean.

    .venv\\Scripts\\python.exe scripts\\create_github_app.py --name "Vesper Bot"
"""

from __future__ import annotations

import argparse
import html
import json
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV = BACKEND_DIR / ".env"

GITHUB_API = "https://api.github.com"

# Lo minimo para el trabajo de Vesper:
#   contents:write      clonar y empujar la rama con los cambios del agente
#   pull_requests:write abrir el PR
#   metadata:read       obligatorio siempre que se pide cualquier otro permiso
PERMISSIONS = {
    "contents": "write",
    "pull_requests": "write",
    "metadata": "read",
}

# Declarados ya para F5 (cron + webhook). El webhook nace desactivado: en local
# no hay URL publica que reciba nada.
EVENTS = ["push", "pull_request"]


def build_manifest(
    name: str,
    frontend_urls: list[str],
    redirect_url: str,
    webhook_url: str,
    webhook_active: bool,
) -> dict:
    return {
        "name": name,
        "url": "https://github.com/Jdrg4/vesper",
        "description": (
            "Vesper revisa tus repositorios de forma continua y abre Pull "
            "Requests con las mejoras que propone."
        ),
        "public": False,
        # Adonde vuelve GitHub tras crear la App (este script).
        "redirect_url": redirect_url,
        # Adonde vuelve el usuario tras INSTALAR la App (el frontend).
        "callback_urls": frontend_urls,
        "setup_url": frontend_urls[0],
        # Sin esto el redirect de instalacion no trae `code` y el backend no
        # puede verificar quien es el dueño de la instalacion: rechaza el
        # callback y el enrollment nunca funciona.
        "request_oauth_on_install": True,
        "setup_on_update": True,
        "default_permissions": PERMISSIONS,
        "default_events": EVENTS,
        "hook_attributes": {"url": webhook_url, "active": webhook_active},
    }


def form_page(manifest: dict, state: str, org: str | None) -> bytes:
    """HTML que se autoenvia a GitHub con el manifest."""
    action = (
        f"https://github.com/organizations/{org}/settings/apps/new?state={state}"
        if org
        else f"https://github.com/settings/apps/new?state={state}"
    )
    manifest_json = html.escape(json.dumps(manifest), quote=True)
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Creando la GitHub App de Vesper</title></head>
<body style="font-family: system-ui; padding: 2rem">
  <p>Redirigiendo a GitHub para crear la App...</p>
  <form id="f" action="{action}" method="post">
    <input type="hidden" name="manifest" value="{manifest_json}">
    <noscript><button type="submit">Continuar a GitHub</button></noscript>
  </form>
  <script>document.getElementById('f').submit()</script>
</body></html>""".encode()


def result_page(title: str, message: str) -> bytes:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body style="font-family: system-ui; padding: 2rem; max-width: 40rem">
  <h1>{html.escape(title)}</h1>
  <p>{html.escape(message)}</p>
  <p style="color:#666">Ya puedes cerrar esta pestaña y volver a la terminal.</p>
</body></html>""".encode()


def convert_manifest(code: str) -> dict:
    """Canjea el `code` del manifest por las credenciales de la App.

    El `code` caduca en una hora y es de un solo uso.
    """
    r = httpx.post(
        f"{GITHUB_API}/app-manifests/{code}/conversions",
        headers={"Accept": "application/vnd.github+json"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def upsert_env(path: Path, values: dict[str, str]) -> None:
    """Escribe/actualiza claves en un `.env` sin tocar el resto del archivo."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("#") else ""
        if key in pending:
            out.append(f"{key}={pending.pop(key)}")
        else:
            out.append(line)
    if pending:
        if out and out[-1].strip():
            out.append("")
        out.append("# --- GitHub App (generado por scripts/create_github_app.py) ---")
        out.extend(f"{k}={v}" for k, v in pending.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    # Inyectados por `run`.
    manifest: dict
    state: str
    org: str | None
    env_file: Path
    result: dict | None = None
    done: threading.Event

    def log_message(self, *args) -> None:  # noqa: A002 - silenciar el log por request
        pass

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - firma de BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, form_page(_Handler.manifest, _Handler.state, _Handler.org))
            return
        if parsed.path != "/callback":
            self._send(404, result_page("No encontrado", "Ruta desconocida."))
            return

        params = parse_qs(parsed.query)
        code = (params.get("code") or [""])[0]
        state = (params.get("state") or [""])[0]

        # El `state` ata este redirect a la peticion que abrio el script; sin
        # comprobarlo, cualquier pagina abierta en el navegador podria empujar
        # su propio `code` a este puerto local y hacernos guardar credenciales
        # de una App ajena.
        if not secrets.compare_digest(state, _Handler.state):
            self._send(400, result_page("Estado invalido", "El parametro `state` no coincide."))
            return
        if not code:
            self._send(400, result_page("Sin codigo", "GitHub no devolvio ningun `code`."))
            return

        try:
            data = convert_manifest(code)
        except httpx.HTTPError as exc:
            self._send(502, result_page("Error al canjear el codigo", str(exc)))
            _Handler.done.set()
            return

        upsert_env(
            _Handler.env_file,
            {
                "GITHUB_APP_ID": str(data["id"]),
                "GITHUB_APP_SLUG": data["slug"],
                # El PEM es multilinea; se guarda escapado y `config.py` lo
                # restaura (una env var de Coolify tampoco admite saltos).
                "GITHUB_APP_PRIVATE_KEY": '"' + data["pem"].replace("\n", "\\n") + '"',
                "GITHUB_APP_CLIENT_ID": data["client_id"],
                "GITHUB_APP_CLIENT_SECRET": data["client_secret"],
                "GITHUB_WEBHOOK_SECRET": data["webhook_secret"],
            },
        )
        _Handler.result = data
        self._send(
            200,
            result_page(
                "GitHub App creada",
                f"«{data['name']}» quedo lista y sus credenciales se guardaron en .env.",
            ),
        )
        _Handler.done.set()


def run(args: argparse.Namespace) -> int:
    redirect_url = f"http://localhost:{args.port}/callback"
    frontend_urls = [u.rstrip("/") + "/repositories" for u in args.frontend_url]

    _Handler.manifest = build_manifest(
        args.name,
        frontend_urls,
        redirect_url,
        args.webhook_url,
        args.webhook_active,
    )
    _Handler.state = secrets.token_urlsafe(24)
    _Handler.org = args.org
    _Handler.env_file = Path(args.env_file)
    _Handler.done = threading.Event()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    start_url = f"http://localhost:{args.port}/"
    print(f"App:        {args.name}")
    print(f"Permisos:   {', '.join(f'{k}:{v}' for k, v in PERMISSIONS.items())}")
    print(f"Eventos:    {', '.join(EVENTS)}")
    print(f"Callbacks:  {', '.join(frontend_urls)}")
    print(f"Destino:    {args.org or 'tu cuenta personal'}")
    print(f"\nAbre esto y pulsa «Create GitHub App»:\n  {start_url}\n")
    webbrowser.open(start_url)

    if not _Handler.done.wait(timeout=args.timeout):
        print(f"Se agoto la espera ({args.timeout}s) sin recibir el callback de GitHub.")
        server.shutdown()
        return 1

    server.shutdown()
    data = _Handler.result
    if data is None:
        print("La creacion fallo. Revisa la pestaña del navegador.")
        return 1

    # Solo datos publicos: ni el PEM ni los secretos se imprimen.
    print("Listo.")
    print(f"  app_id:  {data['id']}")
    print(f"  slug:    {data['slug']}")
    print(f"  url:     {data['html_url']}")
    print(f"\nCredenciales escritas en {_Handler.env_file} (gitignoreado).")
    print(f"Instala la App en tus repos: {data['html_url']}/installations/new")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--name", required=True, help="Nombre de la App (unico en todo GitHub)")
    p.add_argument(
        "--frontend-url",
        action="append",
        default=None,
        help="Origen del frontend; repetible. Default: localhost:3100 y localhost:3000",
    )
    p.add_argument(
        "--org", default=None, help="Crear la App en una organizacion en vez de tu cuenta"
    )
    p.add_argument("--port", type=int, default=8765, help="Puerto del servidor local efimero")
    p.add_argument("--env-file", default=str(DEFAULT_ENV))
    p.add_argument(
        "--webhook-url",
        default="https://example.com/api/v1/webhooks/github",
        help="URL de webhooks (F5). Se puede cambiar despues en los ajustes de la App",
    )
    p.add_argument("--webhook-active", action="store_true", help="Activar el webhook al crearla")
    p.add_argument("--timeout", type=int, default=600, help="Segundos de espera al callback")
    args = p.parse_args()
    if not args.frontend_url:
        args.frontend_url = ["http://localhost:3100", "http://localhost:3000"]
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
