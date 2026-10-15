# Imagen del entorno de dev por job (F6b). Trae Node + navegadores de Playwright.
FROM mcr.microsoft.com/playwright:v1.63.0-noble

ENV DEBIAN_FRONTEND=noninteractive

# make/git/tini/curl + Python. El pip del sistema está bloqueado (PEP 668): se usa un venv.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tini git make curl ca-certificates python3 python3-venv python3-pip \
 && rm -rf /var/lib/apt/lists/*

# La imagen base ya trae un usuario con uid 1000 (pwuser; en noble puede ser "ubuntu"):
# se renombra a `agent` en vez de crear un segundo usuario.
RUN u="$(getent passwd 1000 | cut -d: -f1)" \
 && g="$(getent group 1000 | cut -d: -f1)" \
 && groupmod -n agent "$g" \
 && usermod -l agent -d /home/agent -m -s /bin/bash "$u"

# pnpm y yarn vía corepack; opencode fijado a la versión que usa Vesper.
RUN corepack enable \
 && npm i -g opencode-ai@1.19.0 \
 && npm cache clean --force

# venv de Python para que `pip install -e .` funcione. PATH también en /etc/profile.d:
# `bash -lc` (login) reconstruye el PATH desde los perfiles y perdería el ENV.
RUN python3 -m venv /opt/venv \
 && chown -R agent:agent /opt/venv \
 && echo 'export PATH=/opt/venv/bin:$PATH' > /etc/profile.d/venv.sh
ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv

# Dirs que el backend rellena (auth.json de opencode) o monta (caché por tenant).
RUN mkdir -p /workspace /home/agent/.local/share/opencode /home/agent/.cache \
 && chown -R agent:agent /workspace /home/agent

USER agent
WORKDIR /workspace
ENTRYPOINT ["tini", "--"]
CMD ["sleep", "infinity"]
