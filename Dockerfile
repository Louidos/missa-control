# syntax=docker/dockerfile:1
#
# Missa Control – ein Image mit Backend und gebauter Oberfläche.
# Es werden bewusst nur einzelne Ordner kopiert (kein "COPY . ."), damit weder
# `.env` noch `data/` oder lokale `node_modules` je im Image landen können.

# ---------- Stufe 1: Oberfläche bauen ----------
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/public ./public
COPY frontend/src ./src
RUN npm run build

# ---------- Stufe 2: Python-Umgebung bauen ----------
FROM python:3.12-slim AS backend
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir "uv>=0.9,<1.0"
WORKDIR /build
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---------- Stufe 3: Laufzeit ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp \
    MISSA_CONTROL_HOST=0.0.0.0 \
    MISSA_CONTROL_PORT=8090 \
    MISSA_CONTROL_DATA_DIR=/data \
    MISSA_CONTROL_FRONTEND_DIR=/app/frontend \
    MISSA_CONTROL_INTEGRATIONS_DIR=/app/integrations
RUN groupadd --gid 10001 missa \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin missa \
    && mkdir /data \
    && chown 10001:10001 /data
COPY --from=backend /opt/venv /opt/venv
COPY --from=frontend /build/dist /app/frontend
COPY integrations /app/integrations
COPY config /app/config
WORKDIR /app
USER 10001:10001
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/health', timeout=4)"]
CMD ["python", "-m", "missa_control"]
