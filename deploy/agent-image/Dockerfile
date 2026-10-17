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
 && if [ "$g" != "agent" ]; then groupmod -n agent "$g"; fi \
 && if [ "$u" != "agent" ]; then usermod -l agent -d /home/agent -s /bin/bash "$u"; fi

# pnpm y yarn vía corepack; opencode fijado a la versión que usa Vesper.
# Sin esto el primer pnpm/yarn espera un prompt de descarga y el test muere por timeout.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN npm i -g --unsafe-perm corepack opencode-ai@1.19.0 \
 && corepack enable \
 && npm cache clean --force

# venv de Python para que `pip install -e .` funcione y `pytest` esté listo sin red.
# PATH también en /etc/profile.d: `bash -lc` (login) reconstruye el PATH desde los perfiles y perdería el ENV.
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir pytest \
 && chown -R agent:agent /opt/venv \
 && echo 'export PATH=/opt/venv/bin:$PATH' > /etc/profile.d/venv.sh
ENV PATH=/opt/venv/bin:$PATH \
    VIRTUAL_ENV=/opt/venv

# Dirs que el backend rellena (auth.json de opencode) o monta (caché por tenant).
RUN mkdir -p /workspace /home/agent/.local/share/opencode /home/agent/.cache \
 && chown -R agent:agent /workspace /home/agent

USER agent
WORKDIR /workspace
RUN python -m pytest --version && opencode --version
ENTRYPOINT ["tini", "--"]
CMD ["sleep", "infinity"]
