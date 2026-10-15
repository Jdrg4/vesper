# Anfitrión de jobs (F6b)

Prepara una máquina Ubuntu 24.04 para correr un contenedor de desarrollo por job de Vesper.
Es un anfitrión **separado** del backend: el worker le habla a su Docker por TCP+TLS.

## Qué hace `setup.sh`

- Instala Docker y `iptables-persistent` si faltan.
- Genera una CA, un cert de servidor (SAN = las IPs que le pasas) y un cert de cliente.
- Configura `dockerd` en `tcp://0.0.0.0:2376` con `tlsverify` (`/etc/docker/daemon.json` +
  override de systemd que quita `-H fd://`).
- Crea la red `vesper-jobs` (`172.30.0.0/16`) y reglas `DOCKER-USER`: los contenedores salen
  a internet pero se bloquean `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
  `100.64.0.0/10` y `169.254.0.0/16` (salvo la propia red de jobs). Persistidas.
- Construye la imagen `vesper-agent:1` desde `deploy/agent-image/`.

Es idempotente: se puede volver a correr (no regenera certs existentes).

## Ejecutarlo

```bash
sudo ./deploy/jobs-host/setup.sh <ip-lan-o-tailscale> [<otra-ip> ...]
```

Al final imprime la carpeta con `ca.pem`, `cert.pem` y `key.pem`.

## Comprobar el bloqueo

```bash
# Debe FALLAR (LAN bloqueada):
docker run --rm --network vesper-jobs vesper-agent:1 curl -m3 http://192.168.2.1
# Debe FUNCIONAR (internet y DNS):
docker run --rm --network vesper-jobs vesper-agent:1 curl -m5 -sI https://pypi.org
```

Si el primero responde, las reglas no están activas: revisa `iptables -S DOCKER-USER`.

## Dar los certs al worker

Copia `ca.pem`, `cert.pem` y `key.pem` a una carpeta del worker (permisos `600` en la key) y
define:

```bash
DOCKER_HOST=tcp://<ip-del-anfitrión>:2376
DOCKER_TLS_VERIFY=1
DOCKER_CERT_PATH=/ruta/a/los/certs
```

## Seguridad

- **Nunca expongas el 2376 a internet**: quien tenga un cert de cliente es root del anfitrión.
  Solo LAN o Tailscale (firewall del anfitrión incluido).
- `key.pem` y `ca-key.pem` (en `/etc/docker/certs`) son secretos: no van al repo.
