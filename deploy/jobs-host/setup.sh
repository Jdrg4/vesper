#!/usr/bin/env bash
# Prepara el anfitrión de jobs de Vesper (Ubuntu 24.04, como root). Idempotente.
# Uso: sudo ./setup.sh <ip-del-anfitrión> [<otra-ip> ...]   (las IPs van al SAN del cert)
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Ejecuta como root" >&2; exit 1; }
[ "$#" -ge 1 ] || { echo "Uso: $0 <ip> [<ip> ...]" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NET=vesper-jobs
SUBNET=172.30.0.0/16
CERTS=/etc/docker/certs
CLIENT_CERTS=/root/vesper-docker-client
IMAGE=vesper-agent:1
BRIDGE=vesper-jobs0   # nombre fijo del bridge: las reglas INPUT lo referencian

# iptables-persistent desinstala ufw en Ubuntu: no se pisa un firewall ajeno en silencio.
if dpkg -s ufw >/dev/null 2>&1; then
  echo "ufw está instalado y chocaría con iptables-persistent (apt lo desinstalaría)." >&2
  echo "Este anfitrión se protege con reglas iptables persistidas: quita ufw y reintenta." >&2
  exit 1
fi

# --- Docker + persistencia de iptables ---
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
echo iptables-persistent iptables-persistent/autosave_v4 boolean false | debconf-set-selections
echo iptables-persistent iptables-persistent/autosave_v6 boolean false | debconf-set-selections
apt-get install -y --no-install-recommends iptables-persistent openssl

# --- TLS: CA + servidor + cliente (solo si no existen) ---
mkdir -p "$CERTS" "$CLIENT_CERTS"
if [ ! -f "$CERTS/ca.pem" ]; then
  umask 077
  san="DNS:localhost,IP:127.0.0.1"
  for ip in "$@"; do san="$san,IP:$ip"; done
  openssl genrsa -out "$CERTS/ca-key.pem" 4096
  openssl req -new -x509 -days 3650 -key "$CERTS/ca-key.pem" -sha256 \
    -subj "/CN=vesper-jobs-ca" -out "$CERTS/ca.pem"
  # servidor
  openssl genrsa -out "$CERTS/server-key.pem" 4096
  openssl req -new -key "$CERTS/server-key.pem" -subj "/CN=vesper-jobs-host" -out "$CERTS/server.csr"
  printf 'subjectAltName=%s\nextendedKeyUsage=serverAuth\n' "$san" > "$CERTS/server-ext.cnf"
  openssl x509 -req -days 3650 -sha256 -in "$CERTS/server.csr" -CA "$CERTS/ca.pem" \
    -CAkey "$CERTS/ca-key.pem" -CAcreateserial -out "$CERTS/server-cert.pem" -extfile "$CERTS/server-ext.cnf"
  # cliente (el worker)
  openssl genrsa -out "$CERTS/key.pem" 4096
  openssl req -new -key "$CERTS/key.pem" -subj "/CN=vesper-worker" -out "$CERTS/client.csr"
  printf 'extendedKeyUsage=clientAuth\n' > "$CERTS/client-ext.cnf"
  openssl x509 -req -days 3650 -sha256 -in "$CERTS/client.csr" -CA "$CERTS/ca.pem" \
    -CAkey "$CERTS/ca-key.pem" -CAcreateserial -out "$CERTS/cert.pem" -extfile "$CERTS/client-ext.cnf"
  rm -f "$CERTS"/*.csr "$CERTS"/*.cnf
  umask 022
fi
chmod 600 "$CERTS"/*key.pem
cp "$CERTS/ca.pem" "$CERTS/cert.pem" "$CERTS/key.pem" "$CLIENT_CERTS/"
chmod 600 "$CLIENT_CERTS/key.pem"

# --- dockerd en TCP 2376 con tlsverify ---
# Escucha solo en las IPs indicadas (nunca 0.0.0.0) + el socket unix.
hosts='"unix:///var/run/docker.sock"'
for ip in "$@"; do hosts="$hosts, \"tcp://$ip:2376\""; done
# dns públicos: el resolver embebido reenvía a los upstreams del anfitrión (router LAN o
# MagicDNS de Tailscale), que caen en los DROP de abajo y romperían toda resolución.
cat > /etc/docker/daemon.json <<JSON
{
  "tls": true,
  "tlsverify": true,
  "tlscacert": "$CERTS/ca.pem",
  "tlscert": "$CERTS/server-cert.pem",
  "tlskey": "$CERTS/server-key.pem",
  "dns": ["1.1.1.1", "9.9.9.9"],
  "hosts": [$hosts]
}
JSON
# El unit trae `-H fd://`; con "hosts" en daemon.json dockerd se niega a arrancar si no se quita.
mkdir -p /etc/systemd/system/docker.service.d
cat > /etc/systemd/system/docker.service.d/override.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/usr/bin/dockerd --containerd=/run/containerd/containerd.sock
UNIT
systemctl daemon-reload
systemctl enable docker
systemctl restart docker

# --- Red de jobs ---
# enable_icc=false: un job no alcanza a otro (aislamiento entre tenants).
if docker network inspect "$NET" >/dev/null 2>&1; then
  actual="$(docker network inspect "$NET" -f '{{(index .IPAM.Config 0).Subnet}} {{index .Options "com.docker.network.bridge.name"}} {{index .Options "com.docker.network.bridge.enable_icc"}}')"
  if [ "$actual" != "$SUBNET $BRIDGE false" ]; then
    echo "La red $NET ya existe con otras opciones ($actual)." >&2
    echo "Elimínala (docker network rm $NET, sin jobs corriendo) y reintenta." >&2
    exit 1
  fi
else
  docker network create --subnet "$SUBNET" \
    -o com.docker.network.bridge.name="$BRIDGE" \
    -o com.docker.network.bridge.enable_icc=false "$NET"
fi

# --- Reglas: los jobs salen a internet pero no a la LAN, Tailscale, metadata ni al anfitrión ---
# DNS: con "dns" fijo en daemon.json las consultas salen a 1.1.1.1/9.9.9.9 por FORWARD (permitido);
# el 127.0.0.11 vive dentro del netns del contenedor y no pasa por estas reglas.
add_rule() { local chain=$1; shift; iptables -C "$chain" "$@" 2>/dev/null || iptables -I "$chain" "$@"; }
# -I antepone: se insertan en orden inverso para que ESTABLISHED quede antes que los DROP.
# No hay ACCEPT hacia la propia red: container-container también queda bloqueado (172.16.0.0/12).
for dst in 169.254.0.0/16 100.64.0.0/10 192.168.0.0/16 172.16.0.0/12 10.0.0.0/8; do
  add_rule DOCKER-USER -s "$SUBNET" -d "$dst" -j DROP
done
add_rule DOCKER-USER -s "$SUBNET" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# Tráfico hacia el propio anfitrión (cadena INPUT, no FORWARD): sshd, dockerd 2376, etc.
add_rule INPUT -i "$BRIDGE" -m conntrack ! --ctstate ESTABLISHED,RELATED -j DROP
netfilter-persistent save

# --- Imagen del agente ---
docker build -t "$IMAGE" "$REPO_DIR/deploy/agent-image"

echo
echo "Listo. Certificados de cliente para el worker (DOCKER_CERT_PATH=$CLIENT_CERTS):"
ls -1 "$CLIENT_CERTS"/{ca,cert,key}.pem
echo "Cópialos al worker por un canal seguro; key.pem es secreta."
