# Anfitrión de jobs (F6b)

Prepara una máquina Ubuntu 24.04 para correr un contenedor de desarrollo por job de Vesper.
Es un anfitrión **separado** del backend: el worker le habla a su Docker por TCP+TLS.

## Qué hace `setup.sh`

- Instala Docker y `iptables-persistent` si faltan.
- Genera una CA, un cert de servidor (SAN = las IPs que le pasas) y un cert de cliente.
- Configura `dockerd` con `tlsverify` escuchando en `tcp://<ip>:2376` solo en las IPs que le pasas (`/etc/docker/daemon.json` +
  override de systemd que quita `-H fd://`) y DNS públicos (`1.1.1.1`, `9.9.9.9`) para los
  contenedores, porque el resolver del anfitrión (router o MagicDNS) queda bloqueado.
- Crea la red `vesper-jobs` (`172.30.0.0/16`, bridge `vesper-jobs0`, sin comunicación
  entre contenedores). Reglas `DOCKER-USER`: salen a internet pero se bloquean `10.0.0.0/8`,
  `172.16.0.0/12`, `192.168.0.0/16`, `100.64.0.0/10` y `169.254.0.0/16`. Regla `INPUT`: los
  jobs no alcanzan al propio anfitrión. Todo persistido con `iptables-persistent`.
  Si `vesper-jobs` ya existe con otras opciones, aborta y pide eliminarla.
- Construye la imagen `vesper-agent:1` desde `deploy/agent-image/`.

Es idempotente: se puede volver a correr (no regenera certs existentes).

## Ejecutarlo

```bash
sudo ./deploy/jobs-host/setup.sh <ip-lan-o-tailscale> [<otra-ip> ...]
```

Al final imprime la carpeta con `ca.pem`, `cert.pem` y `key.pem`.

## Comprobar el bloqueo

Cada bloqueo se prueba contra algo que **sí responde** desde el anfitrión; si no, "falla"
no distingue bloqueado de inexistente.

```bash
LAN=<ip-de-un-equipo-de-la-LAN-que-responda>
HOST=<ip-del-anfitrión>

# 1. LAN: responde desde el anfitrión y NO desde un contenedor
curl -m3 -sI http://$LAN                                                        # debe responder
docker run --rm --network vesper-jobs vesper-agent:1 curl -m3 -sI http://$LAN   # debe fallar

# 2. Anfitrión: el contenedor no alcanza sus propios servicios (p. ej. el 2376)
docker run --rm --network vesper-jobs vesper-agent:1 curl -m3 -sk https://$HOST:2376   # debe fallar

# 3. Entre contenedores (otro tenant): debe fallar
docker run -d --rm --name a --network vesper-jobs vesper-agent:1 sleep 60
A=$(docker inspect -f '{{.NetworkSettings.Networks.vesper-jobs.IPAddress}}' a)
docker run --rm --network vesper-jobs vesper-agent:1 curl -m3 -s http://$A      # debe fallar
docker rm -f a

# 4. Internet y DNS: debe funcionar
docker run --rm --network vesper-jobs vesper-agent:1 curl -m5 -sI https://pypi.org
```

Si algún "debe fallar" responde, revisa `iptables -S DOCKER-USER` e `iptables -S INPUT`.

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
- El firewall del anfitrión son reglas `iptables` persistidas: `setup.sh` aborta si hay `ufw`
  instalado (`iptables-persistent` lo desinstalaría).
- `key.pem` y `ca-key.pem` (en `/etc/docker/certs`) son secretos: no van al repo.
