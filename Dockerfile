# syntax=docker/dockerfile:1
# RoomBook application image (ADR-003): the React build is copied into the
# FastAPI runtime, so one image carries both. Built once per commit on
# GitHub-hosted CI, published to GHCR and promoted by digest without rebuilding.

ARG NODE_VERSION=24.19.0
ARG PYTHON_VERSION=3.12.14

# uv at the exact version pinned in backend/pyproject.toml
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

# ---- frontend: compile the static React app ----
FROM node:${NODE_VERSION}-slim AS frontend
WORKDIR /src/frontend
RUN npm install --global npm@11.6.2
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- backend: install locked runtime dependencies into /app/.venv ----
FROM python:${PYTHON_VERSION}-slim AS backend
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/scripts ./scripts

# ---- runtime: no build tools, no secrets, non-root ----
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN useradd --create-home --uid 10001 roombook
WORKDIR /app
COPY --from=backend --chown=roombook:roombook /app /app
COPY --from=frontend --chown=roombook:roombook /src/frontend/dist /app/static
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROOMBOOK_STATIC_DIR=/app/static

# Last, so a new commit does not invalidate the dependency layers above
ARG COMMIT_SHA=unknown
ENV ROOMBOOK_COMMIT_SHA=${COMMIT_SHA}

USER roombook
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

# Runtime settings come from the environment: ROOMBOOK_DATABASE_URL and
# ROOMBOOK_ENVIRONMENT. Migrations and seeding are explicit release steps:
#   alembic upgrade head
#   python -m scripts.seed_rooms
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
