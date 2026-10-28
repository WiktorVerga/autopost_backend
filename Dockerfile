FROM python:3.14-slim-bookworm

# Node.js 22 (per Hyperframes) e ffmpeg
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates ffmpeg \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Prima solo le dipendenze, così Docker riusa la cache se cambia solo il codice
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# Chromium per il rendering HTML → immagine (se usi Playwright)
RUN playwright install --with-deps chromium

EXPOSE 8000
# Migrazioni all'avvio, poi l'API con UN SOLO worker (lo scheduler gira nel processo)
CMD ["sh", "-c", "alembic upgrade head && uvicorn autopost_server.main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'"]